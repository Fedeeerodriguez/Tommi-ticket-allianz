"""Runner del despachador de acciones (Fase 4).

Toma las acciones en cola ('sugerida') y las ejecuta. Envía por SMTP SOLO si hay
credenciales y DRY_RUN=false; en cualquier otro caso simula (no toca la red).

Uso:
    python -m app.run_despacho
"""
from __future__ import annotations

from app import config
from app.acciones import despachar_pendientes
from app.db import RepositorioPostgres, get_repo
from app.envio import emisor_desde_config


def main() -> int:
    repo = get_repo()
    emisor = emisor_desde_config()
    backend = "Supabase/Postgres" if isinstance(repo, RepositorioPostgres) else "SQLite (dev)"

    print(f"\nMODO: {'DRY-RUN' if config.DRY_RUN else 'LIVE'}  |  emisor: {emisor.modo}")
    print(f"DB: {backend}")
    print(f"SMTP: {'ON ('+config.SMTP_HOST+')' if config.hay_smtp() else 'OFF'}  |  "
          f"Allianz dest: {config.ALLIANZ_DEST or '— (bloquea envío a Allianz)'}\n")

    res = despachar_pendientes(repo, emisor)

    print("=" * 70)
    print("DESPACHO DE ACCIONES")
    print("=" * 70)
    for d in res["detalle"]:
        print(f"  acción #{d['accion_id']:<4} ticket #{d['ticket_id']} · "
              f"[{d['tipo_accion']}/{d['canal']}] → {d['resultado']}")
    print("-" * 70)
    print("Resumen:", ", ".join(f"{k}={v}" for k, v in sorted(res["conteo"].items())) or "sin acciones pendientes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
