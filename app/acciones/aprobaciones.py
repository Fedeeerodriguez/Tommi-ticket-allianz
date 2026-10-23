"""Etapa 2 — aprobaciones de Ceci: la guía de aportación del proceso corto.

El motor (motor_etapas.py) deja la guía PENDIENTE al llegar la confirmación de datos (C2). Nada
sale al cliente ni al asesor hasta que Ceci la aprueba, por Telegram (rieles/telegram.py) o desde
el panel; las dos vías terminan acá.

Cada producto tiene su guía y su plantilla de WATI (mensajes_etapa.GUIAS). El sistema pone nombre,
producto, póliza y ticket; Ceci completa o confirma sus campos (no texto libre: WhatsApp no deja
cambiar el texto de una plantilla):
  - Patrimonial y Elite: el MONTO y el N° DE SOLICITUD (este viene del correo de Allianz; Ceci lo confirma);
  - el resto (OptiMaxx Plus): MONTO y DATOS PARA DEPOSITAR.
Reglas:
  - se resuelve una sola vez (la base lo garantiza: Telegram y el panel no la aprueban dos veces);
  - no se aprueba con campos vacíos, ni sin cliente/asesor identificado;
  - al aprobar: guía al cliente y aviso al asesor (avisos únicos) + recordatorio de pago, solo en los
    productos de RECORDATORIO_PAGO_PRODUCTOS (Patrimonial y Elite no: el cliente paga por su cuenta);
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


def _campos(monto: Optional[str] = None, datos_deposito: Optional[str] = None,
            solicitud: Optional[str] = None) -> dict:
    """Lo que Ceci completó (sin vacíos ni saltos de línea: van a variables de WhatsApp)."""
    out = {}
    for k, v in (("monto", monto), ("datos_deposito", datos_deposito), ("solicitud", solicitud)):
        v = " ".join(str(v or "").split())
        if v:
            out[k] = v[:300]
    return out


def _guardar(repo: Repositorio, ap: dict, cambios: dict) -> dict:
    """Aplica los campos de Ceci: datos + texto nuevo + versión nueva. Devuelve la aprobación."""
    datos = {**(ap.get("datos") or {}), **cambios}
    if datos == (ap.get("datos") or {}):
        return ap
    version = int(ap.get("version") or 1) + 1
    repo.actualizar_aprobacion(ap["id"], datos=datos, texto=mensajes_etapa.texto_guia(datos), version=version)
    return repo.obtener_aprobacion(ap["id"])


def puede_aprobarse(repo: Repositorio, ap: Optional[dict], cambios: Optional[dict] = None) -> Optional[str]:
    """None si se puede aprobar; si no, el motivo (se le muestra a Ceci tal cual)."""
    if not ap:
        return "No encontré esa guía."
    if ap.get("estado") != "pendiente":
        return f"Esa guía ya estaba {ap.get('estado')}."
    faltan = mensajes_etapa.faltan_en_guia({**(ap.get("datos") or {}), **(cambios or {})})
    if faltan:
        return f"Falta completar: {' y '.join(faltan)}."
    ticket = repo.obtener_ticket(ap["ticket_id"]) or {}
    if not ticket.get("identificado_por"):
        return "Todavía no está identificado el cliente/asesor del ticket: asígnalo en el panel y vuelve a aprobar."
    return None


def aprobar(repo: Repositorio, aprobacion_id: int, por: str, monto: Optional[str] = None,
            datos_deposito: Optional[str] = None, ahora: Optional[datetime] = None,
            solicitud: Optional[str] = None) -> dict:
    """Aprueba la guía (con los campos que Ceci completó en el momento, si vinieron) y la manda a
    cliente y asesor."""
    ap = repo.obtener_aprobacion(aprobacion_id)
    cambios = _campos(monto, datos_deposito, solicitud)
    motivo = puede_aprobarse(repo, ap, cambios)
    if motivo:
        return _resultado(False, motivo)
    ap = _guardar(repo, ap, cambios)
    if not repo.resolver_aprobacion(aprobacion_id, "aprobada", por):
        return _resultado(False, "Esa guía ya se había resuelto.")
    ahora = _ahora(ahora)
    ap = repo.obtener_aprobacion(aprobacion_id)
    ticket = repo.obtener_ticket(ap["ticket_id"]) or {"id": ap["ticket_id"]}
    tid, ronda = ticket["id"], int(ap.get("ronda") or 1)
    datos = ap.get("datos") or {}
    ctx = {**mensajes_etapa.contexto(ticket, {}, {"cliente_nombre": ticket.get("cliente_nombre")}),
           "ticket_id": tid, "guia": ap["texto"], "resumen_guia": mensajes_etapa.resumen_guia(datos)}
    # La plantilla de la guía (WATI) se arma con estos datos; el texto queda registrado en el aviso.
    params = {**mensajes_etapa.params_wati(ctx, GUIA, ticket.get("telefono_cliente"), "corto"), "guia": datos}
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
        t = mensajes_etapa.texto("ceci", GUIA, ctx, omitidos, proceso="corto")
        a = _encolar(repo, tid, "ceci", t, GUIA, ronda, None, ap.get("correo_id"), params)
        if a:
            res["plan"].append(a)

    # Espera del pago (cliente + asesor; escala a asesor + Ceci), solo en los productos que la llevan.
    producto = ticket.get("producto") or datos.get("tipo")
    if str(producto or "").lower() in config.RECORDATORIO_PAGO_PRODUCTOS:
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


def corregir(repo: Repositorio, aprobacion_id: int, por: str, monto: Optional[str] = None,
             datos_deposito: Optional[str] = None, solicitud: Optional[str] = None) -> dict:
    """Completa o corrige los campos de Ceci (n° de solicitud, o monto / datos de depósito):
    versión nueva, sigue pendiente."""
    ap = repo.obtener_aprobacion(aprobacion_id)
    if not ap:
        return _resultado(False, "No encontré esa guía.")
    if ap.get("estado") != "pendiente":
        return _resultado(False, f"Esa guía ya estaba {ap.get('estado')}.")
    cambios = {k: v for k, v in _campos(monto, datos_deposito, solicitud).items()
               if k in mensajes_etapa.campos_guia(ap.get("datos"))}
    if not cambios:
        nombres = " ni ".join(mensajes_etapa.NOMBRES_CAMPOS[k] for k in mensajes_etapa.campos_guia(ap.get("datos")))
        return _resultado(False, f"No vino {nombres}.")
    nueva = _guardar(repo, ap, cambios)
    if nueva is ap:
        return _resultado(True, "Sin cambios.", version=int(ap.get("version") or 1))
    repo.agregar_evento(ap["ticket_id"], ap.get("correo_id"), "guia_corregida",
                        f"Guía de aportación completada por {por} (v{nueva['version']})")
    return _resultado(True, f"Guía actualizada (versión {nueva['version']}).", version=int(nueva["version"]))


def pendientes(repo: Repositorio) -> list[dict]:
    return repo.listar_aprobaciones(estados=["pendiente"])
