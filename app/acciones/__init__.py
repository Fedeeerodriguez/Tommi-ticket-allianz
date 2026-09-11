"""Motor de acciones (M3/M4/M7): decide y encola lo que Tommy HARÍA por cada ticket.

En modo sugerencia deja las acciones en la tabla `acciones` con estado 'sugerida'.
No envía nada (eso es Fase 4/5, con autorización y accesos SMTP/WATI).
"""
from .despacho import despachar_pendientes
from .motor import decidir_y_encolar, escanear_inactividad

__all__ = ["decidir_y_encolar", "escanear_inactividad", "despachar_pendientes"]
