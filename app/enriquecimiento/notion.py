"""Cruce con Notion (M6): dada la póliza (o el correo del cliente) de un ticket, resuelve
asesor, DAF, cliente y producto contra la base EMISIONES real de Tommy.

Cliente HTTP mínimo con urllib (stdlib) → sin dependencias nuevas. Reusa NOTION_TOKEN y
los NOTION_DB_* del backend principal. Reglas de negocio confirmadas:
  - `Correo Asesor` = el asesor ante el CLIENTE.
  - `Asesor DAF`    = el asesor ante ALLIANZ (el DAF).
"""
from __future__ import annotations

import json
import logging
import urllib.request

from app import config

log = logging.getLogger(__name__)

_API = "https://api.notion.com/v1"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


def _query(db_id: str, filt: dict, page_size: int = 1) -> list[dict]:
    if not (config.NOTION_TOKEN and db_id):
        return []
    payload = {"page_size": page_size}
    if filt:
        payload["filter"] = filt
    req = urllib.request.Request(f"{_API}/databases/{db_id}/query",
                                 data=json.dumps(payload).encode(), method="POST", headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("results", [])
    except Exception as ex:  # noqa: BLE001
        log.warning("Notion query falló (db=%s): %s", db_id[:8], ex)
        return []


# ---------- lectura de propiedades ----------
def _texto(prop: dict | None) -> str | None:
    if not prop:
        return None
    t = prop.get("type")
    v = prop.get(t)
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in (v or [])) or None
    if t in ("select", "status"):
        return v.get("name") if v else None
    if t == "email":
        return v
    if t == "number":
        return v
    return None


def _persona(prop: dict | None) -> tuple[str | None, str | None]:
    """Devuelve (nombre, email) del primer 'people' de una prop people o rollup-people."""
    if not prop:
        return None, None
    t = prop.get("type")
    gente = []
    if t == "people":
        gente = prop.get("people") or []
    elif t == "rollup":
        for item in (prop.get("rollup", {}).get("array") or []):
            if item.get("type") == "people":
                gente = item.get("people") or []
                break
    if not gente:
        return None, None
    p0 = gente[0]
    email = (p0.get("person") or {}).get("email")
    return p0.get("name"), email


def _extraer_emision(page: dict) -> dict:
    props = page.get("properties", {})
    asesor_nombre, asesor_email_people = _persona(props.get("Asesor"))
    daf_nombre, _ = _persona(props.get("Asesor DAF"))
    lider_nombre, _ = _persona(props.get("Líder"))
    return {
        "found": True,
        "fuente": "emisiones",
        "emision_id": page.get("id"),
        "poliza": _texto(props.get("Número de Póliza")),
        "cliente_nombre": _texto(props.get("Nombre Cliente")),
        "cliente_correo": _texto(props.get("Correo Cliente")),
        "telefono_cliente": _texto(props.get("Teléfono Cliente")),
        "asesor_correo": _texto(props.get("Correo Asesor")) or asesor_email_people,
        "asesor_nombre": asesor_nombre,
        "daf_nombre": daf_nombre,          # `Asesor DAF` = asesor ante Allianz
        "lider_nombre": lider_nombre,
        "producto": _texto(props.get("Producto (nombre)")),
        "estado_poliza": _texto(props.get("Estado")),
    }


def enriquecer(entidades: dict) -> dict:
    """Cruza por póliza (preferido) o por correo de cliente. Devuelve {} si no encuentra
    o si no hay Notion configurado."""
    if not config.hay_notion():
        return {}
    poliza = entidades.get("poliza")
    cliente_correo = entidades.get("cliente_correo")

    if poliza:
        res = _query(config.NOTION_DB_EMISIONES,
                     {"property": "Número de Póliza", "rich_text": {"contains": poliza}})
        if res:
            return _extraer_emision(res[0])

    if cliente_correo:
        res = _query(config.NOTION_DB_EMISIONES,
                     {"property": "Correo Cliente", "rich_text": {"contains": cliente_correo}})
        if res:
            return _extraer_emision(res[0])

    return {}
