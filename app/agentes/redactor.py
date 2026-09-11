"""Agente LangChain redactor: mensajes coloquiales de WhatsApp para cliente/asesor.

Cadena LangChain (`ChatPromptTemplate | ChatOpenAI`). Si falla o no hay key, devuelve None
y el que llama (resumen.generar) cae a la plantilla fija sin costo.
"""
from __future__ import annotations

import logging
from typing import Optional

from app import config

log = logging.getLogger(__name__)

_SISTEMA = (
    "Sos Tommy, asistente de Babilonia (correduría de seguros con Allianz). Escribí un "
    "mensaje de WhatsApp BREVE (máx 3 frases), cálido y claro, en español rioplatense neutro, "
    "sin tecnicismos ni datos sensibles. No inventes datos que no estén en el contexto."
)
_USUARIO = (
    "Destinatario: {rol}. Contexto del ticket: {ctx}. "
    "Redactá SOLO el mensaje, sin comillas ni encabezados."
)


def _construir_cadena():
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI

    prompt = ChatPromptTemplate.from_messages([("system", _SISTEMA), ("user", _USUARIO)])
    llm = ChatOpenAI(model=config.MODELO_L2, temperature=0.4, max_tokens=180,
                     api_key=config.OPENAI_API_KEY)
    return prompt | llm


def redactar(rol: str, ctx: dict) -> Optional[str]:
    if not (config.USAR_LLM_RESUMEN and config.hay_llm()):
        return None
    try:
        resp = _construir_cadena().invoke({"rol": rol, "ctx": ctx})
        texto = (resp.content or "").strip()
        return texto or None
    except Exception as ex:  # noqa: BLE001
        log.warning("agente redactor falló, uso plantilla: %s", ex)
        return None
