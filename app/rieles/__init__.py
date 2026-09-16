"""Rieles de Notion (Fase F): autodescubrimiento de bases + mapeo automático de campos."""
from .notion import (
    descubrir_db,
    diagnostico,
    esquema,
    mapear_campos,
    resolver_emision,
    valor,
)

__all__ = [
    "descubrir_db",
    "esquema",
    "mapear_campos",
    "resolver_emision",
    "valor",
    "diagnostico",
]
