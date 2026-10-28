"""Etapa 3 (B) — traer al trámite lo que el cliente mandó por WhatsApp (transferencia, estado de cuenta)."""
import base64
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import api, config
from app.acciones import abrir_tramite
from app.wati import archivos

from test_abrir_tramite import POLIZA, repo  # noqa: F401  (fixture)

AHORA = datetime.now(timezone.utc)
JPG = b"\xff\xd8\xff\xe0 foto de la transferencia"
PDF = b"%PDF-1.4 estado de cuenta"


def _iso(dias):
    return (AHORA - timedelta(days=dias)).isoformat().replace("+00:00", "Z")


class _Resp:
    def __init__(self, status, contenido=b"", json=None):
        self.status_code, self.content, self._json = status, contenido, json

    def json(self):
        return self._json


class _Wati:
    """WATI de mentira: el cliente está guardado como 521 + 10 dígitos (celular mexicano)."""

    def __init__(self):
        self.pedidos = []

    def get(self, url, params=None, headers=None, **_):
        self.pedidos.append(url)
        if "getMessages/5215512345678" in url:
            return _Resp(200, json={"messages": {"items": [
                {"type": "text", "text": "ya pagué", "created": _iso(1)},
                {"type": "image", "data": "img/transferencia.jpg", "created": _iso(1)},
                {"type": "document", "data": "doc/estado.pdf", "created": _iso(2)},
                {"type": "document", "data": "doc/nuestro.pdf", "created": _iso(1), "owner": True},
                {"type": "audio", "data": "aud/nota.ogg", "created": _iso(1)},
                {"type": "image", "data": "img/vieja.jpg", "created": _iso(40)},
                {"type": "document", "data": "doc/borrado.pdf", "created": _iso(3)}]}})
        if "getMessages" in url:
            return _Resp(200, json={"messages": {"items": []}})
        nombre = (params or {}).get("fileName", "")
        if nombre == "img/transferencia.jpg":
            return _Resp(200, JPG)
        if nombre == "doc/estado.pdf":
            return _Resp(200, PDF)
        return _Resp(404, b"<html>no existe</html>")


@pytest.fixture
def wati(monkeypatch):
    monkeypatch.setattr(config, "WATI_API_URL", "https://wati.example")
    monkeypatch.setattr(config, "WATI_API_TOKEN", "tok")
    return _Wati()


def test_variantes_del_numero_mexicano():
    assert archivos.variantes_numero("55 1234 5678") == ["5512345678", "525512345678", "5215512345678"]
    assert archivos.variantes_numero("+52 55 1234 5678") == ["525512345678", "5215512345678"]
    assert archivos.variantes_numero("5215512345678") == ["5215512345678", "525512345678"]
    assert archivos.variantes_numero(None) == []


def test_trae_solo_fotos_y_documentos_del_cliente_recientes(repo, wati):  # noqa: F811
    r = abrir_tramite.archivos_whatsapp(POLIZA, http=wati)
    assert r["ok"] and r["cliente"] == "ANA PRUEBA LOPEZ" and r["telefono"] == "…5678"
    assert [(a["tipo"], base64.b64decode(a["base64"])) for a in r["archivos"]] == [
        ("image/jpeg", JPG), ("application/pdf", PDF)]
    assert r["archivos"][0]["nombre"].startswith("whatsapp_") and r["archivos"][0]["nombre"].endswith(".jpg")
    assert "(1 no se pudieron bajar)" in r["motivo"]  # el borrado; lo nuestro, el audio y lo viejo ni se piden
    assert not any("nuestro" in p or "nota.ogg" in p or "vieja" in p for p in wati.pedidos)


def test_lo_que_trae_se_puede_adjuntar_al_tramite(repo, wati):  # noqa: F811
    traidos = abrir_tramite.archivos_whatsapp(POLIZA, http=wati)["archivos"]
    p = abrir_tramite.preparar("cambio_conducto_cobro", POLIZA, None,
                               [{k: a[k] for k in ("nombre", "tipo", "base64")} for a in traidos])
    assert p["ok"] and p["adjuntos"] == [a["nombre"] for a in traidos]


def test_sin_wati_o_sin_poliza_identificada_lo_dice(repo, wati, monkeypatch):  # noqa: F811
    malo = abrir_tramite.archivos_whatsapp("PLU3-999999", http=wati)
    assert not malo["ok"] and "No se pudo identificar" in malo["motivo"] and wati.pedidos == []
    monkeypatch.setattr(config, "WATI_API_TOKEN", "")
    monkeypatch.delenv("WATI_TOKEN", raising=False)
    r = abrir_tramite.archivos_whatsapp(POLIZA, http=wati)
    assert not r["ok"] and "WATI no está configurado" in r["motivo"]


def test_api_archivos_whatsapp(repo, wati, monkeypatch):  # noqa: F811
    monkeypatch.setattr(api, "_repo", repo)
    real = archivos.archivos_del_cliente
    monkeypatch.setattr(archivos, "archivos_del_cliente", lambda tel, dias=14, http=None: real(tel, dias, http=wati))
    r = TestClient(api.app).post("/api/tickets-allianz/tramites/archivos-whatsapp", json={"poliza": POLIZA, "dias": 7})
    assert r.status_code == 200 and len(r.json()["archivos"]) == 2
