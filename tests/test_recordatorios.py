"""Paso 6 — recordatorios y escalamiento con reloj simulado (hora de CDMX = UTC-6)."""
import json
from datetime import datetime, timezone

import pytest

from app import config
from app.acciones import despachar_pendientes
from app.acciones.criticas import autorizar_ticket
from app.acciones.motor import escanear_inactividad, escanear_vencimientos
from app.acciones.motor_etapas import decidir_por_etapa
from app.acciones.recordatorios import en_horario, escanear_recordatorios
from app.db.repo import RepositorioSQLite

from test_motor_etapas import C1, C3, C4, C5, et, fila, notion


def utc(d, h, m=0, mes=10):
    return datetime(2026, mes, d, h, m, tzinfo=timezone.utc)


VIERNES = utc(23, 15)  # viernes 23/10 09:00 CDMX


@pytest.fixture(autouse=True)
def aislado(monkeypatch):
    monkeypatch.setattr(config, "MOTOR_ETAPAS", True)
    monkeypatch.setattr(config, "NOTION_TOKEN", "")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(config, "DRY_RUN", True)
    monkeypatch.setattr(config, "PANEL_URL", "")
    monkeypatch.setattr(config, "ESCALA_CC", ["penny.ortiz@allianz.com.mx"])
    monkeypatch.setattr(config, "ESCALAR_A_ALLIANZ", True)
    monkeypatch.setattr(config, "ALLIANZ_DEST", "allianz.mexico@allianz.com.mx", raising=False)
    monkeypatch.setattr(config, "WATI_PLANTILLA_ETAPAS", "")


@pytest.fixture
def repo(tmp_path):
    return RepositorioSQLite(str(tmp_path / "t.sqlite"))


def ticket_con(repo, *correos, ahora=VIERNES, buscar=None, nro="2576612"):
    tk = repo.crear_ticket({"nro_ticket": nro, "estado": "abierto"})
    for i, c in enumerate(correos, 1):
        decidir_por_etapa(repo, tk, et(c), correo_id=i, ahora=ahora, buscar=buscar or notion(fila()))
    return tk


def avisos(repo, tk, prefijo):
    return sorted((a["etapa"], a["destinatario"]) for a in repo.listar_avisos(tk) if a["etapa"].startswith(prefijo))


def rec(repo, tk, motivo):
    return next(r for r in repo.listar_recordatorios(tk) if r["motivo"] == motivo)


def test_viernes_a_lunes_y_escalado_sin_repetir(repo):
    tk = ticket_con(repo, C1, C3)
    assert rec(repo, tk, "requerimiento")["vence_en"].startswith("2026-10-28T15:00")  # vie → mié (sin fin de semana)
    assert escanear_recordatorios(repo, utc(26, 16))["recordados"] == []           # lunes: todavía no
    r = escanear_recordatorios(repo, utc(28, 15, 30))
    assert r["recordados"] and avisos(repo, tk, "recordatorio") == [
        ("recordatorio_requerimiento", "asesor"), ("recordatorio_requerimiento", "cliente")]
    cli = next(a for a in r["plan"] if a["rol"] == "cliente")
    assert "sigue esperando: la carta laboral firmada" in cli["mensaje"]
    assert escanear_recordatorios(repo, utc(28, 17))["plan"] == []                 # no se repite
    assert escanear_recordatorios(repo, utc(29, 15))["escalados"] == []           # 24 h hábiles desde el recordatorio
    e = escanear_recordatorios(repo, utc(29, 16))
    assert e["escalados"] and avisos(repo, tk, "escalado") == [
        ("escalado_requerimiento", "asesor"), ("escalado_requerimiento", "ceci")]
    assert not any(a["tipo_accion"] == "escalar_allianz" for a in e["plan"])     # Allianz espera a nosotros
    assert escanear_recordatorios(repo, utc(30, 16))["plan"] == []                 # escalado una sola vez


def test_feriado_no_cuenta(repo):
    tk = ticket_con(repo, C1, C3, ahora=utc(13, 15, mes=11))  # vie 13/11; lun 16/11 es feriado (Revolución)
    assert rec(repo, tk, "requerimiento")["vence_en"].startswith("2026-11-19T15:00")


def test_c4_corta_a_tiempo_y_escala_a_allianz_para_aprobar(repo):
    tk = ticket_con(repo, C1, C3)
    decidir_por_etapa(repo, tk, et(C4), correo_id=3, ahora=utc(26, 16), buscar=notion(fila()))
    assert escanear_recordatorios(repo, utc(28, 16))["plan"] == []                 # el requerimiento ya se cumplió
    assert rec(repo, tk, "requerimiento")["estado"] == "cumplido"
    assert rec(repo, tk, "esperando_allianz")["vence_en"].startswith("2026-10-29T16:00")
    r = escanear_recordatorios(repo, utc(29, 16, 30))
    assert [a["rol"] for a in r["plan"]] == ["ceci"] and "Allianz no responde" in r["plan"][0]["mensaje"]
    e = escanear_recordatorios(repo, utc(30, 17))
    correo = next(a for a in e["plan"] if a["tipo_accion"] == "escalar_allianz")
    assert correo["cc"] == ["penny.ortiz@allianz.com.mx"] and "no hemos recibido respuesta" in correo["cuerpo"]
    assert any(a["rol"] == "ceci" and "para que lo apruebes" in a["mensaje"] for a in e["plan"])

    # Despacho: el correo a Allianz queda retenido hasta que Ceci lo aprueba.
    despachar_pendientes(repo)
    esc = next(a for a in repo.listar_acciones(tk) if a["tipo_accion"] == "escalar_allianz")
    assert esc["estado"] == "pendiente_ceci"
    assert any(a["tipo_accion"] == "visto_bueno_ceci" for a in repo.listar_acciones(tk))
    autorizar_ticket(repo, tk)
    despachar_pendientes(repo)
    esc = next(a for a in repo.listar_acciones(tk) if a["tipo_accion"] == "escalar_allianz")
    res = json.loads(esc["resultado"])
    assert esc["estado"] == "simulada" and res["cc"] == ["penny.ortiz@allianz.com.mx"]  # DRY_RUN


