"""Agente Orquestador (el cerebro LLM) — redacción de la respuesta a Allianz + asertividad.

El motor (determinístico) ya decide QUÉ hacer y por qué canal, con los guardarraíles de
Fase E. Este agente aporta lo que sólo un LLM hace bien: **redactar el cuerpo del correo que
va en el hilo del ticket con Allianz**, en tono profesional, y aplicar **asertividad** — si
Allianz respondió fuera de tema o con una mala práctica, el borrador **re-exige** lo que
pedimos, sin darlo por bueno.

Salida estructurada con LangChain (`with_structured_output`). Defensivo: sin API key, sin
LangChain o ante cualquier error devuelve None y el despacho cae al cuerpo de plantilla
(`_cuerpo_allianz`). Nunca rompe el pipeline por el LLM, y NUNCA envía nada por su cuenta:
sólo redacta; el envío (y el visto bueno de Ceci en críticas) sigue en manos del despacho.
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from app import config
from app.agentes import guardarrailes

log = logging.getLogger(__name__)


class PlanAllianz(BaseModel):
    """Lo que el orquestador DEBE devolver para un correo dirigido a Allianz."""

    cuerpo_allianz: str = Field(
        description="Cuerpo del correo a enviar EN EL HILO del ticket con Allianz. "
                    "Profesional, claro, en español neutro. Incluir la referencia del ticket/póliza "
                    "si están. Si Allianz respondió fuera de tema, re-exigir con firmeza y cortesía "
                    "lo solicitado. No inventar datos que no estén en el contexto.")
    fuera_de_tema: bool = Field(
        description="True si la última respuesta de Allianz NO atiende lo pedido / es una mala "
                    "práctica (respuesta evasiva, pide algo ya enviado, cambia de tema).")
    nota_asertividad: str = Field(
        description="Nota interna breve (para Babilonia/Ceci) explicando el criterio: qué faltó "
                    "y qué se re-exige. Vacío si todo en orden.")
    tramite_resuelto: bool = Field(
        description="True si el último mensaje de Allianz dice que el trámite/solicitud ya fue "
                    "atendido, resuelto, emitido o concluido. En ese caso NO se re-exige nada.")


_SISTEMA = (
    "Sos Tommy, orquestador de Babilonia (correduría de seguros que opera con Allianz). "
    "Redactás la respuesta que Babilonia enviará A ALLIANZ en el hilo de un ticket. "
    "Objetivo: hacer avanzar el trámite del cliente. Tono profesional, cordial y FIRME. "
    "Sos ASERTIVO: si Allianz respondió fuera de tema o con evasivas, no lo das por bueno: "
    "reiterás con precisión lo solicitado y pedís una acción concreta.\n\n"
    "REGLAS DURAS (no negociables; ante la duda, escribí MENOS):\n"
    "1. SOLO hechos ESCRITOS en el último mensaje de Allianz, en el `historial` o en los campos "
    "del contexto. Prohibido deducir, suponer o completar datos.\n"
    "2. JAMÁS afirmes que Babilonia o el cliente enviaron, adjuntaron, entregaron, cargaron o "
    "pagaron algo. No tenés constancia de eso. Si hace falta, PEDÍ que Allianz confirme qué "
    "recibió (\"solicitamos confirmar si cuentan con…\").\n"
    "3. NOMBRES: solo los que aparecen textualmente en el mensaje de Allianz o en el contexto, "
    "y solo del caso de ESTE ticket. Quien firma o \"escribió un mensaje\" en Allianz es un "
    "empleado de Allianz, no el cliente: no lo menciones en el cuerpo. El asegurado suele figurar "
    "después del número de póliza (ej. \"GMMI 98577 MARTHA ZARATE URIBE\"); si no está claro, "
    "no nombres a nadie y referite al ticket.\n"
    "4. No inventes requisitos, documentos, montos, fechas ni plazos que no estén escritos. "
    "Podés pedir un plazo, nunca afirmarlo.\n"
    "5. Si Allianz dice que el trámite fue ATENDIDO, resuelto, emitido o concluido: marcá "
    "`tramite_resuelto`=true, `fuera_de_tema`=false, y no re-exijas nada.\n"
    "6. No reveles datos sensibles (médicos, bancarios) más allá de lo que Allianz ya escribió.\n"
    "Escribís SOLO el cuerpo del correo (sin asunto ni firma corporativa larga)."
)
_USUARIO = (
    "Contexto del ticket (JSON; incluye `historial` = bitácora del hilo con lo que ya pasó):\n"
    "{ctx}\n\n"
    "Último mensaje recibido de Allianz (puede venir vacío):\n{mensaje_allianz}\n\n"
    "Usá el `historial` para saber qué se pidió antes y no repetir ni contradecir. "
    "Redactá el cuerpo del correo para Allianz y evaluá si su última respuesta quedó FUERA DE "
    "TEMA respecto de lo que se venía pidiendo (marcá `fuera_de_tema` en ese caso)."
)


def _construir_llm():
    from langchain_openai import ChatOpenAI

    # temperature=0: misma entrada → misma salida; nada de "creatividad" en correos a Allianz.
    llm = ChatOpenAI(model=config.MODELO_L2, temperature=0, max_tokens=400,
                     api_key=config.OPENAI_API_KEY)
    return llm.with_structured_output(PlanAllianz)


def redactar_allianz(ctx: dict, mensaje_allianz: str = "") -> Optional[dict]:
    """Redacta el cuerpo del correo a Allianz (asertivo) para el contexto dado.

    Devuelve {"cuerpo_allianz", "fuera_de_tema", "nota_asertividad", "tramite_resuelto"} o None.
    Si el cuerpo rompe una regla dura (guardarraíles), se descarta: `cuerpo_allianz`=None y
    `descartado` explica el motivo (el despacho cae al cuerpo de plantilla)."""
    if not (config.USAR_LLM_RESUMEN and config.hay_llm()):
        return None
    try:
        import json as _json

        from langchain_core.messages import HumanMessage, SystemMessage

        contenido = _USUARIO.format(ctx=_json.dumps(ctx, ensure_ascii=False),
                                    mensaje_allianz=(mensaje_allianz or "")[:3000])
        salida: PlanAllianz = _construir_llm().invoke(
            [SystemMessage(content=_SISTEMA), HumanMessage(content=contenido)]
        )
        cuerpo = (salida.cuerpo_allianz or "").strip()
        if not cuerpo:
            return None
        resuelto = bool(salida.tramite_resuelto)
        plan = {"cuerpo_allianz": cuerpo, "fuera_de_tema": bool(salida.fuera_de_tema) and not resuelto,
                "nota_asertividad": (salida.nota_asertividad or "").strip(),
                "tramite_resuelto": resuelto}
        motivo = guardarrailes.validar_cuerpo_allianz(cuerpo, ctx, mensaje_allianz or "")
        if motivo:
            log.warning("orquestador: cuerpo descartado (%s)", motivo)
            plan["cuerpo_allianz"] = None
            plan["descartado"] = motivo
        return plan
    except Exception as ex:  # noqa: BLE001
        log.warning("orquestador (%s) falló, uso cuerpo de plantilla: %s", config.MODELO_L2, ex)
        return None
