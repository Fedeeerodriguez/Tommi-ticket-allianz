"""Agente LangChain redactor: mensajes coloquiales de WhatsApp para cliente/asesor.

Cadena LangChain (`ChatPromptTemplate | ChatOpenAI`). Si falla o no hay key, devuelve None
y el que llama (resumen.generar) cae a la plantilla fija sin costo.

Anti-alucinación: temperatura 0, reglas duras en el prompt y, además, la salida pasa por
`guardarrailes.validar_whatsapp` (determinístico). Si rompe una regla, se descarta.
"""
from __future__ import annotations

import logging
from typing import Optional

from app import config
from app.agentes import guardarrailes

log = logging.getLogger(__name__)

# Marca que devuelve la IA cuando no hay nada concreto que contarle al cliente.
SIN_NOVEDAD = "SIN_NOVEDAD"

_SISTEMA = (
    "Sos Tommy, asistente de Babilonia (correduría de seguros con Allianz). Escribís UN mensaje "
    "de WhatsApp breve (máximo 3 frases), cálido y claro, en español neutro.\n\n"
    "REGLAS DURAS (si no podés cumplir alguna, no la rompas: aplicá la salida indicada):\n"
    "1. SOLO hechos que estén ESCRITOS en `novedad_allianz` o en los campos del contexto. "
    "Prohibido deducir, suponer, completar o adornar. Si un dato no está, no existe.\n"
    "2. NOMBRES: al cliente lo llamás SOLO por `cliente_nombre`. Si `cliente_nombre` viene vacío, "
    "saludá sin nombre (\"Hola,\"). `autor_mensaje_allianz` es un EMPLEADO DE ALLIANZ, nunca el "
    "cliente: jamás lo uses para saludar al cliente. No nombres a ninguna otra persona.\n"
    "3. Nunca digas que Babilonia o el cliente enviaron, adjuntaron, pagaron o entregaron algo, "
    "salvo que `novedad_allianz` lo diga textualmente.\n"
    "4. No prometas plazos, fechas ni resultados. No menciones montos que no estén en "
    "`novedad_allianz`. Sin datos médicos ni sensibles.\n"
    "5. Nada de relleno: prohibido \"estamos revisando tu consulta\", \"te responderemos a la "
    "brevedad\" o similares sin un hecho concreto detrás.\n"
    "6. Destinatario CLIENTE: si `novedad_allianz` no trae un hecho concreto y útil PARA EL "
    f"CLIENTE (un avance, un pedido de documentación, una resolución), respondé exactamente "
    f"{SIN_NOVEDAD} y nada más. Los reenvíos internos de Allianz \"para su conocimiento\" sin "
    "contenido nuevo son SIN_NOVEDAD.\n"
    "7. Destinatario ASESOR: contale en una frase qué pasó en el ticket (quién respondió en "
    "Allianz y qué dijo, según `novedad_allianz`) y mencioná el número de ticket. A "
    "`autor_mensaje_allianz` presentalo como \"de Allianz\", NUNCA como \"el cliente\".\n"
    "Escribí SOLO el mensaje, sin comillas ni encabezados."
)
_USUARIO = "Destinatario: {rol}.\nContexto del ticket (JSON): {ctx}"


def _construir_cadena():
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI

    prompt = ChatPromptTemplate.from_messages([("system", _SISTEMA), ("user", _USUARIO)])
    # temperature=0: la redacción tiene que ser predecible; la creatividad acá es alucinación.
    llm = ChatOpenAI(model=config.MODELO_L2, temperature=0, max_tokens=180,
                     api_key=config.OPENAI_API_KEY)
    return prompt | llm


def redactar(rol: str, ctx: dict) -> Optional[str]:
    """Texto validado, `SIN_NOVEDAD` (cliente sin nada concreto) o None (usar plantilla)."""
    if not (config.USAR_LLM_RESUMEN and config.hay_llm()):
        return None
    try:
        import json as _json

        sin_historial = {k: v for k, v in ctx.items() if k != "historial"}
        resp = _construir_cadena().invoke(
            {"rol": rol, "ctx": _json.dumps(sin_historial, ensure_ascii=False, default=str)})
        texto = (resp.content or "").strip().strip('"').strip()
    except Exception as ex:  # noqa: BLE001
        log.warning("agente redactor falló, uso plantilla: %s", ex)
        return None
    if not texto:
        return None
    if SIN_NOVEDAD in texto.upper():
        return SIN_NOVEDAD if rol == "cliente" else None
    motivo = guardarrailes.validar_whatsapp(rol, texto, ctx)
    if motivo:
        log.warning("redactor: borrador para %s descartado (%s): %r", rol, motivo, texto[:200])
        return None
    return texto
