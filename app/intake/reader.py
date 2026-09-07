"""Lector de buzón, enchufable.

`LectorBuzon` es la interfaz. Hoy implementamos `LectorEmlLocal` (lee archivos .eml de una
carpeta) para poder correr el dry-run sin credenciales. Cuando llegue el acceso a
hola@babilonia.ai se agrega `LectorGmail` implementando la misma interfaz, sin tocar el resto.
"""
from __future__ import annotations

import email
import email.policy
import hashlib
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Iterator, Protocol

from app.models import Correo


class LectorBuzon(Protocol):
    """Contrato de cualquier fuente de correos."""

    def leer(self) -> Iterator[Correo]:
        ...


def _dominio(direccion: str) -> str:
    return direccion.split("@")[-1].strip().lower() if "@" in direccion else ""


def _direcciones(valor: str | None) -> list[str]:
    if not valor:
        return []
    return [addr.strip().lower() for _, addr in getaddresses([valor]) if addr]


def _cuerpo_texto(msg: EmailMessage) -> str:
    """Extrae el texto plano del correo (cae a HTML crudo si no hay parte de texto)."""
    if msg.is_multipart():
        # Preferimos text/plain; si no hay, tomamos el primer text/html.
        html = None
        for parte in msg.walk():
            ctype = parte.get_content_type()
            disp = str(parte.get("Content-Disposition") or "")
            if "attachment" in disp:
                continue
            if ctype == "text/plain":
                try:
                    return parte.get_content().strip()
                except Exception:  # noqa: BLE001
                    continue
            if ctype == "text/html" and html is None:
                try:
                    html = parte.get_content()
                except Exception:  # noqa: BLE001
                    html = None
        return (html or "").strip()
    try:
        return (msg.get_content() or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _adjuntos(msg: EmailMessage) -> list[str]:
    nombres: list[str] = []
    if msg.is_multipart():
        for parte in msg.walk():
            disp = str(parte.get("Content-Disposition") or "")
            if "attachment" in disp:
                nombres.append(parte.get_filename() or "(sin nombre)")
    return nombres


def normalizar_desde_bytes(datos: bytes, origen: str | None = None) -> Correo:
    """Parsea un correo crudo (.eml / RFC822) a un `Correo` normalizado."""
    msg: EmailMessage = email.message_from_bytes(datos, policy=email.policy.default)  # type: ignore[assignment]

    remitentes = _direcciones(msg.get("From"))
    remitente = remitentes[0] if remitentes else ""

    fecha = None
    if msg.get("Date"):
        try:
            fecha = parsedate_to_datetime(msg.get("Date"))
        except Exception:  # noqa: BLE001
            fecha = None

    # message_id: usamos el header si existe; si no, un hash estable del contenido.
    message_id = (msg.get("Message-ID") or "").strip()
    if not message_id:
        message_id = "sha256:" + hashlib.sha256(datos).hexdigest()[:24]

    return Correo(
        message_id=message_id,
        remitente=remitente,
        remitente_dominio=_dominio(remitente),
        para=_direcciones(msg.get("To")),
        cc=_direcciones(msg.get("Cc")),
        asunto=(msg.get("Subject") or "").strip(),
        cuerpo_texto=_cuerpo_texto(msg),
        fecha=fecha,
        headers={k.lower(): v for k, v in msg.items()},
        adjuntos=_adjuntos(msg),
        origen=origen,
    )


class LectorEmlLocal:
    """Lee todos los .eml de una carpeta. Para dry-run con muestras reales o sintéticas."""

    def __init__(self, carpeta: Path):
        self.carpeta = Path(carpeta)

    def leer(self) -> Iterator[Correo]:
        if not self.carpeta.exists():
            return
        for ruta in sorted(self.carpeta.glob("*.eml")):
            yield normalizar_desde_bytes(ruta.read_bytes(), origen=str(ruta.name))


class LectorIMAP:
    """Lee correos por IMAP (proveedor-agnóstico: Gmail/Workspace, Outlook, etc.).

    Cumple la MISMA interfaz que `LectorEmlLocal`, así el resto del sistema no cambia.
    Por defecto trae los NO leídos (`UNSEEN`); no los marca como leídos salvo que se pida
    (para no perder correos si algo falla — la idempotencia real la da `message_id` en DB).
    """

    def __init__(
        self,
        host: str,
        usuario: str,
        password: str,
        carpeta: str = "INBOX",
        puerto: int = 993,
        criterio: str = "UNSEEN",
        marcar_leidos: bool = False,
        limite: int = 200,
    ):
        self.host = host
        self.usuario = usuario
        self.password = password
        self.carpeta = carpeta
        self.puerto = puerto
        self.criterio = criterio
        self.marcar_leidos = marcar_leidos
        self.limite = limite

    def leer(self) -> Iterator[Correo]:
        import imaplib

        conn = imaplib.IMAP4_SSL(self.host, self.puerto)
        try:
            conn.login(self.usuario, self.password)
            conn.select(self.carpeta)
            typ, datos = conn.search(None, self.criterio)
            if typ != "OK":
                return
            ids = datos[0].split()[: self.limite]
            for num in ids:
                typ, msg_datos = conn.fetch(num, "(RFC822)")
                if typ != "OK" or not msg_datos or not msg_datos[0]:
                    continue
                crudo = msg_datos[0][1]
                if isinstance(crudo, bytes):
                    yield normalizar_desde_bytes(crudo, origen=f"imap:{num.decode()}")
                    if self.marcar_leidos:
                        conn.store(num, "+FLAGS", "\\Seen")
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
