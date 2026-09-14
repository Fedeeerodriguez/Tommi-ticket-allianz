"""Catálogo de trámites Allianz (portal de clientes) + ruteo de atención.

Fuente: indicaciones de Ceci. Cada trámite se resuelve de una de dos formas:
  - CLIENTE_PORTAL: el cliente lo hace solo en su portal → le damos las instrucciones paso a paso.
  - NOSOTROS_MAIL: lo gestionamos nosotros y hay que cambiarlo por correo → sale desde nuestro mail.

`identificar_tramite()` detecta el trámite mencionado en un correo (asunto+cuerpo) por
palabras clave; `instrucciones_cliente()` arma el texto guía para los de portal.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union

from app.models import Correo

PORTAL_URL = "https://clientes.allianz.com.mx/portal-clientes-web/home"


class Ruta(str, Enum):
    CLIENTE_PORTAL = "cliente_portal"   # el cliente lo hace solo → le damos instrucciones
    NOSOTROS_MAIL = "nosotros_mail"     # lo gestionamos nosotros por correo


@dataclass(frozen=True)
class Tramite:
    clave: str
    nombre: str                        # etiqueta exacta del portal
    ruta: Ruta
    aliases: tuple[str, ...]           # palabras clave para detectarlo (en minúsculas)
    pasos: tuple[str, ...] = ()        # instrucciones específicas (portal); vacío = flujo genérico
    nota: str = ""                     # aclaraciones/condiciones adicionales


# --- Trámites que gestionamos nosotros por correo (requieren apoyo, no son self-service) ---
_NOSOTROS = [
    Tramite("cambio_conducto_cobro", "Cambio de conducto de cobro", Ruta.NOSOTROS_MAIL,
            ("conducto de cobro", "cambio de conducto", "medio de cobro", "forma de cobro",
             "cuenta de cobro", "cambio de tarjeta", "cambiar la tarjeta", "domiciliaci")),
]

# --- Período de descanso (año de descanso): portal, pero con instrucciones detalladas ---
_PERIODO_DESCANSO = Tramite(
    "periodo_descanso", "Período de descanso (año de descanso)", Ruta.CLIENTE_PORTAL,
    ("período de descanso", "periodo de descanso", "año de descanso", "ano de descanso",
     "año sabático", "ano sabatico", "pausar los cobros", "pausar cobros", "pausar aportaci"),
    pasos=(
        f"Ingresá a tu portal {PORTAL_URL}",
        "Entrá en la sección «Trámites».",
        "Seleccioná tu póliza.",
        "En «Seleccione un trámite» elegí: «Asesoría para endosos».",
        "En Observaciones explicá que solicitás tu año de descanso y que requerís pausar los cobros.",
        "Enviá la solicitud.",
    ),
    nota=("Te va a llegar un correo de confirmación que tenés que contestar dentro del plazo, "
          "confirmando nuevamente la solicitud (estate atento a tu correo). "
          "Importante: tenés que estar al corriente de tus aportaciones, y durante el año de "
          "descanso no realices ninguna aportación — si hacés una, se reactiva y no se puede "
          "volver a solicitar el descanso."),
)

# --- Trámites self-service del portal (el cliente los hace solo) ---
# Nota: 'asesoria_endosos' va al final porque su alias ('endoso') es amplio; los específicos
# (beneficiario, fecha de pago, etc.) deben matchear antes.
_SELF_SERVICE = [
    Tramite("cambio_beneficiario", "Cambio de beneficiario", Ruta.CLIENTE_PORTAL,
            ("cambio de beneficiario", "beneficiario", "beneficiarios")),
    Tramite("cambio_fecha_pago", "Cambio de fecha de pago", Ruta.CLIENTE_PORTAL,
            ("cambio de fecha de pago", "fecha de pago", "fecha de cobro", "cambio de fecha")),
    Tramite("redistribucion_aportaciones", "Redistribución de aportaciones", Ruta.CLIENTE_PORTAL,
            ("redistribución de aportaci", "redistribucion de aportaci", "redistribución",
             "redistribucion", "redistribuir aportaci")),
    Tramite("retiro_alternativas", "Retiro desde alternativas", Ruta.CLIENTE_PORTAL,
            ("retiro desde alternativas", "retiro de alternativas", "retirar desde alternativas",
             "retiro alternativas")),
    Tramite("traspaso_alternativas", "Traspaso entre alternativas de inversión", Ruta.CLIENTE_PORTAL,
            ("traspaso entre alternativas", "traspaso de alternativas", "traspaso entre alternativas de inversión",
             "traspaso alternativas")),
    Tramite("asesoria_endosos", "Asesoría sobre endosos", Ruta.CLIENTE_PORTAL,
            ("asesoría sobre endoso", "asesoria sobre endoso", "endoso", "endosos")),
]

# Orden de detección: primero los específicos (nosotros + período de descanso + self-service
# concretos), y 'asesoría sobre endosos' al final por ser el alias más amplio.
CATALOGO: list[Tramite] = _NOSOTROS + [_PERIODO_DESCANSO] + _SELF_SERVICE

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


def instrucciones_cliente(tramite: Tramite, nombre: Optional[str] = None) -> str:
    """Texto guía para que el cliente haga el trámite solo desde el portal."""
    hola = f"Hola {nombre}! " if nombre else "Hola! "
    if tramite.pasos:
        pasos = tramite.pasos
    else:
        pasos = (
            f"Ingresá a tu portal {PORTAL_URL}",
            "Entrá en la sección «Trámites».",
            "Seleccioná tu póliza.",
            f"En «Seleccione un trámite» elegí: «{tramite.nombre}».",
            "Completá los datos y enviá la solicitud.",
        )
    cuerpo = "\n".join(f"{i}. {p}" for i, p in enumerate(pasos, 1))
    extra = f"\n\n{tramite.nota}" if tramite.nota else ""
    return (f"{hola}El trámite «{tramite.nombre}» lo podés hacer vos mismo desde tu portal:\n\n"
            f"{cuerpo}{extra}\n\nCualquier duda, quedamos a las órdenes. 💛")
