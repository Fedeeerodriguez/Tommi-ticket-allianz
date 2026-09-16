"""Tool de WATI (WhatsApp) — Fase D.

Envía plantillas por WhatsApp: a asesores (avances), al cliente (solo cuando se le pide algo) y a
Ceci (intervención/visto bueno). Real por HTTP solo con credenciales y DRY_RUN=false; en cualquier
otro caso, laboratorio (no toca la red, devuelve lo que HABRÍA enviado). Misma interfaz en ambos.
"""
from .cliente import EnvioWati, WatiHTTP, WatiLaboratorio, wati_desde_config

__all__ = ["EnvioWati", "WatiHTTP", "WatiLaboratorio", "wati_desde_config"]
