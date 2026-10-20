"""Paso 6 de la Etapa 1 — recordatorios y escalamiento del proceso largo.

Los recordatorios los arranca/corta el motor por etapa (motor_etapas.py) al llegar cada correo.
Este escaneo (job del scheduler) los hace avanzar con el reloj:

  activo ──vence_en──▶ se RECUERDA a quien falta (una vez)   [recordado_en]
         ──escala_en─▶ se ESCALA (una vez) → estado 'escalado'
  y se corta solo cuando llega lo que se esperaba (C4, autorizado, C5, rechazo…) o se cierra el ticket.

  - requerimiento (esperamos al cliente): recordatorio al cliente y al asesor; escalado → asesor + Ceci
    ("si vence el plazo, Allianz rechaza"). No se le escribe a Allianz: Allianz está esperando a nosotros.
  - esperando_allianz (mandamos lo pedido): recordatorio a Ceci; escalado → correo en el hilo con
    copia a la ejecutiva (ESCALA_CC) que queda PARA APROBAR por Ceci + aviso a Ceci.

Solo en horario de oficina de CDMX (lunes a viernes, sin feriados). Cada envío se registra en
`avisos` con ronda = id del recordatorio → nunca sale dos veces aunque el job corra cada 30 min.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import config
from app.db import Repositorio
from app.tickets import sla

from . import mensajes_etapa
from .motor_etapas import REC_ESPERANDO_ALLIANZ, _encolar, _parse_ts, mas_horas_habiles, rol_activo

log = logging.getLogger(__name__)


def hora_mx(ahora: datetime) -> datetime:
    return ahora.astimezone(timezone.utc).replace(tzinfo=None) + timedelta(hours=config.UTC_OFFSET_MX)


def en_horario(ahora: datetime) -> bool:
    """Lunes a viernes, sin feriados de México, dentro de HORARIO_AVISOS (hora de CDMX)."""
    local = hora_mx(ahora)
    ini, _, fin = config.HORARIO_AVISOS.partition("-")
    return sla._es_habil(local) and int(ini) <= local.hour < int(fin or 24)


def _ctx(ticket: dict, rec: dict) -> dict:
    etapa = {"nro_ticket": ticket.get("nro_ticket"), "producto": ticket.get("producto"),
             "nro_solicitud": ticket.get("nro_solicitud"), "poliza": ticket.get("poliza"),
             "que_piden": rec.get("nota")}
    # "Desde": cuándo entró el ticket a la etapa actual (ej. cuándo mandamos los documentos, C4).
    desde = _parse_ts(ticket.get("etapa_desde")) or _parse_ts(rec.get("created_at"))
    return {**mensajes_etapa.contexto(ticket, etapa), "ticket_id": ticket["id"],
            "desde": f"{hora_mx(desde):%d/%m}" if desde else "—", "cc": ", ".join(config.ESCALA_CC) or "—"}


def _avisar(repo: Repositorio, ticket: dict, rec: dict, momento: str, roles: list[str]) -> list[dict]:
    """Recordatorio / escalado por WhatsApp a `roles`. Lo que no se pueda avisar va a Ceci."""
    motivo = rec["motivo"]
    clave = f"{momento}_{motivo}"           # 'recordatorio_requerimiento', 'escalado_esperando_allianz'…
    ctx = _ctx(ticket, rec)
    params = mensajes_etapa.params_wati(ctx, clave, ticket.get("telefono_cliente"))
    plan, omitidos = [], []
    identificado = bool(ticket.get("identificado_por"))
    roles = [r for r in roles if rol_activo(r)]  # encendido gradual
    # El cliente primero: el texto del asesor dice "Ya le recordamos al cliente" solo si de verdad salió.
    for rol in sorted(roles, key=lambda r: r != "cliente"):
        if rol == "ceci":
            continue
        if not identificado:
            omitidos.append(f"No hay cliente/asesor identificado: no se le recordó al {rol}.")
            continue
        numero = ticket.get(f"telefono_{rol}")
        if not numero:
            omitidos.append(f"Falta el teléfono del {rol} en Notion: no se le recordó.")
            continue
        t = mensajes_etapa.texto_recordatorio(rol, motivo, momento, ctx)
        if t:
            a = _encolar(repo, ticket["id"], rol, t, clave, rec["id"], str(numero), rec.get("correo_id"), params)
            if a:
                plan.append(a)
                if rol == "cliente":
                    ctx["ya_cliente"] = " Ya le recordamos al cliente."
    if "ceci" in roles or omitidos:
        t = mensajes_etapa.texto_recordatorio("ceci", motivo, momento, ctx, omitidos)
        a = _encolar(repo, ticket["id"], "ceci", t, clave, rec["id"], None, rec.get("correo_id"), params)
        if a:
            plan.append(a)
    return plan


def _correo_escalacion(repo: Repositorio, ticket: dict, rec: dict) -> Optional[dict]:
    """Correo en el hilo a Allianz con copia a la ejecutiva. Queda retenido para que Ceci lo apruebe."""
    ctx = _ctx(ticket, rec)
    cuerpo = mensajes_etapa.CORREO_ESCALACION.format(**ctx)
    aviso_id = repo.registrar_aviso(ticket["id"], f"escalado_{rec['motivo']}", "allianz", ronda=rec["id"],
                                    canal="email", texto=cuerpo, correo_id=rec.get("correo_id"))
    if aviso_id is None:
        return None
    payload = {"rol": "allianz", "destinatario": None, "cc": list(config.ESCALA_CC), "cuerpo": cuerpo,
               "mensaje": f"Escalación: Allianz no responde (ticket {ctx['tk']}).", "requiere_visto_bueno": True,
               "etapa": f"escalado_{rec['motivo']}", "aviso_id": aviso_id}
    accion_id = repo.crear_accion(ticket["id"], "escalar_allianz", "email", payload)
    return {"accion_id": accion_id, "ticket_id": ticket["id"], "tipo_accion": "escalar_allianz", **payload}


def escanear_recordatorios(repo: Repositorio, ahora: Optional[datetime] = None) -> dict:
    ahora = (ahora or datetime.now(timezone.utc))
    ahora = ahora if ahora.tzinfo else ahora.replace(tzinfo=timezone.utc)
    res: dict = {"fuera_de_horario": False, "recordados": [], "escalados": [], "cortados": [], "plan": []}
    if not en_horario(ahora):
        res["fuera_de_horario"] = True
        return res
    for rec in repo.listar_recordatorios(estados=["activo"]):
        ticket = repo.obtener_ticket(rec["ticket_id"])
        if not ticket or ticket.get("estado") == "resuelto":
            repo.actualizar_recordatorio(rec["id"], estado="cancelado", cerrado_en=ahora,
                                         nota=f"{rec.get('nota') or ''} · ticket cerrado"[:200])
            res["cortados"].append(rec["id"])
            continue
        vence, escala = _parse_ts(rec.get("vence_en")), _parse_ts(rec.get("escala_en"))
        if not rec.get("recordado_en"):
            if vence and vence <= ahora:
                roles = list(rec.get("destinatarios") or [])
                res["plan"] += _avisar(repo, ticket, rec, "recordatorio", roles)
                # La escalación nunca llega antes de 24 h hábiles después del recordatorio (si el
                # sistema estuvo caído, no se recuerda y escala en el mismo rato).
                piso = mas_horas_habiles(ahora, config.ESCALA_HORAS_HABILES)
                repo.actualizar_recordatorio(rec["id"], recordado_en=ahora,
                                             escala_en=max(escala, piso) if escala else piso)
                res["recordados"].append(rec["id"])
                repo.agregar_evento(ticket["id"], rec.get("correo_id"), "recordatorio",
                                    f"Recordatorio ({rec['motivo']}) a {', '.join(roles)}")
        elif escala and escala <= ahora:
            if rec["motivo"] == REC_ESPERANDO_ALLIANZ:
                if config.ESCALAR_A_ALLIANZ:
                    correo = _correo_escalacion(repo, ticket, rec)
                    if correo:
                        res["plan"].append(correo)
                    res["plan"] += _avisar(repo, ticket, rec, "escalado", ["ceci"])
                else:  # encendido gradual: todavía sin correo a Allianz, solo se avisa a Ceci
                    res["plan"] += _avisar(repo, ticket, rec, "escalado_sin_correo", ["ceci"])
            else:  # REC_REQUERIMIENTO: el que falta es el cliente → asesor + Ceci
                res["plan"] += _avisar(repo, ticket, rec, "escalado", ["asesor", "ceci"])
            repo.actualizar_recordatorio(rec["id"], estado="escalado", escalado_en=ahora)
            res["escalados"].append(rec["id"])
            repo.agregar_evento(ticket["id"], rec.get("correo_id"), "escalado",
                                f"Escalado ({rec['motivo']})" + (" · correo a Allianz para aprobar"
                                                                 if rec["motivo"] == REC_ESPERANDO_ALLIANZ else ""))
    return res
