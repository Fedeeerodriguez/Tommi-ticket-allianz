"""Etapa 2 — Telegram: Ceci aprueba la guía de aportación con un botón.

Bot API por HTTPS (urllib, sin librerías nuevas) y por POLLING desde el worker (getUpdates cada
pocos segundos): no hace falta exponer un webhook público.

  - Cada guía pendiente → un mensaje a Ceci con [✅ Aprobar] [🗑 Descartar].
  - Ceci RESPONDE al mensaje con "Monto: …" y/o "Datos: …" → versión nueva con botones nuevos
    (los viejos dejan de servir: se aprueba exactamente lo que se ve). La guía sale por una
    plantilla de WhatsApp: solo se completan esos dos campos, no se reescribe el texto.
  - Solo se acepta el chat de Ceci (TELEGRAM_CECI_CHAT_ID). Cualquier otro se ignora; a "/start"
    se le contesta su chat id (para configurarlo la primera vez).
  - Lo que hace cada botón lo decide app/acciones/aprobaciones.py (lo mismo que el panel).

El offset de getUpdates se guarda en la tabla `valores` → tras un reinicio no se repite nada.
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


def _http(metodo: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{metodo}",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read().decode())
    if not resp.get("ok"):
        raise RuntimeError(f"Telegram {metodo}: {resp.get('description')}")
    return resp.get("result")


def _chat_ceci() -> str:
    return str(config.TELEGRAM_CECI_CHAT_ID).strip()


def _botones(ap: dict) -> dict:
    v = f"{ap['id']}:{ap.get('version') or 1}"
    return {"inline_keyboard": [[{"text": "✅ Aprobar", "callback_data": f"ap:{v}"},
                                 {"text": "🗑 Descartar", "callback_data": f"de:{v}"}]]}


def texto_mensaje(ap: dict, ticket: dict) -> str:
    ctx = mensajes_etapa.contexto(ticket, {})
    cab = f"Guía de aportación · Ticket {ctx['tk']} · {ctx['cliente']}{ctx['con_producto']}"
    if int(ap.get("version") or 1) > 1:
        cab += f" (versión {ap['version']})"
    datos = ap.get("datos") or {}
    faltan = mensajes_etapa.faltan_en_guia(datos)
    como = como_responder(datos)
    if faltan:
        pie = f"⚠️ Falta completar {' y '.join(faltan)}. Responde a este mensaje así:\n{como}"
    elif "solicitud" in mensajes_etapa.campos_guia(datos):
        pie = (f"Revisa que el monto ({datos.get('monto')}) y el número de solicitud ({datos.get('solicitud')}) sean "
               f"correctos: el número es la referencia del pago. Si están bien, aprueba. Para corregirlos, responde a "
               f"este mensaje así:\n{como}")
    else:
        pie = f"Para corregirla, responde a este mensaje así (puede ser una sola línea):\n{como}"
    sin = mensajes_etapa.faltan_del_ticket(datos)
    if sin:
        pie = f"⚠️ Al ticket le falta {' y '.join(sin)}: así no se puede aprobar.\n{pie}"
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


def enviar_aprobacion(repo: Repositorio, ap: dict, transporte: Optional[Transporte] = None) -> Optional[str]:
    """Manda la guía a Ceci con los botones y guarda el id del mensaje."""
    enviar = transporte or _http
    ticket = repo.obtener_ticket(ap["ticket_id"]) or {}
    msg = enviar("sendMessage", {"chat_id": _chat_ceci(), "text": texto_mensaje(ap, ticket),
                                 "reply_markup": _botones(ap)})
    mid = str((msg or {}).get("message_id") or "")
    repo.actualizar_aprobacion(ap["id"], telegram_chat_id=_chat_ceci(), telegram_msg_id=mid)
    return mid


def enviar_pendientes(repo: Repositorio, transporte: Optional[Transporte] = None) -> int:
    """Las guías pendientes que todavía no se le mandaron a Ceci."""
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


def cerrar_mensaje(ap: dict, leyenda: str, transporte: Optional[Transporte] = None) -> None:
    """Saca los botones del mensaje y le agrega cómo terminó (aprobada / descartada / reemplazada)."""
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


def _quien(usuario: dict) -> str:
    return "telegram:" + (usuario.get("username") or usuario.get("first_name") or str(usuario.get("id", "?")))


def _boton(repo: Repositorio, cq: dict, enviar: Transporte) -> dict:
    accion, _, resto = (cq.get("data") or "").partition(":")
    aid, _, version = resto.partition(":")
    ap = repo.obtener_aprobacion(int(aid)) if aid.isdigit() else None
    if not ap:
        res = {"ok": False, "motivo": "No encontré esa guía."}
    elif str(ap.get("version") or 1) != version:
        res = {"ok": False, "motivo": "Hay una versión más nueva de esta guía: usa los botones del último mensaje."}
    elif accion == "ap":
        res = aprobaciones.aprobar(repo, ap["id"], _quien(cq.get("from") or {}))
    elif accion == "de":
        res = aprobaciones.descartar(repo, ap["id"], _quien(cq.get("from") or {}))
    else:
        res = {"ok": False, "motivo": "Botón desconocido."}
    enviar("answerCallbackQuery", {"callback_query_id": cq["id"], "text": res["motivo"][:190],
                                   "show_alert": not res["ok"]})
    if res["ok"] and ap:
        leyenda = ("✅ Aprobada: ya salió al cliente y al asesor." if accion == "ap"
                   else "🗑 Descartada: no se mandó nada.")
        cerrar_mensaje(ap, leyenda, enviar)
    elif ap and res.get("version", 0) > int(ap.get("version") or 1):  # se completó con datos del ticket
        cerrar_mensaje(ap, f"✏️ Reemplazada por la versión {res['version']} (abajo).", enviar)
        enviar_aprobacion(repo, repo.obtener_aprobacion(ap["id"]), enviar)
    return res


def _respuesta(repo: Repositorio, msg: dict, enviar: Transporte) -> Optional[dict]:
    """Ceci responde al mensaje de una guía con sus campos ('Solicitud: …', o 'Monto: …' / 'Datos: …')
    → versión nueva."""
    original = str((msg.get("reply_to_message") or {}).get("message_id") or "")
    ap = next((a for a in aprobaciones.pendientes(repo) if str(a.get("telegram_msg_id")) == original), None)
    if not ap:
        enviar("sendMessage", {"chat_id": _chat_ceci(), "reply_to_message_id": msg["message_id"],
                               "text": "No encontré una guía pendiente en ese mensaje (¿ya estaba aprobada?)."})
        return None
    campos = leer_campos(msg.get("text") or "")
    if not campos:
        enviar("sendMessage", {"chat_id": _chat_ceci(), "reply_to_message_id": msg["message_id"],
                               "text": "No entendí qué cambiar. Responde así:\n" + como_responder(ap.get("datos") or {})})
        return None
    res = aprobaciones.corregir(repo, ap["id"], _quien(msg.get("from") or {}), **campos)
    if res["ok"] and res.get("version", 0) > int(ap.get("version") or 1):
        cerrar_mensaje(ap, f"✏️ Reemplazada por la versión {res['version']} (abajo).", enviar)
        enviar_aprobacion(repo, repo.obtener_aprobacion(ap["id"]), enviar)
    return res


def procesar_updates(repo: Repositorio, transporte: Optional[Transporte] = None) -> dict:
    """Lee lo nuevo (botones y respuestas de Ceci) y lo aplica. Devuelve qué hizo."""
    enviar = transporte or _http
    offset = int(repo.leer_valor(_OFFSET) or 0)
    updates = enviar("getUpdates", {"offset": offset + 1 if offset else 0, "timeout": 0,
                                    "allowed_updates": ["callback_query", "message"]}) or []
    res: dict = {"botones": [], "correcciones": [], "ignorados": 0, "plan": []}
    for u in updates:
        try:
            cq, msg = u.get("callback_query"), u.get("message")
            chat = str(((cq or {}).get("message") or msg or {}).get("chat", {}).get("id", ""))
            if msg and (msg.get("text") or "").strip().startswith("/start"):
                enviar("sendMessage", {"chat_id": chat, "text": f"Hola. Tu chat id es {chat}."})
            elif chat != _chat_ceci():
                res["ignorados"] += 1  # solo Ceci aprueba
            elif cq:
                r = _boton(repo, cq, enviar)
                res["botones"].append(r)
                res["plan"] += r.get("plan", [])
            elif msg and msg.get("reply_to_message"):
                r = _respuesta(repo, msg, enviar)
                if r:
                    res["correcciones"].append(r)
        except Exception:  # noqa: BLE001
            log.exception("telegram: falló el update %s", u.get("update_id"))
        finally:
            repo.guardar_valor(_OFFSET, str(u["update_id"]))
    return res
