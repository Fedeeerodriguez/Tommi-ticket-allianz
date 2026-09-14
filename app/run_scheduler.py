"""Runner del servicio autónomo (Fase 5).

Levanta el scheduler con los tres jobs (intake IMAP, inactividad, retención). Es el proceso
que corre en producción (EasyPanel). Todo respeta DRY_RUN: no envía ni borra nada hasta que
se den los accesos y se ponga DRY_RUN=false.

    python -m app.run_scheduler
"""
from __future__ import annotations

from app.scheduler import main

if __name__ == "__main__":
    raise SystemExit(main())
