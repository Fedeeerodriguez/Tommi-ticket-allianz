"""Etapa 1 — base de datos: etapa del ticket, avisos que no se repiten y recordatorios."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.db.repo import RepositorioSQLite

AHORA = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def repo(tmp_path):
    return RepositorioSQLite(str(tmp_path / "t.sqlite"))


@pytest.fixture
def tk(repo):
    return repo.crear_ticket({"nro_ticket": "2576612", "estado": "abierto", "proceso": "largo",
                              "producto": "GMMI", "etapa": "apertura", "etapa_desde": AHORA,
                              "nro_solicitud": "1950110"})


def test_ticket_guarda_la_etapa(repo, tk):
    t = repo.obtener_ticket(tk)
    assert (t["proceso"], t["producto"], t["etapa"], t["nro_solicitud"]) == ("largo", "GMMI", "apertura", "1950110")
    assert t["etapa_ronda"] == 1  # default
    assert repo.buscar_ticket_por_solicitud("1950110")["id"] == tk
    assert repo.buscar_ticket_por_solicitud("999") is None


def test_ticket_sin_datos_de_etapa_sigue_funcionando(repo):
    tid = repo.crear_ticket({"nro_ticket": "1", "estado": "abierto"})
    assert repo.obtener_ticket(tid)["etapa"] is None


def test_aviso_no_se_repite(repo, tk):
    a = repo.registrar_aviso(tk, "apertura", "asesor", canal="wati", texto="hola")
    assert a is not None
    assert repo.registrar_aviso(tk, "apertura", "asesor", canal="wati", texto="hola otra vez") is None
    assert repo.registrar_aviso(tk, "apertura", "cliente") is not None   # otro destinatario sí
    assert repo.registrar_aviso(tk, "requerimiento", "asesor") is not None  # otra etapa sí
    assert len(repo.listar_avisos(tk)) == 3


def test_requerimiento_nuevo_tras_c4_avisa_de_nuevo_con_otra_ronda(repo, tk):
    assert repo.registrar_aviso(tk, "requerimiento", "cliente", ronda=1)
    assert repo.registrar_aviso(tk, "requerimiento", "cliente", ronda=1) is None
    assert repo.registrar_aviso(tk, "requerimiento", "cliente", ronda=2)


def test_un_solo_recordatorio_vivo_por_motivo(repo, tk):
    r1 = repo.crear_recordatorio(tk, "requerimiento", ["cliente", "asesor"], AHORA + timedelta(days=3),
                                 AHORA + timedelta(days=4))
    assert r1 is not None
    assert repo.crear_recordatorio(tk, "requerimiento", ["cliente"], AHORA + timedelta(days=5)) is None
    assert repo.crear_recordatorio(tk, "esperando_allianz", ["ceci"], AHORA + timedelta(days=3)) is not None
    (r,) = repo.listar_recordatorios(tk, estados=["activo"])[:1]
    assert r["destinatarios"] == ["cliente", "asesor"] and r["vence_en"].startswith("2026-10-22T15:00")


def test_escalado_sigue_vivo_y_bloquea_otro(repo, tk):
    r1 = repo.crear_recordatorio(tk, "requerimiento", ["cliente"], AHORA)
    repo.actualizar_recordatorio(r1, estado="escalado", escalado_en=AHORA)
    assert repo.crear_recordatorio(tk, "requerimiento", ["cliente"], AHORA) is None


def test_cerrar_recordatorios_libera_el_motivo(repo, tk):
    repo.crear_recordatorio(tk, "requerimiento", ["cliente"], AHORA)
    repo.crear_recordatorio(tk, "esperando_allianz", ["ceci"], AHORA)
    assert repo.cerrar_recordatorios(tk, "cumplido", motivo="requerimiento", nota="llegó C4") == 1
    assert [r["motivo"] for r in repo.listar_recordatorios(tk, estados=["activo"])] == ["esperando_allianz"]
    hecho = repo.listar_recordatorios(tk, estados=["cumplido"])[0]
    assert hecho["nota"] == "llegó C4" and hecho["cerrado_en"]
    # liberado: se puede arrancar uno nuevo (nuevo requerimiento)
    assert repo.crear_recordatorio(tk, "requerimiento", ["cliente"], AHORA) is not None
    assert repo.cerrar_recordatorios(tk, "cancelado") == 2  # corta todos los vivos


def test_base_vieja_de_dev_suma_las_columnas(tmp_path):
    ruta = str(tmp_path / "vieja.sqlite")
    c = sqlite3.connect(ruta)
    c.execute("create table tickets(id integer primary key autoincrement, nro_ticket text unique, poliza text, "
              "cliente_nombre text, cliente_correo text, asesor_correo text, daf text, estado text, "
              "delicado int, autorizado int, abierto_por text, gmail_thread_id text, asunto_hilo text, "
              "ultimo_message_id text, vence_en text, telefono_cliente text, telefono_asesor text, "
              "ultima_actividad text, created_at text default (datetime('now')))")
    c.execute("insert into tickets(nro_ticket, estado) values('9', 'abierto')")
    c.commit(); c.close()
    repo = RepositorioSQLite(ruta)
    t = repo.listar_tickets()[0]
    assert t["nro_ticket"] == "9" and "etapa" in t and "nro_solicitud" in t
