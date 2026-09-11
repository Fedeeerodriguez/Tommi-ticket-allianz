"""Agentes LangChain: los nodos del grafo que razonan con LLM.

- `clasificar_l2`: clasificación estructurada (with_structured_output) para correos ambiguos.
- `redactar`: redacción coloquial de mensajes de WhatsApp (cliente/asesor).

Ambos son defensivos: si no hay API key o LangChain no está, devuelven None y el sistema
sigue con reglas/plantillas (nunca rompe el pipeline por el LLM).
"""
from .clasificador_l2 import clasificar_l2
from .redactor import redactar

__all__ = ["clasificar_l2", "redactar"]
