"""Runner end-to-end sobre el grafo LangGraph.

Lee el buzón → invoca el grafo por cada correo (clasificar L1/L2 → extraer → persistir →
enriquecer → ticket → Notion → decidir → despachar). Reemplaza a run_pipeline.

Uso:
    python -m app.run_grafo                 # muestras + repo según config
    python -m app.run_grafo ruta/carpeta    # otra carpeta de .eml
    python -m app.run_grafo --despachar     # además ejecuta el envío (respeta DRY_RUN)
"""
from __future__ import annotations

import sys
from pathlib import Path

from app import config
from app.db import RepositorioPostgres, get_repo
from app.envio import emisor_desde_config
from app.grafo import construir_grafo
from app.intake import LectorEmlLocal, LectorIMAP


def main(carpeta: Path | None = None, despachar: bool = False) -> int:
    if config.hay_imap() and carpeta is None:
        lector = LectorIMAP(config.IMAP_HOST, config.IMAP_USER, config.IMAP_PASSWORD,
                            config.IMAP_CARPETA, config.IMAP_PORT)
        fuente = f"IMAP {config.IMAP_HOST}"
    else:
        carpeta = carpeta or config.MUESTRAS_DIR
        lector = LectorEmlLocal(carpeta)
        fuente = str(carpeta)

    repo = get_repo()
    emisor = emisor_desde_config()
    grafo = construir_grafo(repo, emisor)
    backend = "Supabase/Postgres" if isinstance(repo, RepositorioPostgres) else "SQLite (dev)"

    print(f"\nMODO: {'DRY-RUN' if config.DRY_RUN else 'LIVE'}  |  fuente: {fuente}")
    print(f"DB: {backend}  |  LLM L2/redactor: {'ON (LangChain)' if config.hay_llm() else 'OFF (L1+plantillas)'}")
    print(f"Grafo: LangGraph  |  despachar: {'sí' if despachar else 'no'}\n")

    procesados = 0
    for correo in lector.leer():
        final = grafo.invoke({"correo": correo, "despachar": despachar})
        procesados += 1
        clf = final.get("clasificacion")
        tk = f"#{final['ticket_id']}" if final.get("ticket_id") else "—"
        fin = final.get("fin")
        cola = " · ".join(final.get("ruta", []))
        print(f"[{clf.tipo.value:<20}] ticket {tk:<5} {'('+fin+')' if fin else ''}")
        print(f"        ruta: {cola}")
        for a in (final.get("acciones") or []):
            print(f"        → [{a.get('tipo_accion')}/{a.get('canal')}] {a.get('mensaje','')[:70]}")
        desp = final.get("despacho")
        if desp:
            print(f"        despacho ({desp['modo']}): {desp['conteo']}")

    print(f"\nCorreos procesados: {procesados}")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    despachar = "--despachar" in args
    args = [a for a in args if not a.startswith("--")]
    carpeta = Path(args[0]) if args else None
    raise SystemExit(main(carpeta, despachar))
