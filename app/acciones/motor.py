"""Motor de acciones: decide QUÉ haría Tommy por cada ticket y lo encola (estado 'sugerida').

Reglas (modo sugerencia, no envía nada):
  - DELICADO → SOLO escalar a Ceci (no se auto-notifica al cliente).           [M5]
  - A_respuesta_ticket → avisar al cliente + al asesor (WhatsApp coloquial).    [M4]
  - B_acuse_ticket     → avisar al asesor (se abrió el ticket).
  - C_allianz_pide     → avisar al cliente + recordatorio a +2 días.            [M7]
  - E_cc_cliente       → recordatorio a +2 días (esperamos respuesta de Allianz).
  - D_reenvio_asesor   → sugerir envío a Allianz (Fase 4) + avisar al asesor.

Canales: 'wati' (WhatsApp), 'email' (Allianz), 'interno' (Ceci/panel).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import config
from app.db import Repositorio
from app.models import Clasificacion, Correo, TipoCorreo
from app.tramites import Ruta, identificar_tramite, instrucciones_cliente
from . import resumen

_DIAS_RECORDATORIO = 2


def _mas_dias(dias: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat()


def decidir_y_encolar(repo: Repositorio, ticket_id: int, ticket: dict,
                      clf: Clasificacion, notion: dict, correo: Correo) -> list[dict]:
    """Devuelve la lista de acciones sugeridas (y las persiste en la tabla `acciones`)."""
    ctx = {
        "tipo": clf.tipo.value,
        "subtipo": getattr(clf, "subtipo", None),
        "nro_ticket": ticket.get("nro_ticket"),
        "poliza": ticket.get("poliza"),
        "cliente_nombre": ticket.get("cliente_nombre") or notion.get("cliente_nombre"),
        "producto": notion.get("producto"),
        "asunto": correo.asunto,
        # v2: historial del hilo (bitácora) para que el orquestador tenga contexto de qué pasó.
        "historial": _historial_ticket(repo, ticket_id),
    }
    cliente_dest = ticket.get("cliente_correo") or notion.get("cliente_correo")
    asesor_dest = ticket.get("asesor_correo") or notion.get("asesor_correo")
    # Fase F: teléfonos (Notion Emisiones o ya persistidos en el ticket) para el ruteo por WATI.
    tel_cliente = ticket.get("telefono_cliente") or notion.get("telefono_cliente")
    tel_asesor = ticket.get("telefono_asesor") or notion.get("telefono_asesor")

    plan: list[dict] = []

    # M5: delicado → SOLO Ceci (los mensajes a Ceci van por WATI). Fase E: los temas realmente
    # sensibles (fallecimiento, siniestro, cancelación, rescate, fraude…) no se auto-responden;
    # Ceci interviene a mano. Los críticos NO delicados (período de descanso, suspensión de
    # aportaciones) sí se autoarman como trámite y el guardarraíl del despacho retiene el borrador.
    if ticket.get("delicado"):
        plan.append({"tipo_accion": "escalar_ceci", "canal": "wati", "rol": "ceci",
                     "destinatario": None,
                     "mensaje": f"Ticket DELICADO ({clf.tipo.value}) requiere intervención de Ceci. "
                                f"Cliente: {ctx['cliente_nombre'] or '—'} · asunto: {correo.asunto}"})
        return _persistir(repo, ticket_id, plan)

    # Consulta de trámite (F): instruir al cliente (portal) o gestionar nosotros por mail.
    if clf.tipo == TipoCorreo.F_CONSULTA_PRODUCTO:
        return _plan_tramite(repo, ticket_id, ctx, correo, cliente_dest, asesor_dest)

    tipo = clf.tipo
    if tipo == TipoCorreo.A_RESPUESTA_TICKET:
        plan.append(_msg("avisar_cliente", "wati", "cliente", cliente_dest, ctx, numero=tel_cliente))
        plan.append(_msg("avisar_asesor", "wati", "asesor", asesor_dest, ctx, numero=tel_asesor))
        # Asertividad (v2): si el orquestador detecta que Allianz respondió FUERA DE TEMA,
        # el bot re-exige en el hilo (no lo da por bueno). Ese correo saliente pasa igual por
        # el guardarraíl de Fase E (si es crítico → visto bueno de Ceci). Dedup para no apilar.
        orq = _orquestar_allianz(ctx, correo)
        if orq.get("fuera_de_tema") and orq.get("cuerpo_allianz") and not _ya_pendiente_allianz(repo, ticket_id):
            plan.append({"tipo_accion": "enviar_a_allianz", "canal": "email", "rol": "allianz",
                         "destinatario": None,
                         "mensaje": "Re-exigencia: Allianz respondió fuera de tema.",
                         "cuerpo": orq["cuerpo_allianz"], "nota_asertividad": orq.get("nota_asertividad")})
    elif tipo == TipoCorreo.B_ACUSE_TICKET:
        plan.append(_msg("avisar_asesor", "wati", "asesor", asesor_dest, ctx, numero=tel_asesor))
    elif tipo == TipoCorreo.C_ALLIANZ_PIDE:
        plan.append(_msg("avisar_cliente", "wati", "cliente", cliente_dest, ctx, numero=tel_cliente))
        plan.append({"tipo_accion": "recordatorio", "canal": "wati", "rol": "cliente",
                     "destinatario": cliente_dest, "numero": tel_cliente,
                     "programada_para": _mas_dias(_DIAS_RECORDATORIO),
                     "mensaje": "Recordatorio: verificar si el cliente envió lo que pidió Allianz."})
    elif tipo == TipoCorreo.E_CC_CLIENTE:
        plan.append({"tipo_accion": "recordatorio", "canal": "interno", "rol": "seguimiento",
                     "destinatario": None, "programada_para": _mas_dias(_DIAS_RECORDATORIO),
                     "mensaje": "Recordatorio: chequear si Allianz respondió la solicitud del cliente."})
    elif tipo == TipoCorreo.D_REENVIO_ASESOR:
        orq = _orquestar_allianz(ctx, correo)   # el cerebro redacta el cuerpo (asertivo) si hay LLM
        plan.append({"tipo_accion": "enviar_a_allianz", "canal": "email", "rol": "allianz",
                     "destinatario": None,
                     "mensaje": "Levantar el ticket ante Allianz (requiere Directorio + autorización).",
                     "cuerpo": orq.get("cuerpo_allianz"),
                     "nota_asertividad": orq.get("nota_asertividad")})
        plan.append(_msg("avisar_asesor", "wati", "asesor", asesor_dest, ctx, numero=tel_asesor))

    return _persistir(repo, ticket_id, plan)


def _historial_ticket(repo: Repositorio, ticket_id: int, limite: int = 8) -> list[dict]:
    """Bitácora reciente del ticket (para dar contexto al orquestador). Defensivo."""
    try:
        evs = repo.listar_eventos(ticket_id) or []
    except Exception:  # noqa: BLE001
        return []
    return [{"evento": e.get("tipo_evento"), "detalle": e.get("resumen"), "fecha": str(e.get("created_at"))}
            for e in evs[-limite:]]


def _ya_pendiente_allianz(repo: Repositorio, ticket_id: int) -> bool:
    """True si ya hay un correo a Allianz sin despachar (evita apilar re-exigencias)."""
    try:
        acc = repo.listar_acciones(ticket_id=ticket_id) or []
    except Exception:  # noqa: BLE001
        return False
    return any(a.get("tipo_accion") in ("enviar_a_allianz", "gestionar_tramite")
               and a.get("estado") in ("sugerida", "pendiente_ceci") for a in acc)


def _orquestar_allianz(ctx: dict, correo: Correo) -> dict:
    """Pide al orquestador (LLM) el cuerpo asertivo para el correo a Allianz. {} si no hay LLM.
    Defensivo: cualquier problema → {} y el despacho usa el cuerpo de plantilla."""
    try:
        from app.agentes import redactar_allianz
        return redactar_allianz(ctx, mensaje_allianz=(correo.cuerpo_texto or "")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _msg(tipo_accion: str, canal: str, rol: str, destinatario, ctx: dict, numero=None) -> dict:
    # `numero` = teléfono para WATI (Fase F). Si viene, el despacho rutea al WhatsApp real;
    # si no, cae a `destinatario` (y si es un email → pendiente_wati).
    return {"tipo_accion": tipo_accion, "canal": canal, "rol": rol, "destinatario": destinatario,
            "numero": numero, "mensaje": resumen.generar(rol, ctx)}


def _plan_tramite(repo: Repositorio, ticket_id: int, ctx: dict, correo: Correo,
                  cliente_dest, asesor_dest) -> list[dict]:
    """Rutea una consulta de trámite según el catálogo de Ceci:
      - CLIENTE_PORTAL → le mandamos las instrucciones a quien preguntó (email_cliente).
      - NOSOTROS_MAIL  → lo gestionamos por mail (canal email → Allianz) + aviso al cliente.
    Si no se reconoce el trámite, queda para revisión de Ceci (canal interno)."""
    tramite = identificar_tramite(correo)
    # A quién le respondemos: quien escribió; si no, el cliente/asesor del ticket.
    destino = correo.remitente or cliente_dest or asesor_dest
    nombre = (ctx.get("cliente_nombre") or "").split()[0] if ctx.get("cliente_nombre") else None

    if tramite is None:
        return _persistir(repo, ticket_id, [{
            "tipo_accion": "consulta_general", "canal": "wati", "rol": "ceci", "destinatario": None,
            "mensaje": f"Consulta de proceso sin trámite reconocido → revisar. Asunto: {correo.asunto}"}])

    if tramite.ruta == Ruta.CLIENTE_PORTAL:
        return _persistir(repo, ticket_id, [{
            "tipo_accion": "instruir_tramite", "canal": "email_cliente", "rol": "cliente",
            "destinatario": destino, "asunto": f"Cómo hacer: {tramite.nombre}",
            "mensaje": instrucciones_cliente(tramite, nombre)}])

    # NOSOTROS_MAIL: lo hacemos nosotros por correo (a Allianz) + le avisamos al cliente.
    hola = f"Hola {nombre}! " if nombre else "Hola! "
    orq = _orquestar_allianz({**ctx, "tramite": tramite.nombre}, correo)  # cuerpo asertivo si hay LLM
    plan = [
        {"tipo_accion": "gestionar_tramite", "canal": "email", "rol": "allianz", "destinatario": None,
         "mensaje": f"Solicitud de trámite: {tramite.nombre}"
                    + (f" · póliza {ctx.get('poliza')}" if ctx.get("poliza") else "")
                    + (f" · cliente {ctx.get('cliente_nombre')}" if ctx.get("cliente_nombre") else ""),
         "cuerpo": orq.get("cuerpo_allianz"), "nota_asertividad": orq.get("nota_asertividad")},
        {"tipo_accion": "avisar_cliente", "canal": "email_cliente", "rol": "cliente",
         "destinatario": destino, "asunto": f"Estamos gestionando: {tramite.nombre}",
         "mensaje": f"{hola}Recibimos tu solicitud de «{tramite.nombre}». Este trámite lo "
                    f"gestionamos nosotros directamente con Allianz y te mantenemos al tanto. 💛"},
    ]
    return _persistir(repo, ticket_id, plan)


def _persistir(repo: Repositorio, ticket_id: int, plan: list[dict]) -> list[dict]:
    for a in plan:
        repo.crear_accion(ticket_id, a["tipo_accion"], a["canal"],
                          {"rol": a.get("rol"), "destinatario": a.get("destinatario"),
                           "numero": a.get("numero"), "mensaje": a.get("mensaje"),
                           "asunto": a.get("asunto"), "cuerpo": a.get("cuerpo"),
                           "nota_asertividad": a.get("nota_asertividad")},
                          a.get("programada_para"))
    return plan


def escanear_inactividad(repo: Repositorio, dias: int = 3) -> list[dict]:
    """M7: tickets sin actividad hace > `dias` y no resueltos → encola un recordatorio de
    reactivación al responsable. Devuelve las acciones encoladas. (No envía nada.)"""
    encoladas = []
    umbral = datetime.now(timezone.utc) - timedelta(days=dias)
    for t in repo.listar_tickets(limite=500):
        estado = (t.get("estado") or "")
        if estado in ("resuelto",):
            continue
        ult = t.get("ultima_actividad")
        # ult puede venir como datetime (PG) o str (SQLite); normalizamos a comparación simple.
        try:
            ts = ult if isinstance(ult, datetime) else datetime.fromisoformat(str(ult).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            continue
        if ts < umbral:
            rol = "cliente" if estado == "esperando_cliente" else (
                "asesor" if estado == "esperando_asesor" else "seguimiento")
            numero = t.get("telefono_cliente") if rol == "cliente" else (
                t.get("telefono_asesor") if rol == "asesor" else None)
            aid = repo.crear_accion(t["id"], "reactivacion", "wati" if rol != "seguimiento" else "interno",
                                    {"rol": rol, "numero": numero,
                                     "mensaje": f"Reactivar ticket sin novedades hace {dias}+ días "
                                                f"(estado {estado})."})
            encoladas.append({"ticket_id": t["id"], "accion_id": aid, "rol": rol})
    return encoladas


def escanear_vencimientos(repo: Repositorio, ahora: datetime | None = None,
                          umbral_horas: int | None = None) -> list[dict]:
    """SLA (Fase C): tickets con `vence_en` próximo o vencido → encola un recordatorio (una vez)
    al asesor y, si ya venció, marca el ticket `por_cerrar`. No envía nada (lo hace el despacho)."""
    ahora = ahora or datetime.now(timezone.utc)
    umbral = timedelta(hours=umbral_horas if umbral_horas is not None else config.SLA_AVISO_HORAS)
    encoladas = []
    for t in repo.listar_tickets(limite=500):
        if (t.get("estado") or "") in ("resuelto",):
            continue
        v = t.get("vence_en")
        if not v:
            continue
        try:
            vd = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            if vd.tzinfo is None:
                vd = vd.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            continue
        falta = vd - ahora
        if falta > umbral:
            continue  # todavía lejos del vencimiento
        # Evitar duplicar el recordatorio SLA si ya hay uno sugerido para este ticket.
        if any(a.get("tipo_accion") == "recordatorio_sla"
               for a in repo.listar_acciones(ticket_id=t["id"], estado="sugerida")):
            continue
        vencido = falta.total_seconds() <= 0
        etiqueta = "VENCIÓ" if vencido else f"vence en ~{int(falta.total_seconds() // 3600)}h"
        aid = repo.crear_accion(
            t["id"], "recordatorio_sla", "wati",
            {"rol": "asesor", "numero": t.get("telefono_asesor"),
             "mensaje": f"Ticket {t.get('nro_ticket') or '—'} {etiqueta}: responder en el hilo "
                        f"antes de que Allianz lo cierre por inactividad."})
        if vencido and t.get("estado") != "por_cerrar":
            repo.actualizar_ticket(t["id"], estado="por_cerrar")
        encoladas.append({"ticket_id": t["id"], "accion_id": aid, "vencido": vencido})
    return encoladas
