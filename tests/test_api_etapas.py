"""Paso 7 — panel: etapa, próximo recordatorio, línea de tiempo, 'Para Ceci' y asignación manual."""
import pytest
from fastapi.testclient import TestClient

from app import api, config
from app.acciones.motor_etapas import decidir_por_etapa
from app.acciones.recordatorios import escanear_recordatorios
from app.db.repo import RepositorioSQLite

from test_motor_etapas import C1, C3, C4, LUNES, et, fila, notion
from test_recordatorios import utc


@pytest.fixture
def cli(tmp_path, monkeypatch):
    for k, v in (("MOTOR_ETAPAS", True), ("NOTION_TOKEN", ""), ("OPENAI_API_KEY", ""), ("DRY_RUN", True),
                 ("PANEL_URL", ""), ("API_TOKEN", "")):
        monkeypatch.setattr(config, k, v)
    repo = RepositorioSQLite(str(tmp_path / "t.sqlite"))
    monkeypatch.setattr(api, "_repo", repo)
    return TestClient(api.app), repo


def nuevo(repo, nro, *correos, buscar=None):
    tk = repo.crear_ticket({"nro_ticket": nro, "estado": "abierto"})
    for i, c in enumerate(correos, 1):
        decidir_por_etapa(repo, tk, et(c), correo_id=i, ahora=LUNES, buscar=buscar or notion(fila()))
    return tk


def test_lista_trae_etapa_y_proximo_recordatorio(cli):
    c, repo = cli
    tk = nuevo(repo, "2576612", C1, C3)
    item = next(i for i in c.get("/api/tickets-allianz").json()["items"] if i["id"] == tk)
    assert item["etapa"] == "requerimiento" and item["etapa_nombre"] == "Allianz pide documentos"
    assert item["proximo_recordatorio"]["que"] == "recuerda"
    assert item["proximo_recordatorio"]["a_quien"] == ["cliente", "asesor"]
    assert item["identificado_por"] == "solicitud" and item["para_ceci"] == []


def test_para_ceci_sin_identificar_y_asignacion_manual(cli):
    c, repo = cli
    ok = nuevo(repo, "1", C1)
    sin = nuevo(repo, "2", C1, buscar=notion())
    r = c.get("/api/tickets-allianz", params={"filtro": "para_ceci"}).json()
    assert [i["id"] for i in r["items"]] == [sin] and r["items"][0]["para_ceci"] == ["sin_identificar"]
    assert c.put(f"/api/tickets-allianz/{sin}/identificacion", json={"cliente_nombre": "Ana"}).status_code == 400
    put = c.put(f"/api/tickets-allianz/{sin}/identificacion",
                json={"cliente_nombre": "Ana Pérez", "telefono_cliente": "5511112222", "telefono_asesor": "5533334444"})
    assert put.status_code == 200
    assert c.get("/api/tickets-allianz", params={"filtro": "para_ceci"}).json()["items"] == []
    # Desde ahí el ticket usa lo que asignó Ceci (no vuelve a buscar en Notion).
    res = decidir_por_etapa(repo, sin, et(C3), correo_id=9, ahora=LUNES, buscar=notion())
    assert sorted(a["rol"] for a in res["plan"]) == ["asesor", "ceci", "cliente"]
    assert next(a for a in res["plan"] if a["rol"] == "cliente")["numero"] == "5511112222"
    assert ok


@pytest.mark.parametrize("destino,motivo", [("allianz.mexico@allianz.com.mx", "para_aprobar"),
                                            ("", "escalacion_bloqueada")])
def test_para_ceci_escalado_y_para_aprobar(cli, monkeypatch, destino, motivo):
    monkeypatch.setattr(config, "ALLIANZ_DEST", destino, raising=False)
    c, repo = cli
    tk = nuevo(repo, "3", C1, C3, C4)
    escanear_recordatorios(repo, utc(22, 16))
    escanear_recordatorios(repo, utc(23, 17))
    from app.acciones import despachar_pendientes
    despachar_pendientes(repo)
    item = c.get("/api/tickets-allianz", params={"filtro": "para_ceci"}).json()["items"][0]
    assert item["id"] == tk and set(item["para_ceci"]) == {"escalado", motivo}


def test_linea_de_tiempo(cli):
    c, repo = cli
    tk = nuevo(repo, "4", C1, C3, C4)
    lt = c.get(f"/api/tickets-allianz/{tk}/linea-tiempo").json()
    assert [p["etapa"] for p in lt["pasos"]] == ["apertura", "requerimiento", "documentos_enviados"]
    assert sorted(a["para"] for a in lt["pasos"][1]["avisos"]) == ["asesor", "ceci", "cliente"]
    assert {(r["motivo"], r["estado"]) for r in lt["recordatorios"]} == {
        ("requerimiento", "cumplido"), ("esperando_allianz", "activo")}
    assert lt["ticket"]["etapa_nombre"] == "Documentos enviados a Allianz"
    assert c.get("/api/tickets-allianz/999/linea-tiempo").status_code == 404


def test_panel_no_se_rompe_sin_las_tablas_nuevas(cli, monkeypatch):
    c, repo = cli
    nuevo(repo, "5", C1)

    def sin_tabla(*a, **k):
        raise RuntimeError('relation "tickets_allianz.recordatorios" does not exist')
    monkeypatch.setattr(repo, "listar_recordatorios", sin_tabla)
    monkeypatch.setattr(repo, "listar_avisos", sin_tabla)
    r = c.get("/api/tickets-allianz")
    assert r.status_code == 200 and r.json()["items"][0]["proximo_recordatorio"] is None
