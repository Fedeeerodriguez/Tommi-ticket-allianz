"""Lector de buzón por Gmail API (OAuth) — alternativa a IMAP para Google Workspace.

Cumple la MISMA interfaz que `LectorEmlLocal`/`LectorIMAP` (`.leer()`), así el resto del
sistema (grafo, scheduler) no cambia. Trae los correos que matchean `query` (por defecto los
no leídos del INBOX) y los normaliza con `normalizar_desde_bytes` (mismo parseo que IMAP/EML).
Por seguridad NO marca leídos salvo que se pida; la idempotencia real la da `message_id` en DB.
"""
from __future__ import annotations

import base64
import logging
from typing import Iterator

from app.google_auth import construir_servicio
from app.models import Correo

from .reader import normalizar_desde_bytes

log = logging.getLogger(__name__)


class LectorGmail:
    def __init__(self, query: str = "is:unread", carpeta: str = "INBOX",
                 marcar_leidos: bool = False, limite: int = 200):
        self.query = query
        self.carpeta = carpeta
        self.marcar_leidos = marcar_leidos
        self.limite = limite

    def leer(self) -> Iterator[Correo]:
        service = construir_servicio()
        if service is None:
            log.warning("Gmail API sin credenciales/token; no se leyó nada")
            return
        labels = [self.carpeta] if self.carpeta else None
        try:
            resp = service.users().messages().list(
                userId="me", q=self.query, labelIds=labels,
                maxResults=min(self.limite, 500)).execute()
        except Exception as ex:  # noqa: BLE001
            log.warning("Gmail API list falló: %s", ex)
            return
        for meta in resp.get("messages", []):
            try:
                msg = service.users().messages().get(
                    userId="me", id=meta["id"], format="raw").execute()
                crudo = base64.urlsafe_b64decode(msg["raw"].encode("utf-8"))
            except Exception as ex:  # noqa: BLE001
                log.warning("Gmail API get %s falló: %s", meta.get("id"), ex)
                continue
            correo = normalizar_desde_bytes(crudo, origen=f"gmail:{meta['id']}")
            correo.hilo_id = meta.get("threadId")  # para responder en el mismo hilo (Fase B)
            yield correo
            if self.marcar_leidos:
                try:
                    service.users().messages().modify(
                        userId="me", id=meta["id"], body={"removeLabelIds": ["UNREAD"]}).execute()
                except Exception as ex:  # noqa: BLE001
                    log.warning("no se pudo marcar leído %s: %s", meta.get("id"), ex)
