"""Nodos del grafo LangGraph.

Cada nodo es una función pura sobre el estado que envuelve una herramienta determinística
(reglas, extracción, repo, Notion, SMTP) o un agente LangChain (L2, redactor). `repo` y
`emisor` se inyectan por closure/partial al construir el grafo (ver grafo.py).

Se reutilizan las constantes y helpers ya probados del motor de tickets para no duplicar la
lógica de estados/eventos/delicado.
"""
from __future__ import annotations

from app import config
from app.acciones import decidir_y_encolar, despachar_pendientes
from app.acciones.motor_etapas import EMISIONES, decidir_por_etapa, ticket_para_emision, usa_motor_etapas
from app.clasificador import clasificar_l1, clasificar_l2
from app.clasificador.allianz import es_correo_allianz
from app.clasificador.etapas import detectar_etapa
from app.db import Repositorio
from app.enriquecimiento import enriquecer
from app.extraccion import extraer
from app.models import EstadoTicket, TipoCorreo
from app.registro import registrar_en_notion
from app.tickets import sla
from app.tramites import identificar_tramite
from app.tickets.engine import (
    _ESTADO_POR_TIPO, _EVENTO_POR_TIPO, _TIPOS_TICKET, _abierto_por, es_delicado, estado_sugerido,
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
    elif clf.tipo in _TIPOS_TICKET:
        fin = None
    elif clf.tipo == TipoCorreo.F_CONSULTA_PRODUCTO and identificar_tramite(correo) is not None:
        # Consulta con un trámite reconocido → la tratamos como ticket (instruir / gestionar).
        fin = None
    else:
        fin = "no_ticket"
    salida = {"correo_id": correo_id, "es_nuevo": es_nuevo, "fin": fin, "ruta": ["persistir"]}
    if config.MOTOR_ETAPAS and es_nuevo:
        etapa = _etapa(estado)
        # Los avisos de emisión llegan como "sistema" y sin n° de ticket. Si son de un ticket del
        # proceso largo que ya seguimos, siguen por su propio camino (n_emision).
        if fin == "no_ticket" and etapa and etapa.get("etapa") in EMISIONES:
            tid = ticket_para_emision(repo, etapa)
            if tid:
                salida.update(fin=None, emision_ticket_id=tid)
        # Avisos automáticos de Allianz que no son de ningún ticket (DAF, cobranzas, recordatorio de
        # pago…): fuera de alcance, no crean ticket. Los delicados siguen el camino de siempre (Ceci).
        elif fin is None and etapa is None and _buzon_de_avisos(correo.remitente) and not es_delicado(correo):
            salida["fin"] = "fuera_de_alcance"
    return salida


def _buzon_de_avisos(remitente: str) -> bool:
    if not es_correo_allianz(remitente or ""):
        return False
    local = (remitente or "").split("<")[-1].strip(" >").lower().split("@")[0]
    return any(local == b.strip().lower() for b in config.ALLIANZ_BUZONES_AVISOS)


def _etapa(estado: EstadoCorreo) -> dict | None:
    """Etapa del correo (la calcula el clasificador L1; si la L2 la pisó, se recalcula)."""
    clf = estado.get("clasificacion")
    etapa = (getattr(clf, "entidades", None) or {}).get("etapa") or (estado.get("entidades") or {}).get("etapa")
    if etapa:
        return etapa
    c = estado["correo"]
    e = detectar_etapa(c.asunto or "", c.cuerpo_texto or "", c.remitente or "")
    return e.como_dict() if e.etapa.value != "no_aplica" else None


def n_emision(estado: EstadoCorreo, repo: Repositorio) -> dict:
    """Aviso de emisión / emisión registrada de un ticket del proceso largo → motor por etapa."""
    tid, correo = estado["emision_ticket_id"], estado["correo"]
    repo.vincular_correo(estado["correo_id"], tid)
    repo.agregar_evento(tid, estado["correo_id"], "emision", (correo.asunto or "")[:200])
    res = decidir_por_etapa(repo, tid, _etapa(estado), correo_id=estado.get("correo_id"))
    return {"ticket_id": tid, "acciones": res["plan"], "etapa_resultado": res, "ruta": ["emision"]}


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

    estado_tk = estado_sugerido(clf, delicado)
    resueltos = {
        "nro_ticket": ent.get("nro_ticket"), "poliza": ent.get("poliza"),
        "cliente_nombre": ent.get("cliente_nombre"), "cliente_correo": ent.get("cliente_correo"),
        "asesor_correo": notion.get("asesor_correo"), "daf": notion.get("daf_nombre"),
        # Fase F: teléfonos de Notion (Emisiones) → habilitan el ruteo por WATI a cliente/asesor.
        "telefono_cliente": notion.get("telefono_cliente"),
        "telefono_asesor": notion.get("telefono_asesor"),
    }
    # Hilo (Fase B): el thread y el asunto se fijan una vez; el último Message-ID se refresca
    # SIEMPRE para poder responder encadenando en el mismo hilo del ticket.
    hilo = {"gmail_thread_id": correo.hilo_id, "asunto_hilo": correo.asunto}
    # SLA (Fase C): vencimiento según el plazo de Allianz (o 72 h hábiles por default); cierre → None.
    vence_en = sla.vence_en_para(correo, clf)
    ticket = repo.buscar_ticket(ent.get("nro_ticket"), ent.get("poliza"), ent.get("cliente_correo"))
    if ticket:
        ticket_id = ticket["id"]
        campos = {"estado": estado_tk.value, "ultimo_message_id": correo.message_id, "vence_en": vence_en}
        if delicado and not ticket.get("delicado"):
            campos["delicado"] = True
        for col, val in {**resueltos, **hilo}.items():
            if val and not ticket.get(col):
                campos[col] = val
        repo.actualizar_ticket(ticket_id, **campos)
    else:
        ticket_id = repo.crear_ticket({**resueltos, **hilo, "ultimo_message_id": correo.message_id,
                                       "vence_en": vence_en, "estado": estado_tk.value,
                                       "delicado": delicado, "abierto_por": _abierto_por(clf.tipo)})

    repo.vincular_correo(estado["correo_id"], ticket_id)
    repo.agregar_evento(ticket_id, estado["correo_id"],
                        clf.subtipo or _EVENTO_POR_TIPO.get(clf.tipo, "evento"),
                        (correo.asunto or "")[:200])
    ticket_repr = {**resueltos, **hilo, "ultimo_message_id": correo.message_id,
                   "estado": estado_tk.value, "delicado": delicado}
    return {"ticket_id": ticket_id, "ticket": ticket_repr, "ruta": ["upsert_ticket"]}


def n_registrar_notion(estado: EstadoCorreo, repo: Repositorio) -> dict:
    """Objetivo 3: UPSERT en la base Tickets Allianz de Notion (respeta DRY_RUN)."""
    correo, clf = estado["correo"], estado["clasificacion"]
    bitacora = f"{_EVENTO_POR_TIPO.get(clf.tipo, 'evento')}: {(correo.asunto or '')[:160]}"
    reg = registrar_en_notion(estado["ticket"], estado["notion"], correo, clf.tipo.value, bitacora=bitacora)
    return {"registro_notion": reg, "ruta": ["registrar_notion"]}


def n_decidir(estado: EstadoCorreo, repo: Repositorio) -> dict:
    """Motor de acciones: encola lo que Tommy HARÍA (estado 'sugerida').
    Proceso largo + MOTOR_ETAPAS=1 → motor por etapa; el resto, el motor por tipo de correo."""
    etapa = _etapa(estado)
    if etapa and usa_motor_etapas(etapa, repo.obtener_ticket(estado["ticket_id"])):
        res = decidir_por_etapa(repo, estado["ticket_id"], etapa, correo_id=estado.get("correo_id"))
        return {"acciones": res["plan"], "etapa_resultado": res, "ruta": ["decidir_etapa"]}
    plan = decidir_y_encolar(repo, estado["ticket_id"], estado["ticket"],
                             estado["clasificacion"], estado["notion"], estado["correo"])
    return {"acciones": plan, "ruta": ["decidir"]}


def n_despachar(estado: EstadoCorreo, repo: Repositorio, emisor=None) -> dict:
    """Objetivo 2: ejecuta la cola (envío por SMTP). Solo si se pidió `despachar`."""
    if not estado.get("despachar"):
        return {"ruta": ["despachar_omitido"]}
    res = despachar_pendientes(repo, emisor)
    return {"despacho": res, "ruta": ["despachar"]}
