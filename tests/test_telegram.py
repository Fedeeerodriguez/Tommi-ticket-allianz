"""Etapa 2 — Telegram: Ceci aprueba, descarta o corrige la guía de aportación (Bot API falsa)."""
import pytest

from app import config
from app.rieles import telegram

from test_motor_etapa2 import C2_CORTO, C2_PLU3, aislado, correr, repo  # noqa: F401  (fixtures)

CECI = "777"


class BotFalso:
    """Registra lo que se le pide a la Bot API y devuelve los updates que le cargamos."""

    def __init__(self):
        self.llamadas, self.updates, self._mid = [], [], 100

    def __call__(self, metodo, payload):
        self.llamadas.append((metodo, payload))
        if metodo == "getUpdates":
            ups, self.updates = [u for u in self.updates if u["update_id"] >= payload["offset"]], []
            return ups
        if metodo == "sendMessage":
            self._mid += 1
            return {"message_id": self._mid}
        return True

    def de(self, metodo):
        return [p for m, p in self.llamadas if m == metodo]


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_APROBACIONES", True)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setattr(config, "TELEGRAM_CECI_CHAT_ID", CECI)
    return BotFalso()


def boton(uid, data, chat=CECI, mid=101):
    return {"update_id": uid, "callback_query": {"id": f"cq{uid}", "data": data, "from": {"username": "ceci"},
                                                 "message": {"message_id": mid, "chat": {"id": int(chat)}}}}


def respuesta(uid, texto, a_mid=101, chat=CECI):
    return {"update_id": uid, "message": {"message_id": 500 + uid, "text": texto, "from": {"username": "ceci"},
                                          "chat": {"id": int(chat)}, "reply_to_message": {"message_id": a_mid}}}


def preparar(repo, bot, c2=C2_CORTO, nro="2567479"):
    tk = repo.crear_ticket({"nro_ticket": nro, "estado": "abierto"})
    correr(repo, tk, c2, 1)
    assert telegram.enviar_pendientes(repo, bot) == 1
    return tk, repo.listar_aprobaciones(tk)[0]


def test_la_guia_le_llega_a_ceci_con_botones(repo, bot):
    tk, ap = preparar(repo, bot)
    msg = bot.de("sendMessage")[0]
    assert msg["chat_id"] == CECI
    assert msg["text"].startswith("Guía de aportación · Ticket 2567479 · Guillermo Prueba Castro · Elite")
    # Elite: el n° de solicitud ya viene; falta el monto (Ceci lo completa respondiendo).
    assert "⚠️ Falta completar monto. Responde a este mensaje así:\nMonto: $50,000 MXN\nSolicitud: 25290001" in msg["text"]
    botones = msg["reply_markup"]["inline_keyboard"][0]
    assert [b["callback_data"] for b in botones] == [f"ap:{ap['id']}:1", f"de:{ap['id']}:1"]
    assert ap["telegram_msg_id"] == "101"
    assert telegram.enviar_pendientes(repo, bot) == 0  # no se manda dos veces


def test_elite_corrige_la_solicitud_y_aprueba(repo, bot):
    tk, ap = preparar(repo, bot)
    bot.updates = [respuesta(6, "Monto: $50,000 MXN\nSolicitud: 25287682")]
    assert telegram.procesar_updates(repo, bot)["correcciones"][0]["version"] == 2
    nuevo = bot.de("sendMessage")[-1]["text"]
    assert "Revisa que el monto ($50,000 MXN) y el número de solicitud (25287682) sean correctos" in nuevo
    bot.updates = [boton(8, f"ap:{ap['id']}:2", mid=int(repo.obtener_aprobacion(ap["id"])["telegram_msg_id"]))]
    r = telegram.procesar_updates(repo, bot)
    cli = next(a for a in r["plan"] if a["rol"] == "cliente")
    assert "Haz el pago por $50,000 MXN" in cli["mensaje"] and "número de solicitud: 25287682." in cli["mensaje"]


