"""Plazos hábiles: se cuentan con el calendario y el horario de oficina de CDMX, no en UTC."""
from datetime import datetime, timedelta, timezone

from app import config
from app.tickets import sla


def mx(d):
    return d.astimezone(timezone.utc).replace(tzinfo=None) + timedelta(hours=config.UTC_OFFSET_MX)


def utc_desde_mx(*a):
    return (datetime(*a) - timedelta(hours=config.UTC_OFFSET_MX)).replace(tzinfo=timezone.utc)


def test_viernes_a_la_noche_mas_3_dias_habiles_es_el_miercoles():
    # Viernes 23/10 20:00 CDMX ya es sábado en UTC: antes daba el martes.
    v = sla.calcular_vencimiento(utc_desde_mx(2026, 10, 23, 20), 3, "dias_habiles")
    assert mx(v) == datetime(2026, 10, 28, 20)


def test_horas_habiles_en_horario_de_oficina_de_cdmx():
    desde = utc_desde_mx(2026, 10, 22, 10)  # jueves 10:00 CDMX
    assert mx(sla.calcular_vencimiento(desde, 8, "horas_habiles")) == datetime(2026, 10, 22, 18)
    assert mx(sla.calcular_vencimiento(desde, 9, "horas_habiles")) == datetime(2026, 10, 23, 10)
