"""Los tests corren la API sin autenticación (como en desarrollo); test_api_auth.py la prueba aparte."""
import pytest

from app import config


@pytest.fixture(autouse=True)
def _api_abierta_en_tests(monkeypatch):
    monkeypatch.setattr(config, "API_SIN_AUTH", True)
    monkeypatch.setattr(config, "TOMI_JWT_SECRET", "")


@pytest.fixture(autouse=True)
def _sin_casilla_de_lectura(monkeypatch, tmp_path):
    """Herméticos: el token local de integraciones@ (data/, fuera de git) no debe cambiar los tests."""
    monkeypatch.setattr(config, "GMAIL_LECTURA_TOKEN", "")
    monkeypatch.setattr(config, "GMAIL_LECTURA_TOKEN_JSON", str(tmp_path / "sin_token_lectura.json"))
    from app.intake import gmail_api
    monkeypatch.setattr(gmail_api, "_VISTOS", {})

