"""Lector de buzón por Gmail API (OAuth) — alternativa a IMAP para Google Workspace.

Cumple la MISMA interfaz que `LectorEmlLocal`/`LectorIMAP` (`.leer()`), así el resto del
sistema (grafo, scheduler) no cambia. Trae los correos que matchean `query` (por defecto los de
los últimos 2 días, leídos o no, en toda la casilla) y los normaliza con `normalizar_desde_bytes`.
Los que ya se procesaron (`ya_procesados`, por su id de Gmail) no se vuelven a bajar.

Anti rate-limit (Gmail limita "Units per minute per user"): baja como mucho `limite` correos
por ciclo, con **backoff** ante 403/429 (`rateLimitExceeded`) y una **pausa** entre requests.
Si `marcar_leidos=True`, tras procesar cada correo le quita la etiqueta UNREAD → así el poll
siguiente NO vuelve a bajar el mismo backlog (clave para no quemar la cuota). La idempotencia
real la sigue dando `message_id` en la DB.
"""
from __future__ import annotations

import base64
import logging
import random
import re
import time
from datetime import datetime, timezone
from typing import Callable, Iterator, Optional

from app import config
from app.google_auth import construir_servicio
from app.models import Correo

from .reader import normalizar_desde_bytes

log = logging.getLogger(__name__)


def _es_rate_limit(ex: Exception) -> bool:
    s = str(ex)
    return "rateLimitExceeded" in s or "Quota exceeded" in s or "429" in s or "userRateLimitExceeded" in s


# Hasta cuándo Gmail nos pidió no volver a llamar ("Retry after <fecha>"). Cada llamada antes de
# esa hora la corre más para adelante (29/10: los reintentos cada 90 s la tuvieron bloqueada).
_pausa_hasta = 0.0
_RE_RETRY_AFTER = re.compile(r"Retry after (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)")


# Ids de Gmail ya bajados en este proceso, por casilla. Un correo que ya entró por otra casilla (p. ej. un
# aviso que llegó a hola@ y a integraciones@) tiene otro id acá: la base lo descarta por Message-ID pero no
# guarda este origen, y sin esta memoria se volvería a bajar en cada ciclo durante los 2 días de la ventana
# (eso fue lo que quemó la cuota en octubre). El lector se crea en cada ciclo, por eso vive en el módulo.
_VISTOS: dict[str, dict[str, None]] = {}
_MAX_VISTOS = 5000


def _recordar(buzon: str, gmail_id: str) -> None:
    vistos = _VISTOS.setdefault(buzon, {})
    vistos[gmail_id] = None
    while len(vistos) > _MAX_VISTOS:          # dict mantiene el orden: se va el más viejo
        vistos.pop(next(iter(vistos)))


def _retry_after(ex: Exception) -> float:
    m = _RE_RETRY_AFTER.search(str(ex))
    if not m:
        return 0.0
    try:
        return datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _ejecutar(req, intentos: int = 5):
    """Ejecuta un request de la Gmail API con backoff exponencial ante rate-limit. Si Gmail dice
    hasta cuándo esperar, no reintenta: anota la hora y el lector no llama hasta entonces."""
    global _pausa_hasta
    for i in range(intentos):
        try:
            return req.execute()
        except Exception as ex:  # noqa: BLE001
            hasta = _retry_after(ex) if _es_rate_limit(ex) else 0.0
            if hasta:
                _pausa_hasta = max(_pausa_hasta, hasta + 5)
                raise
            if _es_rate_limit(ex) and i < intentos - 1:
                espera = min(2 ** i + random.uniform(0, 0.5), 20)
                log.warning("Gmail rate-limit; reintento %d en %.1fs", i + 1, espera)
                time.sleep(espera)
                continue
            raise


