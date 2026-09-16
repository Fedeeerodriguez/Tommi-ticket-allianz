"""Clasificación y extracción de correos de Allianz — FUENTE ÚNICA DE VERDAD.

La usan el clasificador L1 (pipeline en vivo) y el sandbox (análisis), así hay una sola
implementación de las reglas de negocio (ver docs/PLAN_TICKETS_ALLIANZ.md).

Reglas confirmadas por el equipo:
  - "Sistema escribió un mensaje" → asignación / recordatorio / cierre (según el cuerpo).
  - "creó una nueva solicitud en su nombre" → apertura (nosotros abrimos el ticket).
  - "<actor> escribió un mensaje" → nombre = agente Allianz; correo = externo (cliente/asesor/Babilonia).
  - "solicitud cerrada/atendida/finalizada" → cierre.
Allianz manda el texto en Unicode descompuesto (NFD) → se normaliza a NFC antes de matchear.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app import config

# --- Patrones (canónicos) ---
RE_TICKET = re.compile(r"ticket[-\s#]*([0-9]{4,})", re.I)
RE_SOLICITUD = re.compile(r"solicitud[:\s#]*([0-9]{4,})", re.I)
RE_POLIZA = re.compile(r"\b([A-Z]{2,4}[0-9][A-Z0-9]*-?[0-9]{3,}(?:-[0-9])?)\b")
RE_CIERRE = re.compile(
    r"(solicitud\s+(?:cerrada|atendida|finalizada)|se\s+ha\s+cerrad|ticket\s+cerrad|"
    r"caso\s+cerrad|finalizad\w*\s+ticket)", re.I)
RE_RECORDATORIO = re.compile(
    r"(recordatorio|por\s+cerrar|pr[oó]xim\w*\s+a\s+cerrar|falta\s+de\s+respuesta|sin\s+respuesta|"
    r"cerrad\w*\s+autom[aá]tic|por\s+inactividad|iniciar\s+nuevamente|no\s+recibir\s+la\s+solicitud)", re.I)
RE_CREO_SOLICITUD = re.compile(r"cre[oó]\s+una\s+nueva\s+solicitud", re.I)
RE_SISTEMA_MSG = re.compile(r"sistema\s+escrib\w*\s+un\s+mensaje", re.I)
RE_ESCRIBIO = re.compile(r"escrib\w*\s+un\s+mensaje", re.I)
RE_DEADLINE = re.compile(r"(\d+\s*(?:d[ií]as?|horas?|h[aá]biles?)(?:\s*h[aá]biles?)?)", re.I)
# Acciones críticas → confirmación desde el correo del cliente + revisión de Ceci.
RE_CRITICO = re.compile(
    r"(cancelaci[oó]n\s+de\s+p[oó]liza|cancelar\s+(?:la\s+)?p[oó]liza|"
    r"suspensi[oó]n\s+de\s+aportaci|suspender\s+aportaci|"
    r"per[ií]odo\s+de\s+descanso|a[ñn]o\s+de\s+descanso|"
    r"rescate|retiro\s+total|fallecimiento|defunci|siniestro)", re.I)
_SUBJETO_NOTIF = {
    "daf": re.compile(r"\bDAF\b", re.I),
    "emision": re.compile(r"emisi[oó]n", re.I),
    "cobranza": re.compile(r"cobranza", re.I),
}


class SubtipoAllianz(str, Enum):
    APERTURA_NUESTRA = "apertura_nuestra"        # "creó una nueva solicitud en su nombre"
    ASIGNACION_TICKET = "asignacion_ticket"      # "Sistema escribió un mensaje" (asigna nº)
    RECORDATORIO = "recordatorio"                # "Sistema..." + por cerrar por inactividad
    RESPUESTA_PARTICIPANTE = "respuesta_participante"  # "<actor> escribió un mensaje"
    CIERRE = "cierre"                            # "solicitud cerrada/atendida/finalizada"
    TICKET_OTRO = "ticket_otro"                  # tiene nº de ticket pero patrón no reconocido
    NOTIF_DAF = "notif_daf"
    NOTIF_EMISION = "notif_emision"
    NOTIF_COBRANZA = "notif_cobranza"
    NOTIF_SISTEMA = "notif_sistema"
    OTRO = "otro"


SUBTIPOS_TICKET = {
    SubtipoAllianz.APERTURA_NUESTRA, SubtipoAllianz.ASIGNACION_TICKET, SubtipoAllianz.RECORDATORIO,
    SubtipoAllianz.RESPUESTA_PARTICIPANTE, SubtipoAllianz.CIERRE, SubtipoAllianz.TICKET_OTRO,
}


@dataclass
class InfoAllianz:
    subtipo: SubtipoAllianz
    es_ticket: bool
    nro_ticket: Optional[str] = None
    nro_solicitud: Optional[str] = None
    poliza: Optional[str] = None
    actor: Optional[str] = None
    actor_tipo: Optional[str] = None   # 'sistema' | 'nombre' (agente Allianz) | 'correo' (externo)
    plazos: list[str] = field(default_factory=list)
    critico: bool = False


def nfc(s: Optional[str]) -> str:
    return unicodedata.normalize("NFC", s or "")


def direccion(remitente: str) -> str:
    """Devuelve solo la dirección en minúsculas de un 'Nombre <a@b>' o 'a@b'."""
    m = re.search(r"<([^>]+)>", remitente or "")
    return (m.group(1) if m else (remitente or "")).strip().lower()


def es_correo_allianz(remitente: str) -> bool:
    dom = direccion(remitente).split("@")[-1]
    return any(dom == d or dom.endswith("." + d) for d in config.ALLIANZ_DOMINIOS)


def _actor(asunto: str) -> tuple[Optional[str], Optional[str]]:
    """De '[Allianz México Ticket-XXXX] <ACTOR> escribió un mensaje' saca el actor y su tipo."""
    m = re.search(r"\]\s*(.+?)\s+escrib\w*\s+un\s+mensaje", asunto, re.I)
    if not m:
        return None, None
    actor = m.group(1).strip()
    if actor.lower() == "sistema":
        return actor, "sistema"
    return actor, ("correo" if "@" in actor else "nombre")


def _subtipo(remitente: str, asunto: str, cuerpo: str) -> tuple[SubtipoAllianz, bool]:
    addr = direccion(remitente)
    dom, local = addr.split("@")[-1], addr.split("@")[0]
    if RE_CIERRE.search(asunto) or RE_CIERRE.search(cuerpo):
        return SubtipoAllianz.CIERRE, True
    if RE_TICKET.search(asunto):
        if RE_CREO_SOLICITUD.search(asunto):
            return SubtipoAllianz.APERTURA_NUESTRA, True
        if RE_SISTEMA_MSG.search(asunto):
            return (SubtipoAllianz.RECORDATORIO if RE_RECORDATORIO.search(cuerpo)
                    else SubtipoAllianz.ASIGNACION_TICKET), True
        if RE_ESCRIBIO.search(asunto):
            return SubtipoAllianz.RESPUESTA_PARTICIPANTE, True
        return SubtipoAllianz.TICKET_OTRO, True
    if "allianz" in dom:
        for clave, rx in _SUBJETO_NOTIF.items():
            if rx.search(asunto):
                return SubtipoAllianz(f"notif_{clave}"), False
        if any(t in local for t in ("noreply", "no-reply", "notif", "aviso", "mailer")):
            return SubtipoAllianz.NOTIF_SISTEMA, False
    return SubtipoAllianz.OTRO, False


def clasificar_allianz(asunto: str, cuerpo: str, remitente: str) -> InfoAllianz:
    """Clasifica y extrae un correo de Allianz. Normaliza a NFC internamente."""
    asunto, cuerpo = nfc(asunto), nfc(cuerpo)
    texto = f"{asunto}\n{cuerpo}"
    subtipo, es_ticket = _subtipo(remitente, asunto, cuerpo)
    actor, actor_tipo = _actor(asunto)
    mt = RE_TICKET.search(asunto) or RE_TICKET.search(cuerpo)
    ms = RE_SOLICITUD.search(texto)
    mp = RE_POLIZA.search(texto)
    return InfoAllianz(
        subtipo=subtipo,
        es_ticket=es_ticket,
        nro_ticket=mt.group(1) if mt else None,
        nro_solicitud=ms.group(1) if ms else None,
        poliza=mp.group(1) if mp else None,
        actor=actor,
        actor_tipo=actor_tipo,
        plazos=list(dict.fromkeys(m.strip() for m in RE_DEADLINE.findall(cuerpo)))[:4],
        critico=bool(RE_CRITICO.search(texto)),
    )
