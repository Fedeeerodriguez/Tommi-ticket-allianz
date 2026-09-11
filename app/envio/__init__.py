"""Envío de correo (SMTP) — Fase 4. Real solo con credenciales y DRY_RUN=false."""
from .smtp import Emisor, EmisorLaboratorio, EmisorSMTP, emisor_desde_config

__all__ = ["Emisor", "EmisorSMTP", "EmisorLaboratorio", "emisor_desde_config"]