class LectorGmail:
    def __init__(self, query: str = "is:unread", carpeta: str = "INBOX",
                 marcar_leidos: bool = True, limite: int = 40, pausa_ms: int = 250,
                 ya_procesados: Optional[Callable[[list[str]], set[str]]] = None,
                 buzon: str = "envio", max_paginas: int = 5):
        self.buzon = buzon              # 'envio' (hola@) o 'lectura' (integraciones@)
        self.max_paginas = max(1, max_paginas)
        self.query = query
        self.carpeta = carpeta
        self.marcar_leidos = marcar_leidos
        self.limite = limite
        self.pausa_ms = pausa_ms
        self.ya_procesados = ya_procesados  # origenes ('gmail:<id>') → los que ya están en la base

    def _listar(self, service, labels) -> Optional[list[dict]]:
        """Ids de la ventana (`query`), siguiendo `nextPageToken` hasta `max_paginas` páginas de 100.

        Sin `ya_procesados` alcanza con la primera página (se marcan leídos y no vuelven). Con él, hay que
        ver la ventana entera para no perder correos: integraciones@ recibe ~220 en 2 días. Cada página
        cuesta 5 unidades de cuota (contra 5 por correo bajado), así que listar de más es barato.
        """
        metas: list[dict] = []
        token = None
        paginas = self.max_paginas if self.ya_procesados else 1
        for _ in range(paginas):
            try:
                resp = _ejecutar(service.users().messages().list(
                    userId="me", q=self.query, labelIds=labels, pageToken=token,
                    maxResults=100 if self.ya_procesados else min(self.limite, 100)))
            except Exception as ex:  # noqa: BLE001
                log.warning("Gmail API list falló: %s", ex)
                return metas or None
            metas += resp.get("messages", [])
            token = resp.get("nextPageToken")
            if not token:
                break
        else:
            if token:
                log.warning("Gmail (%s): la ventana '%s' tiene más de %d correos; se ven los más nuevos",
                            self.buzon, self.query, len(metas))
        return metas

    def leer(self) -> Iterator[Correo]:
        service = construir_servicio(self.buzon)
        if service is None:
            log.warning("Gmail API (%s) sin credenciales/token; no se leyó nada", self.buzon)
            return
        if time.time() < _pausa_hasta:
            log.info("Gmail pidió esperar hasta %s UTC; no se lee en este ciclo",
                     datetime.fromtimestamp(_pausa_hasta, timezone.utc).strftime("%H:%M:%S"))
            return
        labels = [self.carpeta] if self.carpeta else None
        metas = self._listar(service, labels)
        if metas is None:
            return
        if self.ya_procesados and metas:
            vistos = _VISTOS.get(self.buzon, {})
            metas = [m for m in metas if m["id"] not in vistos]
            conocidos = self.ya_procesados([f"gmail:{m['id']}" for m in metas]) if metas else set()
            # Los más viejos primero: así un ticket se procesa en el orden en que pasó.
            metas = [m for m in metas if f"gmail:{m['id']}" not in conocidos][::-1][: self.limite]
        for meta in metas:
            try:
                msg = _ejecutar(service.users().messages().get(
                    userId="me", id=meta["id"], format="raw"))
                crudo = base64.urlsafe_b64decode(msg["raw"].encode("utf-8"))
            except Exception as ex:  # noqa: BLE001
                log.warning("Gmail API get %s falló: %s", meta.get("id"), ex)
                if time.time() < _pausa_hasta:
                    return
                continue
            correo = normalizar_desde_bytes(crudo, origen=f"gmail:{meta['id']}")
            correo.hilo_id = meta.get("threadId")  # para responder en el mismo hilo (Fase B)
            yield correo
            if not correo.fallo:  # si falló, se reintenta en el próximo ciclo
                _recordar(self.buzon, meta["id"])
            # Marcar leído DESPUÉS de procesar → el próximo poll no re-baja este correo.
            if self.marcar_leidos and not correo.fallo:  # si falló queda sin leer → se reintenta
                try:
                    _ejecutar(service.users().messages().modify(
                        userId="me", id=meta["id"], body={"removeLabelIds": ["UNREAD"]}))
                except Exception as ex:  # noqa: BLE001
                    log.warning("no se pudo marcar leído %s: %s", meta.get("id"), ex)
            if self.pausa_ms:
                time.sleep(self.pausa_ms / 1000.0)  # throttle para no reventar la cuota
