"""Runner de la Fase 1 (dry-run).

Lee el buzón (por defecto los .eml de docs/muestras), deduplica por message_id,
clasifica con L1 y muestra una tabla + escribe un JSONL en data/ (gitignoreado).
NO envía nada a nadie. Es el andamio para enchufar el buzón real cuando esté el acceso.

Uso:
    python -m app.run_intake                 # usa docs/muestras
    python -m app.run_intake ruta/a/carpeta  # otra carpeta de .eml
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from app import config
from app.clasificador import clasificar
from app.intake import LectorEmlLocal, LectorIMAP


def _serializar(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def main(carpeta: Path | None = None) -> int:
    # Fuente: IMAP real si hay credenciales; si no, las muestras locales (dry-run).
    if config.hay_imap() and carpeta is None:
        lector = LectorIMAP(
            host=config.IMAP_HOST, usuario=config.IMAP_USER, password=config.IMAP_PASSWORD,
            carpeta=config.IMAP_CARPETA, puerto=config.IMAP_PORT,
        )
        fuente = f"IMAP {config.IMAP_HOST}/{config.IMAP_CARPETA}"
    else:
        carpeta = carpeta or config.MUESTRAS_DIR
        lector = LectorEmlLocal(carpeta)
        fuente = str(carpeta)

    vistos: set[str] = set()
    filas = []
    registros = []

    for correo in lector.leer():
        if correo.message_id in vistos:  # idempotencia
            continue
        vistos.add(correo.message_id)

        clf = clasificar(correo)  # L1, y L2 (Haiku) si es ambiguo y hay API key

        filas.append((
            (correo.origen or correo.message_id)[:22],
            clf.tipo.value,
            f"{clf.confianza:.2f}",
            "L2" if clf.necesita_llm else "ok",
            (correo.asunto or "")[:38],
        ))
        registros.append({
            "correo": asdict(correo),
            "clasificacion": asdict(clf),
        })

    # Tabla legible
    print(f"\nMODO: {'DRY-RUN (no envía nada)' if config.DRY_RUN else 'LIVE'}  |  fuente: {fuente}")
    print(f"LLM L2: {'ON (' + config.MODELO_L2 + ')' if config.hay_llm() else 'OFF (solo reglas L1)'}")
    print(f"Correos procesados: {len(filas)}\n")
    cab = ("ORIGEN", "TIPO", "CONF", "FLAG", "ASUNTO")
    print(f"{cab[0]:<22} {cab[1]:<20} {cab[2]:<5} {cab[3]:<4} {cab[4]}")
    print("-" * 96)
    for f in filas:
        print(f"{f[0]:<22} {f[1]:<20} {f[2]:<5} {f[3]:<4} {f[4]}")

    # Resumen por tipo
    from collections import Counter
    conteo = Counter(getattr(r["clasificacion"]["tipo"], "value", r["clasificacion"]["tipo"]) for r in registros)
    print("\nResumen por tipo:")
    for tipo, n in conteo.most_common():
        print(f"  {tipo:<22} {n}")

    # Log JSONL (gitignoreado)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    salida = config.DATA_DIR / "intake_dryrun.jsonl"
    with salida.open("w", encoding="utf-8") as fh:
        for r in registros:
            fh.write(json.dumps(r, ensure_ascii=False, default=_serializar) + "\n")
    print(f"\nLog escrito en: {salida}")
    return 0


if __name__ == "__main__":
    arg = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    raise SystemExit(main(arg))
