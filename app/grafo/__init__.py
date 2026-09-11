"""Orquestación con LangGraph: el grafo que procesa cada correo de punta a punta.

Nodos determinísticos (reglas, extracción, repo, Notion, SMTP) + agentes LangChain
(clasificación L2, redactor). Reemplaza al pipeline lineal hand-rolled de `run_pipeline`.
"""
from .estado import EstadoCorreo
from .grafo import construir_grafo

__all__ = ["EstadoCorreo", "construir_grafo"]
