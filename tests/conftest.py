"""Los tests corren la API sin autenticación (como en desarrollo); test_api_auth.py la prueba aparte."""
import pytest

from app import config


@pytest.fixture(autouse=True)
def _api_abierta_en_tests(monkeypatch):
    monkeypatch.setattr(config, "API_SIN_AUTH", True)
    monkeypatch.setattr(config, "TOMI_JWT_SECRET", "")
