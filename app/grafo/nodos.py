"""Nodos del grafo LangGraph.

Cada nodo es una función pura sobre el estado que envuelve una herramienta determinística
(reglas, extracción, repo, Notion, SMTP) o un agente LangChain (L2, redactor). `repo` y
`emisor` se inyectan por closure/partial al construir el grafo (ver grafo.py).

Se reutilizan las constantes y helpers ya probados del motor de tickets para no duplicar la
lógica de estados/eventos/delicado.
"""
from __future__ import annotations

from app.acciones import decidir_y_encolar, despachar_pendientes
from app.clasificador import clasificar_l1, clasificar_l2
from app.db import Repositorio
from app.enriquecimiento import enriquecer
from app.extraccion import extraer
from app.models import EstadoTicket
from app.registro import registrar_en_notion
from app.tickets.engine import (
    _ESTADO_POR_TIPO, _EVENTO_POR_TIPO, _TIPOS_TICKET, _abierto_por, es_delicado,
)

from .estado import EstadoCorreo


def n_clasificar_l1(estado: EstadoCorreo, repo: Repositorio) -> dict:
    clf = clasificar_l1(estado["correo"])
    return {"clasificacion": clf, "ruta": ["clasificar_l1"]}


def n_clasificar_l2(estado: EstadoCorreo, repo: Repositorio) -> dict:
    """Agente LangChain para el correo ambiguo. Si mejora, reemplaza la clasificación."""
    mejor = clasificar_l2(estado["correo"])
    salida: dict = {"ruta": ["clasificar_l2"]}
    if mejor is not None:
        salida["clasificacion"] = mejor
    return salida


def n_extraer(estado: EstadoCorreo, repo: Repositorio) -> dict:
    ent = extraer(estado["correo"], estado["clasificacion"])
    return {"entidades": ent, "ruta": ["extraer"]}


def n_persistir(estado: EstadoCorreo, repo: Repositorio) -> dict:
    """Guarda el correo (idempotente) y decide si el flujo sigue o termina."""
    correo, clf, ent = estado["correo"], estado["clasificacion"], estado.get("entidades", {})
    correo_id, es_nuevo = repo.guardar_correo(correo, clf, ent)
    if not es_nuevo:
        fin = "duplicado"
    elif clf.tipo not in _TIPOS_TICKET:
        fin = "no_ticket"
    else:
        fin = None
    return {"correo_id": correo_id, "es_nuevo": es_nuevo, "fin": fin, "ruta": ["persistir"]}


def n_enriquecer(estado: EstadoCorreo, repo: Repositorio) -> dict:
    """Cruce con Notion (asesor/DAF/cliente por póliza o correo) + marca de delicado."""
    ent = dict(estado.get("entidades", {}))
    notion = enriquecer(ent)
    for k in ("poliza", "cliente_correo", "cliente_nombre"):
        if notion.get(k):
            ent[k] = notion[k]
    delicado = es_delicado(estado["correo"])
    return {"notion": notion, "entidades": ent, "delicado": delicado, "ruta": ["enriquecer"]}


def n_upsert_ticket(estado: EstadoCorreo, repo: Repositorio) -> dict:
    """Busca/crea/actualiza el ticket, lo vincula al correo y agrega el evento a la bitácora."""
    correo, clf = estado["correo"], estado["clasificacion"]
    ent, notion, delicado = estado["entidades"], estado["notion"], estado.get("delicado", False)

    estado_tk = EstadoTicket.ESCALADO_CECI if delicado else _ESTADO_POR_TIPO.get(clf.tipo, EstadoTicket.ABIERTO)
    resueltos = {
        "nro_ticket": ent.get("nro_ticket"), "poliza": ent.get("poliza"),
        "cliente_nombre": ent.get("cliente_nombre"), "cliente_correo": ent.get("cliente_correo"),
        "asesor_correo": notion.get("asesor_correo"), "daf": notion.get("daf_nombre"),
    }
    ticket = repo.buscar_ticket(ent.get("nro_ticket"), ent.get("poliza"), ent.get("cliente_correo"))
    if ticket:
        ticket_id = ticket["id"]
        campos = {"estado": estado_tk.value}
        if delicado and not ticket.get("delicado"):
            campos["delicado"] = True
        for col, val in resueltos.items():
            if val and not ticket.get(col):
                campos[col] = val
        repo.actualizar_ticket(ticket_id, **campos)
    else:
        ticket_id = repo.crear_ticket({**resueltos, "estado": estado_tk.value,
                                       "delicado": delicado, "abierto_por": _abierto_por(clf.tipo)})

    repo.vincular_correo(estado["correo_id"], ticket_id)
    repo.agregar_evento(ticket_id, estado["correo_id"], _EVENTO_POR_TIPO.get(clf.tipo, "evento"),
                        (correo.asunto or "")[:200])
    ticket_repr = {**resueltos, "estado": estado_tk.value, "delicado": delicado}
    return {"ticket_id": ticket_id, "ticket": ticket_repr, "ruta": ["upsert_ticket"]}


def n_registrar_notion(estado: EstadoCorreo, repo: Repositorio) -> dict:
    """Objetivo 3: UPSERT en la base Tickets Allianz de Notion (respeta DRY_RUN)."""
    correo, clf = estado["correo"], estado["clasificacion"]
    bitacora = f"{_EVENTO_POR_TIPO.get(clf.tipo, 'evento')}: {(correo.asunto or '')[:160]}"
    reg = registrar_en_notion(estado["ticket"], estado["notion"], correo, clf.tipo.value, bitacora=bitacora)
    return {"registro_notion": reg, "ruta": ["registrar_notion"]}


def n_decidir(estado: EstadoCorreo, repo: Repositorio) -> dict:
    """Motor de acciones: encola lo que Tommy HARÍA (estado 'sugerida')."""
    plan = decidir_y_encolar(repo, estado["ticket_id"], estado["ticket"],
                             estado["clasificacion"], estado["notion"], estado["correo"])
    return {"acciones": plan, "ruta": ["decidir"]}


def n_despachar(estado: EstadoCorreo, repo: Repositorio, emisor=None) -> dict:
    """Objetivo 2: ejecuta la cola (envío por SMTP). Solo si se pidió `despachar`."""
    if not estado.get("despachar"):
        return {"ruta": ["despachar_omitido"]}
    res = despachar_pendientes(repo, emisor)
    return {"despacho": res, "ruta": ["despachar"]}
