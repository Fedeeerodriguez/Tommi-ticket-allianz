"""Emisor de correo por SMTP (Fase 4).

Envía correos reales SOLO cuando hay credenciales SMTP y `DRY_RUN=false`. En cualquier
otro caso se comporta como un emisor de laboratorio: no toca la red y devuelve el correo
que HABRÍA mandado (para inspección/tests). La interfaz es la misma en ambos casos, así el
despachador no necesita saber en qué modo corre.

Puerto 465 → SSL directo; 587 (u otros) → STARTTLS.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import Optional, Protocol

from app import config

log = logging.getLogger(__name__)


def _armar_mensaje(remitente_nombre: str, remitente: str, destinatarios: list[str],
                   asunto: str, cuerpo_texto: str, cc: Optional[list[str]] = None,
                   adjuntos: Optional[list[str]] = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((remitente_nombre, remitente))
    msg["To"] = ", ".join(destinatarios)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = asunto
    msg["Message-ID"] = make_msgid(domain=remitente.split("@")[-1] if "@" in remitente else None)
    msg.set_content(cuerpo_texto)
    for ruta in adjuntos or []:
        p = Path(ruta)
        if not p.is_file():
            log.warning("adjunto no encontrado, se omite: %s", ruta)
            continue
        datos = p.read_bytes()
        msg.add_attachment(datos, maintype="application", subtype="octet-stream", filename=p.name)
    return msg


class Emisor(Protocol):
    modo: str
    def enviar(self, destinatarios: list[str], asunto: str, cuerpo_texto: str,
               cc: Optional[list[str]] = None, adjuntos: Optional[list[str]] = None) -> dict: ...


class EmisorSMTP:
    """Envío real por SMTP."""

    modo = "smtp"

    def __init__(self, host: str, port: int, user: str, password: str,
                 remitente: str, remitente_nombre: str = "Babilonia"):
        self.host, self.port = host, port
        self.user, self.password = user, password
        self.remitente, self.remitente_nombre = remitente, remitente_nombre

    def enviar(self, destinatarios, asunto, cuerpo_texto, cc=None, adjuntos=None) -> dict:
        destinatarios = [d for d in destinatarios if d]
        if not destinatarios:
            return {"ok": False, "modo": self.modo, "error": "sin destinatario"}
        msg = _armar_mensaje(self.remitente_nombre, self.remitente, destinatarios,
                             asunto, cuerpo_texto, cc, adjuntos)
        todos = destinatarios + (cc or [])
        try:
            if self.port == 465:
                with smtplib.SMTP_SSL(self.host, self.port, context=ssl.create_default_context(), timeout=30) as s:
                    s.login(self.user, self.password)
                    s.send_message(msg, from_addr=self.remitente, to_addrs=todos)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=30) as s:
                    s.starttls(context=ssl.create_default_context())
                    s.login(self.user, self.password)
                    s.send_message(msg, from_addr=self.remitente, to_addrs=todos)
            return {"ok": True, "modo": self.modo, "message_id": msg["Message-ID"],
                    "para": destinatarios, "cc": cc or [], "asunto": asunto}
        except Exception as ex:  # noqa: BLE001
            log.warning("SMTP falló: %s", ex)
            return {"ok": False, "modo": self.modo, "error": str(ex),
                    "para": destinatarios, "asunto": asunto}


class EmisorLaboratorio:
    """No toca la red: devuelve el correo que HABRÍA enviado. Para DRY_RUN / dev / tests."""

    modo = "dry_run"

    def __init__(self, remitente: str = "hola@babilonia.ai", remitente_nombre: str = "Babilonia"):
        self.remitente, self.remitente_nombre = remitente, remitente_nombre

    def enviar(self, destinatarios, asunto, cuerpo_texto, cc=None, adjuntos=None) -> dict:
        destinatarios = [d for d in destinatarios if d]
        return {"ok": True, "modo": self.modo, "simulado": True,
                "de": self.remitente, "para": destinatarios, "cc": cc or [],
                "asunto": asunto, "cuerpo": cuerpo_texto, "adjuntos": adjuntos or []}


def emisor_desde_config() -> Emisor:
    """SMTP real solo con credenciales y DRY_RUN=false; si no, emisor de laboratorio."""
    if config.hay_smtp() and not config.DRY_RUN:
        return EmisorSMTP(config.SMTP_HOST, config.SMTP_PORT, config.SMTP_USER,
                          config.SMTP_PASSWORD, config.SMTP_REMITENTE, config.SMTP_NOMBRE)
    return EmisorLaboratorio(config.SMTP_REMITENTE, config.SMTP_NOMBRE)
