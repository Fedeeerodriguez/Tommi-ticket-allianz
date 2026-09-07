"""Clasificador L1 — reglas baratas y deterministas.

Filosofía: resolver barato lo obvio (publicidad, sistema, dominio Allianz, CC de cliente)
ANTES de gastar un LLM. Lo que quede ambiguo (confianza < umbral) se marca `necesita_llm`
para que la capa L2 lo resuelva más adelante.

Cada regla devuelve trazabilidad (`motivo`) para poder auditar y afinar con datos reales.
La detección fina de "respuesta vs acuse vs pedido" se hará mejor con la extracción de
entidades + el estado del ticket en DB; acá damos una primera aproximación.
"""
from __future__ import annotations

import re

from app import config
from app.models import Clasificacion, Correo, TipoCorreo

# --- Señales ---
# El nº de ticket/folio SIEMPRE tiene dígitos → exigirlo evita capturar palabras
# sueltas (ej. "solicitud\nEstimado" agarraba "Estimado").
_RE_TICKET = re.compile(
    r"(?:ticket|folio|caso|solicitud)\s*(?:n[°ºo]?\.?|#|:)?\s*([0-9][0-9\-]{3,}|[A-Z]{1,4}[0-9][A-Z0-9\-]{2,})",
    re.I,
)
_RE_ACUSE = re.compile(r"\b(se\s+(?:ha\s+|han\s+)?(?:cre|gener|abri|registr|levant)\w*|hemos\s+recibido|n[uú]mero\s+de\s+(?:ticket|folio|caso)|se\s+(?:le\s+)?asign[oó])\b", re.I)
_RE_PIDE = re.compile(r"\b(favor\s+de|es\s+necesario|requerimos|debe(?:r[aá])?\s+(?:enviar|adjuntar|firmar|completar)|adjunt[ae]|proporcion[ae]|env[ií]e|complete)\b", re.I)
_RE_PREGUNTA_PRODUCTO = re.compile(r"\b(c[oó]mo|cu[aá]l|cu[aá]nto|qu[eé]|se\s+puede|es\s+posible|duda|consulta|producto|cobertura|prima|comisi[oó]n)\b", re.I)
_RE_REENVIO = re.compile(r"^(fw:|fwd:|rv:|reenv)", re.I)
_RE_CODIGO = re.compile(r"\b(c[oó]digo\s+(?:de\s+)?(?:verificaci[oó]n|seguridad|acceso)|one[-\s]?time|otp|2fa|token)\b", re.I)


def _es_allianz(direccion_o_dominio: str) -> bool:
    d = direccion_o_dominio.split("@")[-1].lower()
    return any(d == dom or d.endswith("." + dom) for dom in config.ALLIANZ_DOMINIOS)


def _tiene_dominio_allianz(direcciones: list[str]) -> bool:
    return any(_es_allianz(a) for a in direcciones)


def _nos_copiaron(correo: Correo) -> bool:
    propias = set(config.BABILONIA_ADDRESSES)
    return any(a in propias for a in correo.cc)


def clasificar_l1(correo: Correo) -> Clasificacion:
    asunto = correo.asunto or ""
    cuerpo = correo.cuerpo_texto or ""
    texto = f"{asunto}\n{cuerpo}"

    # 1) Sistema / 2FA (muy barato y de alta certeza).
    remitente_local = correo.remitente.split("@")[0].lower()
    if _RE_CODIGO.search(texto) or any(t in remitente_local for t in ("noreply", "no-reply", "notif", "mailer")):
        return Clasificacion(TipoCorreo.G_SISTEMA, 0.9, "patrón de código/2FA o remitente de sistema")

    # 2) Publicidad / newsletter (header estándar).
    if "list-unsubscribe" in correo.headers:
        return Clasificacion(TipoCorreo.H_PUBLICIDAD, 0.85, "header List-Unsubscribe presente")

    from_allianz = _es_allianz(correo.remitente)

    # 3) CC de cliente: NO viene de Allianz, va dirigido a Allianz, y nos copiaron.
    if not from_allianz and _tiene_dominio_allianz(correo.para) and _nos_copiaron(correo):
        return Clasificacion(TipoCorreo.E_CC_CLIENTE, 0.85,
                             "destinatario Allianz + Babilonia en CC (cliente nos copió)")

    # 4) Viene de Allianz → distinguir respuesta / acuse / pedido.
    if from_allianz:
        m = _RE_TICKET.search(texto)
        entidades = {"nro_ticket": m.group(1)} if m else {}
        if _RE_ACUSE.search(texto):
            return Clasificacion(TipoCorreo.B_ACUSE_TICKET, 0.75,
                                 "remitente Allianz + lenguaje de acuse/creación", entidades=entidades)
        if _RE_PIDE.search(texto):
            return Clasificacion(TipoCorreo.C_ALLIANZ_PIDE, 0.7,
                                 "remitente Allianz + solicitud de acción al cliente", entidades=entidades)
        if m:
            return Clasificacion(TipoCorreo.A_RESPUESTA_TICKET, 0.7,
                                 "remitente Allianz + nº de ticket detectado", entidades=entidades)
        # De Allianz pero sin señal clara → probable respuesta, baja confianza → L2.
        return Clasificacion(TipoCorreo.A_RESPUESTA_TICKET, 0.5,
                             "remitente Allianz sin señal específica", necesita_llm=True, entidades=entidades)

    # 5) Reenvío de asesor pidiendo abrir trámite (aprox.; confirmar asesor con Notion en L2/enriquecimiento).
    if _RE_REENVIO.search(asunto):
        return Clasificacion(TipoCorreo.D_REENVIO_ASESOR, 0.55,
                             "asunto de reenvío (Fw/Fwd/Rv)", necesita_llm=True)

    # 6) Consulta de producto (pregunta sin ser Allianz ni reenvío).
    if _RE_PREGUNTA_PRODUCTO.search(texto):
        return Clasificacion(TipoCorreo.F_CONSULTA_PRODUCTO, 0.5,
                             "lenguaje de pregunta/consulta de producto", necesita_llm=True)

    # 7) Nada matcheó con confianza → a revisión.
    c = Clasificacion(TipoCorreo.I_NO_CLASIFICABLE, 0.3, "ninguna regla L1 matcheó")
    c.necesita_llm = True
    return c
