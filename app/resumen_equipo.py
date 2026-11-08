"""Resumen diario por correo para Ceci: lo que la está esperando en el panel.

Antes (modo copiloto) salía cada 4 horas, las 24 horas, con todos los tickets abiertos y los borradores
del orquestador viejo: el mismo correo 6 veces por día, con ruido y datos de salud (04/11). Ahora:

  - sale una vez por día hábil, a la hora RESUMEN_HORA_MX (hora de México, default 9);
  - solo lista los tickets que necesitan a Ceci, con el mismo criterio que la sección "Para Ceci" del
    panel (`api.motivos_para_ceci`), una línea por ticket y el link al panel. Sin borradores ni detalle;
  - si no hay nada, o la lista es igual a la del último envío, no manda nada.

Es opt-in (RESUMEN_EQUIPO_EMAIL) e interno: sale desde hola@ solo a esa dirección, aun en DRY_RUN.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from app import config
from app.db import Repositorio

log = logging.getLogger(__name__)

CLAVE_ULTIMO = "resumen_equipo:ultimo"
MEXICO = timezone(timedelta(hours=-6))  # México centro no tiene horario de verano desde 2022

MOTIVOS = {
    "sin_identificar": "cliente/asesor sin identificar",
    "escalado": "escalado",
    "para_aprobar": "correo para aprobar",
    "escalacion_bloqueada": "correo a Allianz bloqueado",
    "revisar": "revisar a mano",
    "rebote": "respuesta rebotada",
    "guia_por_aprobar": "guía de aportación por aprobar",
    "solicitud_tommy": "el cliente pidió un trámite",
}


def pendientes_ceci(repo: Repositorio) -> list[dict]:
    """Tickets que necesitan a Ceci (mismo criterio que el panel)."""
    from app.api import motivos_para_ceci
    salida = []
    for t in repo.listar_tickets(limite=500):
        motivos = motivos_para_ceci(repo, t)
        if motivos:
            salida.append({**t, "_motivos": motivos})
    return salida


def construir_digest(repo: Repositorio) -> tuple[str, str, str] | None:
    """(asunto, cuerpo, huella) o None si no hay nada que Ceci tenga que ver."""
    from app.acciones.mensajes_etapa import link_panel
    tickets = pendientes_ceci(repo)
    if not tickets:
        return None
    lineas, claves = [], []
    for t in tickets:
        quien = " · ".join(x for x in (t.get("cliente_nombre"), t.get("poliza")) if x) or (t.get("asunto_hilo") or "")[:60]
        nro = f"Ticket {t['nro_ticket']}" if t.get("nro_ticket") else f"Interno {t['id']}"
        linea = f"• {nro} — {quien}: {', '.join(MOTIVOS.get(m, m) for m in t['_motivos'])}"
        if link_panel(t["id"]):
            linea += f"\n  {link_panel(t['id'])}"
        lineas.append(linea)
        claves.append(f"{t['id']}:{','.join(sorted(t['_motivos']))}")
    huella = hashlib.sha256("|".join(sorted(claves)).encode()).hexdigest()[:16]
    n = len(tickets)
    hoy = datetime.now(MEXICO).strftime("%d/%m")
    asunto = f"[Tommi] {n} ticket{'s' if n != 1 else ''} Allianz te esperan en el panel — {hoy}"
    cuerpo = (f"Hola Ceci, esto es lo que hoy necesita tu revisión en el panel de tickets Allianz:\n\n"
              + "\n".join(lineas)
              + "\n\nTe llega una vez por día hábil y solo si cambió algo desde el anterior.\n— Tommi")
    return asunto, cuerpo, huella


def _emisor_real():
    """Emisor Gmail forzado (envía desde hola@ SOLO al correo interno del equipo)."""
    from app.envio.gmail_api import EmisorGmail
    return EmisorGmail(config.SMTP_REMITENTE, config.SMTP_NOMBRE)


def enviar_resumen_equipo(repo: Repositorio, emisor=None, ahora: datetime | None = None) -> dict:
    destino = config.RESUMEN_EQUIPO_EMAIL
    if not destino:
        return {"enviado": False, "motivo": "sin RESUMEN_EQUIPO_EMAIL configurado"}
    if (ahora or datetime.now(MEXICO)).astimezone(MEXICO).weekday() >= 5:
        return {"enviado": False, "motivo": "fin de semana"}
    dig = construir_digest(repo)
    if not dig:
        return {"enviado": False, "motivo": "nada que revisar"}
    asunto, cuerpo, huella = dig
    if repo.leer_valor(CLAVE_ULTIMO) == huella:
        return {"enviado": False, "motivo": "igual al último resumen"}
    emisor = emisor or _emisor_real()
    res = emisor.enviar([destino], asunto, cuerpo)
    ok = bool(res.get("ok") or res.get("simulado"))
    if ok:
        repo.guardar_valor(CLAVE_ULTIMO, huella)
    log.info("resumen_equipo → %s: %s", destino, "ok" if ok else res.get("error"))
    return {"enviado": ok, "destino": destino, "asunto": asunto, "res": res}
