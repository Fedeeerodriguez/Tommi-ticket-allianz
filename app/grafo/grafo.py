"""Construcción del grafo LangGraph que procesa un correo de punta a punta.

Flujo (con ramas condicionales):

    START
      → clasificar_l1
          ├─ (confianza baja) → clasificar_l2 (agente LangChain) → extraer
          └─ (confianza ok) ─────────────────────────────────────→ extraer
      → extraer → persistir
          ├─ (duplicado / no es ticket) → END
          └─ (ticket nuevo) → enriquecer → upsert_ticket → registrar_notion
                              → decidir → despachar → END

`repo` y `emisor` se inyectan al construir (partial), así los nodos quedan puros y el grafo
es reutilizable. Devuelve un grafo COMPILADO listo para `.invoke(estado_inicial)`.
"""
from __future__ import annotations

from functools import partial
from typing import Optional

from langgraph.graph import END, START, StateGraph

from app.db import Repositorio
from app.envio import Emisor

from . import nodos
from .estado import EstadoCorreo


def _tras_l1(estado: EstadoCorreo) -> str:
    clf = estado.get("clasificacion")
    return "clasificar_l2" if (clf and clf.necesita_llm) else "extraer"


def _tras_persistir(estado: EstadoCorreo) -> str:
    return END if estado.get("fin") else "enriquecer"


def construir_grafo(repo: Repositorio, emisor: Optional[Emisor] = None):
    g = StateGraph(EstadoCorreo)

    g.add_node("clasificar_l1", partial(nodos.n_clasificar_l1, repo=repo))
    g.add_node("clasificar_l2", partial(nodos.n_clasificar_l2, repo=repo))
    g.add_node("extraer", partial(nodos.n_extraer, repo=repo))
    g.add_node("persistir", partial(nodos.n_persistir, repo=repo))
    g.add_node("enriquecer", partial(nodos.n_enriquecer, repo=repo))
    g.add_node("upsert_ticket", partial(nodos.n_upsert_ticket, repo=repo))
    g.add_node("registrar_notion", partial(nodos.n_registrar_notion, repo=repo))
    g.add_node("decidir", partial(nodos.n_decidir, repo=repo))
    g.add_node("despachar", partial(nodos.n_despachar, repo=repo, emisor=emisor))

    g.add_edge(START, "clasificar_l1")
    g.add_conditional_edges("clasificar_l1", _tras_l1, {"clasificar_l2": "clasificar_l2", "extraer": "extraer"})
    g.add_edge("clasificar_l2", "extraer")
    g.add_edge("extraer", "persistir")
    g.add_conditional_edges("persistir", _tras_persistir, {"enriquecer": "enriquecer", END: END})
    g.add_edge("enriquecer", "upsert_ticket")
    g.add_edge("upsert_ticket", "registrar_notion")
    g.add_edge("registrar_notion", "decidir")
    g.add_edge("decidir", "despachar")
    g.add_edge("despachar", END)

    return g.compile()
