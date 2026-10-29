"""Cargo rechazado ("Notificación de Cobranza") → aviso al asesor y a Ceci, nunca al cliente."""
import pytest

from app import config
from app.acciones import cobranza
from app.db.repo import RepositorioSQLite
from app.enriquecimiento import identificar as ident_mod
from app.grafo import construir_grafo
from app.models import Correo

from test_motor_etapas import notion

ASUNTO = "Allianz México - Notificación de Cobranza (PLU3 / 437821)"
# El correo real del 29/10 (nombres de prueba).
CUERPO = """Ref.: Estatus cobranza póliza PLU3 / 437821

Apreciable Luisa Prueba Soto:

Por medio de la presente aprovechamos para enviarle un cordial saludo. Asimismo le informamos que, con base
en sus instrucciones, el pasado 26 de octubre de 2026 hicimos un intento de cargo a la cuenta bancaria. que
amablemente nos proporcionó. Dicho intento fue por la cantidad de $2,000.00 pesos correspondientes a la
aportación número 1 del Periodo Inicial de su plan OptiMaxx plus 3.0.

Como respuesta al intento de cobro, el banco nos notificó "FONDOS INSUFICIENTES". Por tal motivo el próximo
04 de noviembre de 2026 realizaremos un nuevo intento de cobro a su cuenta bancaria..

Le agradecemos de antemano su atención y nos ponemos a sus órdenes en nuestra área de Servicio al Cliente,
en el correo electrónico cliente.optimaxx@allianz.com.mx y en los teléfonos 5201 3182 ó 800 1111 200 ext. 3182.

Atentamente,
Servicio al Cliente | Soluciones Patrimoniales"""
REMITENTE = "Notificaciones Allianz <notificaciones.optimaxx@allianz.com.mx>"


def fila(poliza="PLU3-437821"):
    return {"cliente_nombre": "LUISA PRUEBA SOTO", "nro_solicitud": 25290009, "poliza": poliza,
            "telefono_cliente": "5533334444", "asesor_correo": "asesor1@babilonia.ai",
            "asesor_nombre": "Asesor Uno", "telefono_asesor": "5598765432"}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for k, v in (("MOTOR_ETAPAS", True), ("MOTOR_ETAPAS_ROLES", ["ceci", "asesor", "cliente"]),
                 ("COBRANZA_AVISOS", True), ("TELEGRAM_APROBACIONES", False), ("NOTION_TOKEN", ""),
                 ("OPENAI_API_KEY", ""), ("DRY_RUN", True), ("PANEL_URL", "")):
        monkeypatch.setattr(config, k, v)
    monkeypatch.setattr(ident_mod, "_buscador_notion", lambda: notion(fila()))
    return RepositorioSQLite(str(tmp_path / "t.sqlite"))


def correo(mid="c1", asunto=ASUNTO, remitente=REMITENTE):
    return Correo(mid, remitente, "allianz.com.mx", ["hola@babilonia.ai"], [], asunto, CUERPO)


def test_lee_los_datos_del_correo():
    assert cobranza.detectar(ASUNTO, CUERPO) == {
        "producto": "PLU3", "poliza": "PLU3-437821", "fecha_intento": "26 de octubre de 2026", "monto": "$2,000.00",
        "aportacion": "1", "motivo": "Fondos insuficientes", "proximo_intento": "04 de noviembre de 2026"}
    assert cobranza.detectar("[Allianz México Ticket-2576612] Sistema escribió un mensaje", CUERPO) is None


def test_avisa_al_asesor_y_a_ceci_nunca_al_cliente(repo):
    out = construir_grafo(repo).invoke({"correo": correo(), "despachar": False})
    assert "cobranza" in out["ruta"]
    msgs = {a["rol"]: a for a in out["acciones"]}
    assert sorted(msgs) == ["asesor", "ceci"]
    ases = msgs["asesor"]
    assert ases["numero"] == "5598765432"
    assert ases["mensaje"] == (
        "Cobranza · Luisa Prueba Soto · OptiMaxx Plus (póliza PLU3-437821): Allianz no pudo cobrar la aportación "
        "n° 1 de $2,000.00 el 26 de octubre de 2026. El banco respondió: fondos insuficientes. Próximo intento: "
        "04 de noviembre de 2026. Contacta al cliente para que tenga el monto disponible o se ponga al corriente. "
        "Recuerda: a los 60 días de atraso Allianz puede cancelar el plan en cualquier momento.")
    assert "Contacta al cliente" not in msgs["ceci"]["mensaje"] and "60 días" in msgs["ceci"]["mensaje"]
    assert ases["params"]["tramite"] == "OptiMaxx Plus · Cargo rechazado"
    t = repo.obtener_ticket(out["ticket_id"])
    assert (t["proceso"], t["estado"], t["poliza"], t["identificado_por"]) == ("cobranza", "resuelto", "PLU3-437821", "poliza")


def test_poliza_que_no_esta_en_notion_avisa_solo_a_ceci(repo, monkeypatch):
    monkeypatch.setattr(ident_mod, "_buscador_notion", lambda: notion(fila(poliza="PLU3-000001")))
    out = construir_grafo(repo).invoke({"correo": correo(), "despachar": False})
    assert [a["rol"] for a in out["acciones"]] == ["ceci"]
    assert "⚠️ No pude identificar la póliza PLU3-437821" in out["acciones"][0]["mensaje"]


def test_mismo_correo_dos_veces_no_avisa_de_nuevo(repo):
    g = construir_grafo(repo)
    g.invoke({"correo": correo(), "despachar": False})
    out = g.invoke({"correo": correo(), "despachar": False})
    assert not out.get("acciones") and len(repo.listar_tickets()) == 1


@pytest.mark.parametrize("cambio", [{"COBRANZA_AVISOS": False}, {"MOTOR_ETAPAS": False}])
def test_apagado_sigue_fuera_de_alcance(repo, monkeypatch, cambio):
    for k, v in cambio.items():
        monkeypatch.setattr(config, k, v)
    out = construir_grafo(repo).invoke({"correo": correo(), "despachar": False})
    assert not out.get("acciones") and repo.listar_tickets() == []


def test_si_no_lo_manda_allianz_no_cuenta(repo):
    out = construir_grafo(repo).invoke({"correo": correo(remitente="alguien <x@gmail.com>"), "despachar": False})
    assert "cobranza" not in out.get("ruta", [])
