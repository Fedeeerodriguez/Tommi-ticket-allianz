"""Extracción de entidades de un correo: nº de ticket, póliza, cliente.

Regex puro (barato). Se combina con lo que ya haya detectado el clasificador
(`clf.entidades`). El cruce fino (asesor/DAF) lo hace `enriquecimiento` contra Notion.
"""
from __future__ import annotations

import re

from app import config
from app.models import Clasificacion, Correo

_RE_TICKET = re.compile(
    r"(?:ticket|folio|caso|solicitud)\s*(?:n[°ºo]?\.?|#|:)?\s*([0-9][0-9\-]{3,}|[A-Z]{1,4}[0-9][A-Z0-9\-]{2,})",
    re.I,
)
# Póliza: token alfanumérico con guion tipo PLU3-412364, o "póliza <token>".
_RE_POLIZA_KW = re.compile(r"\bp[oó]liza\s*[:#nº]*\s*([A-Z0-9][A-Z0-9\-]{4,})\b", re.I)
_RE_POLIZA_PAT = re.compile(r"\b([A-Z]{2,5}\d?-\d{4,7})\b")


def _es_allianz(direccion: str) -> bool:
    d = direccion.split("@")[-1].lower()
    return any(d == dom or d.endswith("." + dom) for dom in config.ALLIANZ_DOMINIOS)


def _es_babilonia(direccion: str) -> bool:
    return direccion.lower() in set(config.BABILONIA_ADDRESSES)


def extraer(correo: Correo, clf: Clasificacion | None = None) -> dict:
    texto = f"{correo.asunto}\n{correo.cuerpo_texto}"
    ent: dict = dict(clf.entidades) if clf and clf.entidades else {}

    if not ent.get("nro_ticket"):
        m = _RE_TICKET.search(texto)
        if m:
            ent["nro_ticket"] = m.group(1)

    if not ent.get("poliza"):
        m = _RE_POLIZA_KW.search(texto) or _RE_POLIZA_PAT.search(texto)
        if m:
            ent["poliza"] = m.group(1)

    # Cliente: la dirección que NO es Allianz ni Babilonia (entre remitente/para/cc).
    candidatas = [correo.remitente, *correo.para, *correo.cc]
    for dire in candidatas:
        if dire and not _es_allianz(dire) and not _es_babilonia(dire):
            ent.setdefault("cliente_correo", dire)
            break

    # Nombre del cliente: si el remitente es el cliente, tomamos su display name del header From.
    if correo.remitente and not _es_allianz(correo.remitente) and not _es_babilonia(correo.remitente):
        raw_from = correo.headers.get("from", "")
        nombre = raw_from.split("<")[0].strip().strip('"') if "<" in raw_from else ""
        if nombre:
            ent.setdefault("cliente_nombre", nombre)

    return ent
