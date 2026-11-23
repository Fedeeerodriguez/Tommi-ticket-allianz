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


def _lector(repo=None):
    """Gmail API / IMAP / carpeta de muestras, según la config."""
    return lector_desde_config(repo=repo)


def job_intake(repo, grafo, emisor, lector=None, fuente=None) -> dict:
    """Lee correos nuevos, los pasa por el grafo y despacha las acciones vencidas.

    `lector`/`fuente` se pueden inyectar (tests herméticos con correos de muestra); por
    defecto usa el lector real de la config (Gmail API / IMAP / carpeta de muestras)."""
    if lector is None:
        lector, fuente = _lector(repo)
    nuevos = 0
    for correo in lector.leer():
        try:
            grafo.invoke({"correo": correo, "despachar": False})
            nuevos += 1
        except Exception:  # noqa: BLE001
            correo.fallo = True  # el lector lo deja sin leer: se reintenta en el próximo ciclo
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


def job_recordatorios(repo, emisor) -> dict:
    """Etapa 1: recordatorios y escalamiento del proceso largo (solo con MOTOR_ETAPAS)."""
    from app.acciones.recordatorios import escanear_recordatorios
    res = escanear_recordatorios(repo)
    desp = despachar_pendientes(repo, emisor) if res["plan"] else {"conteo": {}}
    log.info("recordatorios: %s recordados · %s escalados · %s cortados%s · despacho=%s",
             len(res["recordados"]), len(res["escalados"]), len(res["cortados"]),
             " (fuera de horario)" if res["fuera_de_horario"] else "", desp.get("conteo"))
    return {**res, "despacho": desp}


def job_telegram(repo, emisor) -> dict:
    """Telegram: guías de aportación y correos retenidos para Ceci/Jime + sus botones (Autorizar / Modificar)."""
    from app.rieles import telegram
    if not config.hay_telegram():  # falta el chat de Ceci/Jime: solo se contesta "/start" con su chat id
        return telegram.procesar_updates(repo)
    enviadas = telegram.enviar_pendientes(repo) + telegram.enviar_acciones(repo)
    res = telegram.procesar_updates(repo)
    desp = despachar_pendientes(repo, emisor) if res["plan"] else {"conteo": {}}
    if enviadas or res["botones"] or res["correcciones"]:
        log.info("telegram: %d guías enviadas · %d botones · %d correcciones · despacho=%s",
                 enviadas, len(res["botones"]), len(res["correcciones"]), desp.get("conteo"))
    return {**res, "enviadas": enviadas, "despacho": desp}


def job_retencion(repo) -> dict:
    """Purga (o cuenta, en DRY_RUN) lo más viejo que RETENCION_DIAS."""
    res = repo.purgar_antiguos(config.RETENCION_DIAS, dry=config.DRY_RUN)
    log.info("retencion(%dd, dry=%s): %s", config.RETENCION_DIAS, config.DRY_RUN, res)
    return res


def job_resumen_equipo(repo) -> dict:
    """Resumen diario para Ceci con lo que la espera en el panel (opt-in)."""
    from app.resumen_equipo import enviar_resumen_equipo
    res = enviar_resumen_equipo(repo)
    log.info("resumen_equipo: %s", res.get("motivo") or ("enviado a " + str(res.get("destino"))))
    return res


def job_cobranza_resumen(repo, emisor) -> dict:
    """Resumen diario de cobranza (COBRANZA_MODO=resumen): correo con Excel a Yans + WhatsApp a Ceci (sin asesor)."""
    from app.acciones import cobranza_resumen
    res = cobranza_resumen.armar_resumen(repo)
    if res.get("whatsapp_encolados"):
        despachar_pendientes(repo, emisor)
    return res


def job_cobranza_asesores(repo, emisor) -> dict:
    """Martes y jueves: a cada asesor, un correo con sus clientes con cargo rechazado + un WhatsApp con la cantidad."""
    from app.acciones import cobranza_resumen
    res = cobranza_resumen.armar_resumen_asesores(repo)
    if res.get("whatsapp_encolados"):
        despachar_pendientes(repo, emisor)
    return res


def job_seguimiento_notion(repo) -> dict:
    """Sandbox: sincroniza el panel de revisión 'Ticket Allianz Seguimiento' en Notion (opt-in)."""
    from app.registro import sincronizar_seguimiento
    res = sincronizar_seguimiento(repo)
    log.info("seguimiento_notion: %s", res)
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
    if config.MOTOR_ETAPAS:
        sched.add_job(lambda: job_recordatorios(repo, emisor), "interval", minutes=30, id="recordatorios")
        if config.hay_bot_telegram():  # Etapa 2: aprobación de la guía (sin chats todavía: solo "/start")
            sched.add_job(lambda: job_telegram(repo, emisor), "interval", seconds=15, id="telegram",
                          max_instances=1, coalesce=True)
    # Cobranza en modo resumen: lo acumulado sale una vez por día hábil (el lunes incluye el fin de semana).
    from app.acciones import cobranza, cobranza_resumen
    if cobranza.activo() and cobranza_resumen.activo():
        sched.add_job(lambda: job_cobranza_resumen(repo, emisor), "cron", day_of_week="mon-fri",
                      hour=(config.COBRANZA_RESUMEN_HORA_MX + 6) % 24, minute=0, id="cobranza_resumen")
        sched.add_job(lambda: job_cobranza_asesores(repo, emisor), "cron", day_of_week=config.COBRANZA_ASESOR_DIAS,
                      hour=(config.COBRANZA_ASESOR_HORA_MX + 6) % 24, minute=5, id="cobranza_asesores")
    # Resumen para Ceci: una vez por día hábil a RESUMEN_HORA_MX (México = UTC-6), solo si cambió algo.
    # No corre al arrancar: antes cada deploy le mandaba uno más.
    if config.RESUMEN_EQUIPO_EMAIL:
        sched.add_job(lambda: job_resumen_equipo(repo), "cron", day_of_week="mon-fri",
                      hour=(config.RESUMEN_HORA_MX + 6) % 24, minute=0, id="resumen_equipo")
    # Sandbox: panel de revisión en Notion (solo si NOTION_DB_SEGUIMIENTO está configurado).
    if config.NOTION_DB_SEGUIMIENTO:
        sched.add_job(lambda: job_seguimiento_notion(repo), "interval", minutes=15,
                      id="seguimiento_notion",
                      next_run_time=__import__("datetime").datetime.now())

    log.info("Scheduler listo | DB=%s | SMTP=%s | DRY_RUN=%s | poll=%ds",
             backend, "on" if config.hay_smtp() else "off", config.DRY_RUN, config.POLL_SEGUNDOS)
    if not config.DRY_RUN:
        from app.envio import interruptor
        est = interruptor.estado(repo)["procesos"]
        log.info("envío real por proceso: %s",
                 ", ".join(f"{p}={'SI' if e['real'] else 'no'} ({e['origen']})" for p, e in est.items()))
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
