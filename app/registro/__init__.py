"""Registro en Notion (objetivo 3): write-back del ticket a la base `Tickets Allianz`."""
from .notion_writer import registrar_en_notion
from .seguimiento import sincronizar_seguimiento

__all__ = ["registrar_en_notion", "sincronizar_seguimiento"]