def test_otra_escalacion_tambien_pide_aprobacion_aunque_el_ticket_ya_este_autorizado(repo):
    tk = ticket_con(repo, C1, C3, C4)
    repo.actualizar_ticket(tk, autorizado=1)  # Ceci aprobó algo antes
    escanear_recordatorios(repo, utc(28, 16))
    escanear_recordatorios(repo, utc(29, 17))
    despachar_pendientes(repo)
    esc = next(a for a in repo.listar_acciones(tk) if a["tipo_accion"] == "escalar_allianz")
    assert esc["estado"] == "pendiente_ceci"


def test_fuera_de_horario_espera(repo):
    tk = ticket_con(repo, C1, C3)
    assert escanear_recordatorios(repo, utc(31, 16))["fuera_de_horario"]   # sábado
    assert escanear_recordatorios(repo, utc(29, 3))["fuera_de_horario"]    # mié 21:00 CDMX
    assert avisos(repo, tk, "recordatorio") == []
    assert en_horario(utc(28, 15)) and not en_horario(utc(28, 14)) and not en_horario(utc(16, 16, mes=11))


def test_ticket_cerrado_corta_lo_que_quede(repo):
    tk = ticket_con(repo, C1, C3)
    repo.actualizar_ticket(tk, estado="resuelto")  # cerrado a mano
    r = escanear_recordatorios(repo, utc(28, 16))
    assert r["cortados"] and r["plan"] == [] and rec(repo, tk, "requerimiento")["estado"] == "cancelado"


def test_c5_antes_de_vencer_no_recuerda_nada(repo):
    tk = ticket_con(repo, C1, C3, C5)
    assert escanear_recordatorios(repo, utc(30, 16))["plan"] == []


def test_sin_identificar_el_recordatorio_va_a_ceci(repo):
    tk = ticket_con(repo, C1, C3, buscar=notion())
    r = escanear_recordatorios(repo, utc(28, 16))
    assert [a["rol"] for a in r["plan"]] == ["ceci"]
    assert "No hay cliente/asesor identificado" in r["plan"][0]["mensaje"]


def test_los_escaneos_viejos_no_tocan_tickets_con_etapa(repo):
    tk = ticket_con(repo, C1, C3)
    repo.actualizar_ticket(tk, vence_en="2026-10-01T00:00:00+00:00")
    repo.conn.execute("update tickets set ultima_actividad='2026-01-01 00:00:00' where id=?", (tk,))
    repo.conn.commit()
    assert escanear_inactividad(repo, dias=3) == [] and escanear_vencimientos(repo) == []


def test_encendido_gradual_sin_correo_a_allianz(repo, monkeypatch):
    monkeypatch.setattr(config, "ESCALAR_A_ALLIANZ", False)
    tk = ticket_con(repo, C1, C3, C4)
    escanear_recordatorios(repo, utc(28, 16))
    e = escanear_recordatorios(repo, utc(29, 17))
    assert [a["tipo_accion"] for a in e["plan"]] == ["avisar_ceci"]
    assert "Conviene escribirles en el hilo" in e["plan"][0]["mensaje"]
    assert not any(a["tipo_accion"] == "escalar_allianz" for a in repo.listar_acciones(tk))


def test_encendido_gradual_primero_ceci_y_asesor(repo, monkeypatch):
    monkeypatch.setattr(config, "MOTOR_ETAPAS_ROLES", ["ceci", "asesor"])
    tk = ticket_con(repo, C1, C3)
    assert sorted(a["destinatario"] for a in repo.listar_avisos(tk)) == ["asesor", "asesor", "ceci", "ceci"]
    r = escanear_recordatorios(repo, utc(28, 16))
    assert [a["rol"] for a in r["plan"]] == ["asesor"]  # al cliente todavía no
    ceci = [a for a in repo.listar_avisos(tk) if a["destinatario"] == "ceci"]
    assert not any("cliente" in (a["texto"] or "") and "⚠️" in (a["texto"] or "") for a in ceci)


def test_ya_le_recordamos_al_cliente_solo_si_salio(repo):
    tk = ticket_con(repo, C1, C3, buscar=notion(fila(tel_cliente=None)))
    r = escanear_recordatorios(repo, utc(28, 16))
    ases = next(a for a in r["plan"] if a["rol"] == "asesor")
    assert "Ya le recordamos" not in ases["mensaje"]
    tk2 = ticket_con(repo, C1, C3, nro="2576613")
    r2 = escanear_recordatorios(repo, utc(28, 16, 30))
    assert any(a["rol"] == "asesor" and a["mensaje"].endswith("Ya le recordamos al cliente.") for a in r2["plan"])
    assert tk and tk2
