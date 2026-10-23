"""Motor por ETAPA (reemplaza al motor por tipo de correo). Etapa 1: proceso largo; Etapa 2: proceso
corto (guía de aportación con aprobación de Ceci + recordatorio de pago) y trámites.

Detrás de MOTOR_ETAPAS=1. Por cada correo ya clasificado en su etapa (`app/clasificador/etapas.py`):
  1. decide si la etapa del ticket avanza (solo avanza; un correo viejo o repetido no la hace
     retroceder ni repite avisos — excepción: un requerimiento nuevo abre otra "ronda");
  2. identifica cliente y asesor (paso 3) — si no se puede, no se adivina: va solo a Ceci;
  3. registra cada aviso en `avisos` (clave única → nunca sale dos veces) y lo encola en
     `acciones` para el despachador (que respeta DRY_RUN);
  4. arranca / corta los recordatorios (`recordatorios`; el escaneo y la escalación son el paso 6);
  5. actualiza estado y etapa del ticket, y deja la bitácora.

Reglas duras: ningún correo sale hacia Allianz desde acá; rechazado/declinado nunca le
escriben al cliente; ticket delicado → solo Ceci.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from app import config
from app.clasificador.etapas import Etapa, accion_para
from app.db import Repositorio
from app.enriquecimiento.identificar import Buscador, Identificacion, identificar_y_guardar
from app.models import EstadoTicket
from app.tickets import sla

from . import mensajes_etapa

log = logging.getLogger(__name__)

# Orden de avance. Las terminales cierran el ticket y no aceptan nada más.
RANGO = {
    Etapa.APERTURA: 10, Etapa.CONFIRMACION_DATOS: 20, Etapa.REQUERIMIENTO: 30,
    Etapa.DOCUMENTOS_ENVIADOS: 40, Etapa.AUTORIZADO: 50, Etapa.ATENDIDA: 60, Etapa.POLIZA_EMITIDA: 70,
    Etapa.RECHAZADO: 90, Etapa.DECLINADO: 90, Etapa.CERRADO_INACTIVIDAD: 90,
}
TERMINALES = {Etapa.RECHAZADO, Etapa.DECLINADO, Etapa.CERRADO_INACTIVIDAD, Etapa.POLIZA_EMITIDA}
# Un requerimiento nuevo reabre el C3 (otra ronda) si llega en estas etapas.
_REABRE_REQUERIMIENTO = {Etapa.REQUERIMIENTO, Etapa.DOCUMENTOS_ENVIADOS, Etapa.AUTORIZADO}
# Correos que no mueven la etapa (copias, notas, rebotes, recordatorios de Allianz, revisar, emisión registrada).
SIN_AVANCE = {Etapa.COPIA_EJECUTIVA, Etapa.NOTA_EJECUTIVA, Etapa.REBOTE_TICKET_CERRADO,
              Etapa.RECORDATORIO_ALLIANZ, Etapa.REVISAR, Etapa.EMISION_REGISTRADA}

ESTADO_POR_ETAPA = {
    Etapa.APERTURA: EstadoTicket.ABIERTO,
    Etapa.CONFIRMACION_DATOS: EstadoTicket.ESPERANDO_ALLIANZ,
    Etapa.REQUERIMIENTO: EstadoTicket.ESPERANDO_CLIENTE,
    Etapa.DOCUMENTOS_ENVIADOS: EstadoTicket.ESPERANDO_ALLIANZ,
    Etapa.AUTORIZADO: EstadoTicket.ESPERANDO_ALLIANZ,   # autorizado: Allianz cobra
    Etapa.ATENDIDA: EstadoTicket.RESUELTO,
    Etapa.POLIZA_EMITIDA: EstadoTicket.RESUELTO,
    Etapa.RECHAZADO: EstadoTicket.RESUELTO,
    Etapa.DECLINADO: EstadoTicket.RESUELTO,
    Etapa.CERRADO_INACTIVIDAD: EstadoTicket.RESUELTO,
}
# Proceso corto: después de la confirmación de datos se espera el pago del cliente (guía de aportación).
ESTADO_POR_ETAPA_PROCESO = {("corto", Etapa.CONFIRMACION_DATOS): EstadoTicket.ESPERANDO_CLIENTE}


def estado_para(etapa: Etapa, proceso: Optional[str]) -> Optional[EstadoTicket]:
    return ESTADO_POR_ETAPA_PROCESO.get((proceso, etapa)) or ESTADO_POR_ETAPA.get(etapa)

TIPO_ACCION = {"ceci": "avisar_ceci", "asesor": "avisar_asesor", "cliente": "avisar_cliente"}

# Motivos de recordatorio y a quién se le recuerda.
REC_REQUERIMIENTO = "requerimiento"          # esperamos al cliente
REC_ESPERANDO_ALLIANZ = "esperando_allianz"  # mandamos lo pedido; esperamos a Allianz
REC_PAGO = "pago"                            # proceso corto: el cliente tiene que depositar (guía)
_DEST_REC = {REC_REQUERIMIENTO: ("cliente", "asesor"), REC_ESPERANDO_ALLIANZ: ("ceci",),
             REC_PAGO: ("cliente", "asesor")}
# Lo que espera al cliente: se cumple cuando mandamos algo a Allianz (C4).
_ESPERAN_AL_CLIENTE = (REC_REQUERIMIENTO, REC_PAGO)

GUIA = "guia_aportacion"  # tipo de aprobación (tabla aprobaciones) y etapa de su aviso


def procesos_activos() -> set[str]:
    return {p.strip().lower() for p in config.MOTOR_ETAPAS_PROCESOS if p.strip()}


def usa_motor_etapas(etapa: Optional[dict], ticket: Optional[dict] = None) -> bool:
    """¿Este correo lo maneja el motor por etapa? Los procesos de MOTOR_ETAPAS_PROCESOS (largo en la
    Etapa 1; corto y trámite se suman en la Etapa 2); el resto sigue con el motor viejo.
    Copias/notas/rebotes sin proceso propio heredan el del ticket (y si no hay, cuentan como largo)."""
    if not (config.MOTOR_ETAPAS and etapa) or etapa.get("etapa") in (None, Etapa.NO_APLICA.value):
        return False
    proceso = etapa.get("proceso") or (ticket or {}).get("proceso") or "largo"
    return proceso in procesos_activos()


EMISIONES = (Etapa.POLIZA_EMITIDA.value, Etapa.EMISION_REGISTRADA.value)


def ticket_para_emision(repo: Repositorio, etapa: dict) -> Optional[int]:
    """Los avisos de emisión no traen n° de ticket: se cruzan con un ticket que ya esté en el motor
    por etapa (por póliza, n° de solicitud o nombre). Si no hay uno solo → None (no se crea un
    ticket nuevo por cada emisión)."""
    from app.enriquecimiento.identificar import mismo_nombre

    activos = procesos_activos()

    def en_motor(t):
        return t if t and t.get("etapa") and ((t.get("proceso") or "largo") in activos) else None

    if etapa.get("poliza"):
        t = en_motor(repo.buscar_ticket(None, etapa["poliza"], None))
        if t:
            return t["id"]
    if etapa.get("nro_solicitud"):
        t = en_motor(repo.buscar_ticket_por_solicitud(etapa["nro_solicitud"]))
        if t:
            return t["id"]
    if etapa.get("cliente"):
        cands = [t for t in repo.listar_tickets(limite=500)
                 if en_motor(t) and mismo_nombre(t.get("cliente_nombre"), etapa["cliente"])]
        if len(cands) == 1:
            return cands[0]["id"]
    return None


# Reloj inyectable: el replay del paso 8 lo fija a la fecha de cada correo real.
reloj: Optional[Callable[[], datetime]] = None


def _ahora(ahora: Optional[datetime]) -> datetime:
    a = ahora or (reloj() if reloj else datetime.now(timezone.utc))
    return a if a.tzinfo else a.replace(tzinfo=timezone.utc)


def _parse_ts(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def transicion(actual: Optional[str], nueva: Etapa, ronda: int) -> tuple[bool, int, str]:
    """(aplica, ronda, motivo). Solo para etapas que avanzan (no SIN_AVANCE)."""
    try:
        cur = Etapa(actual) if actual else None
    except ValueError:
        cur = None
    if cur is None or cur not in RANGO:
        return True, ronda or 1, "primera etapa conocida del ticket"
    if cur in TERMINALES:
        return False, ronda, f"el ticket ya terminó ({cur.value})"
    if nueva == Etapa.REQUERIMIENTO and cur in _REABRE_REQUERIMIENTO:
        return True, (ronda or 1) + 1, f"nuevo requerimiento después de {cur.value}"
    if RANGO[nueva] > RANGO[cur]:
        return True, ronda or 1, f"{cur.value} → {nueva.value}"
    return False, ronda, f"correo de una etapa anterior o repetida ({nueva.value} con el ticket en {cur.value})"


def _mx(d: datetime) -> str:
    """Para la bitácora y el panel: hora de CDMX, que es la que lee Ceci."""
    return f"{d.astimezone(timezone.utc) + timedelta(hours=config.UTC_OFFSET_MX):%d/%m %H:%M} (CDMX)"


def mas_horas_habiles(desde: datetime, horas: int) -> datetime:
    """'72 h hábiles' = 3 días hábiles: corren las 24 h pero no cuentan fines de semana ni
    feriados de México (sla.py). El resto (<24 h) se suma tal cual."""
    dias, resto = divmod(int(horas), 24)
    return sla.calcular_vencimiento(desde, dias, "dias_habiles") + timedelta(hours=resto)


def _norm_pedido(s: Optional[str]) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return " ".join("".join(c if c.isalnum() else " " for c in s).split())[:150]


def _pedido_vigente_igual(repo: Repositorio, ticket_id: int, que_piden: Optional[str]) -> bool:
    """¿El pedido nuevo es el mismo que el del requerimiento que sigue vivo?"""
    nuevo = _norm_pedido(que_piden)
    if len(nuevo) < 20:
        return False
    for r in repo.listar_recordatorios(ticket_id, estados=["activo", "escalado"]):
        if r.get("motivo") == REC_REQUERIMIENTO and _norm_pedido(r.get("nota")) == nuevo:
            return True
    return False


def _vencimiento(motivo: str, etapa: dict, desde: datetime) -> tuple[datetime, datetime]:
    """Vence: plazo del correo o 72 h hábiles, el que llegue antes. Escala 24 h hábiles después."""
    vence = mas_horas_habiles(desde, config.RECORDATORIO_HORAS_HABILES)
    plazo = etapa.get("plazo") if motivo == REC_REQUERIMIENTO else None
    if plazo:
        vence = min(vence, sla.calcular_vencimiento(desde, int(plazo[0]), plazo[1]))
    return vence, mas_horas_habiles(vence, config.ESCALA_HORAS_HABILES)


def _cancelar_escalaciones(repo: Repositorio, ticket_id: int, motivo: str) -> int:
    """El correo de escalación a Allianz que todavía espera el visto bueno de Ceci deja de tener
    sentido si Allianz ya respondió o el ticket terminó: se descarta (Ceci no lo ve más)."""
    n = 0
    for a in repo.listar_acciones(ticket_id=ticket_id):
        if a.get("tipo_accion") == "escalar_allianz" and a.get("estado") in ("sugerida", "pendiente_ceci"):
            repo.actualizar_accion(a["id"], "omitida", {"motivo": motivo})
            n += 1
    return n


def _recordatorios(repo: Repositorio, ticket_id: int, e: Etapa, etapa: dict, ronda_nueva: bool,
                   ahora: datetime, correo_id: Optional[int],
                   proceso: str = "largo") -> tuple[Optional[datetime], list[str]]:
    """Arranca / corta recordatorios según la etapa. Devuelve (vencimiento del nuevo, bitácora)."""
    log_ = []
    vence = None
    acc = accion_para(e, proceso)
    if e == Etapa.REQUERIMIENTO:
        # Allianz respondió → deja de esperarse a Allianz; si es otra ronda, el pedido viejo se reemplaza.
        if repo.cerrar_recordatorios(ticket_id, "cumplido", REC_ESPERANDO_ALLIANZ, "Allianz respondió"):
            log_.append("se cortó 'esperando a Allianz'")
        if _cancelar_escalaciones(repo, ticket_id, "Allianz respondió antes de que se aprobara la escalación"):
            log_.append("se descartó la escalación pendiente")
        if ronda_nueva and repo.cerrar_recordatorios(ticket_id, "cancelado", REC_REQUERIMIENTO,
                                                     "reemplazado por un requerimiento nuevo"):
            log_.append("se reemplazó el requerimiento anterior")
        vence, escala = _vencimiento(REC_REQUERIMIENTO, etapa, ahora)
        if repo.crear_recordatorio(ticket_id, REC_REQUERIMIENTO, _DEST_REC[REC_REQUERIMIENTO], vence, escala,
                                   correo_id, nota=(etapa.get("que_piden") or "")[:600]):
            log_.append(f"recordatorio al cliente/asesor para el {_mx(vence)}")
    elif e == Etapa.DOCUMENTOS_ENVIADOS:
        for motivo in _ESPERAN_AL_CLIENTE:  # requerimiento (largo/trámite) o pago (corto)
            if repo.cerrar_recordatorios(ticket_id, "cumplido", motivo, "se mandó lo pedido (C4)"):
                log_.append(f"se cortó el recordatorio de {'pago' if motivo == REC_PAGO else 'requerimiento'}")
        vence, escala = _vencimiento(REC_ESPERANDO_ALLIANZ, etapa, ahora)
        if repo.crear_recordatorio(ticket_id, REC_ESPERANDO_ALLIANZ, _DEST_REC[REC_ESPERANDO_ALLIANZ], vence,
                                   escala, correo_id, nota="esperando respuesta de Allianz"):
            log_.append(f"esperando a Allianz hasta el {_mx(vence)}")
    elif acc.cancela_recordatorio:
        estado = "cumplido" if e in (Etapa.AUTORIZADO, Etapa.ATENDIDA, Etapa.POLIZA_EMITIDA) else "cancelado"
        n = repo.cerrar_recordatorios(ticket_id, estado, nota=f"etapa {e.value}")
        if n:
            log_.append(f"se cortaron {n} recordatorio(s)")
        if _cancelar_escalaciones(repo, ticket_id, f"Allianz ya respondió ({e.value}): la escalación no hace falta"):
            log_.append("se descartó la escalación pendiente")
    return vence, log_


_asunto = mensajes_etapa._asunto


def rol_activo(rol: str) -> bool:
    """Encendido gradual (MOTOR_ETAPAS_ROLES): a un rol apagado no se le registra ni encola nada."""
    return rol in {r.strip().lower() for r in config.MOTOR_ETAPAS_ROLES}


def _encolar(repo: Repositorio, ticket_id: int, rol: str, texto: str, etapa: str, ronda: int,
             numero: Optional[str], correo_id: Optional[int], params: dict) -> Optional[dict]:
    """Registra el aviso (único) y lo encola. None si ese aviso ya había salido o el rol está apagado."""
    if not rol_activo(rol):
        return None
    aviso_id = repo.registrar_aviso(ticket_id, etapa, rol, ronda=ronda, canal="wati", texto=texto,
                                    correo_id=correo_id)
    if aviso_id is None:
        return None
    payload = {"rol": rol, "destinatario": None, "numero": numero, "mensaje": texto,
               "etapa": etapa, "ronda": ronda, "aviso_id": aviso_id, "params": params}
    accion_id = repo.crear_accion(ticket_id, TIPO_ACCION[rol], "wati", payload)
    return {"accion_id": accion_id, "aviso_id": aviso_id, "ticket_id": ticket_id, "tipo_accion": TIPO_ACCION[rol], **payload}


def decidir_por_etapa(repo: Repositorio, ticket_id: int, etapa: dict, correo_id: Optional[int] = None,
                      ahora: Optional[datetime] = None, buscar: Optional[Buscador] = None) -> dict:
    """`etapa` = EtapaCorreo.como_dict(). Devuelve qué hizo (para logs, panel y el replay del paso 8)."""
    ahora = _ahora(ahora)
    ticket = repo.obtener_ticket(ticket_id) or {"id": ticket_id}
    try:
        e = Etapa(etapa["etapa"])
    except (KeyError, ValueError):
        return {"aplicada": False, "motivo": f"etapa desconocida: {etapa.get('etapa')}", "plan": []}
    proceso = etapa.get("proceso") or ticket.get("proceso") or "largo"
    acc = accion_para(e, proceso)
    if e in SIN_AVANCE and etapa.get("proceso") is None:
        # Copias/notas/rebotes no traen proceso: hablan como el ticket.
        proceso = ticket.get("proceso") or "largo"
    actual = ticket.get("etapa")
    ronda = int(ticket.get("etapa_ronda") or 1)
    res: dict = {"etapa": e.value, "etapa_anterior": actual, "plan": [], "avisos_omitidos": [],
                 "recordatorios": [], "identificacion": None}

    campos: dict = {}
    # Datos que el correo trae y el ticket no tenía (no pisa lo que ya hay).
    for col, val in (("proceso", proceso if e not in SIN_AVANCE else etapa.get("proceso")),
                     ("producto", etapa.get("producto")), ("nro_solicitud", etapa.get("nro_solicitud")),
                     ("poliza", etapa.get("poliza")),
                     # El nombre como lo escribe Allianz (sirve para leer el panel y enganchar la emisión).
                     # No identifica a nadie: eso lo decide `identificado_por`.
                     ("cliente_nombre", etapa.get("cliente")),
                     # El asunto del trámite va en todos sus avisos (Etapa 2; columna nueva).
                     ("titulo_hilo", _asunto(etapa.get("titulo_hilo")) if proceso == "tramite" else None)):
        if val and not ticket.get(col):
            campos[col] = val

    if e in SIN_AVANCE:
        aplica, ronda_aviso, motivo = True, int(correo_id or 0), "correo sin avance de etapa"
        ronda_nueva = False
    else:
        aplica, nueva_ronda, motivo = transicion(actual, e, ronda)
        # Allianz a veces repite el MISMO pedido (otra persona, o como recordatorio): no es otra ronda.
        if aplica and e == Etapa.REQUERIMIENTO and actual == Etapa.REQUERIMIENTO.value \
                and _pedido_vigente_igual(repo, ticket_id, etapa.get("que_piden")):
            aplica, nueva_ronda, motivo = False, ronda, "Allianz repitió el mismo pedido"
        ronda_nueva = nueva_ronda != ronda
        ronda = ronda_aviso = nueva_ronda
    res.update(aplicada=aplica, motivo=motivo, ronda=ronda)

    etapa_vigente = Etapa(actual) if actual in {x.value for x in Etapa} else None
    if aplica and e not in SIN_AVANCE:
        campos.update(etapa=e.value, etapa_desde=ahora, etapa_ronda=ronda)
        etapa_vigente = e
    # El estado lo manda la etapa (deshace lo que haya puesto el motor viejo al upsertear).
    est = estado_para(etapa_vigente, ticket.get("proceso") or proceso) if etapa_vigente else None
    if est:
        campos["estado"] = est.value
    if campos:
        repo.actualizar_ticket(ticket_id, **campos)
        ticket = {**ticket, **campos}

    if not aplica:
        repo.agregar_evento(ticket_id, correo_id, "etapa_ignorada", motivo[:200])
        return res

    # Recordatorios (solo cuando la etapa realmente cambió).
    vence = None
    if e not in SIN_AVANCE:
        vence, res["recordatorios"] = _recordatorios(repo, ticket_id, e, etapa, ronda_nueva, ahora, correo_id,
                                                     proceso)

    # Emisión registrada: solo registra póliza/solicitud (ya hecho arriba). Revisar: al panel.
    # A quién avisar: lo que decidió el detector para ESTE correo (ej. la copia de la ejecutiva que
    # pide "brindar respuesta" → alerta a Ceci); si no vino, la tabla de acciones.
    roles = list((etapa.get("accion") or {}).get("avisar") or ()) if "accion" in etapa else list(acc.avisar)
    roles = [r for r in roles if rol_activo(r)]  # encendido gradual
    if e == Etapa.REVISAR:
        repo.agregar_evento(ticket_id, correo_id, "revisar", f"Ninguna regla aplica: {etapa.get('motivo', '')}"[:200])

    # Guía de aportación (corto, C2): no sale a nadie hasta que Ceci la apruebe. Si las aprobaciones
    # van por Telegram, Ceci no recibe además el aviso por WhatsApp.
    guia = bool(acc.aprobacion_telegram and e not in SIN_AVANCE)
    if guia and config.hay_telegram():
        roles = [r for r in roles if r != "ceci"]

    # ¿A quién se le puede escribir?
    ident: Optional[Identificacion] = None
    if guia or any(r in ("asesor", "cliente") for r in roles):
        ident = identificar_y_guardar(repo, ticket, etapa, buscar=buscar, correo_id=correo_id)
        res["identificacion"] = {"estado": ident.estado, "via": ident.via, "motivo": ident.motivo}
        if ident.ok:
            ticket = repo.obtener_ticket(ticket_id) or ticket
    ctx = {**mensajes_etapa.contexto(ticket, etapa, ident.datos if ident and ident.ok else None, vence),
           "ticket_id": ticket_id}
    tel_cliente = (ident.datos.get("telefono_cliente") if ident and ident.ok else None)
    params = mensajes_etapa.params_wati(ctx, e.value, tel_cliente, proceso)

    omitidos = res["avisos_omitidos"]
    if guia:
        datos_guia = mensajes_etapa.datos_guia(ctx, etapa.get("producto") or ticket.get("producto"))
        ap = repo.crear_aprobacion(ticket_id, GUIA, mensajes_etapa.texto_guia(datos_guia), ronda=ronda,
                                   correo_id=correo_id, datos=datos_guia)
        res["aprobacion"] = ap
        if ap:
            repo.agregar_evento(ticket_id, correo_id, "guia_por_aprobar",
                                "Guía de aportación lista: espera la aprobación de Ceci"
                                + (" (Telegram)" if config.hay_telegram() else " (panel)"))
            if not (ident and ident.ok):
                omitidos.append(f"No pude identificar al cliente/asesor ({ident.motivo if ident else 'sin datos'}): "
                                f"asígnalo en el panel antes de aprobar la guía.")
    for rol in roles:
        if rol == "ceci":
            continue
        if rol == "cliente" and acc.delicado:
            continue  # rechazado / declinado: el asesor contacta al cliente
        if ticket.get("delicado"):
            omitidos.append(f"Ticket delicado: no se le avisó al {rol}.")
            continue
        if not (ident and ident.ok):
            omitidos.append(f"No pude identificar al cliente/asesor ({ident.motivo if ident else 'sin datos'}): "
                            f"no se le avisó al {rol}.")
            continue
        numero = ident.datos.get(f"telefono_{rol}")
        if not numero:
            omitidos.append(f"Falta el teléfono del {rol} en Notion: no se le avisó.")
            continue
        t = mensajes_etapa.texto(rol, e.value, ctx, proceso=proceso)
        if t:
            a = _encolar(repo, ticket_id, rol, t, e.value, ronda_aviso, str(numero), correo_id, params)
            if a:
                res["plan"].append(a)

    # Ceci: si la etapa la incluye, o si hubo algo que no se pudo avisar (para que lo asigne a mano).
    if "ceci" in roles or omitidos:
        t = mensajes_etapa.texto("ceci", e.value, ctx, omitidos, proceso=proceso)
        a = _encolar(repo, ticket_id, "ceci", t, e.value, ronda_aviso, None, correo_id, params)
        if a:
            res["plan"].append(a)

    resumen = f"{actual or '—'} → {e.value}" if e not in SIN_AVANCE else e.value
    detalle = [resumen, f"ronda {ronda}" if e not in SIN_AVANCE and ronda > 1 else "",
               f"avisos: {', '.join(a['rol'] for a in res['plan']) or 'ninguno'}", *res["recordatorios"]]
    repo.agregar_evento(ticket_id, correo_id, "etapa", " · ".join(d for d in detalle if d)[:200])
    return res
