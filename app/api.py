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
  POST /api/tickets-allianz/aprobacion/{id}            -> guía de aportación: aprobar | corregir | descartar (Etapa 2)
  POST /api/tickets-allianz/{id}/etapa                 -> marcar a mano "pago/respuesta enviada" (Etapa 2)
  POST /api/tickets-allianz/accion/{id}/aprobar        -> correo retenido para Ceci: enviar | descartar
  GET  /api/tickets-allianz/tramites/catalogo          -> trámites para el selector (Etapa 3)
  POST /api/tickets-allianz/tramites/vista-previa      -> identifica la póliza y arma el correo (no guarda)
  POST /api/tickets-allianz/tramites                   -> abre el trámite: ticket + correo a Allianz
  POST /api/tickets-allianz/tramites/archivos-whatsapp -> lo que mandó el cliente por WhatsApp (Etapa 3B)
  GET  /api/health                                     -> ping

Seguridad: `Authorization: Bearer <sesión de Tomi>` de un admin (firmada con TOMI_JWT_SECRET) o,
mientras dura la transición, el `API_TOKEN` fijo. Sin ninguno configurado no atiende. CORS por
`CORS_ORIGINS`. NO envía nada al cliente/Allianz: solo lee/edita el estado de revisión.

Correr:  uvicorn app.api:app --host 0.0.0.0 --port 8090
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import config
from app.acciones.mensajes_etapa import (
    ETIQUETAS, FALTA_COMPLETAR, NOMBRES_CAMPOS, campos_guia, etiqueta, faltan_del_ticket,
    faltan_en_guia,
)
from app.acciones.motor_etapas import RANGO, _parse_ts
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


_ROLES_PANEL = {"admin", "super_admin"}


def _b64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sesion_tomi(token: str) -> Optional[dict]:
    """La sesión de Tomi (JWT HS256 firmado con su SECRET_KEY) si es auténtica y no venció; si no, None."""
    if not (config.TOMI_JWT_SECRET and token):
        return None
    try:
        cab, cuerpo, firma = token.split(".")
        if json.loads(_b64(cab)).get("alg") != "HS256":
            return None  # nunca "none" ni otro algoritmo
        esperada = hmac.new(config.TOMI_JWT_SECRET.encode(), f"{cab}.{cuerpo}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(esperada, _b64(firma)):
            return None
        datos = json.loads(_b64(cuerpo))
    except (ValueError, AttributeError):  # mal armado (base64/JSON/partes)
        return None
    exp = datos.get("exp") if isinstance(datos, dict) else None
    if not isinstance(exp, (int, float)) or exp <= time.time():
        return None
    return datos


def _auth(authorization: str = Header(default="")) -> dict:
    """Quién llama: un admin de Tomi con su sesión, o (transición) el API_TOKEN fijo. Sin ninguno
    configurado la API no atiende: nunca queda abierta por olvido (API_SIN_AUTH=true solo en desarrollo)."""
    token = authorization[7:].strip() if authorization[:7].lower() == "bearer " else ""
    s = sesion_tomi(token)
    if s is not None:
        if s.get("role") not in _ROLES_PANEL:
            raise HTTPException(status_code=403, detail="el gestor de tickets es solo para administradores")
        return {"via": "sesion", "usuario_id": s.get("sub"), "rol": s.get("role")}
    if config.API_TOKEN and token and hmac.compare_digest(token.encode(), config.API_TOKEN.encode()):
        return {"via": "token"}
    if not (config.TOMI_JWT_SECRET or config.API_TOKEN):
        if config.API_SIN_AUTH:
            return {"via": "abierta"}
        raise HTTPException(status_code=503, detail="la API no tiene autenticación configurada (TOMI_JWT_SECRET)")
    raise HTTPException(status_code=401, detail="sesión inválida o vencida")


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
        if not para_ceci and (t.get("estado") or "") == "resuelto":
            continue  # antes de calcular los motivos: son varias consultas por ticket
        t["_guia"] = guia_pendiente(repo, t["id"])
        t["_para_ceci"] = motivos_para_ceci(repo, t, guia=t["_guia"])
        if para_ceci and not t["_para_ceci"]:
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
            "etapa": t.get("etapa"), "etapa_nombre": etiqueta(t.get("etapa"), t.get("proceso")),
            "etapa_desde": t.get("etapa_desde"), "proceso": t.get("proceso"), "producto": t.get("producto"),
            "nro_solicitud": t.get("nro_solicitud"), "identificado_por": t.get("identificado_por"),
            "proximo_recordatorio": proximo_recordatorio(repo, t["id"]),
            "para_ceci": t["_para_ceci"],
            # Etapa 2 (corto + trámites)
            "titulo_hilo": t.get("titulo_hilo"), "guia_pendiente": t["_guia"],
            # Etapa 3 (trámites abiertos desde el panel)
            "abierto_por": t.get("abierto_por"),
        })
    resumen = {"tickets": len(items), "acciones": sum(len(i["acciones"]) for i in items),
               "pendientes": sum(i["pendientes"] for i in items),
               "para_ceci": sum(1 for i in items if i["para_ceci"])}
    return {"resumen": resumen, "items": items}


