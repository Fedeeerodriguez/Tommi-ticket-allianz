"""Credenciales OAuth compartidas para la Gmail API (lectura + envío) — Plan B (Workspace).

Carga el token desde `GOOGLE_TOKEN_JSON` (lo genera `python -m app.google_oauth_setup`), lo
refresca si venció, y arma el cliente de la Gmail API. Todos los imports de google-* son
perezosos: si las libs no están o no hay token, devuelve None y el sistema cae a IMAP/SMTP o
al modo laboratorio (nunca rompe).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from app import config

log = logging.getLogger(__name__)

# Mínimos necesarios: leer + marcar leído (modify) y enviar (send).
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


def cargar_credenciales():
    """Devuelve unas Credentials válidas (refrescando si hace falta) o None."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        log.warning("google-auth no instalado; Gmail API no disponible")
        return None

    token_path = Path(config.GOOGLE_TOKEN_JSON)
    if not token_path.is_file():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    except Exception as ex:  # noqa: BLE001
        log.warning("token de Gmail ilegible: %s", ex)
        return None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
        except Exception as ex:  # noqa: BLE001
            log.warning("no se pudo refrescar el token de Gmail: %s", ex)
            return None
    return creds if (creds and creds.valid) else None


def construir_servicio():
    """Cliente de la Gmail API listo para usar, o None si no hay credenciales/libs."""
    creds = cargar_credenciales()
    if creds is None:
        return None
    try:
        from googleapiclient.discovery import build

        return build("gmail", "v1", credentials=creds, cache_discovery=False)
    except ImportError:
        log.warning("google-api-python-client no instalado; Gmail API no disponible")
        return None
    except Exception as ex:  # noqa: BLE001
        log.warning("no se pudo construir el servicio de Gmail: %s", ex)
        return None
