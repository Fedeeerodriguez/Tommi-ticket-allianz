"""Catálogo de trámites Allianz + ruteo de atención.

Fuente: la lista de Ceci del 17/11/2026 ("Trámites/Endosos"). Cada trámite se resuelve de una de tres formas:
  - CLIENTE_PORTAL: el cliente lo hace solo en su portal → le damos las instrucciones paso a paso y se le
    avisa a Ceci.
  - CLIENTE_MAIL: el cliente lo pide por correo, desde el correo registrado en su póliza, al correo de clientes
    de Allianz de su producto con copia a integraciones@ → Tommy arma las instrucciones, Ceci las autoriza
    (Telegram) y le salen al cliente por WhatsApp. La cancelación es aparte: es delicada (Ceci + asesor).
  - NOSOTROS_MAIL: lo gestionamos nosotros por correo a Allianz, solo con la solicitud firmada del cliente.

`identificar_tramite()` detecta el trámite mencionado en un correo (asunto+cuerpo) por palabras clave;
`instrucciones_cliente()` arma el texto para el cliente (portal o correo). Los textos al cliente van en tuteo
mexicano.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union

from app.models import Correo

PORTAL_URL = "https://clientes.allianz.com.mx/portal-clientes-web/home"


class Ruta(str, Enum):
    CLIENTE_PORTAL = "cliente_portal"   # el cliente lo hace solo en el portal → instrucciones
    CLIENTE_MAIL = "cliente_mail"       # el cliente lo pide por correo → instrucciones aprobadas por Ceci
    NOSOTROS_MAIL = "nosotros_mail"     # lo gestionamos nosotros por correo (con la solicitud firmada)


@dataclass(frozen=True)
class Tramite:
    clave: str
    nombre: str                        # cómo se llama (lo que va en el asunto)
    ruta: Ruta
    aliases: tuple[str, ...]           # palabras clave para detectarlo (en minúsculas)
    pasos: tuple[str, ...] = ()        # instrucciones específicas (portal); vacío = flujo genérico
    nota: str = ""                     # aclaraciones/condiciones adicionales
    requisitos: tuple[str, ...] = ()   # lo que tiene que ir adjunto (nosotros) o en el correo (cliente)
    delicado: bool = False             # cancelación: Ceci + asesor, sin instrucciones al cliente


CANCELACION = "cancelacion_poliza"

# --- Los que hacemos nosotros por correo, con la solicitud firmada (Ceci, 17/11) ---
_NOSOTROS = [
    Tramite("cambio_conducto_cobro", "Cambio de conducto de cobro", Ruta.NOSOTROS_MAIL,
            ("conducto de cobro", "cambio de conducto", "método de cobro", "metodo de cobro", "medio de cobro",
             "forma de cobro", "cuenta de cobro", "cambio de tarjeta", "cambiar la tarjeta", "domiciliaci"),
            requisitos=("el formato de cambio de conducto de cobro", "la INE vigente del cliente")),  # Ceci, 29/10
    Tramite("aumento_disminucion_aportaciones", "Aumento o disminución de aportaciones", Ruta.NOSOTROS_MAIL,
            ("aumento de aportaci", "aumentar aportaci", "aumentar mi aportaci", "aumentar la aportaci",
             "disminución de aportaci", "disminucion de aportaci", "disminuir aportaci", "disminuir mi aportaci",
             "bajar mi aportaci", "subir mi aportaci", "cambiar el monto de mi aportaci"),
            requisitos=("la solicitud de aumento o disminución firmada por el cliente",)),
]

# --- Los que pide el cliente por correo (Ceci, 17/11) ---
_CLIENTE_MAIL = [
    Tramite(CANCELACION, "Cancelación de póliza", Ruta.CLIENTE_MAIL,
            ("cancelación de póliza", "cancelacion de poliza", "cancelar mi póliza", "cancelar mi poliza",
             "cancelar la póliza", "cancelar la poliza", "cancelar mi plan", "cancelar el plan"), delicado=True),
    Tramite("suspension_aportaciones", "Suspensión de aportaciones", Ruta.CLIENTE_MAIL,
            ("suspensión de aportaci", "suspension de aportaci", "suspender aportaci", "suspender mis aportaci",
             "suspender los cobros", "suspender el cobro")),
    Tramite("suspension_inflacion", "Suspensión de inflación", Ruta.CLIENTE_MAIL,
            ("suspensión de inflación", "suspension de inflacion", "suspender la inflación", "suspender la inflacion",
             "quitar la inflación", "quitar la inflacion", "inflación", "inflacion")),
    Tramite("periodo_descanso", "Período de descanso", Ruta.CLIENTE_MAIL,
            ("período de descanso", "periodo de descanso", "año de descanso", "ano de descanso",
             "año sabático", "ano sabatico", "pausar los cobros", "pausar cobros", "pausar aportaci"),
            nota=("Tienes que estar al corriente de tus aportaciones, y durante el periodo de descanso no hagas "
                  "ninguna aportación: si haces una, se reactiva y no se puede volver a pedir el descanso.")),
    Tramite("facturas_estados_cuenta", "Facturas o estados de cuenta", Ruta.CLIENTE_MAIL,
            ("factura", "estado de cuenta", "estados de cuenta", "constancia fiscal")),
]

# --- Los que hace el cliente solo en el portal (Ceci, 17/11) ---
# 'asesoria_endosos' va al final porque su alias ('endoso') es amplio.
_SELF_SERVICE = [
    Tramite("restablecer_contrasena", "Restablecer contraseña", Ruta.CLIENTE_PORTAL,
            ("contraseña", "contrasena", "password", "no puedo entrar al portal", "olvidé mi clave", "olvide mi clave"),
            pasos=(f"Entra a tu portal {PORTAL_URL}",
                   "Toca «¿Olvidaste tu contraseña?».",
                   "Escribe el correo registrado en tu póliza y sigue los pasos del correo que te llega.")),
    Tramite("enviar_a_cobro", "Enviar a cobro", Ruta.CLIENTE_PORTAL,
            ("enviar a cobro", "mandar a cobro", "volver a cobrar", "reintentar el cobro", "cobrar de nuevo")),
    Tramite("cambio_fecha_pago", "Modificar fecha de cobro", Ruta.CLIENTE_PORTAL,
            ("cambio de fecha de pago", "fecha de pago", "fecha de cobro", "cambio de fecha", "modificar fecha")),
    Tramite("cambio_datos_contacto", "Modificar correo o teléfono", Ruta.CLIENTE_PORTAL,
            ("cambiar mi correo", "cambio de correo", "modificar correo", "cambiar mi teléfono", "cambiar mi telefono",
             "cambio de teléfono", "cambio de telefono", "modificar teléfono", "modificar telefono")),
    Tramite("cambio_portafolio", "Cambio de portafolio", Ruta.CLIENTE_PORTAL,
            ("cambio de portafolio", "cambiar de portafolio", "cambiar mi portafolio", "redistribución de aportaci",
             "redistribucion de aportaci", "redistribución", "redistribucion", "traspaso entre alternativas",
             "traspaso de alternativas", "traspaso alternativas")),
    Tramite("retiro_dinero", "Retiro de dinero", Ruta.CLIENTE_PORTAL,
            ("retiro de dinero", "retirar dinero", "retiro parcial", "retiro desde alternativas",
             "retiro de alternativas", "retirar desde alternativas", "retiro alternativas")),
    Tramite("cambio_beneficiario", "Cambio de beneficiario", Ruta.CLIENTE_PORTAL,
            ("cambio de beneficiario", "beneficiario", "beneficiarios")),
    Tramite("asesoria_endosos", "Asesoría sobre endosos", Ruta.CLIENTE_PORTAL,
            ("asesoría sobre endoso", "asesoria sobre endoso", "endoso", "endosos")),
]

# Orden de detección: primero los específicos (nosotros y los de correo), al final los del portal.
CATALOGO: list[Tramite] = _NOSOTROS + _CLIENTE_MAIL + _SELF_SERVICE

_POR_CLAVE = {t.clave: t for t in CATALOGO}


def _texto(correo_o_texto: Union[Correo, str]) -> str:
    if isinstance(correo_o_texto, Correo):
        return f"{correo_o_texto.asunto or ''}\n{correo_o_texto.cuerpo_texto or ''}"
    return correo_o_texto or ""


def identificar_tramite(correo_o_texto: Union[Correo, str]) -> Optional[Tramite]:
    """Devuelve el trámite mencionado (por palabras clave) o None. Respeta el orden del CATALOGO."""
    t = _texto(correo_o_texto).lower()
    if not t.strip():
        return None
    for tramite in CATALOGO:
        if any(alias in t for alias in tramite.aliases):
            return tramite
    return None


def por_clave(clave: str) -> Optional[Tramite]:
    return _POR_CLAVE.get(clave)


def _hola(nombre: Optional[str]) -> str:
    return f"Hola {nombre} 👋 " if nombre else "Hola 👋 "


def instrucciones_cliente(tramite: Tramite, nombre: Optional[str] = None, poliza: Optional[str] = None,
                          cliente: Optional[str] = None, producto: Optional[str] = None) -> str:
    """Texto para el cliente: los pasos del portal, o cómo mandar el correo a Allianz (CLIENTE_MAIL)."""
    if tramite.ruta == Ruta.CLIENTE_MAIL:
        return instrucciones_correo(tramite, nombre, poliza, cliente, producto)
    pasos = tramite.pasos or (
        f"Entra a tu portal {PORTAL_URL}",
        "Ve a la sección «Trámites».",
        "Selecciona tu póliza.",
        f"En «Seleccione un trámite» elige: «{tramite.nombre}».",
        "Completa los datos y envía la solicitud.",
    )
    cuerpo = "\n".join(f"{i}. {p}" for i, p in enumerate(pasos, 1))
    extra = f"\n\n{tramite.nota}" if tramite.nota else ""
    return (f"{_hola(nombre)}El trámite «{tramite.nombre}» lo puedes hacer tú mismo desde tu portal:\n\n"
            f"{cuerpo}{extra}\n\nCualquier duda, escríbeme por aquí.")


def instrucciones_correo(tramite: Tramite, nombre: Optional[str], poliza: Optional[str], cliente: Optional[str],
                         producto: Optional[str]) -> str:
    """Cómo pedirlo por correo (Ceci, 17/11): desde el correo de la póliza, al de clientes del producto con copia
    a integraciones@; asunto "Lo que se solicita / Número de póliza / Nombre"."""
    from app import config
    destino = config.correo_clientes_allianz(producto) or "[correo de Allianz]"
    asunto = " / ".join(x for x in (tramite.nombre, (poliza or "").upper() or None,
                                    re.sub(r"\s+", " ", (cliente or "").strip()).title() or None) if x)
    req = f" Incluye {' y '.join(tramite.requisitos)}." if tramite.requisitos else ""
    extra = f"\n\n{tramite.nota}" if tramite.nota else ""
    return (f"{_hola(nombre)}Para pedir tu {tramite.nombre.lower()}, envía un correo desde el correo registrado en "
            f"tu póliza a {destino} con copia a {config.CC_TRAMITE_CLIENTE}. En el asunto pon: {asunto}.{req}{extra}"
            f"\n\nCualquier duda, escríbeme por aquí.")
