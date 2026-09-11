"""Agente LangChain de clasificación L2 (salida estructurada).

Reemplaza la llamada cruda a OpenAI por un `ChatOpenAI` de LangChain con
`with_structured_output(...)`, que fuerza el esquema de salida (Pydantic) y evita el
parseo manual de JSON. Solo se usa para los correos que L1 marcó ambiguos.

Defensivo: si falta la API key, LangChain no está instalado o el modelo falla, devuelve
None y el pipeline se queda con lo de L1 (nunca rompe por el LLM).
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app import config
from app.models import Clasificacion, Correo, TipoCorreo

log = logging.getLogger(__name__)


class SalidaClasificacion(BaseModel):
    """Esquema que el modelo DEBE devolver (validado por LangChain)."""

    tipo: Literal[
        "A_respuesta_ticket", "B_acuse_ticket", "C_allianz_pide", "D_reenvio_asesor",
        "E_cc_cliente", "F_consulta_producto", "G_sistema", "H_publicidad", "I_no_clasificable",
    ] = Field(description="Tipo de correo según la taxonomía de Babilonia/Allianz.")
    confianza: float = Field(ge=0, le=1, description="Confianza 0-1 en la clasificación.")
    motivo: str = Field(description="Justificación breve de la decisión.")


_SYSTEM = (
    "Sos un clasificador de correos de una correduría de seguros (Babilonia) que opera con "
    "Allianz. Clasificá el correo en UNO de los tipos de la taxonomía.\n"
    "Significado: A_respuesta_ticket=Allianz responde un ticket existente; "
    "B_acuse_ticket=Allianz acusa/crea un ticket nuevo; C_allianz_pide=Allianz pide algo al "
    "cliente; D_reenvio_asesor=un asesor reenvía pidiendo abrir un trámite; "
    "E_cc_cliente=un cliente escribió a Allianz y copió a Babilonia; "
    "F_consulta_producto=un asesor pregunta sobre producto/proceso; "
    "G_sistema=2FA/códigos/notificaciones automáticas; H_publicidad=newsletter/spam; "
    "I_no_clasificable=no se puede determinar."
)


def _construir_llm():
    """Crea el ChatOpenAI con salida estructurada. Import perezoso para no exigir langchain
    en entornos que solo usan L1."""
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model=config.MODELO_L2, temperature=0, api_key=config.OPENAI_API_KEY)
    return llm.with_structured_output(SalidaClasificacion)


def clasificar_l2(correo: Correo) -> Optional[Clasificacion]:
    if not config.hay_llm():
        return None
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        contenido = (
            f"De: {correo.remitente}\nPara: {', '.join(correo.para)}\n"
            f"CC: {', '.join(correo.cc)}\nAsunto: {correo.asunto}\n\n{correo.cuerpo_texto[:4000]}"
        )
        salida: SalidaClasificacion = _construir_llm().invoke(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=contenido)]
        )
        return Clasificacion(
            tipo=TipoCorreo(salida.tipo),
            confianza=float(salida.confianza),
            motivo=f"L2/{config.MODELO_L2} (langchain): {salida.motivo}",
            necesita_llm=False,
        )
    except Exception as ex:  # noqa: BLE001
        log.warning("agente L2 (%s) falló, se mantiene L1: %s", config.MODELO_L2, ex)
        return None
