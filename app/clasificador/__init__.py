"""Clasificación de correos: L1 (reglas baratas) + L2 (Claude Haiku para lo ambiguo)."""
from app import config
from app.models import Clasificacion, Correo

from .llm import clasificar_l2
from .reglas import clasificar_l1


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