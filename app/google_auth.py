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


def _fuente(buzon: str) -> tuple[str, Path]:
    """(token en env, archivo) de cada casilla: 'envio' = hola@ (GOOGLE_TOKEN), 'lectura' = integraciones@."""
    if buzon == "lectura":
        return config.GMAIL_LECTURA_TOKEN, Path(config.GMAIL_LECTURA_TOKEN_JSON)
    return config.GOOGLE_TOKEN, Path(config.GOOGLE_TOKEN_JSON)


def cargar_credenciales(buzon: str = "envio"):
    """Devuelve unas Credentials válidas (refrescando si hace falta) o None.

    Fuente del token, en orden: env var (contenido JSON, para EasyPanel/headless) → archivo local.
    `buzon='envio'` usa GOOGLE_TOKEN / GOOGLE_TOKEN_JSON (hola@); `buzon='lectura'` usa
    GMAIL_LECTURA_TOKEN / GMAIL_LECTURA_TOKEN_JSON (integraciones@). El token de InstalledAppFlow ya
    trae client_id y client_secret, así que alcanza para refrescar solo (no hace falta credentials.json).
    """
    try:
        import json

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        log.warning("google-auth no instalado; Gmail API no disponible")
        return None

    token_env, token_path = _fuente(buzon)
    desde_env = bool(token_env.strip())
    try:
        if desde_env:
            creds = Credentials.from_authorized_user_info(json.loads(token_env), SCOPES)
        elif token_path.is_file():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        else:
            return None
    except Exception as ex:  # noqa: BLE001
        log.warning("token de Gmail (%s) ilegible: %s", buzon, ex)
        return None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Persistir el token refrescado solo si vino de archivo (en env no se puede reescribir;
            # el proceso lo mantiene en memoria y vuelve a refrescar en el próximo arranque).
            if not desde_env:
                token_path.write_text(creds.to_json(), encoding="utf-8")
        except Exception as ex:  # noqa: BLE001
            log.warning("no se pudo refrescar el token de Gmail (%s): %s", buzon, ex)
            return None
    return creds if (creds and creds.valid) else None


def construir_servicio(buzon: str = "envio"):
    """Cliente de la Gmail API de esa casilla ('envio' o 'lectura'), o None si no hay credenciales/libs."""
    creds = cargar_credenciales(buzon)
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
