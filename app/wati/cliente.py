"""Cliente de WATI (WhatsApp) — real por HTTP (httpx) o laboratorio."""
from __future__ import annotations

import logging
from typing import Optional, Protocol

from app import config

log = logging.getLogger(__name__)


class EnvioWati(Protocol):
    modo: str
    def enviar_plantilla(self, numero: str, plantilla: str,
                         params: Optional[dict] = None) -> dict: ...


class WatiHTTP:
    """Envío real por la API de WATI (sendTemplateMessage)."""

    modo = "wati"

    def __init__(self, api_url: str, token: str):
        self.api_url = api_url.rstrip("/")
        self.token = token

    def enviar_plantilla(self, numero, plantilla, params=None) -> dict:
        numero = (numero or "").strip()
        if not numero:
            return {"ok": False, "modo": self.modo, "error": "sin número"}
        if not plantilla:
            return {"ok": False, "modo": self.modo, "error": "sin plantilla"}
        try:
            import httpx
        except ImportError:
            return {"ok": False, "modo": self.modo, "error": "httpx no instalado"}
        # WATI: los params de plantilla van como [{name, value}, ...].
        parametros = [{"name": k, "value": str(v)} for k, v in (params or {}).items()]
        url = f"{self.api_url}/api/v1/sendTemplateMessage"
        try:
            r = httpx.post(url, params={"whatsappNumber": numero},
                           headers={"Authorization": f"Bearer {self.token}",
                                    "Content-Type": "application/json"},
                           json={"template_name": plantilla, "broadcast_name": plantilla,
                                 "parameters": parametros}, timeout=30)
            ok = r.status_code < 300
            return {"ok": ok, "modo": self.modo, "status": r.status_code,
                    "numero": numero, "plantilla": plantilla,
                    "respuesta": (r.json() if "application/json" in r.headers.get("content-type", "") else r.text)}
        except Exception as ex:  # noqa: BLE001
            log.warning("WATI falló: %s", ex)
            return {"ok": False, "modo": self.modo, "error": str(ex),
                    "numero": numero, "plantilla": plantilla}


class WatiLaboratorio:
    """No toca la red: devuelve el mensaje que HABRÍA enviado. Para DRY_RUN / dev / tests."""

    modo = "dry_run"

    def enviar_plantilla(self, numero, plantilla, params=None) -> dict:
        return {"ok": True, "modo": self.modo, "simulado": True,
                "numero": numero, "plantilla": plantilla, "params": params or {}}


def wati_desde_config() -> EnvioWati:
    """WATI real solo con credenciales y DRY_RUN=false; si no, laboratorio."""
    if config.hay_wati() and not config.DRY_RUN:
        return WatiHTTP(config.WATI_API_URL, config.WATI_API_TOKEN)
    return WatiLaboratorio()
