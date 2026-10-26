"""La API del panel acepta la sesión de un admin de Tomi (JWT HS256) y nunca queda abierta por olvido."""
import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import api, config
from app.db.repo import RepositorioSQLite

SECRETO = "clave-de-tomi-de-prueba"
URL = "/api/tickets-allianz"


def jwt(payload, secreto=SECRETO, alg="HS256"):
    """Como lo firma Tomi (python-jose, HS256)."""
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    cab, cuerpo = b({"alg": alg, "typ": "JWT"}), b(payload)
    firma = hmac.new(secreto.encode(), f"{cab}.{cuerpo}".encode(), hashlib.sha256).digest()
    return f"{cab}.{cuerpo}.{base64.urlsafe_b64encode(firma).rstrip(b'=').decode()}"


def sesion(rol="admin", vence_en=3600, **kw):
    return jwt({"sub": "6f1c0e3a-0000-0000-0000-000000000001", "role": rol, "exp": int(time.time()) + vence_en}, **kw)


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_repo", RepositorioSQLite(str(tmp_path / "t.sqlite")))
    monkeypatch.setattr(config, "API_SIN_AUTH", False)
    monkeypatch.setattr(config, "TOMI_JWT_SECRET", SECRETO)
    monkeypatch.setattr(config, "API_TOKEN", "")
    return TestClient(api.app)


def get(cli, token=None):
    return cli.get(URL, headers={"Authorization": f"Bearer {token}"} if token else {})


def test_sesion_de_admin_entra(cli):
    assert get(cli, sesion()).status_code == 200
    assert get(cli, sesion("super_admin")).status_code == 200


@pytest.mark.parametrize("token", [
    None, "cualquier-cosa", "a.b.c",
    sesion(vence_en=-10),                       # vencida
    sesion(secreto="otra-clave"),               # firmada por otro
    sesion(alg="none"),                         # truco del algoritmo "none"
    sesion(alg="HS512"),
])
def test_sin_sesion_valida_no_entra(cli, token):
    assert get(cli, token).status_code == 401


def test_sesion_de_otro_rol_no_entra(cli):
    r = get(cli, sesion("asesor"))
    assert r.status_code == 403 and "administradores" in r.json()["detail"]


def test_sesion_con_el_cuerpo_cambiado_no_entra(cli):
    cab, _, firma = sesion("asesor").split(".")
    cuerpo = base64.urlsafe_b64encode(json.dumps(
        {"sub": "x", "role": "admin", "exp": int(time.time()) + 3600}).encode()).rstrip(b"=").decode()
    assert get(cli, f"{cab}.{cuerpo}.{firma}").status_code == 401


def test_transicion_tambien_acepta_el_token_viejo(cli, monkeypatch):
    monkeypatch.setattr(config, "API_TOKEN", "token-viejo")
    assert get(cli, "token-viejo").status_code == 200
    assert get(cli, sesion()).status_code == 200
    assert get(cli, "token-equivocado").status_code == 401


def test_sin_autenticacion_configurada_no_atiende(cli, monkeypatch):
    monkeypatch.setattr(config, "TOMI_JWT_SECRET", "")
    r = get(cli)
    assert r.status_code == 503 and "TOMI_JWT_SECRET" in r.json()["detail"]
    monkeypatch.setattr(config, "API_SIN_AUTH", True)  # solo desarrollo
    assert get(cli).status_code == 200


def test_health_no_pide_sesion(cli):
    assert cli.get("/api/health").status_code == 200
