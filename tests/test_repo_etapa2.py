"""Etapa 2 — base: aprobaciones de Ceci (guía de aportación) y valores del worker."""
import pytest

from app.db.repo import RepositorioSQLite


@pytest.fixture
def repo(tmp_path):
    return RepositorioSQLite(str(tmp_path / "t.sqlite"))


def test_aprobacion_no_se_pide_dos_veces(repo):
    a = repo.crear_aprobacion(7, "guia_aportacion", "Guía v1", correo_id=3)
    assert a is not None
    assert repo.crear_aprobacion(7, "guia_aportacion", "Guía otra vez") is None
    assert repo.crear_aprobacion(7, "guia_aportacion", "Ronda 2", ronda=2) is not None
    ap = repo.obtener_aprobacion(a)
    assert (ap["estado"], ap["texto"], ap["version"], ap["correo_id"]) == ("pendiente", "Guía v1", 1, 3)


def test_resolver_es_atomico(repo):
    a = repo.crear_aprobacion(7, "guia_aportacion", "Guía v1")
    assert repo.resolver_aprobacion(a, "aprobada", "telegram:ceci")
    # El panel llega tarde: ya no está pendiente → no la vuelve a resolver.
    assert not repo.resolver_aprobacion(a, "descartada", "panel:ceci")
    ap = repo.obtener_aprobacion(a)
    assert (ap["estado"], ap["resuelto_por"], ap["version"]) == ("aprobada", "telegram:ceci", 1)
    assert ap["resuelto_en"]


def test_resolver_con_texto_corregido_sube_la_version(repo):
    a = repo.crear_aprobacion(7, "guia_aportacion", "Guía v1")
    assert repo.resolver_aprobacion(a, "aprobada", "panel:ceci", texto="Guía corregida")
    ap = repo.obtener_aprobacion(a)
    assert (ap["texto"], ap["version"]) == ("Guía corregida", 2)


def test_listar_y_actualizar(repo):
    a = repo.crear_aprobacion(7, "guia_aportacion", "x")
    b = repo.crear_aprobacion(8, "guia_aportacion", "y")
    repo.resolver_aprobacion(b, "descartada", "panel:ceci")
    assert [x["id"] for x in repo.listar_aprobaciones(estados=["pendiente"])] == [a]
    assert [x["id"] for x in repo.listar_aprobaciones(ticket_id=8)] == [b]
    repo.actualizar_aprobacion(a, telegram_msg_id="55", telegram_chat_id="99", texto="x2", version=2)
    ap = repo.obtener_aprobacion(a)
    assert (ap["telegram_msg_id"], ap["texto"], ap["version"]) == ("55", "x2", 2)


def test_valores(repo):
    assert repo.leer_valor("telegram_offset") is None
    repo.guardar_valor("telegram_offset", "10")
    repo.guardar_valor("telegram_offset", "11")
    assert repo.leer_valor("telegram_offset") == "11"
