"""Motor de tickets (M2 + M8 + parte de M5).

A partir de un correo clasificado + entidades:
  1. Persiste el correo (idempotente).
  2. Si el tipo amerita ticket, busca/crea el ticket y ajusta su estado.
  3. Marca `delicado` si el tema es sensible → debe ir con Ceci (M5).
  4. Registra un evento en la bitácora (M8).

NO envía nada (eso es el motor de acciones, Fase 3/4). Solo estructura y registra.
"""
from __future__ import annotations

import re

from app.db import Repositorio
from app.enriquecimiento import enriquecer
from app.models import Clasificacion, Correo, EstadoTicket, TipoCorreo
from app.registro import registrar_en_notion

# Tipos que representan un ticket con Allianz.
_TIPOS_TICKET = {
    TipoCorreo.A_RESPUESTA_TICKET,
    TipoCorreo.B_ACUSE_TICKET,
    TipoCorreo.C_ALLIANZ_PIDE,
    TipoCorreo.D_REENVIO_ASESOR,
    TipoCorreo.E_CC_CLIENTE,
}

# Estado sugerido según el tipo de correo (quién queda "en la pelota").
_ESTADO_POR_TIPO = {
    TipoCorreo.A_RESPUESTA_TICKET: EstadoTicket.ESPERANDO_CLIENTE,   # Allianz respondió → revisar/avisar
    TipoCorreo.B_ACUSE_TICKET: EstadoTicket.ESPERANDO_ALLIANZ,       # ticket abierto, Allianz procesa
    TipoCorreo.C_ALLIANZ_PIDE: EstadoTicket.ESPERANDO_CLIENTE,       # falta algo del cliente
    TipoCorreo.D_REENVIO_ASESOR: EstadoTicket.ABIERTO,               # hay que levantar el ticket
    TipoCorreo.E_CC_CLIENTE: EstadoTicket.ESPERANDO_ALLIANZ,         # cliente escribió, esperamos Allianz
}

_EVENTO_POR_TIPO = {
    TipoCorreo.A_RESPUESTA_TICKET: "respuesta_allianz",
    TipoCorreo.B_ACUSE_TICKET: "ticket_creado",
    TipoCorreo.C_ALLIANZ_PIDE: "pedido_a_cliente",
    TipoCorreo.D_REENVIO_ASESOR: "solicitud_asesor",
    TipoCorreo.E_CC_CLIENTE: "cliente_escribio_allianz",
}

# Temas sensibles → forzosamente Ceci (LISTA TENTATIVA, a confirmar con Ceci).
_RE_DELICADO = re.compile(
    r"\b(beneficiari|cancelaci|cancelar|rescate|retiro\s+total|fallecimiento|defunci|deceso|"
    r"siniestro|reclamaci|fraude|legal|demanda|queja|conducta|devoluci[oó]n\s+de\s+prima)\b",
    re.I,
)


def es_delicado(correo: Correo) -> bool:
    return bool(_RE_DELICADO.search(f"{correo.asunto}\n{correo.cuerpo_texto}"))


def procesar_correo(repo: Repositorio, correo: Correo, clf: Clasificacion, entidades: dict) -> dict:
    """Devuelve un resumen de lo que se hizo (para logging/UI)."""
    correo_id, es_nuevo = repo.guardar_correo(correo, clf, entidades)
    resultado: dict = {"correo_id": correo_id, "es_nuevo": es_nuevo, "tipo": clf.tipo.value,
                       "ticket_id": None, "accion": None}

    if not es_nuevo:
        resultado["accion"] = "correo duplicado (idempotente), ignorado"
        return resultado

    if clf.tipo not in _TIPOS_TICKET:
        resultado["accion"] = "no genera ticket (consulta/sistema/publicidad)"
        return resultado

    delicado = es_delicado(correo)

    # Cruce con Notion (M6): resuelve asesor/DAF/cliente por póliza o correo del cliente.
    # Notion es fuente de verdad para póliza/cliente → completa lo que la extracción no vio.
    notion = enriquecer(entidades)
    for k in ("poliza", "cliente_correo", "cliente_nombre"):
        if notion.get(k):
            entidades[k] = notion[k]
    if notion.get("found"):
        resultado["notion"] = {"asesor": notion.get("asesor_correo"), "daf": notion.get("daf_nombre"),
                               "cliente": notion.get("cliente_nombre"), "producto": notion.get("producto")}

    # Buscar ticket existente por nº / póliza / cliente.
    ticket = repo.buscar_ticket(entidades.get("nro_ticket"), entidades.get("poliza"),
                                entidades.get("cliente_correo"))

    estado = EstadoTicket.ESCALADO_CECI if delicado else _ESTADO_POR_TIPO.get(clf.tipo, EstadoTicket.ABIERTO)

    # Datos resueltos (extracción + Notion) para persistir en el ticket.
    resueltos = {
        "nro_ticket": entidades.get("nro_ticket"),
        "poliza": entidades.get("poliza"),
        "cliente_nombre": entidades.get("cliente_nombre"),
        "cliente_correo": entidades.get("cliente_correo"),
        "asesor_correo": notion.get("asesor_correo"),
        "daf": notion.get("daf_nombre"),
    }

    if ticket:
        ticket_id = ticket["id"]
        campos = {"estado": estado.value}
        if delicado and not ticket.get("delicado"):
            campos["delicado"] = True
        for col, val in resueltos.items():  # completar lo que faltaba
            if val and not ticket.get(col):
                campos[col] = val
        repo.actualizar_ticket(ticket_id, **campos)
        resultado["accion"] = f"ticket actualizado → {estado.value}" + (" [DELICADO→Ceci]" if delicado else "")
    else:
        ticket_id = repo.crear_ticket({
            **resueltos,
            "estado": estado.value,
            "delicado": delicado,
            "abierto_por": _abierto_por(clf.tipo),
        })
        resultado["accion"] = f"ticket creado → {estado.value}" + (" [DELICADO→Ceci]" if delicado else "")

    repo.vincular_correo(correo_id, ticket_id)
    repo.agregar_evento(ticket_id, correo_id, _EVENTO_POR_TIPO.get(clf.tipo, "evento"),
                        (correo.asunto or "")[:200])
    resultado["ticket_id"] = ticket_id
    resultado["delicado"] = delicado

    # Registro en Notion (objetivo 3): UPSERT en la base Tickets Allianz + bitácora.
    # Respeta DRY_RUN (arma el payload, no escribe).
    ticket_repr = {**resueltos, "estado": estado.value}
    resultado["registro_notion"] = registrar_en_notion(
        ticket_repr, notion, correo, clf.tipo.value,
        bitacora=f"{_EVENTO_POR_TIPO.get(clf.tipo, 'evento')}: {(correo.asunto or '')[:160]}",
    )
    return resultado


def _abierto_por(tipo: TipoCorreo) -> str:
    if tipo in (TipoCorreo.A_RESPUESTA_TICKET, TipoCorreo.B_ACUSE_TICKET, TipoCorreo.C_ALLIANZ_PIDE):
        return "allianz"
    if tipo == TipoCorreo.D_REENVIO_ASESOR:
        return "asesor"
    if tipo == TipoCorreo.E_CC_CLIENTE:
        return "cliente"
    return "tommy"
