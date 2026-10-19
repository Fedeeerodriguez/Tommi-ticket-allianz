"""Paso 5 — textos fijos por etapa + plantilla WATI 'actualización de trámite'."""
import re
from datetime import datetime, timezone

import pytest

from app import config
from app.acciones import despachar_pendientes
from app.acciones import mensajes_etapa as M
from app.acciones.despacho import params_plantilla_etapas
from app.acciones.motor_etapas import decidir_por_etapa
from app.db.repo import RepositorioSQLite

from test_motor_etapas import C1, C3, LUNES, et, fila, notion

ETAPA_EJEMPLO = {"etapa": "requerimiento", "nro_ticket": "2576612", "producto": "GMMI", "nro_solicitud": "1950110",
                 "cliente": "HORTENCIA GONZALEZ GAMA", "que_piden": "la carta laboral firmada " * 30,
                 "plazo": (15, "dias_habiles"), "mensaje": "Adjunto la hoja membretada", "poliza": "GMMI-101770"}


@pytest.fixture(autouse=True)
def aislado(monkeypatch):
    monkeypatch.setattr(config, "NOTION_TOKEN", "")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(config, "DRY_RUN", True)
    monkeypatch.setattr(config, "PANEL_URL", "")
    monkeypatch.setattr(config, "CECI_WHATSAPP", "")
    monkeypatch.setattr(config, "WATI_PLANTILLA_ETAPAS", "")


@pytest.mark.parametrize("etapa", sorted(M.TEXTOS))
@pytest.mark.parametrize("rol", ["ceci", "asesor", "cliente"])
def test_todos_los_textos_se_completan(etapa, rol):
    ctx = M.contexto({}, {**ETAPA_EJEMPLO, "etapa": etapa}, {"cliente_nombre": "Hortencia González Gama"},
                     datetime(2026, 10, 22, tzinfo=timezone.utc))
    t = M.texto(rol, etapa, ctx, ["Falta el teléfono del asesor en Notion: no se le avisó."])
    if t is None:
        assert rol != "ceci"
        return
    assert not re.search(r"\{\w+\}", t), t          # sin huecos sin llenar
    assert len(t) <= 1024                           # tope de un parámetro de plantilla WhatsApp
    if rol == "cliente":
        assert t.startswith("Hola Hortencia,")


def test_rechazo_y_declinado_no_tienen_texto_para_el_cliente():
    for etapa in ("rechazado", "declinado", "nota_ejecutiva", "rebote_ticket_cerrado"):
        assert M.texto("cliente", etapa, M.contexto({}, ETAPA_EJEMPLO)) is None


def test_que_piden_se_recorta_y_el_plazo_se_lee():
    ctx = M.contexto({}, ETAPA_EJEMPLO, vence=datetime(2026, 10, 22, tzinfo=timezone.utc))
    assert len(ctx["que_piden"]) <= M.MAX_QUE_PIDEN and ctx["que_piden"].endswith("…")
    assert ctx["plazo"] == "15 días hábiles" and ctx["fecha"] == "22/10/2026"
    assert ctx["producto"] == "Gastos médicos" and ctx["producto_cliente"] == "gastos médicos"
    assert M.contexto({}, {**ETAPA_EJEMPLO, "producto": "PLU3"})["producto_cliente"] == "OptiMaxx Plus"


@pytest.mark.parametrize("pedido,queda", [
    ("Favor de enviar la carta laboral firmada", "la carta laboral firmada"),
    ("Le solicitamos su apoyo proporcionar el RFC del contratante", "el RFC del contratante"),
    ("Por favor de anexar la identificación oficial vigente", "la identificación oficial vigente"),
    ("Favor de firmar el formato de pago", "firmar el formato de pago"),
    ("La identificación no coincide con el nombre", "La identificación no coincide con el nombre"),
])
def test_pedido_se_lee_bien(pedido, queda):
    assert M.contexto({}, {**ETAPA_EJEMPLO, "que_piden": pedido})["que_piden"] == queda


def test_cliente_sin_nombre_no_dice_hola_vacio():
    ctx = M.contexto({}, {**ETAPA_EJEMPLO, "cliente": None})
    assert M.texto("cliente", "apertura", ctx).startswith("Hola, tu solicitud")


def test_link_al_panel_en_el_aviso_a_ceci(monkeypatch):
    monkeypatch.setattr(config, "PANEL_URL", "https://panel.babilonia.ai/")
    ctx = {**M.contexto({}, ETAPA_EJEMPLO), "ticket_id": 7}
    assert M.texto("ceci", "apertura", ctx).endswith("Panel: https://panel.babilonia.ai/tickets/7")


def test_params_de_la_plantilla_segun_la_config(monkeypatch):
    monkeypatch.setattr(config, "WATI_PARAMS_ETAPAS", ["1=ticket", "2=tramite", "nombre=cliente", "mensaje"])
    pay = {"mensaje": "hola", "params": {"ticket": "2576612", "tramite": "Gastos médicos · Allianz pide documentos",
                                         "cliente": "Hortencia"}}
    assert params_plantilla_etapas(pay) == {"1": "2576612", "2": "Gastos médicos · Allianz pide documentos",
                                            "nombre": "Hortencia", "mensaje": "hola"}


def _flujo(tmp_path):
    repo = RepositorioSQLite(str(tmp_path / "t.sqlite"))
    tk = repo.crear_ticket({"nro_ticket": "2576612", "estado": "abierto"})
    decidir_por_etapa(repo, tk, et(C1), correo_id=1, ahora=LUNES, buscar=notion(fila()))
    return repo, tk


def test_despacho_con_plantilla_de_etapas(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WATI_PLANTILLA_ETAPAS", "actualizacion_tramite")
    monkeypatch.setattr(config, "CECI_WHATSAPP", "5215500000000")
    repo, tk = _flujo(tmp_path)
    res = despachar_pendientes(repo)
    assert res["conteo"] == {"simulada": 3}  # DRY_RUN: se compone pero no sale
    for a in repo.listar_acciones(tk):
        r = a["resultado"] if isinstance(a["resultado"], dict) else __import__("json").loads(a["resultado"])
        assert r["plantilla"] == "actualizacion_tramite"
        assert r["params"]["ticket"] == "2576612" and "Solicitud abierta" in r["params"]["tramite"]
        assert r["params"]["cliente"] == "Hortencia González Gama" and r["params"]["mensaje"]


def test_despacho_sin_plantilla_de_etapas_usa_la_de_cada_rol(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WATI_PLANTILLA_ASESOR", "avances")
    repo, tk = _flujo(tmp_path)
    res = despachar_pendientes(repo)
    assert res["conteo"] == {"simulada": 2, "pendiente_wati": 1}  # Ceci sin número configurado
    ases = next(a for a in repo.listar_acciones(tk) if a["tipo_accion"] == "avisar_asesor")
    r = __import__("json").loads(ases["resultado"])
    assert r["plantilla"] == "avances" and list(r["params"]) == ["mensaje"]
