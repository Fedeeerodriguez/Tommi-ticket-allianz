"""Etapa 2 — panel: guía por aprobar, aprobar/corregir/descartar desde el panel y 'Pago enviado'."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import api, config
from app.acciones.motor_etapas import decidir_por_etapa
from app.db.repo import RepositorioSQLite

from test_motor_etapa2 import ANA, C2_CORTO, CALLCENTER, LUNES, T1, et, fila, notion


@pytest.fixture
def cli(tmp_path, monkeypatch):
    for k, v in (("MOTOR_ETAPAS", True), ("MOTOR_ETAPAS_PROCESOS", ["largo", "corto", "tramite"]),
                 ("MOTOR_ETAPAS_ROLES", ["ceci", "asesor", "cliente"]), ("TELEGRAM_APROBACIONES", False),
                 ("GUIA_APORTACION_TEXTO", ""), ("NOTION_TOKEN", ""), ("OPENAI_API_KEY", ""), ("DRY_RUN", True),
                 ("PANEL_URL", ""), ("API_TOKEN", "")):
        monkeypatch.setattr(config, k, v)
    repo = RepositorioSQLite(str(tmp_path / "t.sqlite"))
    monkeypatch.setattr(api, "_repo", repo)
    return TestClient(api.app), repo


def corto(repo, buscar=None):
    tk = repo.crear_ticket({"nro_ticket": "2567479", "estado": "abierto"})
    decidir_por_etapa(repo, tk, et(C2_CORTO), correo_id=1, ahora=LUNES, buscar=buscar or notion(fila()))
    return tk


def test_guia_por_aprobar_en_para_ceci(cli):
    c, repo = cli
    tk = corto(repo)
    r = c.get("/api/tickets-allianz", params={"filtro": "para_ceci"}).json()
    item = next(i for i in r["items"] if i["id"] == tk)
    assert item["para_ceci"] == ["guia_por_aprobar"] and item["proceso"] == "corto"
    g = item["guia_pendiente"]
    assert g["version"] == 1 and g["falta_completar"] and not g["por_telegram"]
    assert g["texto"].startswith("Hola Guillermo,")


def test_aprobar_desde_el_panel(cli):
    c, repo = cli
    tk = corto(repo)
    aid = repo.listar_aprobaciones(tk)[0]["id"]
    # Con [completar] no se puede.
    r = c.post(f"/api/tickets-allianz/aprobacion/{aid}", json={"accion": "aprobar"})
    assert r.status_code == 409 and "sin completar" in r.json()["detail"]
    # Corregir → v2 (sigue pendiente).
    r = c.post(f"/api/tickets-allianz/aprobacion/{aid}",
               json={"accion": "corregir", "texto": "Hola Guillermo, deposita $50,000 a la CLABE 0123."})
    assert r.status_code == 200 and repo.obtener_aprobacion(aid)["version"] == 2
    # Aprobar → guía a cliente y asesor; sale de "Para Ceci".
    r = c.post(f"/api/tickets-allianz/aprobacion/{aid}", json={"accion": "aprobar", "usuario": "Ceci"})
    assert r.status_code == 200 and sorted(r.json()["avisos"]) == ["asesor", "cliente"]
    assert repo.obtener_aprobacion(aid)["resuelto_por"] == "panel:Ceci"
    assert c.get("/api/tickets-allianz", params={"filtro": "para_ceci"}).json()["items"] == []
    linea = c.get(f"/api/tickets-allianz/{tk}/linea-tiempo").json()
    assert linea["aprobaciones"][0]["estado"] == "aprobada"
    assert {e["tipo"] for e in linea["eventos"]} >= {"guia_por_aprobar", "guia_corregida", "guia_aprobada"}
    assert any(r["motivo"] == "pago" for r in linea["recordatorios"])
    # Dos veces no.
    assert c.post(f"/api/tickets-allianz/aprobacion/{aid}", json={"accion": "aprobar"}).status_code == 409


def test_descartar_y_accion_invalida(cli):
    c, repo = cli
    aid = repo.listar_aprobaciones(corto(repo))[0]["id"]
    assert c.post(f"/api/tickets-allianz/aprobacion/{aid}", json={"accion": "borrar"}).status_code == 400
    assert c.post(f"/api/tickets-allianz/aprobacion/{aid}", json={"accion": "descartar"}).status_code == 200
    assert repo.obtener_aprobacion(aid)["estado"] == "descartada"
    assert c.post("/api/tickets-allianz/aprobacion/999", json={"accion": "aprobar"}).status_code == 404


def test_pago_enviado_a_mano(cli):
    c, repo = cli
    tk = corto(repo)
    aid = repo.listar_aprobaciones(tk)[0]["id"]
    c.post(f"/api/tickets-allianz/aprobacion/{aid}", json={"accion": "aprobar", "texto": "Hola, deposita $10."})
    r = c.post(f"/api/tickets-allianz/{tk}/etapa", json={"etapa": "documentos_enviados", "usuario": "Ceci"})
    assert r.status_code == 200 and sorted(r.json()["avisos"]) == ["asesor", "ceci", "cliente"]
    recs = {x["motivo"]: x["estado"] for x in repo.listar_recordatorios(tk)}
    assert recs == {"pago": "cumplido", "esperando_allianz": "activo"}
    # Dos veces: la etapa ya está → 409, sin avisos repetidos.
    assert c.post(f"/api/tickets-allianz/{tk}/etapa", json={"etapa": "documentos_enviados"}).status_code == 409
    assert c.post(f"/api/tickets-allianz/{tk}/etapa", json={"etapa": "atendida"}).status_code == 400


def test_pago_enviado_solo_en_tickets_del_motor(cli):
    c, repo = cli
    viejo = repo.crear_ticket({"nro_ticket": "1", "estado": "abierto"})
    assert c.post(f"/api/tickets-allianz/{viejo}/etapa", json={"etapa": "documentos_enviados"}).status_code == 409


def test_tramite_trae_el_asunto(cli):
    c, repo = cli
    tk = repo.crear_ticket({"nro_ticket": "2587626", "estado": "abierto"})
    decidir_por_etapa(repo, tk, et(T1, CALLCENTER), correo_id=1, ahora=LUNES, buscar=notion(ANA))
    item = next(i for i in c.get("/api/tickets-allianz").json()["items"] if i["id"] == tk)
    assert item["titulo_hilo"] == "Aplicación de pago póliza OPPT-48211" and item["proceso"] == "tramite"
    assert c.get(f"/api/tickets-allianz/{tk}/linea-tiempo").json()["ticket"]["titulo_hilo"] == item["titulo_hilo"]


def test_panel_con_telegram_cierra_el_mensaje_viejo(cli, monkeypatch):
    c, repo = cli
    monkeypatch.setattr(config, "TELEGRAM_APROBACIONES", True)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setattr(config, "TELEGRAM_CECI_CHAT_ID", "777")
    llamadas = []
    from app.rieles import telegram
    monkeypatch.setattr(telegram, "_http", lambda m, p: llamadas.append((m, p)) or {"message_id": 1})
    tk = corto(repo)
    aid = repo.listar_aprobaciones(tk)[0]["id"]
    repo.actualizar_aprobacion(aid, telegram_msg_id="55", telegram_chat_id="777")
    r = c.post(f"/api/tickets-allianz/aprobacion/{aid}", json={"accion": "corregir", "texto": "Hola, $10."})
    assert r.status_code == 200
    assert [m for m, _ in llamadas] == ["editMessageReplyMarkup", "sendMessage"]
    assert repo.obtener_aprobacion(aid)["telegram_msg_id"] == ""  # el worker le manda la versión nueva
