"""Interruptor de envío real por proceso (tickets / cobranza)."""
import pytest

from app import config
from app.acciones import despacho
from app.db.repo import RepositorioSQLite
from app.envio import interruptor


class _Emisor:
    modo = "gmail_api"
    remitente = "hola@babilonia.ai"

    def __init__(self):
        self.enviados = []

    def enviar(self, destinatarios, asunto, cuerpo, **_):
        self.enviados.append(destinatarios[0])
        return {"ok": True}


class _Wati:
    modo = "wati"

    def __init__(self):
        self.enviados = []

    def enviar_plantilla(self, numero, plantilla, params=None):
        self.enviados.append(numero)
        return {"ok": True}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", False)
    monkeypatch.setattr(config, "ENVIO_REAL", [])
    return RepositorioSQLite(str(tmp_path / "t.sqlite"))


@pytest.fixture
def wati(monkeypatch):
    w = _Wati()
    monkeypatch.setattr("app.wati.wati_desde_config", lambda: w)
    return w


def _dos_avisos(repo):
    """Un aviso de un ticket y uno de cobranza (cargo rechazado), los dos por WhatsApp al asesor."""
    tk = repo.crear_ticket({"nro_ticket": "1", "estado": "abierto", "proceso": "largo"})
    cb = repo.crear_ticket({"estado": "cerrado", "proceso": "cobranza"})
    repo.crear_accion(tk, "avisar_asesor", "wati", {"rol": "asesor", "numero": "5511", "mensaje": "ticket"})
    repo.crear_accion(cb, "avisar_asesor", "wati", {"rol": "asesor", "numero": "5522", "mensaje": "cobranza"})
    return tk, cb


def test_dry_run_false_solo_no_prende_nada(repo, wati):
    _dos_avisos(repo)
    r = despacho.despachar_pendientes(repo, _Emisor())
    assert r["conteo"] == {"simulada": 2} and wati.enviados == []


def test_solo_cobranza(repo, wati):
    _dos_avisos(repo)
    interruptor.cambiar(repo, "cobranza", True, por="panel:fede")
    r = despacho.despachar_pendientes(repo, _Emisor())
    assert wati.enviados == ["5522"] and r["conteo"] == {"enviada": 1, "simulada": 1}


def test_lo_del_panel_manda_sobre_la_config(repo, wati, monkeypatch):
    monkeypatch.setattr(config, "ENVIO_REAL", ["tickets", "cobranza"])
    assert interruptor.es_real(repo, "tickets")
    interruptor.cambiar(repo, "tickets", False, por="panel:fede")   # apagar para arreglar algo
    _dos_avisos(repo)
    despacho.despachar_pendientes(repo, _Emisor())
    assert wati.enviados == ["5522"]
    est = interruptor.estado(repo)["procesos"]
    assert est["tickets"] == {"encendido": False, "real": False, "origen": "panel",
                              "cambiado_por": "panel:fede", "cambiado_en": est["tickets"]["cambiado_en"]}
    assert est["cobranza"]["origen"] == "config" and est["cobranza"]["real"]


def test_correo_de_un_proceso_apagado_no_sale(repo):
    tk = repo.crear_ticket({"nro_ticket": "1", "estado": "abierto", "proceso": "largo"})
    repo.crear_accion(tk, "responder", "email_cliente", {"destinatario": "a@b.com", "mensaje": "hola"})
    em = _Emisor()
    assert despacho.despachar_pendientes(repo, em)["conteo"] == {"simulada": 1} and em.enviados == []
    interruptor.cambiar(repo, "tickets", True)
    repo.crear_accion(tk, "responder", "email_cliente", {"destinatario": "c@d.com", "mensaje": "hola"})
    assert despacho.despachar_pendientes(repo, em)["conteo"] == {"enviada": 1} and em.enviados == ["c@d.com"]


def test_con_dry_run_no_sale_nada_aunque_este_prendido(repo, monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", True)
    interruptor.cambiar(repo, "cobranza", True)
    assert not interruptor.es_real(repo, "cobranza")
    assert interruptor.estado(repo) ["procesos"]["cobranza"] ["encendido"] is True


def test_proceso_de():
    assert interruptor.proceso_de({"proceso": "cobranza"}) == "cobranza"
    assert interruptor.proceso_de({}, {"etapa": "cargo_rechazado"}) == "cobranza"
    assert interruptor.proceso_de({"proceso": "corto"}, {"etapa": "requerimiento"}) == "tickets"


def test_api(repo, monkeypatch):
    from fastapi.testclient import TestClient

    from app import api
    monkeypatch.setattr(api, "_repo", repo)
    c = TestClient(api.app)
    assert c.get("/api/tickets-allianz/envio").json()["procesos"]["cobranza"]["encendido"] is False
    r = c.put("/api/tickets-allianz/envio/cobranza", json={"encendido": True, "usuario": "Ceci"}).json()
    assert r["procesos"]["cobranza"] == {**r["procesos"]["cobranza"], "encendido": True, "real": True,
                                         "cambiado_por": "panel:Ceci"}
    assert c.put("/api/tickets-allianz/envio/todo", json={"encendido": True}).status_code == 400
