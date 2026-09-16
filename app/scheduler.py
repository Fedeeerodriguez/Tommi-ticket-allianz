"""Fase 5 — Scheduler: convierte el sistema en un servicio autónomo 24/7.

Tres jobs sobre APScheduler (un solo proceso, sin cron externo):

  1. INTAKE  (cada POLL_SEGUNDOS): lee correos nuevos del buzón → invoca el grafo por cada
     uno (clasificar → … → decidir) → despacha las acciones vencidas. La idempotencia la da
     `message_id` en DB, así que re-ver un correo no lo reprocesa.
  2. INACTIVIDAD (1×/día): escanea tickets sin novedades y encola recordatorios de reactivación.
  3. RETENCIÓN (1×/día): purga correos y tickets resueltos más viejos que RETENCION_DIAS (6 meses).

Modo seguro: en DRY_RUN no sale nada por SMTP (lo decide `emisor_desde_config`) y la purga
solo cuenta (no borra). Con esto, el mismo binario corre igual en dev y en producción; lo
único que cambia son las variables de entorno.

Uso:  python -m app.run_scheduler
"""
from __future__ import annotations

import logging

from app import config
from app.acciones import despachar_pendientes
from app.acciones.motor import escanear_inactividad, escanear_vencimientos
from app.db import RepositorioPostgres, get_repo
from app.envio import emisor_desde_config
from app.grafo import construir_grafo
from app.intake import lector_desde_config

log = logging.getLogger("scheduler")

# Cada cuántos días corre el escaneo de inactividad y a partir de cuántos días sin novedad
# se considera un ticket "estancado".
_INACTIVIDAD_DIAS = 3


def _lector():
    """Gmail API / IMAP / carpeta de muestras, según la config."""
    return lector_desde_config()


def job_intake(repo, grafo, emisor) -> dict:
    """Lee correos nuevos, los pasa por el grafo y despacha las acciones vencidas."""
    lector, fuente = _lector()
    nuevos = 0
    for correo in lector.leer():
        try:
            grafo.invoke({"correo": correo, "despachar": False})
            nuevos += 1
        except Exception:  # noqa: BLE001
            log.exception("intake: falló procesando un correo (%s)", getattr(correo, "message_id", "?"))
    desp = despachar_pendientes(repo, emisor)
    log.info("intake[%s]: %d correos · despacho=%s", fuente, nuevos, desp.get("conteo"))
    return {"correos": nuevos, "despacho": desp}


def job_inactividad(repo, emisor) -> dict:
    """Encola recordatorios para tickets estancados y los despacha."""
    encoladas = escanear_inactividad(repo, dias=_INACTIVIDAD_DIAS)
    desp = despachar_pendientes(repo, emisor)
    log.info("inactividad: %d recordatorios encolados · despacho=%s", len(encoladas), desp.get("conteo"))
    return {"encoladas": len(encoladas), "despacho": desp}


def job_sla(repo, emisor) -> dict:
    """SLA (Fase C): revisa vencimientos, encola recordatorios y los despacha."""
    encoladas = escanear_vencimientos(repo)
    desp = despachar_pendientes(repo, emisor)
    log.info("sla: %d recordatorios por vencimiento · despacho=%s", len(encoladas), desp.get("conteo"))
    return {"encoladas": len(encoladas), "despacho": desp}


def job_retencion(repo) -> dict:
    """Purga (o cuenta, en DRY_RUN) lo más viejo que RETENCION_DIAS."""
    res = repo.purgar_antiguos(config.RETENCION_DIAS, dry=config.DRY_RUN)
    log.info("retencion(%dd, dry=%s): %s", config.RETENCION_DIAS, config.DRY_RUN, res)
    return res


def construir_scheduler():
    """Arma el BlockingScheduler con los tres jobs. Devuelve (scheduler, repo)."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    repo = get_repo()
    emisor = emisor_desde_config()
    grafo = construir_grafo(repo, emisor)
    backend = "Supabase/Postgres" if isinstance(repo, RepositorioPostgres) else "SQLite (dev)"

    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(lambda: job_intake(repo, grafo, emisor), "interval",
                  seconds=config.POLL_SEGUNDOS, id="intake", max_instances=1,
                  coalesce=True, next_run_time=__import__("datetime").datetime.now())
    sched.add_job(lambda: job_inactividad(repo, emisor), "cron", hour=8, minute=0, id="inactividad")
    sched.add_job(lambda: job_sla(repo, emisor), "interval", minutes=60, id="sla")
    sched.add_job(lambda: job_retencion(repo), "cron", hour=3, minute=30, id="retencion")

    log.info("Scheduler listo | DB=%s | SMTP=%s | DRY_RUN=%s | poll=%ds",
             backend, "on" if config.hay_smtp() else "off", config.DRY_RUN, config.POLL_SEGUNDOS)
    return sched, repo


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sched, _ = construir_scheduler()
    print(f"\nMODO: {'DRY-RUN' if config.DRY_RUN else 'LIVE'} | "
          f"intake cada {config.POLL_SEGUNDOS}s | inactividad 08:00 UTC | retención 03:30 UTC")
    print("Ctrl+C para salir.\n")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        print("\nScheduler detenido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
