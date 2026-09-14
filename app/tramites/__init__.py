"""Catálogo de trámites Allianz + ruteo de atención (self-service vs gestión por mail)."""
from .catalogo import (
    CATALOGO, PORTAL_URL, Ruta, Tramite,
    identificar_tramite, instrucciones_cliente, por_clave,
)

__all__ = [
    "CATALOGO", "PORTAL_URL", "Ruta", "Tramite",
    "identificar_tramite", "instrucciones_cliente", "por_clave",
]
