"""API del panel 'Ticket Allianz Seguimiento' (vive en el proyecto Allianz, FUERA de Tomi prod).

El frontend de Tomi la consume por HTTP para mostrar/aprobar/editar lo que el gestor propone.
Así el gestor de tickets queda desacoplado de la implementación de Tomi en producción.

Endpoints (todos bajo /api/tickets-allianz):
  GET  /api/tickets-allianz                            -> tickets + correo entrante + acciones propuestas
  POST /api/tickets-allianz/accion/{id}/calificacion   -> {calificacion: buena|regular|mala, nota}
  PUT  /api/tickets-allianz/accion/{id}/borrador       -> {borrador}
  GET  /api/tickets-allianz?filtro=para_ceci           -> solo lo que necesita a Ceci (Etapa 1)
  GET  /api/tickets-allianz/{id}/linea-tiempo          -> etapas C1→C5 con fecha, avisos y recordatorios
  PUT  /api/tickets-allianz/{id}/identificacion        -> Ceci asigna cliente/asesor a mano
  GET  /api/health                                     -> ping

Seguridad: si `API_TOKEN` está seteado, exige `Authorization: Bearer <token>`. CORS por
`CORS_ORIGINS`. NO envía nada al cliente/Allianz: solo lee/edita el estado de revisión.

Correr:  uvicorn app.api:app --host 0.0.0.0 --port 8090
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import config
from app.acciones.mensajes_etapa import ETIQUETAS
from app.acciones.motor_etapas import _parse_ts
from app.db import get_repo

app = FastAPI(title="Ticket Allianz Seguimiento API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_VIVOS = {"sugerida", "pendiente_ceci", "pendiente_wati", "simulada"}
# Calificación de la respuesta que propone el agente (feedback del equipo en el sandbox).
# Se guarda en la columna `veredicto` (reutilizada) para no migrar la base.
_CALIF = {"pendiente", "buena", "regular", "mala"}
_repo = None


def _get_repo():
    global _repo
    if _repo is None:
        _repo = get_repo()
    return _repo


def _auth(authorization: str = Header(default="")):
    if config.API_TOKEN and authorization != f"Bearer {config.API_TOKEN}":
        raise HTTPException(status_code=401, detail="token inválido")


def _json(v) -> dict:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:  # noqa: BLE001
            return {}
    return v or {}


def _borrador(a: dict) -> Optional[str]:
    pay, res = _json(a.get("payload")), _json(a.get("resultado"))
    return a.get("borrador_editado") or pay.get("cuerpo") or pay.get("mensaje") or res.get("cuerpo")


@app.get("/api/health")
def health():
    return {"ok": True, "servicio": "ticket-allianz-seguimiento"}


@app.get("/api/tickets-allianz")
def listar(filtro: Optional[str] = None, _=Depends(_auth)):
    """`filtro=para_ceci` → solo lo que necesita a Ceci (aunque el ticket esté cerrado): revisar,
    cliente/asesor sin identificar, escalados, correos para aprobar y rebotes."""
    repo = _get_repo()
    para_ceci = filtro == "para_ceci"
    tickets = []
    for t in repo.listar_tickets(limite=500):
        t["_para_ceci"] = motivos_para_ceci(repo, t)
        if para_ceci and not t["_para_ceci"]:
            continue
        if not para_ceci and (t.get("estado") or "") == "resuelto":
            continue
        tickets.append(t)

    def _peso(t):  # lo que necesita a Ceci, por_cerrar y escalado_ceci primero
        return (not t["_para_ceci"], t.get("estado") != "por_cerrar", t.get("estado") != "escalado_ceci")
    tickets.sort(key=_peso)

    items = []
    for t in tickets:
        acc = []
        for a in repo.listar_acciones(ticket_id=t["id"]):
            if a.get("estado") not in _VIVOS:
                continue
            cal = (a.get("veredicto") or "pendiente")
            if cal not in _CALIF:      # veredictos viejos (aprobado/rechazado) → pendiente
                cal = "pendiente"
            acc.append({
                "id": a["id"], "tipo_accion": a.get("tipo_accion"), "canal": a.get("canal"),
                "estado": a.get("estado"), "calificacion": cal,
                "nota_revision": a.get("nota_revision"), "borrador": _borrador(a),
                "editado": bool(a.get("borrador_editado")),
            })
        items.append({
            "id": t["id"], "nro_ticket": t.get("nro_ticket"), "poliza": t.get("poliza"),
            "cliente_nombre": t.get("cliente_nombre"), "estado": t.get("estado"),
            "vence": t.get("vence_en"), "asunto_hilo": t.get("asunto_hilo"),
            "delicado": bool(t.get("delicado")), "correo": _correo_ticket(repo, t["id"]),
            "acciones": acc,
            "pendientes": sum(1 for x in acc if x["calificacion"] == "pendiente"),
            # Etapa 1 (proceso largo)
            "etapa": t.get("etapa"), "etapa_nombre": ETIQUETAS.get(t.get("etapa") or "", t.get("etapa")),
            "etapa_desde": t.get("etapa_desde"), "proceso": t.get("proceso"), "producto": t.get("producto"),
            "nro_solicitud": t.get("nro_solicitud"), "identificado_por": t.get("identificado_por"),
            "proximo_recordatorio": proximo_recordatorio(repo, t["id"]),
            "para_ceci": t["_para_ceci"],
        })
    resumen = {"tickets": len(items), "acciones": sum(len(i["acciones"]) for i in items),
               "pendientes": sum(i["pendientes"] for i in items),
               "para_ceci": sum(1 for i in items if i["para_ceci"])}
    return {"resumen": resumen, "items": items}


# ─────────────────────────── Etapa 1: etapa, recordatorios, Ceci ───────────────────────────
def _seguro(fn, defecto):
    """Las tablas de la Etapa 1 pueden no existir todavía (migración sin correr): el panel sigue."""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return defecto


def proximo_recordatorio(repo, ticket_id: int) -> Optional[dict]:
    """El próximo paso del reloj: cuándo se recuerda (o se escala) y a quién."""
    prox = None
    for r in _seguro(lambda: repo.listar_recordatorios(ticket_id, estados=["activo"]), []):
        cuando, que = (r.get("escala_en"), "escala") if r.get("recordado_en") else (r.get("vence_en"), "recuerda")
        if cuando and (prox is None or str(cuando) < str(prox["cuando"])):
            prox = {"cuando": cuando, "que": que, "motivo": r.get("motivo"), "a_quien": r.get("destinatarios")}
    return prox


def motivos_para_ceci(repo, t: dict) -> list[str]:
    """Por qué este ticket necesita a Ceci (vacío = no la necesita)."""
    motivos = []
    if t.get("etapa") and not t.get("identificado_por") and (t.get("estado") or "") != "resuelto":
        motivos.append("sin_identificar")
    if _seguro(lambda: repo.listar_recordatorios(t["id"], estados=["escalado"]), []):
        motivos.append("escalado")
    if repo.listar_acciones(ticket_id=t["id"], estado="pendiente_ceci"):
        motivos.append("para_aprobar")
    # Correo a Allianz que no pudo ni armarse (ej. falta ALLIANZ_DEST): que no quede en silencio.
    if any(a.get("tipo_accion") == "escalar_allianz" for a in repo.listar_acciones(ticket_id=t["id"], estado="bloqueada")):
        motivos.append("escalacion_bloqueada")
    eventos = repo.listar_eventos(t["id"])
    if eventos and eventos[-1].get("tipo_evento") == "revisar":
        motivos.append("revisar")
    desde = _parse_ts(t.get("etapa_desde"))
    if any(a.get("etapa") == "rebote_ticket_cerrado"
           and (desde is None or (_parse_ts(a.get("created_at")) or desde) >= desde)
           for a in _seguro(lambda: repo.listar_avisos(t["id"]), [])):
        motivos.append("rebote")
    return motivos


@app.get("/api/tickets-allianz/{ticket_id}/linea-tiempo")
def linea_tiempo(ticket_id: int, _=Depends(_auth)):
    """Línea de tiempo C1→C5 del ticket: cada etapa con su fecha y los avisos que salieron, más
    los recordatorios (vivos y cerrados)."""
    repo = _get_repo()
    t = repo.obtener_ticket(ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="ticket no encontrado")
    pasos: dict[tuple, dict] = {}
    for a in repo.listar_avisos(ticket_id):
        k = (a.get("etapa"), a.get("ronda"))
        p = pasos.setdefault(k, {"etapa": a.get("etapa"), "etapa_nombre": ETIQUETAS.get(a.get("etapa"), a.get("etapa")),
                                 "ronda": a.get("ronda"), "fecha": a.get("created_at"), "avisos": []})
        p["avisos"].append({"para": a.get("destinatario"), "canal": a.get("canal"), "texto": a.get("texto"),
                            "fecha": a.get("created_at")})
    eventos = [{"tipo": e.get("tipo_evento"), "detalle": e.get("resumen"), "fecha": e.get("created_at")}
               for e in repo.listar_eventos(ticket_id)
               if e.get("tipo_evento") in ("etapa", "etapa_ignorada", "identificacion", "recordatorio",
                                           "escalado", "revisar", "emision")]
    return {
        "ticket": {"id": t["id"], "nro_ticket": t.get("nro_ticket"), "cliente_nombre": t.get("cliente_nombre"),
                   "etapa": t.get("etapa"), "etapa_nombre": ETIQUETAS.get(t.get("etapa") or "", t.get("etapa")),
                   "estado": t.get("estado"), "producto": t.get("producto"), "nro_solicitud": t.get("nro_solicitud"),
                   "poliza": t.get("poliza"), "identificado_por": t.get("identificado_por"),
                   "para_ceci": motivos_para_ceci(repo, t)},
        "pasos": sorted(pasos.values(), key=lambda p: str(p["fecha"])),
        "recordatorios": [{"motivo": r.get("motivo"), "estado": r.get("estado"), "vence": r.get("vence_en"),
                           "escala": r.get("escala_en"), "recordado": r.get("recordado_en"),
                           "escalado": r.get("escalado_en"), "a_quien": r.get("destinatarios"), "nota": r.get("nota")}
                          for r in repo.listar_recordatorios(ticket_id)],
        "eventos": eventos,
    }


class IdentificacionIn(BaseModel):
    cliente_nombre: Optional[str] = None
    telefono_cliente: Optional[str] = None
    asesor_correo: Optional[str] = None
    telefono_asesor: Optional[str] = None


@app.put("/api/tickets-allianz/{ticket_id}/identificacion")
def asignar_identificacion(ticket_id: int, body: IdentificacionIn, _=Depends(_auth)):
    """Ceci asigna a mano cliente y asesor cuando el sistema no pudo identificarlos sin adivinar.
    Desde ahí, los avisos y recordatorios de este ticket usan estos datos (identificado_por=manual).
    No reenvía los avisos que ya se omitieron: vale para los próximos."""
    repo = _get_repo()
    if not repo.obtener_ticket(ticket_id):
        raise HTTPException(status_code=404, detail="ticket no encontrado")
    campos = {k: (v.strip() or None) for k, v in body.model_dump().items() if v is not None}
    if not (campos.get("telefono_cliente") or campos.get("telefono_asesor")):
        raise HTTPException(status_code=400, detail="hace falta al menos un teléfono (cliente o asesor)")
    repo.actualizar_ticket(ticket_id, **campos, identificado_por="manual")
    repo.agregar_evento(ticket_id, None, "identificacion", "Cliente/asesor asignados a mano por Ceci")
    return {"ok": True, "ticket_id": ticket_id, "identificado_por": "manual"}


def _correo_ticket(repo, ticket_id: int) -> Optional[dict]:
    """Último correo entrante del ticket: 'qué decía el correo' que revisa el equipo."""
    correos = repo.listar_correos(ticket_id, limite=1)
    if not correos:
        return None
    c = correos[0]
    return {"remitente": c.get("remitente"), "asunto": c.get("asunto"),
            "cuerpo": c.get("cuerpo_texto"), "fecha": c.get("fecha")}


class CalificacionIn(BaseModel):
    calificacion: str
    nota: Optional[str] = None


@app.post("/api/tickets-allianz/accion/{accion_id}/calificacion")
def poner_calificacion(accion_id: int, body: CalificacionIn, _=Depends(_auth)):
    """Califica la respuesta propuesta: buena / regular / mala (o pendiente). Se guarda en la
    columna `veredicto`. No envía nada; es feedback del equipo para evaluar al agente."""
    c = (body.calificacion or "").strip().lower()
    if c not in _CALIF:
        raise HTTPException(status_code=400, detail=f"calificación inválida (usar {sorted(_CALIF)})")
    if _get_repo().set_veredicto(accion_id, c, body.nota) == 0:
        raise HTTPException(status_code=404, detail="acción no encontrada")
    return {"ok": True, "accion_id": accion_id, "calificacion": c}


class BorradorIn(BaseModel):
    borrador: str


@app.put("/api/tickets-allianz/accion/{accion_id}/borrador")
def editar_borrador(accion_id: int, body: BorradorIn, _=Depends(_auth)):
    if _get_repo().set_borrador(accion_id, body.borrador) == 0:
        raise HTTPException(status_code=404, detail="acción no encontrada")
    return {"ok": True, "accion_id": accion_id}
