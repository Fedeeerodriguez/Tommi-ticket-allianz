"""Paso 3 de la Etapa 1 — ¿quién es el cliente y quién es su asesor?

Los correos del proceso largo (C1–C5) traen n° de solicitud + nombre del cliente; la póliza
llega recién al final. Se busca en Notion Emisiones, en este orden:
  1. lo que ya quedó guardado en el ticket (los correos siguientes del mismo ticket lo reusan);
  2. n° de solicitud (exacto) — y se verifica que el nombre coincida;
  3. póliza (exacta: 'contains' solo sirve para traer candidatos);
  4. nombre completo (se compara sin acentos ni mayúsculas, en cualquier orden).

Regla dura: **no se adivina**. Varias filas valen solo si son la misma persona con el mismo
asesor (un cliente con varias pólizas). Si hay 0 o personas distintas → no identificado, y el
motor le manda el aviso solo a Ceci para que lo asigne a mano. Nunca a la persona equivocada.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Optional

from app import config

log = logging.getLogger(__name__)

# buscar(campo_logico, operador, valor, page_size) -> (filas extraídas, hay_mas)
Buscador = Callable[[str, str, object, int], tuple[list[dict], bool]]

CAMPOS_TICKET = ("cliente_nombre", "cliente_correo", "telefono_cliente", "asesor_correo", "telefono_asesor")
_CAMPOS_DATOS = CAMPOS_TICKET + ("asesor_nombre", "daf_nombre", "poliza", "nro_solicitud", "emision_id")


@dataclass
class Identificacion:
    estado: str                    # identificado | sin_coincidencia | ambiguo | sin_datos | sin_notion
    via: Optional[str] = None      # ticket | solicitud | poliza | nombre
    datos: dict = field(default_factory=dict)
    candidatos: int = 0
    motivo: str = ""

    @property
    def ok(self) -> bool:
        return self.estado == "identificado"

    def campos_ticket(self) -> dict:
        """Lo que se guarda en el ticket (solo valores con dato)."""
        return {k: self.datos[k] for k in CAMPOS_TICKET if self.datos.get(k) not in (None, "")}


# ----------------------------------------------------------------- comparación
def norm_nombre(s: Optional[str]) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z ]", " ", s.lower()).split())


def mismo_nombre(a: Optional[str], b: Optional[str]) -> bool:
    """Mismas palabras (sin acentos/mayúsculas/espacios dobles), en cualquier orden."""
    ta, tb = norm_nombre(a).split(), norm_nombre(b).split()
    return bool(ta) and sorted(ta) == sorted(tb)


def nombres_compatibles(a: Optional[str], b: Optional[str]) -> bool:
    """Para validar un cruce por n° exacto: iguales, o uno contiene al otro (le falta un segundo
    nombre) con al menos 2 palabras en común."""
    if mismo_nombre(a, b):
        return True
    sa, sb = set(norm_nombre(a).split()), set(norm_nombre(b).split())
    chico, grande = sorted((sa, sb), key=len)
    return len(chico) >= 2 and chico <= grande


def _digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))[-10:]


def _asesor(d: dict) -> str:
    return (d.get("asesor_correo") or "").strip().lower() or norm_nombre(d.get("asesor_nombre"))


def _consolidar(filas: list[dict]) -> tuple[Optional[dict], str]:
    """Varias filas → una persona, si no se contradicen (mismo nombre, teléfono y asesor).
    Las filas vienen de la más nueva a la más vieja: se toma el primer dato no vacío de cada campo."""
    if not filas:
        return None, "sin filas"
    for clave, etiqueta in ((lambda d: norm_nombre(d.get("cliente_nombre")), "clientes distintos"),
                            (lambda d: _digitos(d.get("telefono_cliente")), "teléfonos de cliente distintos"),
                            (_asesor, "asesores distintos")):
        valores = {clave(f) for f in filas} - {""}
        if len(valores) > 1:
            return None, etiqueta
    junto: dict = {}
    for f in filas:
        for k in _CAMPOS_DATOS:
            if junto.get(k) in (None, "") and f.get(k) not in (None, ""):
                junto[k] = f[k]
    return junto, ""


# ----------------------------------------------------------------- búsqueda
def _buscador_notion() -> Optional[Buscador]:
    if not config.hay_notion():
        return None
    from app.rieles.notion import buscar_emisiones
    return lambda campo, op, valor, n: buscar_emisiones(campo, op, valor, n)


def _resultado(filas: list[dict], via: str, cliente: Optional[str]) -> Identificacion:
    persona, porque = _consolidar(filas)
    if not persona:
        return Identificacion("ambiguo", via, candidatos=len(filas), motivo=f"{via}: {porque}")
    if cliente and persona.get("cliente_nombre") and not nombres_compatibles(cliente, persona["cliente_nombre"]):
        return Identificacion("ambiguo", via, candidatos=len(filas),
                              motivo=f"{via}: en Notion es de otro cliente ({persona['cliente_nombre']})")
    return Identificacion("identificado", via, persona, len(filas), f"por {via}")


def identificar(*, nro_solicitud: Optional[str] = None, poliza: Optional[str] = None,
                cliente: Optional[str] = None, ticket: Optional[dict] = None,
                buscar: Optional[Buscador] = None) -> Identificacion:
    # 1) Ya identificado por este flujo o asignado a mano por Ceci. Lo que llenó el enriquecimiento
    #    viejo (sin `identificado_por`) NO se reusa: se vuelve a verificar.
    if ticket and ticket.get("identificado_por"):
        return Identificacion("identificado", "ticket", {k: ticket.get(k) for k in CAMPOS_TICKET},
                              motivo=f"ya identificado en el ticket ({ticket['identificado_por']})")
    if not (nro_solicitud or poliza or cliente):
        return Identificacion("sin_datos", motivo="el correo no trae solicitud, póliza ni nombre")
    buscar = buscar or _buscador_notion()
    if buscar is None:
        return Identificacion("sin_notion", motivo="Notion no está configurado")

    try:
        # 2) N° de solicitud (exacto en Notion: es un campo numérico).
        if nro_solicitud:
            filas, _ = buscar("nro_solicitud", "equals", nro_solicitud, 5)
            if filas:
                return _resultado(filas, "solicitud", cliente)

        # 3) Póliza: candidatos por número y verificación exacta.
        if poliza:
            from app.rieles.notion import misma_poliza, numero_poliza
            filas, _ = buscar("poliza", "contains", numero_poliza(poliza), 10)
            filas = [f for f in filas if misma_poliza(f.get("poliza"), poliza)]
            if filas:
                return _resultado(filas, "poliza", cliente)

        # 4) Nombre: Notion distingue acentos, así que se prueba palabra por palabra (las más
        #    largas primero) y se compara el nombre completo de nuestro lado.
        if cliente:
            palabras = sorted({p for p in norm_nombre(cliente).split() if len(p) >= 3}, key=len, reverse=True)
            if len(palabras) < 2:
                return Identificacion("sin_coincidencia", motivo="nombre demasiado corto para buscar seguro")
            for palabra in palabras[:4]:
                filas, hay_mas = buscar("cliente_nombre", "contains", palabra, 100)
                iguales = [f for f in filas if mismo_nombre(f.get("cliente_nombre"), cliente)]
                if iguales and not hay_mas:  # lista completa → se puede decidir
                    return _resultado(iguales, "nombre", None)
    except Exception as ex:  # noqa: BLE001 — si Notion falla, no se adivina
        log.warning("identificar: Notion falló: %s", ex)
        return Identificacion("sin_coincidencia", motivo=f"Notion falló: {ex}")

    return Identificacion("sin_coincidencia", motivo="no está en Notion Emisiones")


def identificar_y_guardar(repo, ticket: dict, etapa: dict, buscar: Optional[Buscador] = None,
                          correo_id: Optional[int] = None) -> Identificacion:
    """Identifica con los datos del correo (`etapa` = EtapaCorreo.como_dict()) y, si es una
    identificación nueva, la guarda en el ticket y deja constancia en la bitácora."""
    ident = identificar(nro_solicitud=etapa.get("nro_solicitud") or ticket.get("nro_solicitud"),
                        poliza=etapa.get("poliza") or ticket.get("poliza"),
                        cliente=etapa.get("cliente") or ticket.get("cliente_nombre"),
                        ticket=ticket, buscar=buscar)
    if ident.ok and ident.via != "ticket":
        repo.actualizar_ticket(ticket["id"], **ident.campos_ticket(), identificado_por=ident.via)
        repo.agregar_evento(ticket["id"], correo_id, "identificacion",
                            f"Cliente y asesor identificados {ident.motivo} "
                            f"({ident.datos.get('cliente_nombre')} · asesor {ident.datos.get('asesor_nombre') or ident.datos.get('asesor_correo')})")
    return ident
