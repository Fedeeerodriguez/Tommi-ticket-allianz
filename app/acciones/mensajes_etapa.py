"""Textos FIJOS por etapa (sin IA) — Etapa 1, proceso largo. Tabla del paso 5 del plan.

Lo único variable es lo que sale del correo de Allianz ("qué piden", recortado) y los datos del
ticket. Tuteo mexicano: clientes y asesores son de México. Ceci recibe el texto del asesor (o
el suyo propio) + lo que no se pudo avisar + el link al panel.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from app import config
from app.clasificador.etapas import PRODUCTOS

MAX_QUE_PIDEN = 300

TEXTOS: dict[str, dict[str, str]] = {
    "apertura": {
        "asesor": "Ticket {tk} · {cliente} · {producto}: Allianz abrió la solicitud {sol}.",
        "cliente": "Hola {nombre}, tu solicitud de {producto_cliente} ya está en Allianz y está en proceso "
                   "de autorización. Te avisamos cada avance.",
    },
    "requerimiento": {
        "asesor": "Ticket {tk} · {cliente}: Allianz pide → {que_piden}. Plazo: {plazo}.",
        "cliente": "Hola {nombre}, para avanzar Allianz necesita: {que_piden}. Tienes hasta el {fecha}. "
                   "Mándamelo por aquí y yo lo envío.",
    },
    "autorizado": {
        "asesor": "Ticket {tk} · {cliente}: autorizado, pasa a cobro.",
        "cliente": "Hola {nombre}, ¡tu solicitud fue autorizada! Sigue el cobro.",
    },
    "documentos_enviados": {
        "asesor": "Ticket {tk} · {cliente}: se enviaron los documentos a Allianz, esperamos respuesta.",
        "cliente": "Hola {nombre}, ya enviamos tus documentos a Allianz. Te avisamos cuando respondan.",
    },
    "atendida": {
        "asesor": "Ticket {tk} · {cliente}: atendido y cobrado. Ticket cerrado.",
        "cliente": "Hola {nombre}, ¡listo! Tu solicitud quedó atendida y cobrada.",
    },
    "rechazado": {
        "asesor": "Ticket {tk} · {cliente}: Allianz rechazó el ticket (venció el plazo). Contacta al cliente; "
                  "para seguir hay que cotizar de nuevo.",
    },
    "declinado": {
        "asesor": "Ticket {tk} · {cliente}: Selección de riesgos declinó el riesgo. Contacta al cliente.",
    },
    "cerrado_inactividad": {
        "asesor": "Ticket {tk} · {cliente}: Allianz cerró el ticket por inactividad. Contacta al cliente para retomarlo.",
        "cliente": "Hola {nombre}, Allianz cerró tu solicitud por falta de respuesta. Tu asesor te va a "
                   "contactar para retomarla.",
    },
    "poliza_emitida": {
        "asesor": "Ticket {tk} · {cliente}: póliza {poliza} emitida.",
        "cliente": "Hola {nombre}, ¡tu póliza {poliza} ya está emitida! Te va a llegar el acceso al portal de Allianz.",
    },
    "nota_ejecutiva": {
        "asesor": "Ticket {tk} · {cliente}: la ejecutiva de Allianz escribió: {mensaje}",
    },
    "copia_ejecutiva": {
        "ceci": "Ticket {tk} · {cliente}: la ejecutiva pide que respondamos directo en el ticket (con copia a ella).",
    },
    "rebote_ticket_cerrado": {
        "ceci": "Ticket {tk}: nuestra respuesta NO entró porque el ticket ya estaba cerrado en Allianz. "
                "Hay que abrir uno nuevo.",
    },
}


# Nombre de cada etapa como lo lee el equipo (va en el parámetro "tipo de trámite" de WATI).
ETIQUETAS = {
    "apertura": "Solicitud abierta en Allianz",
    "requerimiento": "Allianz pide documentos",
    "autorizado": "Autorizado para cobro",
    "documentos_enviados": "Documentos enviados a Allianz",
    "atendida": "Atendida y cobrada",
    "rechazado": "Rechazado por Allianz",
    "declinado": "Riesgo declinado",
    "cerrado_inactividad": "Cerrado por inactividad",
    "poliza_emitida": "Póliza emitida",
    "nota_ejecutiva": "Nota de la ejecutiva",
    "copia_ejecutiva": "La ejecutiva pide respuesta",
    "rebote_ticket_cerrado": "Respuesta no entregada (ticket cerrado)",
}


def params_wati(ctx: dict, etapa: str, telefono_cliente: Optional[str]) -> dict:
    """Datos sueltos para la plantilla 'actualización de trámite' (el despacho elige cuáles usa)."""
    return {"ticket": ctx.get("tk"), "tramite": f"{ctx.get('producto')} · {ETIQUETAS.get(etapa, etapa)}",
            "etapa": ETIQUETAS.get(etapa, etapa), "cliente": ctx.get("cliente"),
            "telefono": telefono_cliente or "—", "poliza": ctx.get("poliza"), "solicitud": ctx.get("sol")}


# "favor de enviar la carta laboral" → "la carta laboral" (para que lea bien: "Allianz necesita: …").
_RE_PEDIDO = re.compile(
    r"^(?:(?:le|les)\s+(?:solicitamos|pedimos)\s+(?:su\s+apoyo\s+)?|(?:por\s+)?favor\s+de\s+|requerimos\s+)"
    r"(?:(?:nos\s+)?(?:enviar|env[ií]e|proporcionar|proporcione|anexar|adjuntar|remitir|hacernos\s+llegar)\s+)?",
    re.I)


def _pedido(s: Optional[str]) -> str:
    t = _recortar(s)
    sin = _RE_PEDIDO.sub("", t, count=1).strip()
    return sin if len(sin) >= 3 else t


def _recortar(s: Optional[str], n: int = MAX_QUE_PIDEN) -> str:
    """Una línea, sin el punto final (lo pone la plantilla) y con '…' si se cortó."""
    s = re.sub(r"\s+", " ", s or "").strip()
    return s.rstrip(" .;:,") if len(s) <= n else s[: n - 1].rstrip(" ,.;:") + "…"


def _plazo(plazo) -> str:
    if not plazo:
        return f"{config.RECORDATORIO_HORAS_HABILES} h hábiles"
    n, unidad = plazo
    nombre = {"dias": "días", "dias_habiles": "días hábiles", "horas": "horas", "horas_habiles": "horas hábiles"}
    return f"{n} {nombre.get(unidad, unidad)}"


def _primer_nombre(nombre: Optional[str]) -> str:
    p = (nombre or "").split()
    return p[0].capitalize() if p else ""


def contexto(ticket: dict, etapa: dict, datos: Optional[dict] = None,
             vence: Optional[datetime] = None) -> dict:
    """Variables de las plantillas. `datos` = lo identificado en Notion (nombres con acentos)."""
    datos = datos or {}
    prod = etapa.get("producto") or ticket.get("producto")
    ramo = PRODUCTOS.get(prod, (None, prod or "tu seguro"))[1]
    cliente = datos.get("cliente_nombre") or etapa.get("cliente") or ticket.get("cliente_nombre") or "—"
    if cliente.isupper():  # Allianz escribe "MARTHA ZARATE URIBE"; Notion ya viene bien escrito
        cliente = cliente.title()
    return {
        "tk": etapa.get("nro_ticket") or ticket.get("nro_ticket") or "—",
        "cliente": re.sub(r"\s+", " ", cliente).strip(),
        "nombre": _primer_nombre(cliente) if cliente != "—" else "",
        "producto": ramo,
        "producto_cliente": ramo if any(c.isupper() for c in ramo[1:]) else ramo.lower(),
        "sol": etapa.get("nro_solicitud") or ticket.get("nro_solicitud") or "—",
        "poliza": etapa.get("poliza") or ticket.get("poliza") or "—",
        "que_piden": _pedido(etapa.get("que_piden")) or "información adicional",
        "plazo": _plazo(etapa.get("plazo")),
        "fecha": vence.strftime("%d/%m/%Y") if vence else "—",
        "mensaje": _recortar(etapa.get("mensaje")),
    }


def texto(rol: str, etapa: str, ctx: dict, avisos_omitidos: Optional[list[str]] = None) -> Optional[str]:
    """Texto para `rol` en `etapa`. None si esa etapa no le habla a ese rol."""
    t = TEXTOS.get(etapa, {})
    if rol == "ceci":
        base = t.get("ceci") or t.get("asesor") or f"Ticket {{tk}} · {{cliente}}: {etapa.replace('_', ' ')}."
        lineas = [_puntuacion(base.format(**ctx))]
        lineas += [f"⚠️ {a}" for a in (avisos_omitidos or [])]
        if config.PANEL_URL and ctx.get("ticket_id"):
            lineas.append(f"Panel: {config.PANEL_URL.rstrip('/')}/tickets/{ctx['ticket_id']}")
        return "\n".join(lineas)
    plantilla = t.get(rol)
    if not plantilla:
        return None
    if rol == "cliente" and not ctx.get("nombre"):
        plantilla = plantilla.replace("Hola {nombre}, ", "Hola, ")
    return _puntuacion(plantilla.format(**ctx))


def _puntuacion(t: str) -> str:
    return t.replace("….", "…").replace("..", ".")
