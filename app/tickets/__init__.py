"""Motor de tickets: crea/actualiza tickets y su bitácora a partir de correos clasificados."""
from .engine import es_delicado, procesar_correo

__all__ = ["procesar_correo", "es_delicado"]
