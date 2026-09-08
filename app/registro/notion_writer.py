"""Write-back del ticket a la base `Tickets Allianz` de Notion (objetivo 3).

Mapea nuestro ticket interno al esquema real que ya usa José (Estado, Estado Interno de
Allianz, Tipo de Trámite, Ticket Allianz, Requerimiento, Emisiones, fechas) y hace UPSERT:
busca la página por `Ticket Allianz` (número) y la crea o actualiza; además deja una
entrada de bitácora fechada en el cuerpo de la página.

⚠️ SEGURIDAD: respeta `DRY_RUN`. En dry-run arma el payload y lo devuelve, pero NO escribe
en Notion. Esa base también la puebla el Zapier viejo de José → antes de escribir en vivo
hay que apagar ese flujo para no duplicar.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from datetime import datetime, timezone

from app import config
from app.models import Correo, EstadoTicket

log = logging.getLogger(__name__)
_API = "https://api.notion.com/v1"

# EstadoTicket (interno) → opción de `Estado` en Notion.
_ESTADO_NOTION = {
    EstadoTicket.ABIERTO.value: "🟡 Por iniciar",
    EstadoTicket.ESPERANDO_ALLIANZ.value: "🟠 Pendiente Allianz",
    EstadoTicket.ESPERANDO_CLIENTE.value: "🔴 Pendiente Cliente",
    EstadoTicket.ESPERANDO_ASESOR.value: "⚪️ Pendiente Babilonia",
    EstadoTicket.RESUELTO.value: "🟢 Resuelto",
    EstadoTicket.ESCALADO_CECI.value: "⚪️ Pendiente Babilonia",
}

# tipo de correo → `Estado Interno de Allianz`.
_INTERNO_ALLIANZ = {
    "B_acuse_ticket": "NUEVA SOLICITUD",
    "A_respuesta_ticket": "NUEVO MENSAJE",
    "C_allianz_pide": "NUEVO MENSAJE",
    "E_cc_cliente": "NUEVA SOLICITUD",
    "D_reenvio_asesor": "NUEVA SOLICITUD",
}

# inferencia de `Tipo de Trámite` a partir del texto.
_TRAMITES = [
    (r"beneficiari", "Cambio de beneficiario"),
    (r"cancelaci|cancelar", "Cancelación"),
    (r"rehabilitaci", "Rehabilitación"),
    (r"siniestro|reclamaci", "Siniestro"),
    (r"cobranza|cobro|pago|forma\s+de\s+pago", "Cobranza"),
    (r"renovaci", "RENOVACIÓN"),
    (r"endoso|cambio", "Endoso"),
    (r"emisi[oó]n", "Emisión"),
]


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.NOTION_TOKEN}",
            "Content-Type": "application/json", "Notion-Version": "2022-06-28"}


def _post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(f"{_API}/{path}", data=json.dumps(payload).encode(),
                                 method="POST", headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _patch(path: str, payload: dict) -> dict:
    req = urllib.request.Request(f"{_API}/{path}", data=json.dumps(payload).encode(),
                                 method="PATCH", headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _tipo_tramite(texto: str) -> str | None:
    for patron, nombre in _TRAMITES:
        if re.search(patron, texto, re.I):
            return nombre
    return None


def _num_ticket(nro) -> int | None:
    if not nro:
        return None
    m = re.search(r"\d{3,}", str(nro))
    return int(m.group()) if m else None


def construir_payload(ticket: dict, notion_enrich: dict, correo: Correo, tipo_correo: str) -> dict:
    """Arma las `properties` de la página de Notion a partir del ticket + enriquecimiento."""
    texto = f"{correo.asunto}\n{correo.cuerpo_texto}"
    ahora = datetime.now(timezone.utc).isoformat()
    cliente = ticket.get("cliente_nombre") or notion_enrich.get("cliente_nombre") or "Cliente"
    poliza = ticket.get("poliza") or notion_enrich.get("poliza")
    titulo = f"{cliente}" + (f" · póliza {poliza}" if poliza else "")

    props: dict = {
        "Nombre del Trámite": {"title": [{"text": {"content": titulo[:190]}}]},
        "Requerimiento": {"rich_text": [{"text": {"content": (correo.cuerpo_texto or correo.asunto or "")[:1900]}}]},
        "Última Actualización": {"date": {"start": ahora}},
    }
    estado_notion = _ESTADO_NOTION.get(ticket.get("estado"))
    if estado_notion:
        props["Estado"] = {"status": {"name": estado_notion}}
    interno = _INTERNO_ALLIANZ.get(tipo_correo)
    if interno:
        props["Estado Interno de Allianz"] = {"status": {"name": interno}}
    tramite = _tipo_tramite(texto)
    if tramite:
        props["Tipo de Trámite"] = {"select": {"name": tramite}}
    n = _num_ticket(ticket.get("nro_ticket"))
    if n is not None:
        props["Ticket Allianz"] = {"number": n}
    # Vincular a la póliza (relación Emisiones) si el enriquecimiento la resolvió.
    if notion_enrich.get("emision_id"):
        props["Emisiones"] = {"relation": [{"id": notion_enrich["emision_id"]}]}
    if tipo_correo == "A_respuesta_ticket":
        props["Última Respuesta Allianz"] = {"date": {"start": ahora}}
    return props


def _buscar_pagina(nro_ticket_num: int) -> str | None:
    r = _post(f"databases/{config.NOTION_DB_TICKETS_ALLIANZ}/query",
              {"filter": {"property": "Ticket Allianz", "number": {"equals": nro_ticket_num}}, "page_size": 1})
    res = r.get("results", [])
    return res[0]["id"] if res else None


def _bitacora_block(texto: str) -> dict:
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": f"[{fecha}] {texto}"[:1900]}}]}}


def registrar_en_notion(ticket: dict, notion_enrich: dict, correo: Correo, tipo_correo: str,
                        bitacora: str | None = None) -> dict:
    """UPSERT del ticket en Notion. Respeta DRY_RUN (no escribe; devuelve el payload)."""
    if not config.hay_notion() or not config.NOTION_DB_TICKETS_ALLIANZ:
        return {"ok": False, "motivo": "Notion no configurado"}

    props = construir_payload(ticket, notion_enrich, correo, tipo_correo)

    if config.DRY_RUN:
        return {"ok": True, "dry_run": True, "accion": "PAYLOAD (no escrito)", "properties": props}

    try:
        n = _num_ticket(ticket.get("nro_ticket"))
        page_id = _buscar_pagina(n) if n is not None else None
        if page_id:
            _patch(f"pages/{page_id}", {"properties": props})
            accion = "actualizada"
        else:
            creada = _post("pages", {"parent": {"database_id": config.NOTION_DB_TICKETS_ALLIANZ},
                                     "properties": props})
            page_id = creada.get("id")
            accion = "creada"
        if bitacora and page_id:
            _patch(f"blocks/{page_id}/children", {"children": [_bitacora_block(bitacora)]})
        return {"ok": True, "dry_run": False, "accion": accion, "page_id": page_id}
    except Exception as ex:  # noqa: BLE001
        log.error("registro en Notion falló: %s", ex)
        return {"ok": False, "motivo": str(ex)}
