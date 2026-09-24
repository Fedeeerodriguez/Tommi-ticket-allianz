"""Sincroniza la base de Notion 'Ticket Allianz Seguimiento' (panel de evaluación, sandbox).

Una fila por ACCIÓN PROPUESTA (respuesta a Allianz / aviso a cliente / escalar Ceci…), con el
BORRADOR y un campo **Veredicto** (Pendiente/Aprobado/Rechazado) que edita el equipo. El bot
crea/actualiza los datos, pero NUNCA pisa el Veredicto ni las Notas de Ceci (son del humano).

Es un panel de REVISIÓN interno: escribe SOLO en esta base de Notion, nunca le manda nada al
cliente/Allianz, así que corre aunque DRY_RUN=true. La idempotencia la da `AccionID` (id de la
acción en la DB).
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone

from app import config
from app.db import Repositorio

log = logging.getLogger(__name__)
_API = "https://api.notion.com/v1"

# Acciones "vivas" (propuestas / pendientes) que ameritan revisión.
_ESTADOS_VIVOS = {"sugerida", "pendiente_ceci", "pendiente_wati", "simulada"}
_ETIQUETA = {
    "enviar_a_allianz": "Responder a Allianz", "gestionar_tramite": "Gestionar con Allianz",
    "instruir_tramite": "Instruir al cliente", "avisar_cliente": "Avisar al cliente",
    "avisar_asesor": "Avisar al asesor", "escalar_ceci": "Escalar a Ceci",
    "recordatorio_sla": "Recordatorio SLA", "recordatorio": "Recordatorio",
    "consulta_general": "Consulta a Ceci", "reactivacion": "Reactivar ticket",
}


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.NOTION_TOKEN}",
            "Content-Type": "application/json", "Notion-Version": "2022-06-28"}


def _req(path: str, payload: dict, method: str) -> dict:
    r = urllib.request.Request(f"{_API}/{path}", data=json.dumps(payload).encode(),
                               method=method, headers=_headers())
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.load(resp)


def _rt(texto) -> list:
    """rich_text (Notion corta a 2000 chars por bloque)."""
    s = (str(texto) if texto is not None else "")[:1900]
    return [{"type": "text", "text": {"content": s}}] if s else []


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


def _borrador(a: dict) -> str:
    pay, res = _pay(a), _res(a)
    return (pay.get("cuerpo") or res.get("cuerpo") or pay.get("mensaje") or "").strip()


def _buscar_pagina(db_id: str, accion_id: int) -> str | None:
    resp = _req(f"databases/{db_id}/query",
                {"filter": {"property": "AccionID", "number": {"equals": accion_id}},
                 "page_size": 1}, "POST")
    r = resp.get("results", [])
    return r[0]["id"] if r else None


def _props(t: dict, a: dict) -> dict:
    """Propiedades gestionadas por el BOT (no incluye Veredicto/Notas: esos son del humano)."""
    tipo = a.get("tipo_accion", "")
    etiqueta = _ETIQUETA.get(tipo, tipo)
    nro = t.get("nro_ticket") or "s/n"
    props = {
        "Acción": {"title": _rt(f"{etiqueta} · Ticket {nro}")},
        "Ticket": {"rich_text": _rt(nro)},
        "Cliente": {"rich_text": _rt(t.get("cliente_nombre") or "")},
        "Asunto": {"rich_text": _rt(t.get("asunto_hilo") or "")},
        "Estado ticket": {"select": {"name": t.get("estado") or "abierto"}},
        "Canal": {"select": {"name": a.get("canal") or "interno"}},
        "Borrador": {"rich_text": _rt(_borrador(a))},
        "AccionID": {"number": a.get("id")},
        "TicketID": {"number": t.get("id")},
    }
    v = t.get("vence_en")
    if v:
        props["Vence"] = {"date": {"start": str(v)[:10]}}
    return props


def sincronizar_seguimiento(repo: Repositorio) -> dict:
    """Vuelca a Notion las acciones propuestas de tickets no resueltos. Idempotente por AccionID.
    Preserva Veredicto/Notas del equipo (solo los setea 'Pendiente' al crear la fila)."""
    db = config.NOTION_DB_SEGUIMIENTO
    if not (config.NOTION_TOKEN and db):
        return {"ok": False, "motivo": "sin NOTION_DB_SEGUIMIENTO"}
    creadas = actualizadas = 0
    for t in repo.listar_tickets(limite=500):
        if (t.get("estado") or "") == "resuelto":
            continue
        for a in repo.listar_acciones(ticket_id=t["id"]):
            if a.get("estado") not in _ESTADOS_VIVOS:
                continue
            props = _props(t, a)
            try:
                pid = _buscar_pagina(db, a["id"])
                if pid:
                    _req(f"pages/{pid}", {"properties": props}, "PATCH")
                    actualizadas += 1
                else:
                    props["Veredicto"] = {"select": {"name": "Pendiente"}}  # solo al crear
                    _req("pages", {"parent": {"database_id": db}, "properties": props}, "POST")
                    creadas += 1
            except Exception as ex:  # noqa: BLE001
                log.warning("seguimiento: falló acción %s: %s", a.get("id"), ex)
    log.info("seguimiento Notion: %d creadas, %d actualizadas", creadas, actualizadas)
    return {"ok": True, "creadas": creadas, "actualizadas": actualizadas}
