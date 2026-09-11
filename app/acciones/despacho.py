"""Despachador de acciones (Fase 4): toma lo que el motor dejó en la cola y lo EJECUTA.

Cierra el objetivo 2 ("enviar tickets a Allianz"): la acción `enviar_a_allianz` (canal
`email`) se compone y sale por SMTP. El resto de canales todavía no tiene integración de
envío en este repo, así que se marcan de forma explícita (no se pierden).

Estados que deja en `acciones.estado`:
  - enviada     → salió por SMTP real (ok).
  - simulada    → DRY_RUN / sin credenciales: se compuso pero no se mandó (queda el correo en `resultado`).
  - fallida     → intento de envío con error (queda el error en `resultado`).
  - bloqueada   → guardarraíl: ticket delicado sin autorización, o falta el Directorio Allianz.
  - pendiente_wati → canal WhatsApp (WATI): lo envía la integración de WATI, no este despachador.
  - omitida     → canal interno (Ceci/panel): no requiere envío externo.
  - diferida    → tiene `programada_para` en el futuro: todavía no toca.

Nada de esto envía nada salvo que haya SMTP y `DRY_RUN=false` (lo decide `emisor_desde_config`).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app import config
from app.db import Repositorio
from app.envio import Emisor, emisor_desde_config

log = logging.getLogger(__name__)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _vencida(programada_para, ahora: datetime) -> bool:
    """True si la acción ya puede ejecutarse (sin fecha = inmediata; con fecha = ya pasó)."""
    if not programada_para:
        return True
    val = programada_para
    try:
        ts = val if isinstance(val, datetime) else datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return True  # si no se puede parsear, no la dejamos colgada
    return ts <= ahora


def _payload(accion: dict) -> dict:
    p = accion.get("payload")
    if isinstance(p, str):
        try:
            return json.loads(p)
        except Exception:  # noqa: BLE001
            return {}
    return p or {}


def _asunto_allianz(ticket: dict) -> str:
    nro = ticket.get("nro_ticket")
    pol = ticket.get("poliza")
    if nro:
        return f"Seguimiento ticket {nro}" + (f" · póliza {pol}" if pol else "")
    if pol:
        return f"Solicitud de trámite · póliza {pol}"
    return "Solicitud de trámite"


def _cuerpo_allianz(ticket: dict, pay: dict) -> str:
    lineas = ["Estimados,", ""]
    detalle = pay.get("mensaje") or "Solicitamos gestionar el trámite referido."
    lineas.append(detalle)
    lineas.append("")
    datos = []
    if ticket.get("nro_ticket"):
        datos.append(f"Ticket: {ticket['nro_ticket']}")
    if ticket.get("poliza"):
        datos.append(f"Póliza: {ticket['poliza']}")
    if ticket.get("cliente_nombre"):
        datos.append(f"Cliente: {ticket['cliente_nombre']}")
    if datos:
        lineas += datos + [""]
    lineas += ["Quedamos atentos.", "Babilonia"]
    return "\n".join(lineas)


def _despachar_una(repo: Repositorio, accion: dict, emisor: Emisor, ahora: datetime) -> str:
    canal = (accion.get("canal") or "").lower()
    tipo = accion.get("tipo_accion") or ""
    aid = accion["id"]
    pay = _payload(accion)

    if not _vencida(accion.get("programada_para"), ahora):
        return "diferida"  # no se toca todavía; sigue 'sugerida'

    # Canal interno (Ceci / seguimiento / panel): no hay envío externo.
    if canal == "interno":
        repo.actualizar_accion(aid, "omitida", {"motivo": "canal interno (panel/Ceci)"})
        return "omitida"

    # Canal WhatsApp: lo manda la integración WATI, no este despachador (aún sin credenciales).
    if canal == "wati":
        repo.actualizar_accion(aid, "pendiente_wati", {"motivo": "envío por WATI (integración pendiente)",
                                                       "destinatario": pay.get("destinatario"),
                                                       "mensaje": pay.get("mensaje")})
        return "pendiente_wati"

    # Canal email → único caso que sale por SMTP. Hoy: envío a Allianz.
    if canal == "email":
        ticket = repo.obtener_ticket(accion["ticket_id"]) or {}
        # Guardarraíl 1: delicado sin autorización → nunca sale solo.
        if ticket.get("delicado") and not ticket.get("autorizado"):
            repo.actualizar_accion(aid, "bloqueada",
                                   {"motivo": "ticket delicado sin autorización (requiere Ceci)"})
            return "bloqueada"
        # Guardarraíl 2: sin Directorio Allianz no hay a quién mandarle.
        destino = config.ALLIANZ_DEST
        if not destino:
            repo.actualizar_accion(aid, "bloqueada",
                                   {"motivo": "falta ALLIANZ_DEST (Directorio Allianz sin confirmar)"})
            return "bloqueada"

        asunto = _asunto_allianz(ticket)
        cuerpo = _cuerpo_allianz(ticket, pay)
        res = emisor.enviar([destino], asunto, cuerpo)
        if res.get("simulado"):
            repo.actualizar_accion(aid, "simulada", res)
            return "simulada"
        if res.get("ok"):
            repo.actualizar_accion(aid, "enviada", res)
            return "enviada"
        repo.actualizar_accion(aid, "fallida", res)
        return "fallida"

    # Canal desconocido: lo marcamos para no reprocesarlo en loop.
    repo.actualizar_accion(aid, "omitida", {"motivo": f"canal no soportado: {canal}", "tipo_accion": tipo})
    return "omitida"


def despachar_pendientes(repo: Repositorio, emisor: Optional[Emisor] = None,
                         ahora: Optional[datetime] = None, limite: int = 500) -> dict:
    """Procesa todas las acciones en estado 'sugerida'. Devuelve el conteo por resultado."""
    emisor = emisor or emisor_desde_config()
    ahora = ahora or _ahora()
    conteo: dict[str, int] = {}
    detalle: list[dict] = []
    for accion in repo.listar_acciones(estado="sugerida")[:limite]:
        r = _despachar_una(repo, accion, emisor, ahora)
        conteo[r] = conteo.get(r, 0) + 1
        detalle.append({"accion_id": accion["id"], "ticket_id": accion.get("ticket_id"),
                        "tipo_accion": accion.get("tipo_accion"), "canal": accion.get("canal"),
                        "resultado": r})
    return {"modo": emisor.modo, "conteo": conteo, "detalle": detalle}
