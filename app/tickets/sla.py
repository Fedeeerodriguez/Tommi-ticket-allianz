"""SLA de tickets Allianz (Fase C): parsea el plazo de la respuesta de Allianz y calcula el
vencimiento en días/horas HÁBILES (calendario laboral de México). Si Allianz no da plazo, usa
el default (72 h hábiles).

`holidays` es opcional: sin la librería, 'hábil' = lunes a viernes (sin feriados). Import perezoso.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import config

# "15 días hábiles", "72 horas", "2 días hábiles", "48 horas hábiles"
_RE_PLAZO = re.compile(r"(\d+)\s*(d[ií]as?|horas?)\s*(h[aá]biles?)?", re.I)
HORA_INI, HORA_FIN = 9, 18  # jornada laboral (para 'horas hábiles')

_FERIADOS = None


def _feriados_mx():
    global _FERIADOS
    if _FERIADOS is None:
        try:
            import holidays
            _FERIADOS = holidays.Mexico()
        except Exception:  # noqa: BLE001
            _FERIADOS = set()
    return _FERIADOS


def _es_habil(dt: datetime) -> bool:
    return dt.weekday() < 5 and dt.date() not in _feriados_mx()


def parsear_plazo(texto: str) -> Optional[tuple[int, str]]:
    """(cantidad, unidad) o None. unidad ∈ dias | dias_habiles | horas | horas_habiles."""
    if not texto:
        return None
    m = _RE_PLAZO.search(texto)
    if not m:
        return None
    n = int(m.group(1))
    base = "horas" if m.group(2).lower().startswith("hora") else "dias"
    if m.group(3):
        base += "_habiles"
    return n, base


def _sumar_dias_habiles(dt: datetime, n: int) -> datetime:
    d = dt
    while n > 0:
        d += timedelta(days=1)
        if _es_habil(d):
            n -= 1
    return d


def _sumar_horas_habiles(dt: datetime, n: int) -> datetime:
    d = dt
    restantes = n
    limite = 24 * 60 * 60  # tope de seguridad de iteraciones
    while restantes > 0 and limite > 0:
        d += timedelta(hours=1)
        limite -= 1
        if _es_habil(d) and HORA_INI <= d.hour < HORA_FIN:
            restantes -= 1
    return d


def calcular_vencimiento(desde: datetime, cantidad: int, unidad: str) -> datetime:
    if unidad == "dias":
        return desde + timedelta(days=cantidad)
    if unidad == "horas":
        return desde + timedelta(hours=cantidad)
    if unidad == "dias_habiles":
        return _sumar_dias_habiles(desde, cantidad)
    if unidad == "horas_habiles":
        return _sumar_horas_habiles(desde, cantidad)
    return desde


def vencimiento(plazos: list[str], desde: Optional[datetime] = None) -> datetime:
    """Vencimiento a partir del primer plazo parseable; si no hay, el default (72 h hábiles)."""
    desde = desde or datetime.now(timezone.utc)
    if desde.tzinfo is None:
        desde = desde.replace(tzinfo=timezone.utc)
    for p in (plazos or []):
        r = parsear_plazo(p)
        if r:
            return calcular_vencimiento(desde, r[0], r[1])
    return _sumar_horas_habiles(desde, config.SLA_DEFAULT_HORAS)


def vence_en_para(correo, clf) -> Optional[str]:
    """ISO del vencimiento para un correo de ticket, o None si es cierre / no aplica."""
    sub = getattr(clf, "subtipo", None)
    if not sub or sub == "cierre":
        return None
    plazos = (getattr(clf, "entidades", None) or {}).get("plazos")
    desde = getattr(correo, "fecha", None) or datetime.now(timezone.utc)
    return vencimiento(plazos, desde).isoformat()