def test_corregir_respondiendo_y_aprobar(repo, bot):
    # OptiMaxx Plus: guía general, Ceci completa monto y datos para depositar.
    tk, ap = preparar(repo, bot, C2_PLU3, "2590002")
    assert "⚠️ Falta completar monto y datos para depositar" in bot.de("sendMessage")[0]["text"]
    # Aprobar sin monto ni datos → no se puede (alerta) y no sale nada.
    bot.updates = [boton(1, f"ap:{ap['id']}:1")]
    r = telegram.procesar_updates(repo, bot)
    assert r["plan"] == [] and bot.de("answerCallbackQuery")[-1]["show_alert"]
    assert "Falta completar" in bot.de("answerCallbackQuery")[-1]["text"]
    # Una respuesta que no dice qué cambiar → le explica cómo, sin cambiar nada.
    bot.updates = [respuesta(5, "dale, mandala")]
    telegram.procesar_updates(repo, bot)
    assert bot.de("sendMessage")[-1]["text"].startswith("No entendí qué cambiar")
    assert repo.obtener_aprobacion(ap["id"])["version"] == 1
    # Ceci responde con monto y datos → versión 2 con botones nuevos.
    bot.updates = [respuesta(6, "Monto: $50,000 MXN\nDatos: CLABE 0123 a nombre de Allianz")]
    r = telegram.procesar_updates(repo, bot)
    assert r["correcciones"][0]["version"] == 2
    nuevo = bot.de("sendMessage")[-1]
    assert "(versión 2)" in nuevo["text"] and nuevo["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == \
        f"ap:{ap['id']}:2"
    # Los botones de la versión 1 ya no sirven.
    bot.updates = [boton(7, f"ap:{ap['id']}:1")]
    assert telegram.procesar_updates(repo, bot)["plan"] == []
    assert "versión más nueva" in bot.de("answerCallbackQuery")[-1]["text"]
    # Aprobar la versión 2 → sale al cliente y al asesor.
    bot.updates = [boton(8, f"ap:{ap['id']}:2", mid=int(repo.obtener_aprobacion(ap["id"])["telegram_msg_id"]))]
    r = telegram.procesar_updates(repo, bot)
    assert sorted(a["rol"] for a in r["plan"]) == ["asesor", "cliente"]
    cli = next(a for a in r["plan"] if a["rol"] == "cliente")
    assert "• Monto: $50,000 MXN\n• Datos para depositar: CLABE 0123 a nombre de Allianz" in cli["mensaje"]
    final = repo.obtener_aprobacion(ap["id"])
    assert (final["estado"], final["resuelto_por"]) == ("aprobada", "telegram:ceci")
    assert bot.de("sendMessage")[-1]["text"].startswith("✅ Aprobada")
    assert bot.de("editMessageReplyMarkup")[-1]["reply_markup"] == {"inline_keyboard": []}


def test_descartar(repo, bot):
    tk, ap = preparar(repo, bot)
    bot.updates = [boton(1, f"de:{ap['id']}:1")]
    r = telegram.procesar_updates(repo, bot)
    assert r["plan"] == [] and repo.obtener_aprobacion(ap["id"])["estado"] == "descartada"
    assert bot.de("sendMessage")[-1]["text"].startswith("🗑 Descartada")


def test_otro_chat_no_puede_aprobar(repo, bot):
    tk, ap = preparar(repo, bot)
    bot.updates = [boton(1, f"de:{ap['id']}:1", chat="999"), respuesta(2, "texto pirata", chat="999")]
    r = telegram.procesar_updates(repo, bot)
    assert r["ignorados"] == 2 and repo.obtener_aprobacion(ap["id"])["estado"] == "pendiente"
    assert repo.obtener_aprobacion(ap["id"])["version"] == 1


def test_start_responde_el_chat_id(repo, bot):
    bot.updates = [{"update_id": 1, "message": {"message_id": 9, "text": "/start", "chat": {"id": 4242}}}]
    telegram.procesar_updates(repo, bot)
    assert bot.de("sendMessage")[-1] == {"chat_id": "4242", "text": "Hola. Tu chat id es 4242."}


def test_offset_no_repite_updates(repo, bot):
    tk, ap = preparar(repo, bot)
    bot.updates = [boton(7, f"de:{ap['id']}:1")]
    telegram.procesar_updates(repo, bot)
    assert repo.leer_valor("telegram_offset") == "7"
    telegram.procesar_updates(repo, bot)
    assert bot.de("getUpdates")[-1]["offset"] == 8


def test_update_roto_no_frena_a_los_demas(repo, bot):
    tk, ap = preparar(repo, bot)
    bot.updates = [{"update_id": 1, "callback_query": {"id": "x", "data": "ap:no-numero",
                                                        "message": {"chat": {"id": int(CECI)}}}},
                   boton(2, f"de:{ap['id']}:1")]
    telegram.procesar_updates(repo, bot)
    assert repo.obtener_aprobacion(ap["id"])["estado"] == "descartada"
    assert repo.leer_valor("telegram_offset") == "2"
