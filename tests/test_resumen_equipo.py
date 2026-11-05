"""Resumen para Ceci: una vez por día hábil, solo lo que la espera en el panel y solo si cambió (04/11:
salía cada 4 h, las 24 h, con el mismo contenido y borradores viejos)."""
from datetime import datetime

import pytest

from app import config
from app.db.repo import RepositorioSQLite
from app.resumen_equipo import MEXICO, construir_digest, enviar_resumen_equipo


class Emisor:
    def __init__(self):
        self.enviados = []

    def enviar(self, para, asunto, cuerpo):
        self.enviados.append((para, asunto, cuerpo))
        return {"ok": True}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RESUMEN_EQUIPO_EMAIL", "ceci@babilonia.ai")
    monkeypatch.setattr(config, "PANEL_URL", "https://tomi.babilonia.ai")
    return RepositorioSQLite(str(tmp_path / "t.sqlite"))


MARTES = datetime(2026, 11, 3, 9, 0, tzinfo=MEXICO)


def test_solo_lista_lo_que_espera_a_ceci_sin_borradores(repo):
    sol = repo.crear_ticket({"estado": "abierto", "etapa": "apertura", "poliza": "PLU3-1",
                             "cliente_nombre": "Ana Prueba"})
    viejo = repo.crear_ticket({"estado": "esperando_cliente", "asunto_hilo": "Invitación Oktoberfest"})
    repo.crear_accion(viejo, "enviar_a_allianz", "email", {"cuerpo": "historia clínica…"})
    asunto, cuerpo, _ = construir_digest(repo)
    assert "1 ticket Allianz te esperan" in asunto
    assert "Ana Prueba · PLU3-1: cliente/asesor sin identificar" in cuerpo
    assert f"tickets-allianz?ticket={sol}" in cuerpo
    assert "Oktoberfest" not in cuerpo and "historia clínica" not in cuerpo and "BORRADOR" not in cuerpo


def test_no_repite_el_mismo_resumen_ni_manda_vacio(repo):
    e = Emisor()
    assert enviar_resumen_equipo(repo, e, MARTES)["motivo"] == "nada que revisar"
    repo.crear_ticket({"estado": "abierto", "etapa": "apertura", "poliza": "PLU3-1"})
    assert enviar_resumen_equipo(repo, e, MARTES)["enviado"]
    assert enviar_resumen_equipo(repo, e, MARTES)["motivo"] == "igual al último resumen"
    repo.crear_ticket({"estado": "abierto", "etapa": "apertura", "poliza": "PLU3-2"})
    assert enviar_resumen_equipo(repo, e, MARTES)["enviado"] and len(e.enviados) == 2


def test_fin_de_semana_no_sale(repo):
    repo.crear_ticket({"estado": "abierto", "etapa": "apertura", "poliza": "PLU3-1"})
    sabado = datetime(2026, 11, 7, 9, 0, tzinfo=MEXICO)
    assert enviar_resumen_equipo(repo, Emisor(), sabado)["motivo"] == "fin de semana"


def test_el_scheduler_lo_corre_una_vez_por_dia_habil_y_no_al_arrancar(monkeypatch):
    from app import scheduler
    monkeypatch.setattr(config, "RESUMEN_EQUIPO_EMAIL", "ceci@babilonia.ai")
    monkeypatch.setattr(config, "RESUMEN_HORA_MX", 9)
    monkeypatch.setattr(config, "DATABASE_URL", "")
    monkeypatch.setattr(config, "NOTION_DB_SEGUIMIENTO", "")
    sched, _ = scheduler.construir_scheduler()
    job = sched.get_job("resumen_equipo")
    campos = {f.name: str(f) for f in job.trigger.fields}
    assert campos["day_of_week"] == "mon-fri" and campos["hour"] == "15" and campos["minute"] == "0"
