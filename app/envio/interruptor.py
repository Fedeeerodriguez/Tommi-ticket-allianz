"""Interruptor de envío real por proceso: tickets y cobranza (pedido de José, 12/11).

La idea es poder dejar a Tommy manejando tickets, cobranza o las dos cosas, y apagar uno para hacer
arreglos sin frenar el otro y sin redeploy.

  - `DRY_RUN` sigue siendo el freno general: con `DRY_RUN=true` no sale nada a nadie, como siempre.
  - Con `DRY_RUN=false`, cada proceso sale de verdad solo si su interruptor está prendido. Lo apagado se
    compone igual y queda como "simulada" en el panel, como en el sandbox.
  - El estado se cambia desde el panel y se guarda en la base (`valores`), así lo ven el worker y la
    API sin reiniciar. Mientras nadie lo toque, vale lo que diga `ENVIO_REAL` (por defecto, ninguno:
    pasar `DRY_RUN` a false no prende nada por sí solo).

Los avisos internos al equipo (resumen diario a Ceci, aprobaciones por Telegram) no pasan por acá.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from app import config

PROCESOS = ("tickets", "cobranza")
_CLAVE = "envio_real:{}"


def proceso_de(ticket: Optional[dict], payload: Optional[dict] = None) -> str:
    """A qué proceso pertenece una acción: 'cobranza' (cargo rechazado) o 'tickets' (todo lo demás)."""
    from app.acciones.cobranza import ETAPA, PROCESO
    if (ticket or {}).get("proceso") == PROCESO or (payload or {}).get("etapa") == ETAPA:
        return "cobranza"
    return "tickets"


def _guardado(repo, proceso: str) -> Optional[dict]:
    try:
        crudo = repo.leer_valor(_CLAVE.format(proceso)) if repo is not None else None
    except Exception:  # noqa: BLE001  (sin tabla o sin base: vale la config)
        return None
    if not crudo:
        return None
    try:
        dato = json.loads(crudo)
    except ValueError:
        return None
    return dato if isinstance(dato, dict) and isinstance(dato.get("encendido"), bool) else None


def encendido(repo, proceso: str) -> bool:
    """Si el interruptor del proceso está prendido (lo del panel manda; si no, `ENVIO_REAL`)."""
    g = _guardado(repo, proceso)
    return g["encendido"] if g else proceso in config.ENVIO_REAL


def es_real(repo, proceso: str) -> bool:
    """Si lo de este proceso sale de verdad: hace falta `DRY_RUN=false` Y el interruptor prendido."""
    return (not config.DRY_RUN) and encendido(repo, proceso)


def cambiar(repo, proceso: str, prender: bool, por: Optional[str] = None) -> dict:
    if proceso not in PROCESOS:
        raise ValueError(f"proceso desconocido: {proceso}")
    repo.guardar_valor(_CLAVE.format(proceso), json.dumps({
        "encendido": bool(prender), "por": por,
        "en": datetime.now(timezone.utc).isoformat(timespec="seconds")}))
    return estado(repo)


def estado(repo) -> dict:
    """Para el panel: el freno general y cada proceso (prendido, si sale de verdad, quién lo cambió)."""
    procesos = {}
    for p in PROCESOS:
        g = _guardado(repo, p)
        prendido = g["encendido"] if g else p in config.ENVIO_REAL
        procesos[p] = {"encendido": prendido, "real": (not config.DRY_RUN) and prendido,
                       "origen": "panel" if g else "config",
                       "cambiado_por": (g or {}).get("por"), "cambiado_en": (g or {}).get("en")}
    return {"dry_run": config.DRY_RUN, "procesos": procesos}
