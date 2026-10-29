"""Textos FIJOS por etapa (sin IA). Etapa 1: proceso largo (paso 5 del plan). Etapa 2: proceso corto
(guía de aportación, pago) y trámites (siempre con n° de ticket + cliente + asunto).

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
        "asesor": "Ticket {tk} · {cliente}{con_producto}: Allianz abrió la solicitud{con_sol}, está en proceso "
                  "de autorización.",
        "cliente": "Hola {nombre}, tu solicitud{de_producto} ya está en Allianz y está en proceso "
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
        "asesor": "Ticket {tk} · {cliente}: Allianz rechazó el ticket (venció el plazo). Antes de contactar al "
                  "cliente, comunícate con Ceci para revisarlo; para seguir hay que cotizar de nuevo.",
        "ceci": "Ticket {tk} · {cliente}: Allianz rechazó el ticket (venció el plazo). Le pedimos al asesor que "
                "lo revise contigo antes de contactar al cliente.",
    },
    "declinado": {
        "asesor": "Ticket {tk} · {cliente}: Selección de riesgos declinó el riesgo. Antes de contactar al "
                  "cliente, comunícate con Ceci para revisarlo.",
        "ceci": "Ticket {tk} · {cliente}: Selección de riesgos declinó el riesgo. Le pedimos al asesor que lo "
                "revise contigo antes de contactar al cliente.",
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

# Etapa 2: lo que cambia por proceso (lo que no está acá usa TEXTOS).
TEXTOS_PROCESO: dict[tuple[str, str], dict[str, str]] = {
    # --- Trámites (los abrimos nosotros): SIEMPRE n° de ticket + cliente + asunto (pedido de Ceci).
    ("tramite", "apertura"): {
        "asesor": "Ticket {tk} · {cliente}{con_asunto}: Allianz recibió el trámite.",
        "cliente": "Hola {nombre}, Allianz ya recibió tu trámite{de_asunto} (ticket {tk}). Te aviso cada avance.",
    },
    ("tramite", "requerimiento"): {
        "asesor": "Ticket {tk} · {cliente}{con_asunto}: Allianz pide → {que_piden}. Plazo: {plazo}.",
        "cliente": "Hola {nombre}, para avanzar con tu trámite{de_asunto}, Allianz necesita: {que_piden}. "
                   "Tienes hasta el {fecha}. Mándamelo por aquí y yo lo envío.",
    },
    ("tramite", "documentos_enviados"): {
        "asesor": "Ticket {tk} · {cliente}{con_asunto}: le respondimos a Allianz, esperamos respuesta.",
        "cliente": "Hola {nombre}, ya le mandamos a Allianz lo de tu trámite{de_asunto}. Te aviso cuando respondan.",
    },
    ("tramite", "atendida"): {
        "asesor": "Ticket {tk} · {cliente}{con_asunto}: Allianz lo atendió. Ticket cerrado.",
        "cliente": "Hola {nombre}, ¡listo! Allianz atendió tu trámite{de_asunto}.",
    },
    ("tramite", "cerrado_inactividad"): {
        "asesor": "Ticket {tk} · {cliente}{con_asunto}: Allianz cerró el ticket por inactividad. "
                  "Contacta al cliente para retomarlo.",
        "cliente": "Hola {nombre}, Allianz cerró tu trámite{de_asunto} por falta de respuesta. Tu asesor te va "
                   "a contactar para retomarlo.",
    },
    ("tramite", "rechazado"): {
        "asesor": "Ticket {tk} · {cliente}{con_asunto}: Allianz rechazó el trámite. Antes de contactar al "
                  "cliente, comunícate con Ceci para revisarlo.",
        "ceci": "Ticket {tk} · {cliente}{con_asunto}: Allianz rechazó el trámite. Le pedimos al asesor que lo "
                "revise contigo antes de contactar al cliente.",
    },
    # --- Proceso corto (Elite / Patrimonial / OptiMaxx Plus).
    ("corto", "confirmacion_datos"): {
        "ceci": "Ticket {tk} · {cliente}{con_producto}: Allianz confirmó los datos{con_poliza}{con_solicitud}. "
                "La guía de aportación está lista para que confirmes el número de solicitud y el monto, y la apruebes.",
    },
    ("corto", "documentos_enviados"): {
        # En Elite y Patrimonial el comprobante lo manda el cliente (al ticket o a cliente.inversion@).
        "asesor": "Ticket {tk} · {cliente}: Allianz ya tiene el comprobante de pago, esperamos la emisión.",
        "cliente": "Hola {nombre}, Allianz ya tiene tu comprobante de pago. Te aviso cuando tu póliza "
                   "quede emitida.",
    },
    ("corto", "atendida"): {
        "asesor": "Ticket {tk} · {cliente}: Allianz lo atendió. Ticket cerrado.",
        "cliente": "Hola {nombre}, ¡listo! Allianz atendió tu solicitud.",
    },
    # Aviso de la guía aprobada por Ceci. Al cliente le sale la plantilla de la guía de su producto
    # (GUIAS); el texto queda registrado tal cual le llega.
    ("corto", "guia_aportacion"): {
        "asesor": "Ticket {tk} · {cliente}: le mandamos al cliente la guía de aportación (aprobada por Ceci). "
                  "{resumen_guia}.",
        "cliente": "{guia}",
    },
}

# Guía de aportación = la plantilla de WATI `tommy_guia_aportacion` (misma redacción). El sistema
# pone nombre, producto y póliza; Ceci completa MONTO y DATOS PARA DEPOSITAR antes de aprobar
# (sin esos dos no se puede aprobar).
GUIA_PLANTILLA = (
    "Hola {nombre} 👋 Allianz ya confirmó tu solicitud de {producto} (póliza {poliza}). Para activarla "
    "falta tu aportación inicial:\n\n"
    "• Monto: {monto}\n"
    "• Datos para depositar: {datos_deposito}\n"
    "• Referencia: póliza {poliza}\n\n"
    "Cuando deposites, mándame por aquí el comprobante y tu estado de cuenta, y yo lo envío a Allianz."
)
# Patrimonial y Elite: los pasos que Ceci les manda hoy (22/10). La cuenta para depositar viene en el
# correo "Felicidades" de Allianz; Ceci confirma el MONTO (la cantidad exacta de la solicitud) y el
# N° DE SOLICITUD (la referencia del pago; viene precargado del correo de Allianz).
# Patrimonial: el comprobante va a cliente.inversion@; Elite: como respuesta al mismo ticket de soporte.
GUIA_PATRIMONIAL = (
    "Hola {nombre} 👋 Allianz ya registró tu solicitud de Patrimonial. Para activarla falta tu aportación:\n\n"
    "1. En el correo de Allianz “Felicidades” (Emisión de póliza) está la cuenta bancaria para la aportación.\n"
    "2. Haz el pago por {monto}, la cantidad exacta registrada en tu solicitud. En concepto y referencia pon SOLO "
    "tu número de solicitud: {solicitud}. Si no lo incluyes, Allianz no podrá reconocer tu pago.\n"
    "3. Envía el comprobante y tu estado de cuenta bancario a cliente.inversion@allianz.com.mx con copia a "
    "soporte@babilonia.ai. En el asunto pon: Aplicación de fondos / {poliza} / {cliente}\n\n"
    "Tu aportación se refleja en el portal 48 horas hábiles después de que Allianz confirme el pago."
)
GUIA_ELITE = (
    "Hola {nombre} 👋 Allianz ya registró tu solicitud de Elite. Para activarla falta tu aportación:\n\n"
    "1. En el correo de Allianz “Felicidades” (Emisión de póliza) está la cuenta bancaria para la aportación.\n"
    "2. Haz el pago por {monto}, la cantidad exacta registrada en tu solicitud. En concepto y referencia pon tu "
    "número de solicitud: {solicitud}. Si no lo incluyes, Allianz no podrá reconocer tu pago.\n"
    "3. Envía el comprobante y tu estado de cuenta bancario respondiendo al correo del ticket de soporte {ticket} "
    "de Allianz (no abras uno nuevo), con copia a soporte@babilonia.ai. En el asunto pon: Aplicación de fondos / "
    "{poliza} / {cliente}\n\n"
    "Tu aportación se refleja en el portal 48 horas hábiles después de que Allianz confirme el pago."
)
# Una guía por producto: texto, lo que completa/confirma Ceci y las variables de su plantilla de WATI.
# Los productos que no están acá (OptiMaxx Plus) usan la guía general (monto + datos para depositar).
GUIAS = {
    "OPPT": {"plantilla": "patrimonial", "texto": GUIA_PATRIMONIAL, "campos": ("monto", "solicitud"),
             "variables": ("nombre", "monto", "solicitud", "poliza", "cliente")},
    "SVIP": {"plantilla": "elite", "texto": GUIA_ELITE, "campos": ("monto", "solicitud"),
             "variables": ("nombre", "monto", "solicitud", "ticket", "poliza", "cliente")},
}
GUIA_GENERAL = {"plantilla": "general", "texto": GUIA_PLANTILLA, "campos": ("monto", "datos_deposito"),
                "variables": ("nombre", "producto", "poliza", "monto", "datos_deposito")}
CAMPOS_CECI = ("monto", "datos_deposito", "solicitud")
NOMBRES_CAMPOS = {"monto": "monto", "datos_deposito": "datos para depositar", "solicitud": "número de solicitud"}
FALTA_COMPLETAR = "[completar"


def guia_de(datos: Optional[dict]) -> dict:
    """La guía que corresponde (por el producto guardado en la aprobación; las viejas, la general)."""
    return GUIAS.get((datos or {}).get("tipo") or "", GUIA_GENERAL)


def campos_guia(datos: Optional[dict]) -> tuple:
    return guia_de(datos)["campos"]


def _dato(v) -> str:
    """Los rellenos de `contexto` ("—", "cliente sin identificar") no son datos: la guía los deja vacíos."""
    return "" if v in (None, "", "—", "cliente sin identificar") else str(v)


def datos_guia(ctx: dict, producto: Optional[str] = None) -> dict:
    """Variables de la guía que pone el sistema. Lo de Ceci arranca vacío, salvo el n° de solicitud,
    que viene del correo de Allianz y Ceci solo lo confirma (o lo corrige)."""
    return {"tipo": producto if producto in GUIAS else "", "nombre": ctx.get("nombre") or "",
            "producto": ctx.get("producto_cliente") or "", "poliza": _dato(ctx.get("poliza")),
            "ticket": _dato(ctx.get("tk")), "cliente": _dato(ctx.get("cliente")),
            "monto": "", "datos_deposito": "", "solicitud": _dato(ctx.get("sol"))}


def faltan_en_guia(datos: dict) -> list[str]:
    return [NOMBRES_CAMPOS[k] for k in campos_guia(datos) if not str((datos or {}).get(k) or "").strip()]


# Datos de la guía que pone el sistema (del ticket), sin los cuales el texto al cliente queda roto.
DATOS_DEL_TICKET = {"poliza": "la póliza", "ticket": "el n° de ticket", "cliente": "el nombre del cliente"}


def faltan_del_ticket(datos: dict) -> list[str]:
    return [DATOS_DEL_TICKET[k] for k in guia_de(datos)["variables"]
            if k in DATOS_DEL_TICKET and not _dato(str((datos or {}).get(k) or "").strip())]


def completar_del_ticket(datos: dict, ticket: dict) -> dict:
    """Lo que la guía no tenía al crearse (póliza, ticket, nombre…) y el ticket ya tiene."""
    nuevos = datos_guia(contexto(ticket, {}))
    return {k: nuevos[k] for k in ("nombre", *DATOS_DEL_TICKET)
            if nuevos.get(k) and not _dato((datos or {}).get(k))}


def valores_guia(datos: dict) -> dict:
    """Todas las variables de la guía, con [completar] en lo que falta (nunca vacías: WhatsApp no las acepta)."""
    d = {k: str(v).strip() for k, v in (datos or {}).items() if v is not None}
    valores = {"nombre": d.get("nombre") or "de nuevo", "producto": d.get("producto") or "tu plan",
               "poliza": d.get("poliza") or "[completar]", "ticket": d.get("ticket") or "[completar]",
               "cliente": d.get("cliente") or "[completar]"}
    for k in CAMPOS_CECI:
        valores[k] = d.get(k) or "[completar]"
    return valores


def texto_guia(datos: dict) -> str:
    """Lo que le llega al cliente (lo que no está completo queda como [completar])."""
    return guia_de(datos)["texto"].format(**valores_guia(datos))


def resumen_guia(datos: dict) -> str:
    """Lo que completó Ceci, para el aviso al asesor: 'N° de solicitud: 25290001'."""
    v = valores_guia(datos)
    return " · ".join(f"{NOMBRES_CAMPOS[k][:1].upper()}{NOMBRES_CAMPOS[k][1:]}: {v[k]}" for k in campos_guia(datos))


# Recordatorios (paso 6). Clave: (motivo, momento) → rol → texto. momento = recordatorio | escalado.
TEXTOS_RECORDATORIO: dict[tuple[str, str], dict[str, str]] = {
    ("requerimiento", "recordatorio"): {
        "cliente": "Hola {nombre}, te recuerdo que Allianz sigue esperando: {que_piden}. "
                   "Mándamelo por aquí y yo lo envío.",
        "asesor": "Ticket {tk} · {cliente}{con_asunto}: sigue pendiente lo que pidió Allianz → {que_piden}.{ya_cliente}",
    },
    ("requerimiento", "escalado"): {
        "asesor": "Ticket {tk} · {cliente}{con_asunto}: el cliente todavía no manda lo que pidió Allianz ({que_piden}). "
                  "Si vence el plazo, Allianz rechaza el ticket. Contacta al cliente.",
        "ceci": "Ticket {tk} · {cliente}{con_asunto}: el cliente todavía no manda lo que pidió Allianz ({que_piden}). "
                "Si vence el plazo, Allianz rechaza el ticket.",
    },
    ("esperando_allianz", "recordatorio"): {
        "ceci": "Ticket {tk} · {cliente}{con_asunto}: Allianz no responde desde que mandamos {lo_enviado} ({desde}). "
                "Si sigue sin responder, se escala con copia a la ejecutiva.",
    },
    ("esperando_allianz", "escalado"): {
        "ceci": "Ticket {tk} · {cliente}{con_asunto}: Allianz sigue sin responder. Dejé listo un correo en el hilo con "
                "copia a {cc} para que lo apruebes.",
    },
    ("esperando_allianz", "escalado_sin_correo"): {  # ESCALAR_A_ALLIANZ apagado
        "ceci": "Ticket {tk} · {cliente}{con_asunto}: Allianz sigue sin responder. Conviene escribirles en el hilo con "
                "copia a {cc}.",
    },
    # Etapa 2 — proceso corto: el cliente tiene que depositar (desde que Ceci aprobó la guía).
    ("pago", "recordatorio"): {
        "cliente": "Hola {nombre}, te recuerdo que falta tu aportación para activar tu {producto_cliente}. "
                   "Cuando deposites, mándame por aquí el comprobante y tu estado de cuenta.",
        "asesor": "Ticket {tk} · {cliente}: el cliente todavía no manda el comprobante de pago de la guía "
                  "de aportación.{ya_cliente}",
    },
    ("pago", "escalado"): {
        "asesor": "Ticket {tk} · {cliente}: sigue sin llegar el comprobante de pago de la guía de aportación. "
                  "Contacta al cliente.",
        "ceci": "Ticket {tk} · {cliente}: sigue sin llegar el comprobante de pago de la guía de aportación.",
    },
}

# Correo de escalación a Allianz (en el hilo del ticket, formal: usted).
CORREO_ESCALACION = (
    "Buen día,\n\n"
    "Damos seguimiento {referencia}. El {desde} enviamos {lo_enviado_formal} "
    "y a la fecha no hemos recibido respuesta.\n\n"
    "¿Nos apoyan con el estatus, por favor?\n\n"
    "Quedamos atentos.\nBabilonia"
)


def link_panel(ticket_id) -> str:
    """Link directo al ticket en el panel de Tomi (página Ticket Allianz Seguimiento). PANEL_URL es la
    dirección de Tomi; si ya trae /tickets-allianz al final, también sirve. Sin PANEL_URL, sin link."""
    base = (config.PANEL_URL or "").strip().rstrip("/")
    if not (base and ticket_id):
        return ""
    if base.endswith("/tickets-allianz"):
        base = base[: -len("/tickets-allianz")]
    return f"{base}/tickets-allianz?ticket={ticket_id}"


def texto_recordatorio(rol: str, motivo: str, momento: str, ctx: dict,
                       avisos_omitidos: Optional[list[str]] = None) -> Optional[str]:
    t = TEXTOS_RECORDATORIO.get((motivo, momento), {}).get(rol)
    if rol == "ceci" and not t:
        t = TEXTOS_RECORDATORIO.get((motivo, momento), {}).get("asesor") or "Ticket {tk} · {cliente}: recordatorio."
    if not t:
        return None
    if rol == "cliente" and not ctx.get("nombre"):
        t = t.replace("Hola {nombre}, ", "Hola, ")
    lineas = [_puntuacion(t.format(**ctx))]
    if rol == "ceci":
        lineas += [f"⚠️ {a}" for a in (avisos_omitidos or [])]
        if link_panel(ctx.get("ticket_id")):
            lineas.append(f"Panel: {link_panel(ctx['ticket_id'])}")
    return "\n".join(lineas)


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
    "copia_ejecutiva": "Copia de la ejecutiva",
    "confirmacion_datos": "Allianz confirmó los datos",
    "emision_registrada": "Emisión registrada",
    "revisar": "Revisar a mano",
    "recordatorio_allianz": "Recordatorio automático de Allianz",
    "rebote_ticket_cerrado": "Respuesta no entregada (ticket cerrado)",
    "recordatorio_requerimiento": "Recordatorio: Allianz espera documentos",
    "escalado_requerimiento": "Urgente: documentos pendientes",
    "recordatorio_esperando_allianz": "Allianz sin respuesta",
    "escalado_esperando_allianz": "Escalado a Allianz",
    "escalado_sin_correo_esperando_allianz": "Allianz sigue sin responder",
    "guia_aportacion": "Guía de aportación",
    "recordatorio_pago": "Recordatorio: falta el pago",
    "escalado_pago": "Urgente: falta el pago",
}


# Etapa 2: el nombre cambia según el proceso (un trámite no se "cobra"; en el corto lo enviado es el pago).
ETIQUETAS_PROCESO = {
    ("tramite", "apertura"): "Trámite recibido por Allianz",
    ("tramite", "requerimiento"): "Allianz pide algo del trámite",
    ("tramite", "documentos_enviados"): "Respuesta enviada a Allianz",
    ("tramite", "atendida"): "Trámite atendido",
    ("corto", "confirmacion_datos"): "Datos confirmados · guía de aportación",
    ("corto", "documentos_enviados"): "Pago enviado a Allianz",
    ("corto", "atendida"): "Atendido",
}


def etiqueta(etapa: Optional[str], proceso: Optional[str] = None) -> str:
    return ETIQUETAS_PROCESO.get((proceso or "", etapa or "")) or ETIQUETAS.get(etapa or "", etapa or "")


def params_wati(ctx: dict, etapa: str, telefono_cliente: Optional[str], proceso: Optional[str] = None) -> dict:
    """Datos sueltos para la plantilla 'actualización de trámite' (el despacho elige cuáles usa)."""
    nombre = etiqueta(etapa, proceso)
    # Trámites: el asunto con que lo abrimos (pedido de Ceci); el resto, el producto.
    que = ctx.get("asunto") if proceso == "tramite" and ctx.get("asunto") not in (None, "", "—") else ctx.get("producto")
    return {"ticket": ctx.get("tk"), "tramite": f"{que} · {nombre}" if que not in (None, "", "—") else nombre,
            "etapa": nombre, "cliente": ctx.get("cliente"), "nombre": ctx.get("nombre"),
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
    """Una línea, sin el punto final (lo pone la plantilla) y con '…' si se cortó (en una palabra entera)."""
    s = re.sub(r"\s+", " ", s or "").strip()
    if len(s) <= n:
        return s.rstrip(" .;:,")
    corte = s[: n - 1]
    if " " in corte[n // 2:]:
        corte = corte.rsplit(" ", 1)[0]
    return corte.rstrip(" ,.;:(") + "…"


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
    ramo = PRODUCTOS.get(prod, (None, prod or ""))[1]
    # "gastos médicos" va en minúscula; las marcas del proceso corto (Elite, Patrimonial, OptiMaxx Plus), no.
    marca = PRODUCTOS.get(prod, ("",))[0] == "corto" or any(c.isupper() for c in ramo[1:])
    ramo_cliente = ramo if marca else ramo.lower()
    cliente = datos.get("cliente_nombre") or etapa.get("cliente") or ticket.get("cliente_nombre") or ""
    if cliente.isupper():  # Allianz escribe "MARTHA ZARATE URIBE"; Notion ya viene bien escrito
        cliente = cliente.title()
    # Nombres de Notion a veces traen ruido ("María .  del Carmen"): fuera puntos sueltos y espacios dobles.
    cliente = re.sub(r"\s+", " ", re.sub(r"(?<!\w)\.(?!\w)", " ", cliente)).strip()
    sol = etapa.get("nro_solicitud") or ticket.get("nro_solicitud")
    poliza = etapa.get("poliza") or ticket.get("poliza")
    tk = etapa.get("nro_ticket") or ticket.get("nro_ticket") or "—"
    asunto = _asunto(etapa.get("titulo_hilo")) if (etapa.get("proceso") or ticket.get("proceso")) == "tramite" \
        else None
    asunto = asunto or ticket.get("titulo_hilo") or ""
    cliente_ref = cliente or "cliente sin identificar"
    if asunto:
        referencia = f"al trámite «{asunto}» de {cliente_ref} (ticket {tk})"
    elif sol:
        referencia = f"a la solicitud {sol} de {cliente_ref} (ticket {tk})"
    elif poliza:
        referencia = f"a la póliza {poliza} de {cliente_ref} (ticket {tk})"
    else:
        referencia = f"al ticket {tk} de {cliente_ref}"
    return {
        "tk": tk,
        "cliente": cliente or "cliente sin identificar",
        "nombre": _primer_nombre(cliente),
        "producto": ramo or "—",
        "producto_cliente": ramo_cliente or "tu seguro",
        # Partes que desaparecen si no se saben (para no escribir "tu seguro" o "solicitud —").
        "con_producto": f" · {ramo}" if ramo else "",
        "de_producto": f" de {ramo_cliente}" if ramo else "",
        "con_sol": f" {sol}" if sol else "",
        "con_solicitud": f", solicitud {sol}" if sol else "",
        "ya_cliente": "",
        "sol": sol or "—",
        "poliza": poliza or "—",
        "con_poliza": f" (póliza {poliza})" if poliza else "",
        # Trámites: el asunto con que lo abrimos ("Aplicación de mensualidad").
        "asunto": asunto or "—",
        "con_asunto": f" · {asunto}" if asunto else "",
        "de_asunto": f" «{asunto}»" if asunto else "",
        "referencia": referencia,
        # Lo que le mandamos a Allianz y quedó sin respuesta (recordatorio "esperando a Allianz").
        "lo_enviado": {"corto": "el comprobante de pago", "tramite": "nuestra respuesta"}.get(
            etapa.get("proceso") or ticket.get("proceso"), "los documentos"),
        "lo_enviado_formal": {"corto": "el comprobante de pago", "tramite": "la información solicitada"}.get(
            etapa.get("proceso") or ticket.get("proceso"), "la documentación solicitada"),
        "guia": "",
        "resumen_guia": "",
        "que_piden": _pedido(etapa.get("que_piden")) or "información adicional",
        "plazo": _plazo(etapa.get("plazo")),
        "fecha": vence.strftime("%d/%m/%Y") if vence else "—",
        "mensaje": _recortar(etapa.get("mensaje")),
    }


def texto(rol: str, etapa: str, ctx: dict, avisos_omitidos: Optional[list[str]] = None,
          proceso: Optional[str] = None) -> Optional[str]:
    """Texto para `rol` en `etapa` (y proceso). None si esa etapa no le habla a ese rol."""
    t = {**TEXTOS.get(etapa, {}), **TEXTOS_PROCESO.get((proceso or "", etapa), {})}
    if rol == "ceci":
        base = t.get("ceci") or t.get("asesor") or f"Ticket {{tk}} · {{cliente}}: {etapa.replace('_', ' ')}."
        lineas = [_puntuacion(base.format(**ctx))]
        lineas += [f"⚠️ {a}" for a in (avisos_omitidos or [])]
        if link_panel(ctx.get("ticket_id")):
            lineas.append(f"Panel: {link_panel(ctx['ticket_id'])}")
        return "\n".join(lineas)
    plantilla = t.get(rol)
    if not plantilla:
        return None
    if rol == "cliente" and not ctx.get("nombre"):
        plantilla = plantilla.replace("Hola {nombre}, ", "Hola, ")
    return _puntuacion(plantilla.format(**ctx))


def _puntuacion(t: str) -> str:
    return t.replace("….", "…").replace("..", ".")


def _asunto(titulo: Optional[str]) -> Optional[str]:
    """'[EXT] Aplicaciónes de mensualidad' → 'Aplicaciónes de mensualidad'."""
    t = re.sub(r"^\s*\[EXT\]\s*", "", titulo or "", flags=re.I).strip()
    return t[:200] or None
