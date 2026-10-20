"""Etapa 2 — aprobaciones de Ceci: la guía de aportación del proceso corto.

El motor (motor_etapas.py) deja la guía PENDIENTE al llegar la confirmación de datos (C2). Nada
sale al cliente ni al asesor hasta que Ceci la aprueba, por Telegram (rieles/telegram.py) o desde
el panel; las dos vías terminan acá. Reglas:
  - se resuelve una sola vez (la base lo garantiza: Telegram y el panel no la aprueban dos veces);
  - no se aprueba con datos sin completar ("[completar …]") ni sin cliente/asesor identificado;
  - al aprobar: guía al cliente y aviso al asesor (avisos únicos) + arranca el recordatorio de pago;
  - corregir = versión nueva, sigue pendiente (lo que se aprueba es exactamente lo que se ve).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app import config
from app.db import Repositorio

from . import mensajes_etapa
from .motor_etapas import GUIA, REC_PAGO, _DEST_REC, _ahora, _encolar, mas_horas_habiles

log = logging.getLogger(__name__)


def _resultado(ok: bool, motivo: str, **extra) -> dict:
    return {"ok": ok, "motivo": motivo, "plan": [], **extra}


def _ctx(repo: Repositorio, ticket: dict, guia: str) -> dict:
    datos = {"cliente_nombre": ticket.get("cliente_nombre")}
    return {**mensajes_etapa.contexto(ticket, {}, datos), "ticket_id": ticket["id"], "guia": guia}


def puede_aprobarse(repo: Repositorio, ap: Optional[dict], texto: Optional[str] = None) -> Optional[str]:
    """None si se puede aprobar; si no, el motivo (se le muestra a Ceci tal cual)."""
    if not ap:
        return "No encontré esa guía."
    if ap.get("estado") != "pendiente":
        return f"Esa guía ya estaba {ap.get('estado')}."
    if mensajes_etapa.FALTA_COMPLETAR in (texto or ap.get("texto") or ""):
        return "La guía tiene datos sin completar ([completar]). Corrígela antes de aprobarla."
    ticket = repo.obtener_ticket(ap["ticket_id"]) or {}
    if not ticket.get("identificado_por"):
        return "Todavía no está identificado el cliente/asesor del ticket: asígnalo en el panel y vuelve a aprobar."
    return None


def aprobar(repo: Repositorio, aprobacion_id: int, por: str, texto: Optional[str] = None,
            ahora: Optional[datetime] = None) -> dict:
    """Aprueba la guía (con `texto` si Ceci la corrigió al aprobar) y la manda a cliente y asesor."""
    ap = repo.obtener_aprobacion(aprobacion_id)
    texto = (texto or "").strip() or None
    motivo = puede_aprobarse(repo, ap, texto)
    if motivo:
        return _resultado(False, motivo)
    cambio = texto if texto and texto != ap["texto"] else None
    if not repo.resolver_aprobacion(aprobacion_id, "aprobada", por, cambio):
        return _resultado(False, "Esa guía ya se había resuelto.")
    ahora = _ahora(ahora)
    ap = repo.obtener_aprobacion(aprobacion_id)
    ticket = repo.obtener_ticket(ap["ticket_id"]) or {"id": ap["ticket_id"]}
    tid, ronda = ticket["id"], int(ap.get("ronda") or 1)
    ctx = _ctx(repo, ticket, ap["texto"])
    params = mensajes_etapa.params_wati(ctx, GUIA, ticket.get("telefono_cliente"), "corto")
    res = _resultado(True, "Guía aprobada.")
    omitidos: list[str] = []
    for rol in ("cliente", "asesor"):
        if ticket.get("delicado"):
            omitidos.append(f"Ticket delicado: no se le mandó la guía al {rol}.")
            continue
        numero = ticket.get(f"telefono_{rol}")
        if not numero:
            omitidos.append(f"Falta el teléfono del {rol} en Notion: no se le mandó la guía.")
            continue
        t = mensajes_etapa.texto(rol, GUIA, ctx, proceso="corto")
        a = _encolar(repo, tid, rol, t, GUIA, ronda, str(numero), ap.get("correo_id"), params)
        if a:
            res["plan"].append(a)
    if omitidos:
        t = mensajes_etapa.texto("ceci", GUIA, {**ctx, "guia": "(ver panel)"}, omitidos, proceso="corto")
        a = _encolar(repo, tid, "ceci", t, GUIA, ronda, None, ap.get("correo_id"), params)
        if a:
            res["plan"].append(a)

    # Arranca la espera del pago (cliente + asesor; escala a asesor + Ceci).
    vence = mas_horas_habiles(ahora, config.RECORDATORIO_PAGO_HORAS_HABILES)
    escala = mas_horas_habiles(vence, config.ESCALA_HORAS_HABILES)
    if repo.crear_recordatorio(tid, REC_PAGO, _DEST_REC[REC_PAGO], vence, escala, ap.get("correo_id"),
                               nota="guía de aportación aprobada: falta el pago"):
        res["recordatorio_pago"] = vence
    repo.agregar_evento(tid, ap.get("correo_id"), "guia_aprobada",
                        f"Guía de aportación aprobada por {por} (v{ap.get('version')}) · "
                        f"avisos: {', '.join(a['rol'] for a in res['plan']) or 'ninguno'}"[:200])
    return res


def descartar(repo: Repositorio, aprobacion_id: int, por: str) -> dict:
    """Ceci la descarta: no sale nada (ej. la guía ya se mandó a mano)."""
    ap = repo.obtener_aprobacion(aprobacion_id)
    if not ap:
        return _resultado(False, "No encontré esa guía.")
    if not repo.resolver_aprobacion(aprobacion_id, "descartada", por):
        return _resultado(False, f"Esa guía ya estaba {ap.get('estado')}.")
    repo.agregar_evento(ap["ticket_id"], ap.get("correo_id"), "guia_descartada",
                        f"Guía de aportación descartada por {por}: no se mandó nada")
    return _resultado(True, "Guía descartada: no se mandó nada.")


def corregir(repo: Repositorio, aprobacion_id: int, texto: str, por: str) -> dict:
    """Versión nueva del texto; sigue pendiente (hay que aprobar lo que se ve)."""
    ap = repo.obtener_aprobacion(aprobacion_id)
    texto = (texto or "").strip()
    if not ap:
        return _resultado(False, "No encontré esa guía.")
    if ap.get("estado") != "pendiente":
        return _resultado(False, f"Esa guía ya estaba {ap.get('estado')}.")
    if not texto:
        return _resultado(False, "El texto nuevo está vacío.")
    version = int(ap.get("version") or 1) + 1
    repo.actualizar_aprobacion(aprobacion_id, texto=texto, version=version)
    repo.agregar_evento(ap["ticket_id"], ap.get("correo_id"), "guia_corregida",
                        f"Guía de aportación corregida por {por} (v{version})")
    return _resultado(True, f"Guía corregida (versión {version}).", version=version)


def pendientes(repo: Repositorio) -> list[dict]:
    return repo.listar_aprobaciones(estados=["pendiente"])
