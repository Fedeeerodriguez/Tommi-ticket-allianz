"""Motor de acciones (M3/M4/M7): decide y encola lo que Tommy HARÍA por cada ticket.

En modo sugerencia deja las acciones en la tabla `acciones` con estado 'sugerida'.
No envía nada (eso es Fase 4/5, con autorización y accesos SMTP/WATI).
"""
from .criticas import (
    autorizar_ticket,
    es_accion_critica,
    rechazar_ticket,
    texto_critico,
)
from .despacho import despachar_pendientes
from .motor import decidir_y_encolar, escanear_inactividad, escanear_vencimientos

__all__ = [
    "decidir_y_encolar",
    "escanear_inactividad",
    "escanear_vencimientos",
    "despachar_pendientes",
    "es_accion_critica",
    "texto_critico",
    "autorizar_ticket",
    "rechazar_ticket",
]
