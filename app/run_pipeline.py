"""Runner end-to-end (Fase 1+2, DRY-RUN).

Lee el buzón → clasifica (L1/L2) → extrae entidades → PERSISTE → motor de tickets + bitácora.
Backend de DB: Supabase (si hay DATABASE_URL) o SQLite dev. No envía nada a nadie.

Uso:
    python -m app.run_pipeline                 # muestras + repo según config
    python -m app.run_pipeline ruta/carpeta    # otra carpeta de .eml
"""
from __future__ import annotations

import sys
from pathlib import Path

from app import config
from app.clasificador import clasificar
from app.db import RepositorioPostgres, get_repo
from app.extraccion import extraer
from app.intake import LectorEmlLocal, LectorIMAP
from app.tickets import procesar_correo


def main(carpeta: Path | None = None) -> int:
    if config.hay_imap() and carpeta is None:
        lector = LectorIMAP(config.IMAP_HOST, config.IMAP_USER, config.IMAP_PASSWORD,
                            config.IMAP_CARPETA, config.IMAP_PORT)
        fuente = f"IMAP {config.IMAP_HOST}"
    else:
        carpeta = carpeta or config.MUESTRAS_DIR
        lector = LectorEmlLocal(carpeta)
        fuente = str(carpeta)

    repo = get_repo()
    backend = "Supabase/Postgres" if isinstance(repo, RepositorioPostgres) else "SQLite (dev)"

    print(f"\nMODO: {'DRY-RUN' if config.DRY_RUN else 'LIVE'}  |  fuente: {fuente}")
    print(f"DB: {backend}  ({config.DB_SCHEMA if isinstance(repo, RepositorioPostgres) else 'local'})")
    print(f"LLM L2: {'ON' if config.hay_llm() else 'OFF (solo L1)'}\n")

    procesados = 0
    for correo in lector.leer():
        clf = clasificar(correo)
        ent = extraer(correo, clf)
        res = procesar_correo(repo, correo, clf, ent)
        procesados += 1
        tk = f"#{res['ticket_id']}" if res.get("ticket_id") else "—"
        print(f"[{res['tipo']:<20}] ticket {tk:<5} · {res['accion']}")
        reg = res.get("registro_notion")
        if reg and reg.get("ok"):
            if reg.get("dry_run"):
                props = reg.get("properties", {})
                estado = (props.get("Estado", {}).get("status") or {}).get("name", "—")
                interno = (props.get("Estado Interno de Allianz", {}).get("status") or {}).get("name", "—")
                tram = (props.get("Tipo de Trámite", {}).get("select") or {}).get("name", "—")
                emis = "sí" if props.get("Emisiones") else "no"
                print(f"        └─ Notion [DRY-RUN] → Estado:{estado} · Interno:{interno} · "
                      f"Trámite:{tram} · vincula póliza:{emis}")
            else:
                print(f"        └─ Notion {reg.get('accion')} · page {reg.get('page_id','')[:8]}")

    # Estado final de los tickets + bitácora
    print("\n" + "=" * 90)
    print("TICKETS")
    print("=" * 90)
    for t in repo.listar_tickets():
        print(f"#{t['id']} · {t.get('estado'):<18} · ticket:{t.get('nro_ticket') or '—'} · "
              f"póliza:{t.get('poliza') or '—'}"
              f"{'  ⚠️ DELICADO/Ceci' if t.get('delicado') else ''}")
        print(f"     cliente:{t.get('cliente_nombre') or t.get('cliente_correo') or '—'} · "
              f"asesor:{t.get('asesor_correo') or '—'} · DAF:{t.get('daf') or '—'}")
        for ev in repo.listar_eventos(t["id"]):
            print(f"     └─ {ev.get('tipo_evento'):<22} {ev.get('resumen')}")

    print(f"\nCorreos procesados: {procesados}")
    return 0


if __name__ == "__main__":
    arg = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    raise SystemExit(main(arg))
