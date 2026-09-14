"""Emisor por Gmail API (OAuth) — alternativa a SMTP para Google Workspace.

Cumple la interfaz `Emisor` (mismo `.enviar()` y mismo dict de retorno que EmisorSMTP), así
el despachador no distingue el modo. Reutiliza `_armar_mensaje` (mismo MIME que SMTP) y lo
manda con `users.messages.send`. Solo se usa con `DRY_RUN=false` (lo decide el factory).
"""
from __future__ import annotations

import base64
import logging

from app.google_auth import construir_servicio

from .smtp import _armar_mensaje

log = logging.getLogger(__name__)


class EmisorGmail:
    modo = "gmail_api"

    def __init__(self, remitente: str, remitente_nombre: str = "Babilonia"):
        self.remitente, self.remitente_nombre = remitente, remitente_nombre

    def enviar(self, destinatarios, asunto, cuerpo_texto, cc=None, adjuntos=None) -> dict:
        destinatarios = [d for d in destinatarios if d]
        if not destinatarios:
            return {"ok": False, "modo": self.modo, "error": "sin destinatario"}
        service = construir_servicio()
        if service is None:
            return {"ok": False, "modo": self.modo, "error": "Gmail API sin credenciales/token"}
        msg = _armar_mensaje(self.remitente_nombre, self.remitente, destinatarios,
                             asunto, cuerpo_texto, cc, adjuntos)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        try:
            res = service.users().messages().send(userId="me", body={"raw": raw}).execute()
            return {"ok": True, "modo": self.modo, "message_id": res.get("id"),
                    "para": destinatarios, "cc": cc or [], "asunto": asunto}
        except Exception as ex:  # noqa: BLE001
            log.warning("Gmail API send falló: %s", ex)
            return {"ok": False, "modo": self.modo, "error": str(ex),
                    "para": destinatarios, "asunto": asunto}
