"""Paso 5 — textos fijos por etapa + plantilla WATI 'actualización de trámite'."""
import re
from datetime import datetime, timezone

import pytest

from app import config
from app.acciones import despachar_pendientes
from app.acciones import mensajes_etapa as M
from app.acciones.despacho import plantilla_etapas, sin_saludo, una_linea
from app.acciones.motor_etapas import decidir_por_etapa
from app.db.repo import RepositorioSQLite

from test_motor_etapas import C1, C3, LUNES, et, fila, notion

ETAPA_EJEMPLO = {"etapa": "requerimiento", "nro_ticket": "2576612", "producto": "GMMI", "nro_solicitud": "1950110",
                 "cliente": "HORTENCIA PRUEBA GAMA", "que_piden": "la carta laboral firmada " * 30,
                 "plazo": (15, "dias_habiles"), "mensaje": "Adjunto la hoja membretada", "poliza": "GMMI-101770"}


@pytest.fixture(autouse=True)
def aislado(monkeypatch):
    monkeypatch.setattr(config, "NOTION_TOKEN", "")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(config, "DRY_RUN", True)
    monkeypatch.setattr(config, "PANEL_URL", "")
    monkeypatch.setattr(config, "CECI_WHATSAPP", "")


@pytest.mark.parametrize("etapa", sorted(M.TEXTOS))
@pytest.mark.parametrize("rol", ["ceci", "asesor", "cliente"])
def test_todos_los_textos_se_completan(etapa, rol):
    ctx = M.contexto({}, {**ETAPA_EJEMPLO, "etapa": etapa}, {"cliente_nombre": "Hortencia Prueba Gama"},
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


_P = {"ticket": "2576612", "tramite": "Gastos médicos · Allianz pide documentos",
      "cliente": "Hortencia Prueba Gama", "nombre": "Hortencia"}


def test_plantilla_del_equipo():
    pay = {"rol": "asesor", "mensaje": "Ticket 2576612 · Hortencia: Allianz pide → la carta.\n⚠️ Falta el teléfono",
           "params": _P}
    assert plantilla_etapas(pay) == ("tommy_aviso_equipo", {
        "ticket": "2576612", "cliente": "Hortencia Prueba Gama", "tramite": "Gastos médicos · Allianz pide documentos",
        "mensaje": "Allianz pide → la carta. · ⚠️ Falta el teléfono"})  # sin repetir ticket y cliente
    assert plantilla_etapas({**pay, "rol": "ceci"})[0] == "tommy_aviso_equipo"


def test_plantilla_del_equipo_en_un_tramite_lleva_el_asunto():
    tk = {"nro_ticket": "2587626", "proceso": "tramite"}
    ctx = M.contexto(tk, {"proceso": "tramite", "titulo_hilo": "[EXT] Aplicación de mensualidad"},
                     {"cliente_nombre": "Ana Ruiz Pérez"})
    assert M.params_wati(ctx, "apertura", None, "tramite")["tramite"] == "Aplicación de mensualidad · Trámite recibido por Allianz"
    # Sin producto ni asunto: solo la etapa (no "— · …").
    sin = M.contexto({"nro_ticket": "1"}, {}, None)
    assert M.params_wati(sin, "apertura", None, "largo")["tramite"] == "Solicitud abierta en Allianz"
    pay = {"rol": "ceci", "params": M.params_wati(ctx, "rebote_ticket_cerrado", None, "tramite"),
           "mensaje": "Ticket 2587626: nuestra respuesta NO entró."}
    assert plantilla_etapas(pay)[1]["mensaje"] == "Nuestra respuesta NO entró."


def test_plantilla_del_cliente_sin_saludo_repetido():
    pay = {"rol": "cliente", "params": _P,
           "mensaje": "Hola Hortencia, para avanzar Allianz necesita: la carta laboral. Tienes hasta el 22/10/2026."}
    assert plantilla_etapas(pay) == ("tommy_actualizacion_cliente", {
        "nombre": "Hortencia",
        "mensaje": "Para avanzar Allianz necesita: la carta laboral. Tienes hasta el 22/10/2026."})
    # Sin nombre: WhatsApp no acepta variables vacías.
    assert plantilla_etapas({**pay, "params": {}})[1]["nombre"] == "de nuevo"


def test_plantilla_de_la_guia():
    guia = {"nombre": "Guillermo", "producto": "Elite", "poliza": "SVIP-21799", "monto": "$50,000 MXN",
            "datos_deposito": "CLABE 0123\na nombre de Allianz"}
    plantilla, params = plantilla_etapas({"rol": "cliente", "mensaje": "…", "params": {**_P, "guia": guia}})
    assert plantilla == "tommy_guia_aportacion"
    assert params == {"nombre": "Guillermo", "producto": "Elite", "poliza": "SVIP-21799", "monto": "$50,000 MXN",
                      "datos_deposito": "CLABE 0123 · a nombre de Allianz"}


@pytest.mark.parametrize("entra,sale", [
    ("Hola, te recuerdo que falta tu aportación.", "Te recuerdo que falta tu aportación."),
    ("Tu póliza ya está emitida.", "Tu póliza ya está emitida."),
])
def test_sin_saludo(entra, sale):
    assert sin_saludo(entra) == sale


def test_una_linea_cumple_las_reglas_de_whatsapp():
    assert una_linea("a\n\nb\tc     d") == "a · b c d"
    assert una_linea("") == "—" and una_linea(None) == "—"
    largo = una_linea("palabra " * 300)
    assert len(largo) <= 900 and largo.endswith("…")


def _flujo(tmp_path):
    repo = RepositorioSQLite(str(tmp_path / "t.sqlite"))
    tk = repo.crear_ticket({"nro_ticket": "2576612", "estado": "abierto"})
    decidir_por_etapa(repo, tk, et(C1), correo_id=1, ahora=LUNES, buscar=notion(fila()))
    return repo, tk


def test_despacho_usa_la_plantilla_de_cada_destinatario(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CECI_WHATSAPP", "5215500000000")
    repo, tk = _flujo(tmp_path)
    res = despachar_pendientes(repo)
    assert res["conteo"] == {"simulada": 3}  # DRY_RUN: se compone pero no sale
    r = {a["tipo_accion"]: __import__("json").loads(a["resultado"]) for a in repo.listar_acciones(tk)}
    for tipo in ("avisar_asesor", "avisar_ceci"):
        assert r[tipo]["plantilla"] == "tommy_aviso_equipo"
        assert r[tipo]["params"]["ticket"] == "2576612" and "Solicitud abierta" in r[tipo]["params"]["tramite"]
        assert r[tipo]["params"]["cliente"] == "Hortencia Prueba Gama"
    cli = r["avisar_cliente"]
    assert cli["plantilla"] == "tommy_actualizacion_cliente" and cli["params"]["nombre"] == "Hortencia"
    assert cli["params"]["mensaje"].startswith("Tu solicitud de gastos médicos ya está en Allianz")


def test_ceci_sin_numero_queda_pendiente(tmp_path):
    repo, tk = _flujo(tmp_path)
    assert despachar_pendientes(repo)["conteo"] == {"simulada": 2, "pendiente_wati": 1}


def test_recorte_en_palabra_entera_y_nombre_sin_ruido():
    largo = "Historia clínica completa y actualizada, por su médico tratante, indicando antecedente " * 6
    q = M.contexto({}, {**ETAPA_EJEMPLO, "que_piden": largo})["que_piden"]
    assert q.endswith("…") and not q[:-1].endswith(" ") and q[:-1].split()[-1] in largo.split()
    assert M.contexto({}, {}, {"cliente_nombre": "María .  del Carmen Montero  Querejeta"})["cliente"] == \
        "María del Carmen Montero Querejeta"


@pytest.mark.parametrize("prod,plantilla,variables", [
    ("SVIP", "tommy_guia_elite", {"nombre": "Guillermo", "monto": "$50,000 MXN", "solicitud": "25287681",
                                  "ticket": "2567479",
                                  "poliza": "SVIP-21799", "cliente": "Guillermo Prueba Castro"}),
    ("OPPT", "tommy_guia_patrimonial", {"nombre": "Guillermo", "monto": "$50,000 MXN", "solicitud": "25287681",
                                        "poliza": "SVIP-21799",
                                        "cliente": "Guillermo Prueba Castro"}),
])
def test_cada_producto_sale_por_su_plantilla_de_guia(prod, plantilla, variables):
    ctx = M.contexto({"nro_ticket": "2567479", "poliza": "SVIP-21799", "nro_solicitud": "25287681", "producto": prod},
                     {}, {"cliente_nombre": "Guillermo Prueba Castro"})
    g = {**M.datos_guia(ctx, prod), "monto": "$50,000 MXN"}
    assert plantilla_etapas({"rol": "cliente", "mensaje": "…", "params": {"guia": g}}) == (plantilla, variables)


@pytest.mark.parametrize("entra,sale", [
    ("Hola Guillermo, ¡tu póliza SVIP-21799 ya está emitida!", "¡Tu póliza SVIP-21799 ya está emitida!"),
    ("Hola Ana, ¡listo! Tu solicitud quedó atendida.", "¡Listo! Tu solicitud quedó atendida."),
    ("Hola, ya enviamos tus documentos.", "Ya enviamos tus documentos."),
])
def test_sin_saludo_deja_mayuscula_aunque_empiece_con_exclamacion(entra, sale):
    assert sin_saludo(entra) == sale


def test_la_guia_no_guarda_rellenos_como_datos():
    ctx = M.contexto({"producto": "OPPT"}, {"producto": "OPPT"}, None)
    d = M.datos_guia(ctx, "OPPT")
    assert (d["poliza"], d["ticket"], d["cliente"]) == ("", "", "")
    assert M.faltan_del_ticket(d) == ["la póliza", "el nombre del cliente"]  # Patrimonial no usa el ticket
