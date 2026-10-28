"""Etapa 3 (B) — los archivos que el cliente mandó por WhatsApp (transferencia, estado de cuenta).

WATI deja bajarlos (prueba F5 del 28/10: getMessages + getMedia). Desde el panel, al abrir un
trámite, Ceci trae lo que mandó el cliente de esa póliza en los últimos días y elige qué adjuntar.
Solo LEE: no manda nada, por eso funciona también con DRY_RUN.
"""
from __future__ import annotations

import base64
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import config

TIPOS_ARCHIVO = {"image", "document", "video", "audio", "sticker"}
TIPOS_ADJUNTABLES = {"image", "document"}   # lo que sirve como comprobante
MAX_ARCHIVOS = 10
MAX_BYTES_ARCHIVO = 5 * 1024 * 1024

FIRMAS = (
    (b"%PDF", "pdf"),
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG", "png"),
    (b"RIFF", "webp"),
    (b"OggS", "ogg"),
    (b"PK\x03\x04", "zip/office"),
)
MIME = {"pdf": "application/pdf", "jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def tipo_por_firma(contenido: bytes) -> str:
    """El tipo real del archivo por sus primeros bytes ('?' si no se reconoce)."""
    for firma, tipo in FIRMAS:
        if contenido.startswith(firma):
            return tipo
    if contenido[4:8] == b"ftyp":
        return "mp4"
    return "?"


def mensajes_con_archivo(respuesta) -> list[dict]:
    """Los mensajes que traen archivo, de la respuesta de getMessages (tolera las dos formas de WATI)."""
    if not isinstance(respuesta, dict):
        return []
    items = respuesta.get("messages")
    if isinstance(items, dict):
        items = items.get("items")
    salida = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        tipo = str(it.get("type") or "").lower()
        archivo = it.get("data") or it.get("fileName") or ""
        if tipo in TIPOS_ARCHIVO and archivo:
            salida.append({"tipo": tipo, "archivo": str(archivo), "fecha": it.get("created") or "",
                           "nuestro": bool(it.get("owner"))})
    return salida


def variantes_numero(telefono: Optional[str]) -> list[str]:
    """Cómo puede estar guardado el número en WATI. México: con y sin el 1 después del 52;
    10 dígitos sueltos = celular mexicano sin código de país."""
    d = re.sub(r"\D", "", telefono or "")
    if not d:
        return []
    vs = [d]
    if len(d) == 10:
        vs += ["52" + d, "521" + d]
    elif len(d) == 12 and d.startswith("52"):
        vs.append("521" + d[2:])
    elif len(d) == 13 and d.startswith("521"):
        vs.append("52" + d[3:])
    return list(dict.fromkeys(vs))


def credenciales() -> tuple[str, str]:
    """URL + token de WATI (también acepta WATI_SERVER + WATI_TOKEN, los nombres de n8n / Tomi)."""
    url = (config.WATI_API_URL or os.getenv("WATI_SERVER", "")).rstrip("/")
    token = config.WATI_API_TOKEN or re.sub(r"^\s*bearer\s+", "", os.getenv("WATI_TOKEN", ""), flags=re.I).strip()
    return url, token


def bajar(http, url: str, token: str, archivo: str):
    """Baja un archivo de WATI: por getMedia, o directo si WATI ya da la URL completa."""
    headers = {"Authorization": f"Bearer {token}"}
    if archivo.startswith("http"):
        return http.get(archivo, headers=headers, timeout=60, follow_redirects=True)
    return http.get(f"{url}/api/v1/getMedia", params={"fileName": archivo}, headers=headers,
                    timeout=60, follow_redirects=True)


def _fecha(v) -> Optional[datetime]:
    try:
        f = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return f if f.tzinfo else f.replace(tzinfo=timezone.utc)


def archivos_del_cliente(telefono: Optional[str], dias: int = 14, http=None,
                         ahora: Optional[datetime] = None) -> dict:
    """Las fotos y documentos que mandó el cliente en los últimos `dias`, ya bajados.
    {ok, motivo, archivos: [{nombre, tipo, base64, bytes, fecha}]}. Los más nuevos primero."""
    url, token = credenciales()
    if not (url and token):
        return {"ok": False, "motivo": "WATI no está configurado (WATI_API_URL + WATI_API_TOKEN)", "archivos": []}
    numeros = variantes_numero(telefono)
    if not numeros:
        return {"ok": False, "motivo": "el cliente no tiene teléfono en Notion", "archivos": []}
    if http is None:
        import httpx as http
    desde = (ahora or datetime.now(timezone.utc)) - timedelta(days=dias)
    mensajes = []
    for n in numeros:
        r = http.get(f"{url}/api/v1/getMessages/{n}", params={"pageSize": 100, "pageNumber": 1},
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if r.status_code < 300:
            mensajes = mensajes_con_archivo(r.json())
            if mensajes:
                break
    elegibles = []
    for m in mensajes:
        f = _fecha(m["fecha"])
        if m["nuestro"] or m["tipo"] not in TIPOS_ADJUNTABLES or (f and f < desde):
            continue
        elegibles.append((f or desde, m))
    elegibles.sort(key=lambda x: x[0], reverse=True)
    archivos, fallidos = [], 0
    for f, m in elegibles[:MAX_ARCHIVOS]:
        try:
            d = bajar(http, url, token, m["archivo"])
        except Exception:  # noqa: BLE001
            fallidos += 1
            continue
        contenido = d.content if d.status_code < 300 else b""
        real = tipo_por_firma(contenido)
        if real not in MIME or len(contenido) > MAX_BYTES_ARCHIVO:
            fallidos += 1
            continue
        archivos.append({"nombre": f"whatsapp_{f:%Y-%m-%d_%H%M}_{len(archivos) + 1}.{real}",
                         "tipo": MIME[real], "base64": base64.b64encode(contenido).decode(),
                         "bytes": len(contenido), "fecha": f.isoformat()})
    if archivos:
        motivo = f"{len(archivos)} archivo(s) de los últimos {dias} días"
    else:
        motivo = f"el cliente no mandó fotos ni documentos en los últimos {dias} días"
    if fallidos:
        motivo += f" ({fallidos} no se pudieron bajar)"
    return {"ok": True, "motivo": motivo, "archivos": archivos}
