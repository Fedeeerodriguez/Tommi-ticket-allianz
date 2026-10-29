"""Cargo rechazado (cobranza) — aviso al asesor y a Ceci. Al cliente NO: le escribe el equipo de
cobranza por su WATI (decisión del 23/09, confirmada el 29/10).

Allianz manda "Allianz México - Notificación de Cobranza (PLU3 / 437821)" cuando un cargo
automático no pasa: fecha del intento, monto, n° de aportación, lo que respondió el banco
("FONDOS INSUFICIENTES") y la fecha del próximo intento. Antes esos correos se descartaban como
fuera de alcance; ahora, con COBRANZA_AVISOS, se identifica la póliza en Notion y se le avisa al
asesor (para que contacte al cliente) y a Ceci, con lo que pidió Ceci: la cantidad pendiente y que a
los 60 días de atraso Allianz puede cancelar el plan.

Cada correo queda como un ticket `proceso=cobranza` ya cerrado: así se ve en el panel y los avisos
usan el mismo despacho (respeta DRY_RUN y MOTOR_ETAPAS_ROLES).
"""
from __future__ import annotations

import re
from typing import Optional

from app import config
from app.acciones.mensajes_etapa import contexto, link_panel
from app.acciones.motor_etapas import _encolar
from app.clasificador.etapas import PRODUCTOS
from app.db.repo import Repositorio
from app.enriquecimiento.identificar import Buscador, identificar

ETAPA = "cargo_rechazado"
PROCESO = "cobranza"

_RE_ASUNTO = re.compile(r"notificaci[oó]n\s+de\s+cobranza\s*\(\s*([A-Z0-9]{3,5})\s*/\s*(\d+)\s*\)", re.I)
_FECHA = r"(\d{1,2}\s+de\s+[a-záéíóú]+\s+de\s+\d{4})"
_RE_INTENTO = re.compile(r"pasado\s+" + _FECHA + r"\s+hicimos\s+un\s+intento\s+de\s+cargo", re.I)
_RE_MONTO = re.compile(r"cantidad\s+de\s+(\$\s?[\d.,]+)", re.I)
_RE_APORTACION = re.compile(r"aportaci[oó]n\s+n[uú]mero\s+(\d+)", re.I)
_RE_MOTIVO = re.compile(r"(?:banco|instituci[oó]n)\s+nos\s+notific[oó]\s+[\"“”']([^\"“”']{2,80})[\"“”']", re.I)
_RE_PROXIMO = re.compile(r"pr[oó]ximo\s+" + _FECHA + r"\s+realizaremos\s+un\s+nuevo\s+intento", re.I)


def detectar(asunto: Optional[str], cuerpo: Optional[str]) -> Optional[dict]:
    """Datos del aviso de cobranza, o None si el correo no es uno. Lo que no se encuentra queda en None."""
    m = _RE_ASUNTO.search(asunto or "")
    if not m:
        return None
    texto = re.sub(r"\s+", " ", cuerpo or "")

    def uno(rx):
        x = rx.search(texto)
        return x.group(1).strip() if x else None

    prod = m.group(1).upper()
    motivo = uno(_RE_MOTIVO)
    return {"producto": prod, "poliza": f"{prod}-{m.group(2)}", "fecha_intento": uno(_RE_INTENTO),
            "monto": (uno(_RE_MONTO) or "").replace("$ ", "$") or None, "aportacion": uno(_RE_APORTACION),
            "motivo": motivo.capitalize() if motivo else None, "proximo_intento": uno(_RE_PROXIMO)}


def textos(d: dict, cliente: str) -> dict[str, str]:
    """Aviso al asesor y a Ceci. Lo que no vino en el correo no se menciona."""
    plan = PRODUCTOS.get(d["producto"], (None, d["producto"]))[1]
    cargo = f"la aportación{' n° ' + d['aportacion'] if d.get('aportacion') else ''}"
    cargo += f" de {d['monto']}" if d.get("monto") else ""
    base = (f"Cobranza · {cliente} · {plan} (póliza {d['poliza']}): Allianz no pudo cobrar {cargo}"
            f"{' el ' + d['fecha_intento'] if d.get('fecha_intento') else ''}.")
    if d.get("motivo"):
        base += f" El banco respondió: {d['motivo'].lower()}."
    if d.get("proximo_intento"):
        base += f" Próximo intento: {d['proximo_intento']}."
    sesenta = " Recuerda: a los 60 días de atraso Allianz puede cancelar el plan en cualquier momento."
    return {"asesor": base + " Contacta al cliente para que tenga el monto disponible o se ponga al corriente." + sesenta,
            "ceci": base + sesenta}


def procesar(repo: Repositorio, correo_id: Optional[int], asunto: str, d: dict,
             buscar: Optional[Buscador] = None) -> dict:
    """Crea el ticket de cobranza (cerrado) y encola los avisos. Devuelve {ticket_id, plan, omitidos}."""
    ident = identificar(poliza=d["poliza"], buscar=buscar)
    datos = ident.datos if ident.ok else {}
    tid = repo.crear_ticket({"estado": "resuelto", "proceso": PROCESO, "producto": d["producto"],
                             "poliza": d["poliza"], "titulo_hilo": asunto, "etapa": ETAPA,
                             **({k: datos.get(k) for k in ("cliente_nombre", "cliente_correo", "telefono_cliente",
                                                            "asesor_correo", "telefono_asesor")} if ident.ok else {}),
                             **({"identificado_por": ident.via} if ident.ok else {})})
    if correo_id:
        repo.vincular_correo(correo_id, tid)
    ctx = contexto({"poliza": d["poliza"], "producto": d["producto"]}, {}, datos)
    t = textos(d, ctx["cliente"])
    plan_nombre = PRODUCTOS.get(d["producto"], (None, d["producto"]))[1]
    params = {"ticket": "Cobranza", "tramite": f"{plan_nombre} · Cargo rechazado", "cliente": ctx["cliente"],
              "etapa": "Cargo rechazado", "nombre": ctx["nombre"], "poliza": d["poliza"]}
    plan, omitidos = [], []
    if not ident.ok:
        omitidos.append(f"No pude identificar la póliza {d['poliza']} en Notion ({ident.motivo}): no se le avisó al asesor.")
    elif not datos.get("telefono_asesor"):
        omitidos.append("Falta el teléfono del asesor en Notion: no se le avisó.")
    else:
        a = _encolar(repo, tid, "asesor", t["asesor"], ETAPA, 1, str(datos["telefono_asesor"]), correo_id, params)
        if a:
            plan.append(a)
    lineas = [t["ceci"], *[f"⚠️ {o}" for o in omitidos]]
    if link_panel(tid):
        lineas.append(f"Panel: {link_panel(tid)}")
    a = _encolar(repo, tid, "ceci", "\n".join(lineas), ETAPA, 1, None, correo_id, params)
    if a:
        plan.append(a)
    repo.agregar_evento(tid, correo_id, "cobranza",
                        f"Cargo rechazado · avisos: {', '.join(x['rol'] for x in plan) or 'ninguno'}"[:200])
    return {"ticket_id": tid, "plan": plan, "omitidos": omitidos, "identificacion": ident.estado}


def activo() -> bool:
    return bool(config.MOTOR_ETAPAS and config.COBRANZA_AVISOS)
