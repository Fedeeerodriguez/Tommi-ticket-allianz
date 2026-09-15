"""Runner del sandbox de análisis de correos de Allianz (SOLO LECTURA).

Lee los correos reales por Gmail API, imprime un reporte legible y vuelca el detalle a
`data/sandbox_analisis.json` para análisis posterior. No envía ni escribe nada en la DB.

    python -m app.run_sandbox                       # últimos correos de allianz.com.mx
    python -m app.run_sandbox "from:Allianz.Mexico@allianz.com.mx" 80
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app import config
from app.sandbox import analizar, como_dicts, resumen

# La consola de Windows suele ser cp1252 y rompe con acentos/emoji → forzar UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "from:allianz.com.mx"
    limite = int(sys.argv[2]) if len(sys.argv) > 2 else 60

    print(f"SANDBOX (solo lectura) | query: {query} | límite: {limite}\n" + "=" * 100)
    items = analizar(query=query, limite=limite)

    for a in items:
        tk = a.nro_ticket or "—"
        crit = "  ⚠ CRÍTICO" if a.critico else ""
        roto = " [MID-roto]" if a.message_id_roto else ""
        actor = f" · {a.actor_tipo}:{a.actor}" if a.actor else ""
        print(f"[{a.subtipo:<22}] tk={tk:<9}{roto} | {a.asunto[:52]}")
        print(f"     de: {a.remitente[:50]}{actor}")
        if a.plazos:
            print(f"     plazos: {', '.join(a.plazos)}")
        print(f"     acción: {a.accion_sugerida}{crit}")

    print("=" * 100)
    r = resumen(items)
    print("RESUMEN:")
    print(f"  total: {r['total']} · tickets: {r['tickets']} · con nº ticket: {r['con_nro_ticket']} "
          f"· críticos: {r['criticos']} · MID-roto: {r['message_id_roto']} · en-hilo: {r['en_hilo']}")
    print("  por subtipo:")
    for k, v in r["por_subtipo"].items():
        print(f"     {v:>3}  {k}")

    salida = config.DATA_DIR / "sandbox_analisis.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps({"resumen": r, "items": como_dicts(items)}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\nDetalle completo → {salida}")
    print("(No se envió ni escribió NADA. Solo lectura.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