# ─────────────────────────── Etapa 1: etapa, recordatorios, Ceci ───────────────────────────
_ETAPAS_CON_RONDA = {e.value for e in RANGO}


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


def guia_pendiente(repo, ticket_id: int) -> Optional[dict]:
    """Etapa 2: la guía de aportación que espera a Ceci (si hay)."""
    for ap in _seguro(lambda: repo.listar_aprobaciones(ticket_id, estados=["pendiente"]), []):
        datos = ap.get("datos") or {}
        return {"id": ap["id"], "version": ap.get("version"), "texto": ap.get("texto"),
                "por_telegram": bool(ap.get("telegram_msg_id")),
                "monto": datos.get("monto") or "", "datos_deposito": datos.get("datos_deposito") or "",
                # Lo que Ceci completa o confirma en esta guía (depende del producto).
                "campos": [{"clave": k, "nombre": NOMBRES_CAMPOS[k], "valor": datos.get(k) or ""}
                           for k in campos_guia(datos)],
                "faltan": faltan_en_guia(datos),
                "faltan_del_ticket": faltan_del_ticket(datos),  # póliza/ticket/nombre: bloquean la aprobación
                "falta_completar": FALTA_COMPLETAR in (ap.get("texto") or "")}
    return None


_SIN_CALCULAR = object()


