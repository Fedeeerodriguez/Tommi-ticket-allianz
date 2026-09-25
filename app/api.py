"""API del panel 'Ticket Allianz Seguimiento' (vive en el proyecto Allianz, FUERA de Tomi prod).

El frontend de Tomi la consume por HTTP para mostrar/aprobar/editar lo que el gestor propone.
Así el gestor de tickets queda desacoplado de la implementación de Tomi en producción.

Endpoints (todos bajo /api/tickets-allianz):
  GET  /api/tickets-allianz                            -> tickets + correo entrante + acciones propuestas
  POST /api/tickets-allianz/accion/{id}/calificacion   -> {calificacion: buena|regular|mala, nota}
  PUT  /api/tickets-allianz/accion/{id}/borrador       -> {borrador}
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
def listar(_=Depends(_auth)):
    repo = _get_repo()
    tickets = [t for t in repo.listar_tickets(limite=500) if (t.get("estado") or "") != "resuelto"]

    def _peso(t):  # por_cerrar y escalado_ceci primero
        return (t.get("estado") != "por_cerrar", t.get("estado") != "escalado_ceci")
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
        })
    resumen = {"tickets": len(items), "acciones": sum(len(i["acciones"]) for i in items),
               "pendientes": sum(i["pendientes"] for i in items)}
    return {"resumen": resumen, "items": items}


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
