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

from app.db import Repositorio
from app.models import Clasificacion, Correo, TipoCorreo
from . import resumen

_DIAS_RECORDATORIO = 2


def _mas_dias(dias: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat()


def decidir_y_encolar(repo: Repositorio, ticket_id: int, ticket: dict,
                      clf: Clasificacion, notion: dict, correo: Correo) -> list[dict]:
    """Devuelve la lista de acciones sugeridas (y las persiste en la tabla `acciones`)."""
    ctx = {
        "tipo": clf.tipo.value,
        "nro_ticket": ticket.get("nro_ticket"),
        "poliza": ticket.get("poliza"),
        "cliente_nombre": ticket.get("cliente_nombre") or notion.get("cliente_nombre"),
        "producto": notion.get("producto"),
        "asunto": correo.asunto,
    }
    cliente_dest = ticket.get("cliente_correo") or notion.get("cliente_correo")
    asesor_dest = ticket.get("asesor_correo") or notion.get("asesor_correo")

    plan: list[dict] = []

    # M5: delicado → SOLO Ceci.
    if ticket.get("delicado"):
        plan.append({"tipo_accion": "escalar_ceci", "canal": "interno", "rol": "ceci",
                     "destinatario": None,
                     "mensaje": f"Ticket DELICADO ({clf.tipo.value}) requiere intervención de Ceci. "
                                f"Cliente: {ctx['cliente_nombre'] or '—'} · asunto: {correo.asunto}"})
        return _persistir(repo, ticket_id, plan)

    tipo = clf.tipo
    if tipo == TipoCorreo.A_RESPUESTA_TICKET:
        plan.append(_msg("avisar_cliente", "wati", "cliente", cliente_dest, ctx))
        plan.append(_msg("avisar_asesor", "wati", "asesor", asesor_dest, ctx))
    elif tipo == TipoCorreo.B_ACUSE_TICKET:
        plan.append(_msg("avisar_asesor", "wati", "asesor", asesor_dest, ctx))
    elif tipo == TipoCorreo.C_ALLIANZ_PIDE:
        plan.append(_msg("avisar_cliente", "wati", "cliente", cliente_dest, ctx))
        plan.append({"tipo_accion": "recordatorio", "canal": "wati", "rol": "cliente",
                     "destinatario": cliente_dest, "programada_para": _mas_dias(_DIAS_RECORDATORIO),
                     "mensaje": "Recordatorio: verificar si el cliente envió lo que pidió Allianz."})
    elif tipo == TipoCorreo.E_CC_CLIENTE:
        plan.append({"tipo_accion": "recordatorio", "canal": "interno", "rol": "seguimiento",
                     "destinatario": None, "programada_para": _mas_dias(_DIAS_RECORDATORIO),
                     "mensaje": "Recordatorio: chequear si Allianz respondió la solicitud del cliente."})
    elif tipo == TipoCorreo.D_REENVIO_ASESOR:
        plan.append({"tipo_accion": "enviar_a_allianz", "canal": "email", "rol": "allianz",
                     "destinatario": None,
                     "mensaje": "Sugerencia: levantar el ticket ante Allianz (requiere Directorio + SMTP + autorización)."})
        plan.append(_msg("avisar_asesor", "wati", "asesor", asesor_dest, ctx))

    return _persistir(repo, ticket_id, plan)


def _msg(tipo_accion: str, canal: str, rol: str, destinatario, ctx: dict) -> dict:
    return {"tipo_accion": tipo_accion, "canal": canal, "rol": rol, "destinatario": destinatario,
            "mensaje": resumen.generar(rol, ctx)}


def _persistir(repo: Repositorio, ticket_id: int, plan: list[dict]) -> list[dict]:
    for a in plan:
        repo.crear_accion(ticket_id, a["tipo_accion"], a["canal"],
                          {"rol": a.get("rol"), "destinatario": a.get("destinatario"), "mensaje": a.get("mensaje")},
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
            aid = repo.crear_accion(t["id"], "reactivacion", "wati" if rol != "seguimiento" else "interno",
                                    {"rol": rol, "mensaje": f"Reactivar ticket sin novedades hace {dias}+ días "
                                                            f"(estado {estado})."})
            encoladas.append({"ticket_id": t["id"], "accion_id": aid, "rol": rol})
    return encoladas
