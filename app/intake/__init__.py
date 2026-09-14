"""Intake: leer el buzón y normalizar cada correo a un objeto `Correo`.

`lector_desde_config()` elige la fuente según la config, sin que el resto del sistema
(grafo, scheduler, runners) tenga que saber cuál:
  Gmail API (si está autorizada) → IMAP (si hay credenciales) → carpeta local de muestras (dev).
"""
from .reader import LectorBuzon, LectorEmlLocal, LectorIMAP, normalizar_desde_bytes

__all__ = ["LectorBuzon", "LectorEmlLocal", "LectorIMAP", "normalizar_desde_bytes",
           "lector_desde_config"]


def lector_desde_config(carpeta=None):
    """Devuelve (lector, descripcion_fuente). `carpeta` fuerza el lector local de .eml."""
    from app import config

    if carpeta is not None:
        return LectorEmlLocal(carpeta), f"local {carpeta}"
    if config.hay_gmail_api():
        from .gmail_api import LectorGmail

        return LectorGmail(query=config.GMAIL_QUERY, carpeta=config.IMAP_CARPETA), "Gmail API"
    if config.hay_imap():
        return (LectorIMAP(config.IMAP_HOST, config.IMAP_USER, config.IMAP_PASSWORD,
                           config.IMAP_CARPETA, config.IMAP_PORT),
                f"IMAP {config.IMAP_HOST}")
    return LectorEmlLocal(config.MUESTRAS_DIR), f"local {config.MUESTRAS_DIR}"
