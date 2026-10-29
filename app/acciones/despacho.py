"""Despachador de acciones (Fase 4): toma lo que el motor dejó en la cola y lo EJECUTA.

Cierra el objetivo 2 ("enviar tickets a Allianz"): la acción `enviar_a_allianz` (canal
`email`) se compone y sale por SMTP. El resto de canales todavía no tiene integración de
envío en este repo, así que se marcan de forma explícita (no se pierden).

Estados que deja en `acciones.estado`:
  - enviada     → salió por SMTP real (ok).
  - simulada    → DRY_RUN / sin credenciales: se compuso pero no se mandó (queda el correo en `resultado`).
  - fallida     → intento de envío con error (queda el error en `resultado`).
  - bloqueada   → guardarraíl: falta el Directorio Allianz o el destinatario.
  - pendiente_ceci → guardarraíl crítico (Fase E): se compuso el BORRADOR pero es una acción
                     crítica → espera el visto bueno de Ceci (queda el borrador en `resultado`).
  - pendiente_wati → canal WhatsApp (WATI): lo envía la integración de WATI, no este despachador.
  - omitida     → canal interno (Ceci/panel): no requiere envío externo.
  - diferida    → tiene `programada_para` en el futuro: todavía no toca.

Nada de esto envía nada salvo que haya SMTP y `DRY_RUN=false` (lo decide `emisor_desde_config`).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from app import config
from app.acciones.criticas import CANALES_SALIENTES, es_accion_critica, retener_para_ceci
from app.db import Repositorio
from app.envio import Emisor, emisor_desde_config

log = logging.getLogger(__name__)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _vencida(programada_para, ahora: datetime) -> bool:
    """True si la acción ya puede ejecutarse (sin fecha = inmediata; con fecha = ya pasó)."""
    if not programada_para:
        return True
    val = programada_para
    try:
        ts = val if isinstance(val, datetime) else datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return True  # si no se puede parsear, no la dejamos colgada
    return ts <= ahora


def _payload(accion: dict) -> dict:
    p = accion.get("payload")
    if isinstance(p, str):
        try:
            return json.loads(p)
        except Exception:  # noqa: BLE001
            return {}
    return p or {}


def _asunto_allianz(ticket: dict) -> str:
    nro = ticket.get("nro_ticket")
    pol = ticket.get("poliza")
    if nro:
        return f"Seguimiento ticket {nro}" + (f" · póliza {pol}" if pol else "")
    if pol:
        return f"Solicitud de trámite · póliza {pol}"
    return "Solicitud de trámite"


def _cuerpo_allianz(ticket: dict, pay: dict) -> str:
    lineas = ["Estimados,", ""]
    # `pay["mensaje"]` es la nota INTERNA de la acción ("Re-exigencia: …", "Levantar el ticket…"):
    # nunca va en el correo a Allianz. Sin borrador validado, el cuerpo es neutro.
    detalle = "Solicitamos por favor su apoyo para gestionar el trámite referido y nos confirmen los siguientes pasos."
    lineas.append(detalle)
    lineas.append("")
    datos = []
    if ticket.get("nro_ticket"):
        datos.append(f"Ticket: {ticket['nro_ticket']}")
    if ticket.get("poliza"):
        datos.append(f"Póliza: {ticket['poliza']}")
    if ticket.get("cliente_nombre"):
        datos.append(f"Cliente: {ticket['cliente_nombre']}")
    if datos:
        lineas += datos + [""]
    lineas += ["Quedamos atentos.", "Babilonia"]
    return "\n".join(lineas)


def _guardar_si_critico(repo: Repositorio, accion: dict, ticket: dict, pay: dict,
                        borrador: dict) -> Optional[str]:
    """Fase E: si la acción es crítica y el ticket NO está autorizado, retiene el borrador para
    el visto bueno de Ceci y devuelve 'pendiente_ceci'. Si no es crítica o Ceci ya autorizó,
    devuelve None (sigue el envío normal)."""
    # Trámite abierto por Ceci desde el panel: ella misma lo armó y lo revisó → no se retiene.
    if accion.get("tipo_accion") == "abrir_tramite":
        return None
    # Ceci ya aprobó ESTA acción (panel "Enviar" o autorizar el ticket): sale. Antes solo se miraba
    # en las escalaciones, y un correo crítico aprobado desde el panel se volvía a retener para siempre.
    res = accion.get("resultado")
    if isinstance(res, str):
        try:
            res = json.loads(res)
        except Exception:  # noqa: BLE001
            res = {}
    if (res or {}).get("aprobado_por"):
        return None
    # Escalación a Allianz (Etapa 1): se aprueba de a UNA acción (no alcanza con el ticket autorizado).
    if pay.get("requiere_visto_bueno"):
        retener_para_ceci(repo, accion, ticket, borrador)
        return "pendiente_ceci"
    if not es_accion_critica(ticket, pay):
        return None
    if ticket.get("autorizado"):
        return None  # Ceci ya dio el visto bueno → se ejecuta
    retener_para_ceci(repo, accion, ticket, borrador)
    return "pendiente_ceci"


@contextmanager
def _archivos(adjuntos: Optional[list]):
    """Adjuntos guardados en el payload ({nombre, base64}) → archivos temporales para el emisor."""
    if not adjuntos:
        yield []
        return
    with tempfile.TemporaryDirectory(prefix="adjuntos_") as carpeta:
        rutas = []
        for a in adjuntos:
            ruta = os.path.join(carpeta, os.path.basename(a.get("nombre") or "adjunto"))
            with open(ruta, "wb") as f:
                f.write(base64.b64decode(a.get("base64") or ""))
            rutas.append(ruta)
        yield rutas


_MAX_VARIABLE = 900  # WhatsApp: el cuerpo entero no puede pasar de 1024 caracteres


def una_linea(v) -> str:
    """WhatsApp rechaza variables con saltos de línea, tabs o más de 4 espacios seguidos.
    Vacío también lo rechaza → '—'."""
    import re
    t = re.sub(r"\s*\n\s*", " · ", str(v or "")).replace("\t", " ")
    t = re.sub(r" {2,}", " ", t).strip(" ·")
    if len(t) > _MAX_VARIABLE:
        t = t[:_MAX_VARIABLE - 1].rsplit(" ", 1)[0] + "…"
    return t or "—"


def sin_saludo(texto: str) -> str:
    """La plantilla del cliente ya dice 'Hola {{nombre}} 👋': 'Hola Ana, tu solicitud…' → 'Tu solicitud…'."""
    import re
    t = re.sub(r"^\s*hola(?:\s+[^,.!¡]{1,40})?\s*[,!.]\s*", "", texto or "", count=1, flags=re.I)
    # Mayúscula en la primera letra, aunque arranque con '¡' o '¿' ("¡tu póliza…" → "¡Tu póliza…").
    return re.sub(r"^([¡¿\s]*)(\w)", lambda m: m.group(1) + m.group(2).upper(), t, count=1)


def sin_encabezado(texto: str) -> str:
    """La plantilla del equipo ya muestra Ticket / Cliente / Trámite arriba:
    'Ticket 2576612 · Ana: Allianz pide → …' → 'Allianz pide → …'."""
    import re
    t = re.sub(r"^\s*Ticket\s[^:\n]{1,200}:\s*", "", texto or "", count=1)
    return t[:1].upper() + t[1:] if t else t


def plantilla_etapas(pay: dict) -> tuple[str, dict]:
    """Avisos del motor por etapa → (plantilla WATI, variables por nombre). Una plantilla por
    destinatario: equipo (asesor/Ceci), cliente, y la guía de aportación."""
    p = pay.get("params") or {}
    rol = (pay.get("rol") or "").lower()
    if rol == "cliente" and p.get("guia"):
        from app.acciones.mensajes_etapa import guia_de, valores_guia
        g, guia = p["guia"], guia_de(p["guia"])
        plantilla = {"patrimonial": config.WATI_PLANTILLA_GUIA_PATRIMONIAL,
                     "elite": config.WATI_PLANTILLA_GUIA_ELITE,
                     "optimaxx": config.WATI_PLANTILLA_GUIA_OPTIMAXX}.get(guia["plantilla"], config.WATI_PLANTILLA_GUIA)
        valores = valores_guia(g)
        return plantilla, {k: una_linea(valores[k]) for k in guia["variables"]}
    if rol == "cliente":
        return config.WATI_PLANTILLA_AVISO_CLIENTE, {
            "nombre": una_linea(p.get("nombre") or "de nuevo"),
            "mensaje": una_linea(sin_saludo(pay.get("mensaje", "")))}
    return config.WATI_PLANTILLA_AVISO_EQUIPO, {
        "ticket": una_linea(p.get("ticket")), "cliente": una_linea(p.get("cliente")),
        "tramite": una_linea(p.get("tramite")), "mensaje": una_linea(sin_encabezado(pay.get("mensaje", "")))}


def _despachar_una(repo: Repositorio, accion: dict, emisor: Emisor, ahora: datetime) -> str:
    canal = (accion.get("canal") or "").lower()
    tipo = accion.get("tipo_accion") or ""
    aid = accion["id"]
    pay = _payload(accion)

    if not _vencida(accion.get("programada_para"), ahora):
        return "diferida"  # no se toca todavía; sigue 'sugerida'

    # Canal interno (Ceci / seguimiento / panel): no hay envío externo.
    if canal == "interno":
        repo.actualizar_accion(aid, "omitida", {"motivo": "canal interno (panel/Ceci)"})
        return "omitida"

    # Canal WhatsApp (WATI): plantilla según el rol. Ceci usa su número fijo; asesor/cliente usan
    # el número del payload (lo completa Notion en Fase F). Sin número → queda pendiente.
    if canal == "wati":
        rol = (pay.get("rol") or "").lower()
        if rol == "ceci":
            numero = config.CECI_WHATSAPP
            plantilla = config.WATI_PLANTILLA_CECI
        elif rol == "asesor":
            numero = pay.get("numero") or pay.get("destinatario")
            plantilla = config.WATI_PLANTILLA_ASESOR
        else:  # cliente
            numero = pay.get("numero") or pay.get("destinatario")
            plantilla = config.WATI_PLANTILLA_CLIENTE
        # Un número de WhatsApp es telefónico; si el destinatario es un email, no sirve.
        if not numero or "@" in str(numero):
            repo.actualizar_accion(aid, "pendiente_wati",
                                   {"motivo": "sin número de WhatsApp", "rol": rol,
                                    "mensaje": pay.get("mensaje")})
            return "pendiente_wati"
        from app.wati import wati_desde_config
        wati = wati_desde_config()
        params = {"mensaje": pay.get("mensaje", "")}
        # Avisos del motor por etapa → la plantilla de su destinatario (equipo / cliente / guía).
        if pay.get("etapa"):
            plantilla, params = plantilla_etapas(pay)
        res = wati.enviar_plantilla(numero, plantilla, params)
        if res.get("simulado"):
            repo.actualizar_accion(aid, "simulada", res)
            return "simulada"
        if res.get("ok"):
            repo.actualizar_accion(aid, "enviada", res)
            return "enviada"
        repo.actualizar_accion(aid, "fallida", res)
        return "fallida"

    # Canal email al cliente/asesor (instrucciones de trámite o aviso): sale por SMTP a quien
    # preguntó. No lleva el guardarraíl de Allianz (no es un envío al Directorio Allianz).
    if canal == "email_cliente":
        destino = pay.get("destinatario")
        if not destino:
            repo.actualizar_accion(aid, "bloqueada", {"motivo": "sin destinatario para responder"})
            return "bloqueada"
        asunto = pay.get("asunto") or "Sobre tu trámite"
        cuerpo = accion.get("borrador_editado") or pay.get("mensaje") or ""  # lo editado en el panel manda
        # Guardarraíl crítico (Fase E): confirmaciones al cliente en temas críticos (cancelación,
        # suspensión de aportaciones, período de descanso…) pasan primero por Ceci.
        ticket = repo.obtener_ticket(accion["ticket_id"]) or {}
        hold = _guardar_si_critico(repo, accion, ticket, pay,
                                   {"destino": destino, "asunto": asunto, "cuerpo": cuerpo,
                                    "canal": "email_cliente"})
        if hold:
            return hold
        res = emisor.enviar([destino], asunto, cuerpo)
        if res.get("simulado"):
            repo.actualizar_accion(aid, "simulada", res)
            return "simulada"
        if res.get("ok"):
            repo.actualizar_accion(aid, "enviada", res)
            return "enviada"
        repo.actualizar_accion(aid, "fallida", res)
        return "fallida"

    # Canal email → envío a Allianz (Directorio). Guardarraíles antes de salir.
    if canal == "email":
        ticket = repo.obtener_ticket(accion["ticket_id"]) or {}
        # Guardarraíl 1: sin Directorio Allianz no hay a quién mandarle.
        # Directorio por trámite (lo resuelve quien encola, p. ej. abrir_tramite); si no, ALLIANZ_DEST.
        destino = pay.get("destinatario") or config.ALLIANZ_DEST
        if not destino:
            repo.actualizar_accion(aid, "bloqueada",
                                   {"motivo": "falta ALLIANZ_DEST (Directorio Allianz sin confirmar)"})
            return "bloqueada"

        # Responder EN EL MISMO HILO del ticket (Fase B): mantenemos el asunto del hilo y
        # encadenamos con el último Message-ID; si es un ticket nuevo, sale sin hilo.
        asunto = ticket.get("asunto_hilo") or _asunto_allianz(ticket)
        # Cuerpo: si el ORQUESTADOR (LLM) ya lo redactó (asertivo), lo usamos; si no, plantilla.
        # Lo que Ceci editó en el panel tiene prioridad sobre el borrador original.
        cuerpo = accion.get("borrador_editado") or pay.get("cuerpo") or _cuerpo_allianz(ticket, pay)
        # Guardarraíl 2 crítico (Fase E): si es delicado/crítico y Ceci no lo autorizó, se
        # compone el borrador pero NO se manda: espera el visto bueno de Ceci.
        cc = [c for c in (pay.get("cc") or []) if c] or None
        hold = _guardar_si_critico(repo, accion, ticket, pay,
                                   {"destino": destino, "asunto": asunto, "cuerpo": cuerpo,
                                    "canal": "email", "cc": cc})
        if hold:
            return hold
        with _archivos(pay.get("adjuntos")) as adjuntos:
            res = emisor.enviar([destino], asunto, cuerpo, cc=cc, adjuntos=adjuntos or None,
                                hilo_id=ticket.get("gmail_thread_id"),
                                in_reply_to=ticket.get("ultimo_message_id"))
        if res.get("simulado"):
            repo.actualizar_accion(aid, "simulada", res)
            return "simulada"
        if res.get("ok"):
            repo.actualizar_accion(aid, "enviada", res)
            return "enviada"
        repo.actualizar_accion(aid, "fallida", res)
        return "fallida"

    # Canal desconocido: lo marcamos para no reprocesarlo en loop.
    repo.actualizar_accion(aid, "omitida", {"motivo": f"canal no soportado: {canal}", "tipo_accion": tipo})
    return "omitida"


# Los jobs del worker (intake, Telegram, recordatorios…) corren en hilos y todos despachan: sin
# esto, dos a la vez leían la misma acción 'sugerida' y el mensaje salía dos veces.
_UNO_A_LA_VEZ = threading.Lock()


def despachar_pendientes(repo: Repositorio, emisor: Optional[Emisor] = None,
                         ahora: Optional[datetime] = None, limite: int = 500) -> dict:
    """Procesa todas las acciones en estado 'sugerida'. Devuelve el conteo por resultado."""
    with _UNO_A_LA_VEZ:
        return _despachar_pendientes(repo, emisor, ahora, limite)


def _despachar_pendientes(repo: Repositorio, emisor: Optional[Emisor], ahora: Optional[datetime],
                          limite: int) -> dict:
    emisor = emisor or emisor_desde_config()
    ahora = ahora or _ahora()
    conteo: dict[str, int] = {}
    detalle: list[dict] = []
    for accion in repo.listar_acciones(estado="sugerida")[:limite]:
        try:
            r = _despachar_una(repo, accion, emisor, ahora)
        except Exception as ex:  # noqa: BLE001 — una acción rota no frena al resto de la cola
            log.exception("despacho: falló la acción %s", accion.get("id"))
            repo.actualizar_accion(accion["id"], "fallida", {"error": f"{type(ex).__name__}: {ex}"[:300]})
            r = "fallida"
        conteo[r] = conteo.get(r, 0) + 1
        detalle.append({"accion_id": accion["id"], "ticket_id": accion.get("ticket_id"),
                        "tipo_accion": accion.get("tipo_accion"), "canal": accion.get("canal"),
                        "resultado": r})
    return {"modo": emisor.modo, "conteo": conteo, "detalle": detalle}
