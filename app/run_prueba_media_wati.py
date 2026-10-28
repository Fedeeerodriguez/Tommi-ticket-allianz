"""Prueba técnica F5: ¿WATI nos deja descargar los archivos que manda el cliente?

Destraba la Etapa 3B (cliente atrasado: transferencia + estado de cuenta). Solo LEE: no manda nada.
  1. Trae los últimos mensajes de UN número (getMessages).
  2. De los que traen archivo (imagen, documento…) intenta bajar cada uno (getMedia).
  3. Dice si el archivo llegó entero (tamaño + tipo real por la firma: PDF, JPG, PNG…).

Antes de correrlo: desde ese WhatsApp, mandale al número de WATI una foto y un PDF.
Credenciales: WATI_API_URL + WATI_API_TOKEN (también acepta WATI_SERVER + WATI_TOKEN).

Uso:  python -m app.run_prueba_media_wati --numero 5492954407096 [--guardar /tmp/media_wati]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from app import config
from app.wati.archivos import bajar, mensajes_con_archivo, tipo_por_firma


def main() -> int:
    p = argparse.ArgumentParser(description="Prueba si WATI deja bajar los archivos que manda un cliente.")
    p.add_argument("--numero", required=True, help="WhatsApp con código de país, sin +. Ej. 5492954407096")
    p.add_argument("--cantidad", type=int, default=30, help="cuántos mensajes recientes revisar")
    p.add_argument("--guardar", default="", help="carpeta donde guardar lo bajado (opcional)")
    a = p.parse_args()
    numero = "".join(ch for ch in a.numero if ch.isdigit())
    url = (os.getenv("WATI_API_URL") or os.getenv("WATI_SERVER") or config.WATI_API_URL).rstrip("/")
    token = os.getenv("WATI_API_TOKEN") or os.getenv("WATI_TOKEN") or config.WATI_API_TOKEN
    if token.lower().startswith("bearer "):
        token = token[7:]
    if not (url and token):
        print("Faltan las credenciales de WATI (WATI_API_URL + WATI_API_TOKEN).")
        return 1
    import httpx

    r = httpx.get(f"{url}/api/v1/getMessages/{numero}", params={"pageSize": a.cantidad, "pageNumber": 1},
                  headers={"Authorization": f"Bearer {token}"}, timeout=30)
    print(f"getMessages → HTTP {r.status_code}")
    if r.status_code >= 300:
        print(f"   {r.text[:300]}")
        return 1
    archivos = mensajes_con_archivo(r.json())
    if not archivos:
        print(f"En los últimos {a.cantidad} mensajes no hay archivos. Mandá una foto y un PDF y volvé a correrlo.")
        return 1
    carpeta = Path(a.guardar) if a.guardar else None
    if carpeta:
        carpeta.mkdir(parents=True, exist_ok=True)
    bajados = 0
    for i, m in enumerate(archivos, 1):
        quien = "nosotros" if m["nuestro"] else "cliente"
        print(f"\n[{i}] {m['tipo']} de {quien} ({m['fecha']})")
        try:
            d = bajar(httpx, url, token, m["archivo"])
        except Exception as ex:  # noqa: BLE001
            print(f"   → FALLÓ: {ex}")
            continue
        contenido = d.content if d.status_code < 300 else b""
        real = tipo_por_firma(contenido)
        ok = bool(contenido) and real != "?"
        print(f"   → {'OK' if ok else 'FALLÓ'} HTTP {d.status_code} · {d.headers.get('content-type', '')} · "
              f"{len(contenido)} bytes · tipo real: {real}")
        if not ok and d.status_code >= 300:
            print(f"   {d.text[:200]}")
        if ok:
            bajados += 1
            if carpeta:
                (carpeta / f"archivo_{i}.{real.split('/')[0]}").write_bytes(contenido)
    print(f"\nResultado: {bajados} de {len(archivos)} archivos bajados enteros.")
    return 0 if bajados else 1


if __name__ == "__main__":
    raise SystemExit(main())
