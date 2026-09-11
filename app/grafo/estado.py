"""Estado del grafo de procesamiento de un correo (LangGraph).

Un correo entrante recorre el grafo y va llenando este estado. Cada nodo devuelve un dict
parcial que LangGraph fusiona. `ruta` usa un reducer (operator.add) para acumular la traza
de nodos recorridos (útil para debug/observabilidad).
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict

from app.models import Clasificacion, Correo


class EstadoCorreo(TypedDict, total=False):
    # Entrada
    correo: Correo
    despachar: bool                 # si True, el grafo también ejecuta el envío al final

    # Clasificación
    clasificacion: Optional[Clasificacion]

    # Extracción + enriquecimiento
    entidades: dict[str, Any]
    notion: dict[str, Any]
    delicado: bool

    # Persistencia / ticket
    correo_id: Optional[int]
    es_nuevo: bool
    ticket_id: Optional[int]
    ticket: dict[str, Any]          # ticket_repr (datos resueltos)

    # Salidas
    registro_notion: dict[str, Any]
    acciones: list[dict[str, Any]]
    despacho: dict[str, Any]

    # Observabilidad
    ruta: Annotated[list[str], operator.add]
    fin: Optional[str]              # motivo de terminación temprana (duplicado / no_ticket)
