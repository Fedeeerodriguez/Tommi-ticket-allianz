"""Clasificación de correos: L1 (reglas baratas) + L2 (agente LangChain para lo ambiguo).

L2 es el agente LangChain (`app.agentes.clasificar_l2`, salida estructurada). Si no está
disponible, cae al clasificador L2 crudo de `llm.py` (OpenAI directo) como último recurso.
"""
from app import config
from app.models import Clasificacion, Correo

from .llm import clasificar_l2 as _clasificar_l2_crudo
from .reglas import clasificar_l1


def clasificar_l2(correo: Correo):
    """L2 vía agente LangChain; si devuelve None, intenta el camino crudo (OpenAI directo)."""
    from app.agentes import clasificar_l2 as _agente_l2

    return _agente_l2(correo) or _clasificar_l2_crudo(correo)


def clasificar(correo: Correo) -> Clasificacion:
    """Corre L1; si la confianza cae bajo el umbral y hay LLM disponible, intenta L2."""
    clf = clasificar_l1(correo)
    if clf.confianza < config.UMBRAL_LLM:
        clf.necesita_llm = True
        mejor = clasificar_l2(correo)
        if mejor is not None:
            return mejor
    return clf


__all__ = ["clasificar", "clasificar_l1", "clasificar_l2"]