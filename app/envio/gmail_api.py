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


def _hilo_invalido(ex: Exception) -> bool:
    t = str(ex).lower()
    return "404" in t or "not found" in t or "invalid thread" in t or "threadid" in t


class EmisorGmail:
    modo = "gmail_api"

    def __init__(self, remitente: str, remitente_nombre: str = "Babilonia", buzon: str = "envio"):
        self.remitente, self.remitente_nombre = remitente, remitente_nombre
        self.buzon = buzon  # 'envio' (hola@) o 'lectura' (integraciones@): de qué token sale

    def enviar(self, destinatarios, asunto, cuerpo_texto, cc=None, adjuntos=None,
               hilo_id=None, in_reply_to=None) -> dict:
        destinatarios = [d for d in destinatarios if d]
        if not destinatarios:
            return {"ok": False, "modo": self.modo, "error": "sin destinatario"}
        service = construir_servicio(self.buzon)
        if service is None:
            return {"ok": False, "modo": self.modo, "error": "Gmail API sin credenciales/token"}
        msg = _armar_mensaje(self.remitente_nombre, self.remitente, destinatarios,
                             asunto, cuerpo_texto, cc, adjuntos, in_reply_to)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        cuerpo_envio = {"raw": raw}
        if hilo_id:
            cuerpo_envio["threadId"] = hilo_id  # responder DENTRO del hilo del ticket
        try:
            try:
                res = service.users().messages().send(userId="me", body=cuerpo_envio).execute()
            except Exception as ex:  # noqa: BLE001
                # El hilo es de otra casilla (tickets viejos leídos en hola@, o al revés): Gmail no lo
                # encuentra. Sale igual, encadenado por In-Reply-To/References.
                if not hilo_id or not _hilo_invalido(ex):
                    raise
                log.warning("Gmail (%s): el hilo %s no existe en esta casilla; sale sin threadId", self.buzon, hilo_id)
                cuerpo_envio.pop("threadId", None)
                hilo_id = None
                res = service.users().messages().send(userId="me", body=cuerpo_envio).execute()
            return {"ok": True, "modo": self.modo, "de": self.remitente, "message_id": res.get("id"),
                    "thread_id": res.get("threadId"), "para": destinatarios, "cc": cc or [],
                    "asunto": asunto, "en_hilo": bool(hilo_id)}
        except Exception as ex:  # noqa: BLE001
            log.warning("Gmail API send falló: %s", ex)
            return {"ok": False, "modo": self.modo, "error": str(ex),
                    "para": destinatarios, "asunto": asunto}