def motivos_para_ceci(repo, t: dict, guia=_SIN_CALCULAR) -> list[str]:
    """Por qué este ticket necesita a Ceci (vacío = no la necesita)."""
    motivos = []
    if (guia_pendiente(repo, t["id"]) if guia is _SIN_CALCULAR else guia):
        motivos.append("guia_por_aprobar")
    if t.get("etapa") and not t.get("identificado_por") and (t.get("estado") or "") != "resuelto":
        motivos.append("sin_identificar")
    if _seguro(lambda: repo.listar_recordatorios(t["id"], estados=["escalado"]), []):
        motivos.append("escalado")
    if repo.listar_acciones(ticket_id=t["id"], estado="pendiente_ceci"):
        motivos.append("para_aprobar")
    # Correo a Allianz que no pudo ni armarse (ej. falta ALLIANZ_DEST): que no quede en silencio.
    if any(a.get("tipo_accion") in ("escalar_allianz", "abrir_tramite")
           for a in repo.listar_acciones(ticket_id=t["id"], estado="bloqueada")):
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
        # La "ronda" solo significa algo en las etapas que avanzan (requerimiento 2, 3…); en notas,
        # rebotes y recordatorios es un id interno.
        ronda = a.get("ronda") if a.get("etapa") in _ETAPAS_CON_RONDA else None
        p = pasos.setdefault(k, {"etapa": a.get("etapa"), "etapa_nombre": etiqueta(a.get("etapa"), t.get("proceso")),
                                 "ronda": ronda, "fecha": a.get("created_at"), "avisos": []})
        p["avisos"].append({"para": a.get("destinatario"), "canal": a.get("canal"), "texto": a.get("texto"),
                            "fecha": a.get("created_at")})
    eventos = [{"tipo": e.get("tipo_evento"), "detalle": e.get("resumen"), "fecha": e.get("created_at")}
               for e in repo.listar_eventos(ticket_id)
               if e.get("tipo_evento") in ("etapa", "etapa_ignorada", "identificacion", "recordatorio",
                                           "escalado", "revisar", "emision", "guia_por_aprobar",
                                           "guia_aprobada", "guia_corregida", "guia_descartada", "etapa_manual")]
    return {
        "ticket": {"id": t["id"], "nro_ticket": t.get("nro_ticket"), "cliente_nombre": t.get("cliente_nombre"),
                   "etapa": t.get("etapa"), "etapa_nombre": etiqueta(t.get("etapa"), t.get("proceso")),
                   "estado": t.get("estado"), "producto": t.get("producto"), "nro_solicitud": t.get("nro_solicitud"),
                   "poliza": t.get("poliza"), "identificado_por": t.get("identificado_por"),
                   "proceso": t.get("proceso"), "titulo_hilo": t.get("titulo_hilo"),
                   "para_ceci": motivos_para_ceci(repo, t)},
        "aprobaciones": [{"id": a["id"], "tipo": a.get("tipo"), "estado": a.get("estado"), "version": a.get("version"),
                          "texto": a.get("texto"), "datos": a.get("datos") or {}, "resuelto_por": a.get("resuelto_por"),
                          "resuelto_en": a.get("resuelto_en"), "fecha": a.get("created_at")}
                         for a in _seguro(lambda: repo.listar_aprobaciones(ticket_id), [])],
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


# ─────────────────────────── Etapa 2: guía de aportación y etapa a mano ───────────────────────────
class AprobacionIn(BaseModel):
    accion: str                           # aprobar | corregir | descartar
    monto: Optional[str] = None           # lo que completa Ceci (aprobar: opcional, aprueba con esto)
    datos_deposito: Optional[str] = None
    solicitud: Optional[str] = None       # Patrimonial / Elite: el n° de solicitud que confirma Ceci
    usuario: Optional[str] = None         # quién (para la bitácora)


@app.post("/api/tickets-allianz/aprobacion/{aprobacion_id}")
def resolver_aprobacion(aprobacion_id: int, body: AprobacionIn, _=Depends(_auth)):
    """Ceci aprueba, corrige o descarta la guía de aportación desde el panel (lo mismo que los
    botones de Telegram). Aprobar encola la guía al cliente y al asesor (el worker la despacha,
    respetando DRY_RUN) y arranca el recordatorio de pago."""
    from app.acciones import aprobaciones
    repo = _get_repo()
    ap = repo.obtener_aprobacion(aprobacion_id)
    if not ap:
        raise HTTPException(status_code=404, detail="aprobación no encontrada")
    por = f"panel:{(body.usuario or 'ceci').strip()[:40]}"
    if body.accion == "aprobar":
        res = aprobaciones.aprobar(repo, aprobacion_id, por, monto=body.monto, datos_deposito=body.datos_deposito,
                                   solicitud=body.solicitud)
        leyenda = "✅ Aprobada desde el panel: ya salió al cliente y al asesor."
    elif body.accion == "descartar":
        res = aprobaciones.descartar(repo, aprobacion_id, por)
        leyenda = "🗑 Descartada desde el panel: no se mandó nada."
    elif body.accion == "corregir":
        res = aprobaciones.corregir(repo, aprobacion_id, por, monto=body.monto, datos_deposito=body.datos_deposito,
                                    solicitud=body.solicitud)
        leyenda = f"✏️ Corregida desde el panel (versión {res.get('version')}): te llega la nueva abajo."
    else:
        raise HTTPException(status_code=400, detail="accion: aprobar | corregir | descartar")
    if not res["ok"]:
        if res.get("version", 0) > int(ap.get("version") or 1):  # se completó con datos del ticket
            _avisar_telegram(repo, ap, f"✏️ Completada con datos del ticket (versión {res['version']}): "
                                       "te llega la nueva abajo.", reenviar=True)
        raise HTTPException(status_code=409, detail=res["motivo"])
    _avisar_telegram(repo, ap, leyenda, reenviar=body.accion == "corregir")
    return {"ok": True, "motivo": res["motivo"], "avisos": [a["rol"] for a in res.get("plan", [])]}


def _avisar_telegram(repo, ap: dict, leyenda: str, reenviar: bool) -> None:
    """Si la guía ya estaba en Telegram, ese mensaje deja de servir (sus botones son de otra versión
    o ya está resuelta). Al corregir, el worker le manda a Ceci la versión nueva."""
    if not ap.get("telegram_msg_id") or not config.hay_telegram():
        return
    from app.rieles import telegram
    telegram.cerrar_mensaje(ap, leyenda)
    if reenviar:
        repo.actualizar_aprobacion(ap["id"], telegram_msg_id="")


_ETAPAS_A_MANO = {"documentos_enviados"}


class EtapaIn(BaseModel):
    etapa: str
    usuario: Optional[str] = None


@app.post("/api/tickets-allianz/{ticket_id}/etapa")
def marcar_etapa(ticket_id: int, body: EtapaIn, _=Depends(_auth)):
    """Marcar a mano lo que no llega por correo al hilo. Hoy: 'documentos_enviados' = el pago de
    Patrimonial (va en un correo nuevo a 'cliente inversión') o una respuesta mandada por fuera.
    Corre por el mismo motor: avisos únicos, corta el recordatorio de pago y arranca 'esperando a Allianz'."""
    from app.acciones.motor_etapas import decidir_por_etapa
    repo = _get_repo()
    t = repo.obtener_ticket(ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="ticket no encontrado")
    if body.etapa not in _ETAPAS_A_MANO:
        raise HTTPException(status_code=400, detail=f"etapa a mano: {', '.join(sorted(_ETAPAS_A_MANO))}")
    if not t.get("etapa"):
        raise HTTPException(status_code=409, detail="el ticket no está en el motor por etapa")
    quien = (body.usuario or "ceci").strip()[:40]
    res = decidir_por_etapa(repo, ticket_id, {"etapa": body.etapa, "proceso": t.get("proceso"),
                                              "motivo": f"marcado a mano en el panel ({quien})"})
    repo.agregar_evento(ticket_id, None, "etapa_manual",
                        f"{ETIQUETAS.get(body.etapa, body.etapa)} — marcado a mano por {quien}"
                        + ("" if res.get("aplicada") else f" (sin efecto: {res.get('motivo')})"))
    if not res.get("aplicada"):
        raise HTTPException(status_code=409, detail=res.get("motivo") or "no aplica")
    return {"ok": True, "etapa": body.etapa, "avisos": [a["rol"] for a in res["plan"]],
            "recordatorios": res.get("recordatorios", [])}


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


# ─────────────────────────── Correos retenidos para Ceci: enviar o descartar ───────────────────────────
class DecisionIn(BaseModel):
    decision: str                         # enviar | descartar
    usuario: Optional[str] = None
    motivo: Optional[str] = None


@app.post("/api/tickets-allianz/accion/{accion_id}/aprobar")
def aprobar_accion(accion_id: int, body: DecisionIn, _=Depends(_auth)):
    """Correos retenidos para el visto bueno de Ceci (escalación a Allianz con copia a Penny,
    temas críticos): 'enviar' lo libera para el próximo despacho (con el borrador editado, si
    lo editó); 'descartar' no lo manda. De a una acción: aprobar una no aprueba las demás."""
    repo = _get_repo()
    a = next((x for x in repo.listar_acciones(estado="pendiente_ceci") if x["id"] == accion_id), None)
    if not a:
        raise HTTPException(status_code=404, detail="no hay un correo esperando aprobación con ese id")
    por = f"panel:{(body.usuario or 'ceci').strip()[:40]}"
    if body.decision == "enviar":
        repo.actualizar_accion(accion_id, "sugerida", {"aprobado_por": por})
        repo.agregar_evento(a["ticket_id"], None, "visto_bueno", f"Correo aprobado por {por}")
        return {"ok": True, "accion_id": accion_id, "estado": "sugerida",
                "motivo": "aprobado: sale en el próximo ciclo"}
    if body.decision == "descartar":
        repo.actualizar_accion(accion_id, "rechazada", {"rechazado_por": por, "motivo": body.motivo or ""})
        repo.agregar_evento(a["ticket_id"], None, "visto_bueno", f"Correo descartado por {por}")
        return {"ok": True, "accion_id": accion_id, "estado": "rechazada", "motivo": "descartado: no se manda"}
    raise HTTPException(status_code=400, detail="decision: enviar | descartar")


# ─────────────────────────── Etapa 3: abrir un trámite desde el panel ───────────────────────────
class AdjuntoIn(BaseModel):
    nombre: str
    tipo: Optional[str] = None
    base64: str


class TramiteIn(BaseModel):
    tramite: str                          # clave del catálogo o nombre libre
    poliza: str
    nota: Optional[str] = None
    adjuntos: list[AdjuntoIn] = []
    usuario: Optional[str] = None


@app.get("/api/tickets-allianz/tramites/catalogo")
def catalogo_tramites(_=Depends(_auth)):
    from app.acciones import abrir_tramite
    return {"tramites": abrir_tramite.catalogo()}


def _publico(p: dict) -> dict:
    return {k: v for k, v in p.items() if not k.startswith("_")}


@app.post("/api/tickets-allianz/tramites/vista-previa")
def vista_previa_tramite(body: TramiteIn, _=Depends(_auth)):
    """Identifica la póliza y muestra el correo tal como saldría. No guarda nada."""
    from app.acciones import abrir_tramite
    p = abrir_tramite.preparar(body.tramite, body.poliza, body.nota,
                               [a.model_dump() for a in body.adjuntos])
    return _publico(p)


@app.post("/api/tickets-allianz/tramites")
def abrir_tramite_panel(body: TramiteIn, _=Depends(_auth)):
    """Abre el trámite: crea el ticket y encola el correo a Allianz (sale en el próximo ciclo del
    worker, respetando DRY_RUN). El acuse de Allianz se engancha solo a este ticket."""
    from app.acciones import abrir_tramite
    r = abrir_tramite.abrir(_get_repo(), body.tramite, body.poliza, body.nota,
                            [a.model_dump() for a in body.adjuntos],
                            usuario=(body.usuario or "ceci").strip()[:40])
    if not r["ok"]:
        raise HTTPException(status_code=409 if r.get("duplicado") else 422, detail=r["motivo"])
    return _publico(r)


class ArchivosWhatsappIn(BaseModel):
    poliza: str
    dias: int = 14


@app.post("/api/tickets-allianz/tramites/archivos-whatsapp")
def archivos_whatsapp(body: ArchivosWhatsappIn, _=Depends(_auth)):
    """Etapa 3B: las fotos y documentos que el cliente de la póliza mandó por WhatsApp en los
    últimos días, ya bajados de WATI, para elegir cuáles adjuntar al trámite. Solo lee."""
    from app.acciones import abrir_tramite
    return abrir_tramite.archivos_whatsapp(body.poliza, body.dias)
