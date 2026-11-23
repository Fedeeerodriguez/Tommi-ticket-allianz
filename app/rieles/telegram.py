"""Telegram: Ceci (y Jime, que la reemplaza) autoriza o modifica lo que Tommy necesita que apruebe.

Bot API por HTTPS (urllib, sin librerías nuevas) y por POLLING desde el worker (getUpdates cada
pocos segundos): no hace falta exponer un webhook público.

Qué le llega (cada cosa una sola vez, a todos los chats de TELEGRAM_CECI_CHAT_ID):
  - la guía de aportación del proceso corto (tabla `aprobaciones`);
  - los correos retenidos para su visto bueno (acciones `pendiente_ceci`): la escalación a Allianz con copia a
    la ejecutiva y a Penny, los trámites que se abren con la solicitud firmada, las instrucciones al cliente…

Cada mensaje trae dos botones (Ceci, 17/11):
  - ✅ Autorizar → sale tal cual.
  - ✏️ Modificar → el bot le pide el texto corregido, listo para enviar; el próximo mensaje que mande en ese
    chat (o la respuesta a ese mensaje) es lo que sale. En la guía también se pueden mandar solo los datos
    ("Monto: … / Solicitud: …"): sale una versión nueva para autorizar.
Solo se aceptan los chats configurados; a "/start" se le contesta su chat id (para configurarlo).
Lo que hace cada botón con la guía lo decide app/acciones/aprobaciones.py (lo mismo que el panel).

El offset de getUpdates, los mensajes enviados y lo que espera corrección se guardan en `valores`.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from typing import Callable, Optional

from app import config
from app.acciones import aprobaciones, mensajes_etapa
from app.db import Repositorio

log = logging.getLogger(__name__)

Transporte = Callable[[str, dict], dict]  # (método, payload) → respuesta "result" de la Bot API
_OFFSET = "telegram_offset"
PIDE_TEXTO = ("✏️ Mándame el texto corregido, listo para enviar, en un solo mensaje. Sale exactamente lo que "
              "escribas.")


def _http(metodo: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{metodo}",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read().decode())
    if not resp.get("ok"):
        raise RuntimeError(f"Telegram {metodo}: {resp.get('description')}")
    return resp.get("result")


def _chats() -> list[str]:
    return config.telegram_chats()


def _chat_ceci() -> str:
    chats = _chats()
    return chats[0] if chats else ""


# ─────────────────────────── qué mensaje es qué ───────────────────────────
def _guardar_msgs(repo: Repositorio, clave: str, enviados: list[tuple[str, str]]) -> None:
    repo.guardar_valor(f"tg_msgs:{clave}", json.dumps(enviados))
    for chat, mid in enviados:
        repo.guardar_valor(f"tg_msg:{chat}:{mid}", clave)


def _msgs(repo: Repositorio, clave: str, ap: Optional[dict] = None) -> list[tuple[str, str]]:
    v = repo.leer_valor(f"tg_msgs:{clave}")
    if v:
        return [tuple(x) for x in json.loads(v)]
    if ap and ap.get("telegram_msg_id"):  # guías mandadas antes de que hubiera varios chats
        return [(ap.get("telegram_chat_id") or _chat_ceci(), ap["telegram_msg_id"])]
    return []


def _clave_de_mensaje(repo: Repositorio, chat: str, mid) -> Optional[str]:
    clave = repo.leer_valor(f"tg_msg:{chat}:{mid}")
    if clave:
        return clave
    ap = next((a for a in aprobaciones.pendientes(repo) if str(a.get("telegram_msg_id")) == str(mid)), None)
    return f"ap:{ap['id']}" if ap else None


def _enviar_a_todos(repo: Repositorio, clave: str, texto: str, botones: dict, enviar: Transporte) -> list:
    enviados = []
    for chat in _chats():
        msg = enviar("sendMessage", {"chat_id": chat, "text": texto[:4000], "reply_markup": botones})
        enviados.append((chat, str((msg or {}).get("message_id") or "")))
    _guardar_msgs(repo, clave, enviados)
    return enviados


def cerrar(repo: Repositorio, clave: str, leyenda: str, transporte: Optional[Transporte] = None,
           ap: Optional[dict] = None) -> None:
    """Saca los botones de todos los chats y agrega cómo terminó (autorizada / descartada / reemplazada)."""
    enviar = transporte or _http
    for chat, mid in _msgs(repo, clave, ap):
        try:
            enviar("editMessageReplyMarkup", {"chat_id": chat, "message_id": int(mid),
                                              "reply_markup": {"inline_keyboard": []}})
            enviar("sendMessage", {"chat_id": chat, "text": leyenda, "reply_to_message_id": int(mid)})
        except Exception:  # noqa: BLE001
            log.exception("telegram: no pude cerrar el mensaje %s en %s", clave, chat)


def cerrar_mensaje(ap: dict, leyenda: str, transporte: Optional[Transporte] = None, repo=None) -> None:
    """Compatibilidad: cerrar el mensaje de una guía."""
    if repo is None:
        if not ap.get("telegram_msg_id"):
            return
        enviar = transporte or _http
        try:
            enviar("editMessageReplyMarkup", {"chat_id": ap.get("telegram_chat_id") or _chat_ceci(),
                                              "message_id": int(ap["telegram_msg_id"]),
                                              "reply_markup": {"inline_keyboard": []}})
            enviar("sendMessage", {"chat_id": ap.get("telegram_chat_id") or _chat_ceci(), "text": leyenda,
                                   "reply_to_message_id": int(ap["telegram_msg_id"])})
        except Exception:  # noqa: BLE001
            log.exception("telegram: no pude cerrar el mensaje de la guía %s", ap.get("id"))
        return
    cerrar(repo, f"ap:{ap['id']}", leyenda, transporte, ap)


# ─────────────────────────── guía de aportación ───────────────────────────
def _botones(ap: dict) -> dict:
    v = f"{ap['id']}:{ap.get('version') or 1}"
    return {"inline_keyboard": [[{"text": "✅ Autorizar", "callback_data": f"ap:{v}"},
                                 {"text": "✏️ Modificar", "callback_data": f"mo:{v}"}]]}


def texto_mensaje(ap: dict, ticket: dict) -> str:
    ctx = mensajes_etapa.contexto(ticket, {})
    cab = f"Guía de aportación · Ticket {ctx['tk']} · {ctx['cliente']}{ctx['con_producto']}"
    if int(ap.get("version") or 1) > 1:
        cab += f" (versión {ap['version']})"
    datos = ap.get("datos") or {}
    faltan = mensajes_etapa.faltan_en_guia(datos)
    como = como_responder(datos)
    if faltan:
        pie = (f"⚠️ Falta completar {' y '.join(faltan)}. Toca Modificar y mándame los datos así:\n{como}\n"
               f"o el texto completo corregido.")
    elif "solicitud" in mensajes_etapa.campos_guia(datos):
        pie = (f"Revisa que el monto ({datos.get('monto')}) y el número de solicitud ({datos.get('solicitud')}) sean "
               f"correctos: el número es la referencia del pago. Si está bien, toca Autorizar. Para cambiarla, toca "
               f"Modificar y mándame el texto corregido, o solo los datos así:\n{como}")
    else:
        pie = (f"Si está bien, toca Autorizar. Para cambiarla, toca Modificar y mándame el texto corregido, o solo "
               f"los datos así:\n{como}")
    sin = mensajes_etapa.faltan_del_ticket(datos)
    if sin:
        pie = f"⚠️ Al ticket le falta {' y '.join(sin)}: así no se puede autorizar.\n{pie}"
    return f"{cab}\n\n{ap['texto']}\n\n{pie}"


def como_responder(datos: dict) -> str:
    if "solicitud" in mensajes_etapa.campos_guia(datos):
        # El número del ejemplo es el de ESTA guía: tiene que coincidir con el de arriba (Ceci, 29/10).
        sol = str((datos or {}).get("solicitud") or "").strip() or "25290001"
        return f"Monto: $50,000 MXN\nSolicitud: {sol}"
    if "datos_deposito" not in mensajes_etapa.campos_guia(datos):
        return "Monto: $50,000 MXN"
    return "Monto: $50,000 MXN\nDatos: CLABE 012345678901234567 a nombre de …"


_RE_CAMPO = re.compile(r"\b(monto|importe|datos(?:\s+para\s+depositar)?|dep[oó]sito|"
                       r"(?:n[uú]mero\s+de\s+|no\.?\s*(?:de\s+)?)?solicitud)\s*[:=]", re.I)


def leer_campos(texto: str) -> dict:
    """'Monto: $50,000\nDatos: CLABE 0123' (o todo en una línea) →
    {'monto': '$50,000', 'datos_deposito': 'CLABE 0123'}."""
    out = {}
    marcas = list(_RE_CAMPO.finditer(texto or ""))
    for i, m in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        valor = " ".join(texto[m.end():fin].split()).strip(" ,;·-")
        tipo = m.group(1).lower()
        clave = ("monto" if tipo in ("monto", "importe") else "solicitud" if "solicitud" in tipo
                 else "datos_deposito")
        if valor:
            out[clave] = valor
    return out


def _solo_campos(texto: str) -> bool:
    """¿El mensaje son solo datos ("Monto: …", "Solicitud: …") y no un texto completo para el cliente?"""
    if not leer_campos(texto):
        return False
    resto = _RE_CAMPO.sub("", texto)
    return len(resto.split()) <= 12 * max(1, len(leer_campos(texto)))


def enviar_aprobacion(repo: Repositorio, ap: dict, transporte: Optional[Transporte] = None) -> Optional[str]:
    """Manda la guía a los chats con los botones y guarda los mensajes."""
    enviar = transporte or _http
    ticket = repo.obtener_ticket(ap["ticket_id"]) or {}
    enviados = _enviar_a_todos(repo, f"ap:{ap['id']}", texto_mensaje(ap, ticket), _botones(ap), enviar)
    mid = enviados[0][1] if enviados else ""
    repo.actualizar_aprobacion(ap["id"], telegram_chat_id=_chat_ceci(), telegram_msg_id=mid)
    return mid


def enviar_pendientes(repo: Repositorio, transporte: Optional[Transporte] = None) -> int:
    """Las guías pendientes que todavía no se mandaron."""
    n = 0
    for ap in aprobaciones.pendientes(repo):
        if ap.get("telegram_msg_id"):
            continue
        try:
            enviar_aprobacion(repo, ap, transporte)
            n += 1
        except Exception:  # noqa: BLE001
            log.exception("telegram: no pude mandar la guía %s", ap["id"])
    return n


# ─────────────────────────── correos retenidos (acciones pendiente_ceci) ───────────────────────────
def _payload(a: dict) -> dict:
    p = a.get("payload")
    return json.loads(p) if isinstance(p, str) else (p or {})


def _botones_accion(accion_id: int) -> dict:
    return {"inline_keyboard": [[{"text": "✅ Autorizar", "callback_data": f"aa:{accion_id}"},
                                 {"text": "✏️ Modificar", "callback_data": f"am:{accion_id}"}]]}


def texto_accion(a: dict, ticket: dict) -> str:
    p = _payload(a)
    ctx = mensajes_etapa.contexto(ticket, {})
    cuerpo = a.get("borrador_editado") or p.get("cuerpo") or p.get("mensaje") or ""
    if (a.get("canal") or "").lower() == "wati":
        cab = f"WhatsApp para {p.get('rol') or 'el cliente'} · Ticket {ctx['tk']} · {ctx['cliente']}"
        meta = []
    else:
        cab = f"✉️ {p.get('titulo') or 'Correo para Allianz'} · Ticket {ctx['tk']} · {ctx['cliente']}"
        meta = [f"Para: {p.get('destinatario') or 'el hilo del ticket en Allianz'}"]
        if p.get("cc"):
            meta.append(f"Copia: {', '.join(p['cc'])}")
        if p.get("asunto"):
            meta.append(f"Asunto: {p['asunto']}")
        if p.get("adjuntos"):
            meta.append(f"Adjuntos: {', '.join(x.get('nombre', '?') for x in p['adjuntos'])}")
    pie = "Si está bien, toca Autorizar y sale tal cual. Para cambiarlo, toca Modificar y mándame el texto corregido."
    return "\n".join([cab, *meta, "", cuerpo, "", pie])


def enviar_acciones(repo: Repositorio, transporte: Optional[Transporte] = None) -> int:
    """Los correos retenidos para Ceci que todavía no se mandaron por Telegram."""
    enviar = transporte or _http
    n = 0
    for a in repo.listar_acciones(estado="pendiente_ceci"):
        if repo.leer_valor(f"tg_msgs:ac:{a['id']}"):
            continue
        try:
            _enviar_a_todos(repo, f"ac:{a['id']}", texto_accion(a, repo.obtener_ticket(a["ticket_id"]) or {}),
                            _botones_accion(a["id"]), enviar)
            n += 1
        except Exception:  # noqa: BLE001
            log.exception("telegram: no pude mandar la acción %s", a["id"])
    return n


def _accion_pendiente(repo: Repositorio, accion_id: int) -> Optional[dict]:
    return next((x for x in repo.listar_acciones(estado="pendiente_ceci") if x["id"] == accion_id), None)


def autorizar_accion(repo: Repositorio, accion_id: int, por: str, texto: Optional[str] = None) -> dict:
    """Libera la acción para el próximo despacho; con `texto`, sale ese texto en vez del borrador."""
    a = _accion_pendiente(repo, accion_id)
    if not a:
        return {"ok": False, "motivo": "Eso ya no está esperando aprobación.", "plan": []}
    if texto:
        repo.set_borrador(accion_id, texto.strip())
    repo.actualizar_accion(accion_id, "sugerida", {"aprobado_por": por, "modificado": bool(texto)})
    repo.agregar_evento(a["ticket_id"], None, "visto_bueno",
                        f"{'Modificado y autorizado' if texto else 'Autorizado'} por {por}"[:200])
    return {"ok": True, "motivo": "Autorizado: sale en el próximo ciclo.", "plan": [{"accion_id": accion_id}]}


# ─────────────────────────── botones y respuestas ───────────────────────────
def _quien(usuario: dict) -> str:
    return "telegram:" + (usuario.get("username") or usuario.get("first_name") or str(usuario.get("id", "?")))


def _esperar_texto(repo: Repositorio, chat: str, clave: str, enviar: Transporte, mid=None) -> None:
    repo.guardar_valor(f"tg_modificar:{chat}", clave)
    payload = {"chat_id": chat, "text": PIDE_TEXTO}
    if mid:
        payload["reply_to_message_id"] = int(mid)
    enviar("sendMessage", payload)


def _boton(repo: Repositorio, cq: dict, enviar: Transporte, chat: str) -> dict:
    accion, _, resto = (cq.get("data") or "").partition(":")
    mid = (cq.get("message") or {}).get("message_id")
    por = _quien(cq.get("from") or {})
    if accion in ("aa", "am"):
        res = _boton_accion(repo, accion, resto, por, chat, mid, enviar)
        enviar("answerCallbackQuery", {"callback_query_id": cq["id"], "text": res["motivo"][:190],
                                       "show_alert": not res["ok"]})
        return res
    aid, _, version = resto.partition(":")
    ap = repo.obtener_aprobacion(int(aid)) if aid.isdigit() else None
    if not ap:
        res = {"ok": False, "motivo": "No encontré esa guía.", "plan": []}
    elif str(ap.get("version") or 1) != version:
        res = {"ok": False, "motivo": "Hay una versión más nueva de esta guía: usa los botones del último mensaje.",
               "plan": []}
    elif accion == "ap":
        res = aprobaciones.aprobar(repo, ap["id"], por)
    elif accion == "mo":
        if ap.get("estado") != "pendiente":
            res = {"ok": False, "motivo": f"Esa guía ya estaba {ap.get('estado')}.", "plan": []}
        else:
            _esperar_texto(repo, chat, f"ap:{ap['id']}:{version}", enviar, mid)
            res = {"ok": True, "motivo": "Mándame el texto corregido.", "plan": [], "esperando": True}
    elif accion == "de":  # botón de los mensajes viejos
        res = aprobaciones.descartar(repo, ap["id"], por)
    else:
        res = {"ok": False, "motivo": "Botón desconocido.", "plan": []}
    enviar("answerCallbackQuery", {"callback_query_id": cq["id"], "text": res["motivo"][:190],
                                   "show_alert": not res["ok"]})
    if res["ok"] and ap and accion in ("ap", "de"):
        leyenda = ("✅ Autorizada: ya salió al cliente y al asesor." if accion == "ap"
                   else "🗑 Descartada: no se mandó nada.")
        cerrar(repo, f"ap:{ap['id']}", leyenda, enviar, ap)
    elif ap and res.get("version", 0) > int(ap.get("version") or 1):  # se completó con datos del ticket
        cerrar(repo, f"ap:{ap['id']}", f"✏️ Reemplazada por la versión {res['version']} (abajo).", enviar, ap)
        enviar_aprobacion(repo, repo.obtener_aprobacion(ap["id"]), enviar)
    return res


def _boton_accion(repo: Repositorio, accion: str, resto: str, por: str, chat: str, mid, enviar: Transporte) -> dict:
    if not resto.isdigit():
        return {"ok": False, "motivo": "Botón desconocido.", "plan": []}
    accion_id = int(resto)
    if accion == "am":
        if not _accion_pendiente(repo, accion_id):
            return {"ok": False, "motivo": "Eso ya no está esperando aprobación.", "plan": []}
        _esperar_texto(repo, chat, f"ac:{accion_id}", enviar, mid)
        return {"ok": True, "motivo": "Mándame el texto corregido.", "plan": [], "esperando": True}
    res = autorizar_accion(repo, accion_id, por)
    if res["ok"]:
        cerrar(repo, f"ac:{accion_id}", "✅ Autorizado: sale en unos minutos.", enviar)
    return res


def _aplicar_texto(repo: Repositorio, clave: str, msg: dict, enviar: Transporte, chat: str,
                   libre: bool = True) -> Optional[dict]:
    """El texto que mandó Ceci para algo que estaba esperando corrección (guía o correo retenido).
    `libre`: si apretó Modificar, el texto sale tal cual; si solo respondió al mensaje, se aceptan solo los datos
    de la guía (así un "ok" respondido no le llega al cliente)."""
    texto = (msg.get("text") or "").strip()
    por = _quien(msg.get("from") or {})
    tipo, _, resto = clave.partition(":")
    if not libre and not (tipo == "ap" and leer_campos(texto)):
        ap = repo.obtener_aprobacion(int(resto.split(":")[0])) if tipo == "ap" else None
        como = f"o mándame solo los datos así:\n{como_responder(ap.get('datos') or {})}" if ap else ""
        enviar("sendMessage", {"chat_id": chat, "reply_to_message_id": msg["message_id"],
                               "text": f"No entendí qué cambiar. Para mandar otro texto, toca Modificar primero, {como}"})
        return None
    if tipo == "ac":
        accion_id = int(resto.split(":")[0])
        res = autorizar_accion(repo, accion_id, por, texto)
        if res["ok"]:
            cerrar(repo, f"ac:{accion_id}", "✏️ Modificado y autorizado: sale con tu texto en unos minutos.", enviar)
        else:
            enviar("sendMessage", {"chat_id": chat, "reply_to_message_id": msg["message_id"], "text": res["motivo"]})
        return res
    ap = repo.obtener_aprobacion(int(resto.split(":")[0]))
    if not ap or ap.get("estado") != "pendiente":
        enviar("sendMessage", {"chat_id": chat, "reply_to_message_id": msg["message_id"],
                               "text": "Esa guía ya no está pendiente (¿ya estaba autorizada?)."})
        return None
    if _solo_campos(texto):   # solo los datos → versión nueva para autorizar
        res = aprobaciones.corregir(repo, ap["id"], por, **leer_campos(texto))
        if res["ok"] and res.get("version", 0) > int(ap.get("version") or 1):
            cerrar(repo, f"ap:{ap['id']}", f"✏️ Reemplazada por la versión {res['version']} (abajo).", enviar, ap)
            enviar_aprobacion(repo, repo.obtener_aprobacion(ap["id"]), enviar)
        elif not res["ok"]:
            enviar("sendMessage", {"chat_id": chat, "reply_to_message_id": msg["message_id"], "text": res["motivo"]})
        return res
    res = aprobaciones.aprobar(repo, ap["id"], por, texto_libre=texto)   # el texto completo de Ceci
    if res["ok"]:
        cerrar(repo, f"ap:{ap['id']}", "✏️ Modificada y autorizada: le salió tu texto al cliente.", enviar, ap)
    else:
        enviar("sendMessage", {"chat_id": chat, "reply_to_message_id": msg["message_id"], "text": res["motivo"]})
    return res


def _mensaje(repo: Repositorio, msg: dict, enviar: Transporte, chat: str) -> Optional[dict]:
    """Texto de Ceci: respuesta a un mensaje del bot, o lo que pidió Modificar."""
    clave = None
    if msg.get("reply_to_message"):
        clave = _clave_de_mensaje(repo, chat, msg["reply_to_message"].get("message_id"))
    pendiente = repo.leer_valor(f"tg_modificar:{chat}")
    if not clave and pendiente:
        clave = pendiente
    if not clave:
        enviar("sendMessage", {"chat_id": chat, "reply_to_message_id": msg["message_id"],
                               "text": "Para cambiar algo, toca Modificar en el mensaje y después mándame el texto."})
        return None
    libre = bool(pendiente) and clave.split(":")[:2] == pendiente.split(":")[:2]
    if libre:
        repo.guardar_valor(f"tg_modificar:{chat}", "")
    return _aplicar_texto(repo, clave, msg, enviar, chat, libre=libre)


def procesar_updates(repo: Repositorio, transporte: Optional[Transporte] = None) -> dict:
    """Lee lo nuevo (botones y textos de Ceci/Jime) y lo aplica. Devuelve qué hizo."""
    enviar = transporte or _http
    offset = int(repo.leer_valor(_OFFSET) or 0)
    updates = enviar("getUpdates", {"offset": offset + 1 if offset else 0, "timeout": 0,
                                    "allowed_updates": ["callback_query", "message"]}) or []
    res: dict = {"botones": [], "correcciones": [], "ignorados": 0, "plan": []}
    for u in updates:
        try:
            cq, msg = u.get("callback_query"), u.get("message")
            chat = str(((cq or {}).get("message") or msg or {}).get("chat", {}).get("id", ""))
            # "/start" (como sea que lo escriba) o cualquier mensaje de un chat que todavía no está cargado:
            # se contesta el chat id, para que configurarlo no dependa de escribir exacto "/start".
            if msg and ((msg.get("text") or "").strip().lower().startswith(("/start", "start"))
                        or chat not in _chats()):
                enviar("sendMessage", {"chat_id": chat, "text": f"Hola. Tu chat id es {chat}."})
                if chat not in _chats():
                    res["ignorados"] += 1  # se le contesta el id, pero no aprueba ni corrige nada
                nombre =((msg.get("from") or {}).get("first_name") or "").strip()
                log.info("telegram: mensaje de %s · chat id %s%s", nombre or "?", chat,
                         "" if chat in _chats() else " (todavía no está en TELEGRAM_CECI_CHAT_ID)")
            elif chat not in _chats():
                res["ignorados"] += 1  # solo Ceci y Jime aprueban
            elif cq:
                r = _boton(repo, cq, enviar, chat)
                res["botones"].append(r)
                res["plan"] += r.get("plan", [])
            elif msg and (msg.get("text") or "").strip():
                r = _mensaje(repo, msg, enviar, chat)
                if r:
                    res["correcciones"].append(r)
                    res["plan"] += r.get("plan", [])
        except Exception:  # noqa: BLE001
            log.exception("telegram: falló el update %s", u.get("update_id"))
        finally:
            repo.guardar_valor(_OFFSET, str(u["update_id"]))
    return res
