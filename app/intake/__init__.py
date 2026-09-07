"""Intake: leer el buzón y normalizar cada correo a un objeto `Correo`."""
from .reader import LectorBuzon, LectorEmlLocal, LectorIMAP, normalizar_desde_bytes

__all__ = ["LectorBuzon", "LectorEmlLocal", "LectorIMAP", "normalizar_desde_bytes"]
