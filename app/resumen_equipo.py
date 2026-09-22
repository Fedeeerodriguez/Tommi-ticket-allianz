"""Modo copiloto (primera parte en vivo): resumen interno por correo.

En vez de responderle a Allianz o al cliente, el bot le manda a un **correo interno del equipo**
(`RESUMEN_EQUIPO_EMAIL`) un digest con los tickets que necesitan acción y **el borrador que
propondría** el orquestador. Así el equipo ve el valor y usa los borradores a mano, sin ningún
envío autónomo a terceros.

Es opt-in: si `RESUMEN_EQUIPO_EMAIL` está vacío, no hace nada. Y es interno: envía SOLO a esa
dirección, por eso puede mandarse aunque el resto del sistema esté en DRY_RUN (no le escribe a
Allianz/clientes/WATI). El envío sale desde la casilla del token (hola@babilonia.ai).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app import config
from app.db import Repositorio

log = logging.getLogger(__name__)

# Estados de ticket que ameritan aparecer en el resumen (no resueltos).
_ESTADOS_ACCIONABLES = {"por_cerrar", "escalado_ceci", "esperando_cliente",
                        "esperando_asesor", "abierto", "esperando_allianz"}
# Estados de acción que representan "algo propuesto/pendiente" (no ya despachado a terceros).
_ACCIONES_VIVAS = {"sugerida", "pendiente_ceci", "pendiente_wati", "simulada"}


def _pay(a: dict) -> dict:
    p = a.get("payload")
    if isinstance(p, str):
        try:
            return json.loads(p)
        except Exception:  # noqa: BLE001
            return {}
    return p or {}


def _res(a: dict) -> dict:
    r = a.get("resultado")
    if isinstance(r, str):
        try:
            return json.loads(r)
        except Exception:  # noqa: BLE001
            return {}
    return r or {}


def _borrador_de(a: dict) -> str | None:
    """Texto del borrador que propone la acción (cuerpo a Allianz o mensaje)."""
    pay, res = _pay(a), _res(a)
    return pay.get("cuerpo") or res.get("cuerpo") or pay.get("mensaje")


def construir_digest(repo: Repositorio, limite: int = 50) -> tuple[str, str] | None:
    """Arma (asunto, cuerpo) del resumen. Devuelve None si no hay nada accionable."""
    tickets = repo.listar_tickets(limite=500)
    bloques: list[str] = []
    n = 0
    for t in tickets:
        estado = (t.get("estado") or "")
        if estado in ("resuelto",):
            continue
        acciones = [a for a in repo.listar_acciones(ticket_id=t["id"])
                    if a.get("estado") in _ACCIONES_VIVAS]
        if not acciones and estado not in _ESTADOS_ACCIONABLES:
            continue
        n += 1
        if n > limite:
            break
        cab = f"• Ticket {t.get('nro_ticket') or '—'}"
        if t.get("cliente_nombre"):
            cab += f" · {t['cliente_nombre']}"
        cab += f" · estado: {estado}"
        if t.get("vence_en"):
            cab += f" · vence: {str(t['vence_en'])[:16]}"
        lineas = [cab]
        if t.get("asunto_hilo"):
            lineas.append(f"    asunto: {t['asunto_hilo']}")
        for a in acciones:
            etiqueta = {"escalar_ceci": "⚠️ REQUIERE CECI", "enviar_a_allianz": "→ responder a Allianz",
                        "gestionar_tramite": "→ gestionar con Allianz", "instruir_tramite": "→ instruir al cliente",
                        "avisar_cliente": "→ avisar al cliente", "avisar_asesor": "→ avisar al asesor",
                        "recordatorio_sla": "⏰ SLA por vencer"}.get(a.get("tipo_accion"), a.get("tipo_accion"))
            lineas.append(f"    {etiqueta}  [{a.get('estado')}]")
            borrador = _borrador_de(a)
            if borrador and a.get("tipo_accion") in ("enviar_a_allianz", "gestionar_tramite",
                                                     "instruir_tramite", "avisar_cliente"):
                texto = borrador.strip().replace("\n", "\n      ")
                lineas.append(f"      BORRADOR PROPUESTO:\n      {texto}")
        bloques.append("\n".join(lineas))

    if not bloques:
        return None
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cuerpo = (
        f"Resumen de tickets Allianz — {hoy}\n"
        f"(Modo copiloto: el bot NO envió nada a Allianz ni a clientes; esto es solo para el equipo.)\n\n"
        + f"{n} ticket(s) con algo para revisar:\n\n"
        + "\n\n".join(bloques)
        + "\n\n— Tommi (seguimiento de tickets Allianz)"
    )
    asunto = f"[Tommi] {n} ticket(s) Allianz para revisar — {hoy}"
    return asunto, cuerpo


def _emisor_real():
    """Emisor Gmail forzado (envía desde hola@ SOLO al correo interno del equipo)."""
    from app.envio.gmail_api import EmisorGmail
    return EmisorGmail(config.SMTP_REMITENTE, config.SMTP_NOMBRE)


def enviar_resumen_equipo(repo: Repositorio, emisor=None) -> dict:
    """Manda el digest al correo interno del equipo. Opt-in por RESUMEN_EQUIPO_EMAIL."""
    destino = config.RESUMEN_EQUIPO_EMAIL
    if not destino:
        return {"enviado": False, "motivo": "sin RESUMEN_EQUIPO_EMAIL configurado"}
    dig = construir_digest(repo)
    if not dig:
        return {"enviado": False, "motivo": "nada accionable que reportar"}
    asunto, cuerpo = dig
    emisor = emisor or _emisor_real()
    res = emisor.enviar([destino], asunto, cuerpo)
    ok = bool(res.get("ok") or res.get("simulado"))
    log.info("resumen_equipo → %s: %s", destino, "ok" if ok else res.get("error"))
    return {"enviado": ok, "destino": destino, "asunto": asunto, "res": res}
