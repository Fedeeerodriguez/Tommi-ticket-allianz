"""Intake: leer el buzón y normalizar cada correo a un objeto `Correo`.

`lector_desde_config()` elige la fuente según la config, sin que el resto del sistema
(grafo, scheduler, runners) tenga que saber cuál:
  Gmail API de integraciones@ (si hay token) → Gmail API de hola@ → IMAP (si hay credenciales) → carpeta local de muestras (dev).
"""
from .reader import LectorBuzon, LectorEmlLocal, LectorIMAP, normalizar_desde_bytes

__all__ = ["LectorBuzon", "LectorEmlLocal", "LectorIMAP", "normalizar_desde_bytes",
           "lector_desde_config"]


def lector_desde_config(carpeta=None, repo=None):
    """Devuelve (lector, descripcion_fuente). `carpeta` fuerza el lector local de .eml. Con `repo`, el
    lector Gmail saltea los correos que ya están en la base (no depende de leídos/no leídos)."""
    from app import config

    if carpeta is not None:
        return LectorEmlLocal(carpeta), f"local {carpeta}"
    if config.hay_gmail_lectura() or config.hay_gmail_api():
        from .gmail_api import LectorGmail

        # Con token de integraciones@ se lee SOLO esa casilla (todo lo de Allianz que llega a hola@ también
        # llega ahí); sin él, como antes, hola@.
        buzon = "lectura" if config.hay_gmail_lectura() else "envio"
        nombre = config.GMAIL_LECTURA_BUZON if buzon == "lectura" else config.BUZON
        query = config.GMAIL_QUERY
        if buzon == "lectura" and config.GMAIL_LECTURA_EXCLUIR.strip():
            query = f"{query} {config.GMAIL_LECTURA_EXCLUIR.strip()}"
        return LectorGmail(query=query, carpeta=config.GMAIL_CARPETA,
                           marcar_leidos=config.GMAIL_MARCAR_LEIDOS,
                           limite=config.GMAIL_MAX_POR_CICLO,
                           pausa_ms=config.GMAIL_PAUSA_MS,
                           ya_procesados=repo.origenes_conocidos if repo is not None else None,
                           buzon=buzon, max_paginas=config.GMAIL_MAX_PAGINAS), f"Gmail API {nombre}"
    if config.hay_imap():
        return (LectorIMAP(config.IMAP_HOST, config.IMAP_USER, config.IMAP_PASSWORD,
                           config.IMAP_CARPETA, config.IMAP_PORT),
                f"IMAP {config.IMAP_HOST}")
    return LectorEmlLocal(config.MUESTRAS_DIR), f"local {config.MUESTRAS_DIR}"
