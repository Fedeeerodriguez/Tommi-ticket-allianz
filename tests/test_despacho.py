"""Despacho: nada sale dos veces, una acción rota no traba la cola y WATI 200 + result:false es fallo."""
import threading
import time

import pytest

from app import config
from app.acciones import despacho
from app.db.repo import RepositorioSQLite
from app.wati import cliente as wati_cliente


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", True)
    return RepositorioSQLite(str(tmp_path / "t.sqlite"))


class WatiLento:
    modo = "wati"

    def __init__(self):
        self.enviados = []

    def enviar_plantilla(self, numero, plantilla, params=None):
        time.sleep(0.05)  # como la red: deja tiempo a que otro hilo lea la misma cola
        self.enviados.append(numero)
        return {"ok": True}


def aviso(repo, tk, numero):
    return repo.crear_accion(tk, "avisar_cliente", "wati", {"rol": "cliente", "numero": numero, "mensaje": "hola"})


def test_dos_jobs_a_la_vez_no_mandan_dos_veces(repo, monkeypatch):
    w = WatiLento()
    monkeypatch.setattr("app.wati.wati_desde_config", lambda: w)
    tk = repo.crear_ticket({"nro_ticket": "1", "estado": "abierto"})
    for n in ("5511", "5522", "5533"):
        aviso(repo, tk, n)
    hilos = [threading.Thread(target=despacho.despachar_pendientes, args=(repo,)) for _ in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert sorted(w.enviados) == ["5511", "5522", "5533"]


def test_una_accion_rota_no_frena_a_las_demas(repo, monkeypatch):
    w = WatiLento()
    monkeypatch.setattr("app.wati.wati_desde_config", lambda: w)
    tk = repo.crear_ticket({"nro_ticket": "1", "estado": "abierto"})
    rota, buena = aviso(repo, tk, "5511"), aviso(repo, tk, "5522")
    original = despacho._despachar_una

    def falla_la_primera(repo_, accion, *a):
        if accion["id"] == rota:
            raise KeyError("params")
        return original(repo_, accion, *a)

    monkeypatch.setattr(despacho, "_despachar_una", falla_la_primera)
    r = despacho.despachar_pendientes(repo)
    assert r["conteo"] == {"fallida": 1, "enviada": 1} and w.enviados == ["5522"]
    estados = {a["id"]: a["estado"] for a in repo.listar_acciones(tk)}
    assert estados == {rota: "fallida", buena: "enviada"}


def test_wati_200_con_result_false_es_fallo(monkeypatch):
    class Resp:
        status_code = 200
        headers = {"content-type": "application/json; charset=utf-8"}

        def json(self):
            return {"result": False, "info": "Invalid WhatsApp number"}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    r = wati_cliente.WatiHTTP("https://live.wati.io/1", "t").enviar_plantilla("5511", "tommy_aviso_cliente", {})
    assert r["ok"] is False and r["error"] == "Invalid WhatsApp number"
