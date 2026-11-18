"""Telegram con Autorizar / Modificar (Ceci, 17/11): guías, correos retenidos (escalación a Allianz) y Jime."""
import json

import pytest

from app import config
from app.rieles import telegram

from test_motor_etapa2 import C2_CORTO, aislado, correr, repo  # noqa: F401  (fixtures)
from test_telegram import CECI, BotFalso, boton

JIME = "888"


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_APROBACIONES", True)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setattr(config, "TELEGRAM_CECI_CHAT_ID", f"{CECI},{JIME}")
    return BotFalso()


def texto(uid, txt, chat=CECI, a_mid=None):
    msg = {"message_id": 500 + uid, "text": txt, "from": {"username": "ceci"}, "chat": {"id": int(chat)}}
    if a_mid:
        msg["reply_to_message"] = {"message_id": a_mid}
    return {"update_id": uid, "message": msg}


def guia(repo, bot):
    tk = repo.crear_ticket({"nro_ticket": "2567479", "estado": "abierto"})
    correr(repo, tk, C2_CORTO, 1)
    assert telegram.enviar_pendientes(repo, bot) == 1
    return tk, repo.listar_aprobaciones(tk)[0]


def test_la_guia_le_llega_a_ceci_y_a_jime(repo, bot):
    tk, ap = guia(repo, bot)
    assert [m["chat_id"] for m in bot.de("sendMessage")] == [CECI, JIME]


def test_jime_tambien_autoriza_y_se_cierra_en_los_dos_chats(repo, bot):
    tk, ap = guia(repo, bot)
    repo.actualizar_aprobacion(ap["id"], datos={**ap["datos"], "monto": "$50,000 MXN"})
    bot.updates = [boton(1, f"ap:{ap['id']}:1", chat=JIME, mid=102)]
    r = telegram.procesar_updates(repo, bot)
    assert sorted(a["rol"] for a in r["plan"]) == ["asesor", "cliente"]
    assert {p["chat_id"] for p in bot.de("editMessageReplyMarkup")} == {CECI, JIME}


def test_modificar_la_guia_sale_el_texto_de_ceci_tal_cual(repo, bot):
    tk, ap = guia(repo, bot)
    bot.updates = [boton(1, f"mo:{ap['id']}:1")]
    telegram.procesar_updates(repo, bot)
    assert bot.de("sendMessage")[-1]["text"] == telegram.PIDE_TEXTO
    propio = ("Hola Guillermo, para activar tu Elite deposita $48,000 MXN a la cuenta del correo Felicidades y "
              "manda el comprobante respondiendo al ticket 2567479.")
    bot.updates = [texto(2, propio)]
    r = telegram.procesar_updates(repo, bot)
    cli = next(a for a in r["plan"] if a["rol"] == "cliente")
    assert cli["mensaje"] == propio and "guia" not in cli["params"]      # va por la plantilla general del cliente
    final = repo.obtener_aprobacion(ap["id"])
    assert final["estado"] == "aprobada" and final["texto"] == propio
    assert bot.de("sendMessage")[-1]["text"].startswith("✏️ Modificada y autorizada")


def test_modificar_con_solo_los_datos_arma_una_version_nueva(repo, bot):
    tk, ap = guia(repo, bot)
    bot.updates = [boton(1, f"mo:{ap['id']}:1"), texto(2, "Monto: $50,000 MXN")]
    r = telegram.procesar_updates(repo, bot)
    assert r["plan"] == [] and repo.obtener_aprobacion(ap["id"])["version"] == 2
    assert repo.obtener_aprobacion(ap["id"])["estado"] == "pendiente"


def test_un_ok_respondido_sin_tocar_modificar_no_le_llega_al_cliente(repo, bot):
    tk, ap = guia(repo, bot)
    bot.updates = [texto(1, "ok, dale", a_mid=101)]
    r = telegram.procesar_updates(repo, bot)
    assert r["plan"] == [] and repo.obtener_aprobacion(ap["id"])["estado"] == "pendiente"
    assert bot.de("sendMessage")[-1]["text"].startswith("No entendí qué cambiar")


def _escalacion(repo):
    tk = repo.crear_ticket({"nro_ticket": "2576612", "estado": "esperando_allianz", "cliente_nombre": "HORTENCIA",
                            "producto": "GMMI"})
    aid = repo.crear_accion(tk, "escalar_allianz", "email", {
        "rol": "allianz", "destinatario": None, "cc": ["blanca.xuluc@allianz.com.mx", "penny.ortiz@allianz.com.mx"],
        "cuerpo": "Buen día,\n\nDamos seguimiento…\n\nQuedamos atentos.\nCecilia Cansino\nBabilonia",
        "mensaje": "Escalación", "requiere_visto_bueno": True, "etapa": "escalado_esperando_allianz"})
    repo.actualizar_accion(aid, "pendiente_ceci", {"motivo": "visto bueno"})
    return tk, aid


def test_el_correo_retenido_le_llega_con_copias_y_se_autoriza(repo, bot):
    tk, aid = _escalacion(repo)
    assert telegram.enviar_acciones(repo, bot) == 1
    assert telegram.enviar_acciones(repo, bot) == 0                     # no se manda dos veces
    msg = bot.de("sendMessage")[0]
    assert "Copia: blanca.xuluc@allianz.com.mx, penny.ortiz@allianz.com.mx" in msg["text"]
    assert [b["callback_data"] for b in msg["reply_markup"]["inline_keyboard"][0]] == [f"aa:{aid}", f"am:{aid}"]
    bot.updates = [boton(1, f"aa:{aid}")]
    r = telegram.procesar_updates(repo, bot)
    assert r["plan"] == [{"accion_id": aid}]
    a = next(x for x in repo.listar_acciones(tk) if x["id"] == aid)
    assert a["estado"] == "sugerida" and json.loads(a["resultado"])["aprobado_por"] == "telegram:ceci"


def test_modificar_el_correo_sale_con_el_texto_de_ceci(repo, bot):
    tk, aid = _escalacion(repo)
    telegram.enviar_acciones(repo, bot)
    nuevo = "Buen día,\n\n¿Nos confirman el estatus de la solicitud?\n\nCecilia Cansino"
    bot.updates = [boton(1, f"am:{aid}", chat=JIME, mid=102), texto(2, nuevo, chat=JIME)]
    telegram.procesar_updates(repo, bot)
    a = next(x for x in repo.listar_acciones(tk) if x["id"] == aid)
    # El despacho usa borrador_editado antes que el cuerpo original (igual que lo editado en el panel).
    assert a["estado"] == "sugerida" and a["borrador_editado"] == nuevo
    assert json.loads(a["resultado"])["modificado"] is True


def test_si_el_correo_ya_no_espera_aprobacion_avisa(repo, bot):
    tk, aid = _escalacion(repo)
    telegram.enviar_acciones(repo, bot)
    repo.actualizar_accion(aid, "descartada", {"motivo": "Allianz respondió"})
    bot.updates = [boton(1, f"aa:{aid}")]
    telegram.procesar_updates(repo, bot)
    assert bot.de("answerCallbackQuery")[-1]["text"] == "Eso ya no está esperando aprobación."
