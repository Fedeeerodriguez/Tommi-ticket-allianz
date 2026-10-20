"""Paso 4 — de punta a punta por el grafo: con MOTOR_ETAPAS el proceso largo usa el motor por etapa."""
import pytest

from app import config
from app.db.repo import RepositorioSQLite
from app.enriquecimiento import identificar as ident_mod
from app.grafo import construir_grafo
from app.models import Correo

from test_motor_etapas import C1, C3, SISTEMA, fila, notion

ALLIANZ_TK = "allianz.mexico@allianz.com.mx"


def correo(mid, asunto, cuerpo, remitente=ALLIANZ_TK):
    return Correo(mid, remitente, remitente.split("@")[1], ["hola@babilonia.ai"], [], asunto, cuerpo)


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "NOTION_TOKEN", "")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(config, "DRY_RUN", True)
    monkeypatch.setattr(config, "PANEL_URL", "")
    monkeypatch.setattr(ident_mod, "_buscador_notion", lambda: notion(fila()))
    repo = RepositorioSQLite(str(tmp_path / "t.sqlite"))
    return repo, construir_grafo(repo)


def test_con_motor_etapas_avisa_por_etapa_una_sola_vez(entorno, monkeypatch):
    monkeypatch.setattr(config, "MOTOR_ETAPAS", True)
    repo, g = entorno
    out = g.invoke({"correo": correo("m1", *C1), "despachar": False})
    assert "decidir_etapa" in out["ruta"]
    tk = out["ticket_id"]
    assert sorted(a["rol"] for a in out["acciones"]) == ["asesor", "ceci", "cliente"]
    assert repo.obtener_ticket(tk)["etapa"] == "apertura"

    out3 = g.invoke({"correo": correo("m3", *C3), "despachar": False})
    assert out3["ticket_id"] == tk and len(out3["acciones"]) == 3
    assert repo.obtener_ticket(tk)["estado"] == "esperando_cliente"
    # El mismo correo otra vez (idempotencia por message_id) → no pasa nada.
    assert g.invoke({"correo": correo("m3", *C3), "despachar": False})["fin"] == "duplicado"
    assert len(repo.listar_avisos(tk)) == 6 and len(repo.listar_acciones(tk)) == 6


def test_aviso_de_emision_se_engancha_al_ticket(entorno, monkeypatch):
    monkeypatch.setattr(config, "MOTOR_ETAPAS", True)
    repo, g = entorno
    tk = g.invoke({"correo": correo("m1", *C1), "despachar": False})["ticket_id"]
    em = correo("m9", "Aviso de emisión de póliza GMMI-101770 Hortencia Gonzalez Gama",
                "<html><body>Aviso de emisión</body></html>", "notificaciones.optimaxx@allianz.com.mx")
    out = g.invoke({"correo": em, "despachar": False})
    assert "emision" in out["ruta"] and out["ticket_id"] == tk
    assert sorted(a["rol"] for a in out["acciones"]) == ["asesor", "ceci", "cliente"]
    t = repo.obtener_ticket(tk)
    assert t["etapa"] == "poliza_emitida" and t["poliza"] == "GMMI-101770" and t["estado"] == "resuelto"


def test_emision_de_un_cliente_que_no_seguimos_no_crea_nada(entorno, monkeypatch):
    monkeypatch.setattr(config, "MOTOR_ETAPAS", True)
    repo, g = entorno
    em = correo("m9", "Aviso de emisión de póliza PLU3-429083 a nombre de Alejandra Rivero Macias",
                "<html><body>Aviso</body></html>", "notificaciones.optimaxx@allianz.com.mx")
    out = g.invoke({"correo": em, "despachar": False})
    assert out["fin"] == "emision_sin_ticket" and repo.listar_tickets() == []


@pytest.mark.parametrize("asunto,cuerpo", [
    ("Notificacion DAF. Solicitud: 25232893. Agente: 020981 / Fecha Solicitud", "Favor de enviar la documentación DAF."),
    ("Recordatorio de pago. Solicitud: 1859903", "Le recordamos que su pago vence el día 30."),
])
def test_avisos_automaticos_sin_ticket_no_crean_ticket(entorno, monkeypatch, asunto, cuerpo):
    monkeypatch.setattr(config, "MOTOR_ETAPAS", True)
    repo, g = entorno
    out = g.invoke({"correo": correo("m5", asunto, cuerpo, "aviso.electronico@allianz.com.mx"), "despachar": False})
    assert out["fin"] == "fuera_de_alcance" and repo.listar_tickets() == []


def test_aviso_automatico_delicado_sigue_a_ceci(entorno, monkeypatch):
    monkeypatch.setattr(config, "MOTOR_ETAPAS", True)
    repo, g = entorno
    out = g.invoke({"correo": correo("m6", "Notificacion Proceso de CANCELACION. Agente 020981",
                                     "Se informa la cancelación de la póliza.", "aviso.electronico@allianz.com.mx"),
                    "despachar": False})
    assert out.get("fin") != "fuera_de_alcance"


def test_sin_interruptor_sigue_el_motor_viejo(entorno, monkeypatch):
    monkeypatch.setattr(config, "MOTOR_ETAPAS", False)
    repo, g = entorno
    out = g.invoke({"correo": correo("m1", *C1), "despachar": False})
    assert "decidir" in out["ruta"] and "decidir_etapa" not in out["ruta"]
    assert repo.listar_avisos(out["ticket_id"]) == []
    assert repo.obtener_ticket(out["ticket_id"])["etapa"] is None
