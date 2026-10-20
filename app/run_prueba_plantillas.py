"""Prueba de las 3 plantillas de WATI con el MISMO camino que los avisos del motor por etapa.

Arma un aviso de cada tipo con datos de prueba (textos y variables de mensajes_etapa.py, plantilla
y variables de despacho.plantilla_etapas) y los manda a UN número:
  1. tommy_aviso_equipo           (lo que recibe el asesor / Ceci)
  2. tommy_actualizacion_cliente  (lo que recibe el cliente)
  3. tommy_guia_aportacion        (la guía de aportación aprobada)

Sin --enviar solo muestra lo que mandaría. Con --enviar manda de verdad (ignora DRY_RUN: es un
envío de prueba a mano, a un solo número). Credenciales: WATI_API_URL + WATI_API_TOKEN (también
acepta WATI_SERVER + WATI_TOKEN, los nombres de n8n / Tomi).

Uso:  python -m app.run_prueba_plantillas --numero 5492954407096 [--enviar]
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

from app import config
from app.acciones import mensajes_etapa as m
from app.acciones.despacho import plantilla_etapas


def avisos_de_prueba() -> list[dict]:
    ticket = {"nro_ticket": "PRUEBA-0001", "producto": "GMMI", "nro_solicitud": "1950110", "proceso": "largo"}
    etapa = {"etapa": "requerimiento", "producto": "GMMI", "que_piden": "la carta laboral firmada (esto es una prueba)",
             "plazo": (15, "dias_habiles")}
    datos = {"cliente_nombre": "Cliente Prueba"}
    ctx = m.contexto(ticket, etapa, datos, datetime(2026, 10, 23, 15, tzinfo=timezone.utc))
    params = m.params_wati(ctx, "requerimiento", None, "largo")
    equipo = {"rol": "asesor", "etapa": "requerimiento", "params": params,
              "mensaje": m.texto("asesor", "requerimiento", ctx, proceso="largo")}
    cliente = {"rol": "cliente", "etapa": "requerimiento", "params": params,
               "mensaje": m.texto("cliente", "requerimiento", ctx, proceso="largo")}
    corto = {"nro_ticket": "PRUEBA-0002", "producto": "SVIP", "poliza": "SVIP-00000", "proceso": "corto"}
    ctx_c = m.contexto(corto, {}, datos)
    g = {**m.datos_guia(ctx_c), "monto": "$1 MXN (prueba)", "datos_deposito": "CLABE de prueba, no depositar"}
    guia = {"rol": "cliente", "etapa": "guia_aportacion", "mensaje": m.texto_guia(g),
            "params": {**m.params_wati(ctx_c, "guia_aportacion", None, "corto"), "guia": g}}
    return [equipo, cliente, guia]


def main() -> int:
    p = argparse.ArgumentParser(description="Manda las 3 plantillas de WATI a un número, por el camino del motor.")
    p.add_argument("--numero", required=True, help="WhatsApp con código de país, sin +. Ej. 5492954407096")
    p.add_argument("--enviar", action="store_true", help="mandar de verdad (si no, solo muestra)")
    a = p.parse_args()
    numero = "".join(ch for ch in a.numero if ch.isdigit())
    url = (os.getenv("WATI_API_URL") or os.getenv("WATI_SERVER") or config.WATI_API_URL).rstrip("/")
    token = os.getenv("WATI_API_TOKEN") or os.getenv("WATI_TOKEN") or config.WATI_API_TOKEN
    if token.lower().startswith("bearer "):
        token = token[7:]
    from app.wati import WatiHTTP
    wati = WatiHTTP(url, token) if (a.enviar and url and token) else None
    if a.enviar and not wati:
        print("Faltan las credenciales de WATI (WATI_API_URL + WATI_API_TOKEN). No se mandó nada.")
        return 1
    ok = True
    for pay in avisos_de_prueba():
        plantilla, params = plantilla_etapas(pay)
        print(f"\n== {plantilla} → {numero}\n{json.dumps(params, ensure_ascii=False, indent=2)}")
        if wati:
            r = wati.enviar_plantilla(numero, plantilla, params)
            cuerpo = r.get("respuesta") or r.get("body") or r.get("error") or ""
            print(f"   → {'OK' if r.get('ok') else 'FALLÓ'} (HTTP {r.get('status')}) {str(cuerpo)[:300]}")
            ok = ok and bool(r.get("ok"))
    if not wati:
        print("\n(solo vista previa: agregá --enviar para mandar)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
