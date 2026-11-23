"""Cobranza en modo resumen (acordado con Yans y Ceci el 17/11/2026):
  - todos los días hábiles: un correo con Excel a Yans y un WhatsApp a Ceci con las pólizas sin asesor;
  - martes y jueves: a cada asesor un correo con sus clientes y un WhatsApp con la cantidad;
  - las pólizas con el pago aplicado en Notion no salen."""
import io
import json
import os
from datetime import date, datetime, timedelta, timezone

import pytest

from app import config
from app.acciones import cobranza_resumen as cr
from app.acciones import despacho
from app.db.repo import RepositorioSQLite
from app.enriquecimiento import identificar as ident_mod
from app.envio import interruptor
from app.grafo import construir_grafo

from test_cobranza import ASUNTO, correo, fila
from test_motor_etapas import notion

HOY = datetime(2026, 11, 18, 16, 0, tzinfo=timezone.utc)   # 10:00 en México; el cargo fue el 26/10 → 23 días
NINGUNA = lambda polizas: set()  # noqa: E731 — nada pagado en Notion


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for k, v in (("MOTOR_ETAPAS", True), ("MOTOR_ETAPAS_ROLES", ["ceci", "asesor", "cliente"]),
                 ("COBRANZA_AVISOS", True), ("TELEGRAM_APROBACIONES", False), ("NOTION_TOKEN", ""),
                 ("OPENAI_API_KEY", ""), ("DRY_RUN", True), ("PANEL_URL", ""), ("COBRANZA_MODO", "resumen"),
                 ("COBRANZA_RESUMEN_EMAILS", ["yans@babilonia.ai"]), ("ENVIO_REAL", [])):
        monkeypatch.setattr(config, k, v)
    filas = [fila("PLU3-437821"), {**fila("PLU3-500001"), "cliente_nombre": "PEDRO DOS"},
             {**fila("PLU3-600001"), "cliente_nombre": "ANA TRES", "asesor_nombre": "Bruno Dos",
              "asesor_correo": "asesor2@babilonia.ai", "telefono_asesor": "5511112222"}]
    monkeypatch.setattr(ident_mod, "_buscador_notion", lambda: notion(*filas))
    return RepositorioSQLite(str(tmp_path / "t.sqlite"))


def _aviso(grafo, n, poliza, cuerpo=None):
    from app.models import Correo
    from test_cobranza import CUERPO, REMITENTE
    prod, num = poliza.split("-")
    asunto = ASUNTO.replace("PLU3 / 437821", f"{prod} / {num}")
    c = Correo(f"c{n}", REMITENTE, "allianz.com.mx", ["integraciones@babilonia.ai"], [], asunto, cuerpo or CUERPO)
    return grafo.invoke({"correo": c, "despachar": False})


def _llegan(repo):
    g = construir_grafo(repo)
    # El 437821 avisa dos veces (Allianz reintenta); el 500001 tiene un cargo más reciente; el 999999 no está en
    # Notion.
    from test_cobranza import CUERPO
    for n, (p, cuerpo) in enumerate([("PLU3-437821", None), ("PLU3-500001", CUERPO.replace("26 de octubre", "9 de noviembre")),
                                     ("PLU3-437821", None), ("PLU3-600001", None), ("PLU3-999999", None)]):
        _aviso(g, n, p, cuerpo)


class _Emisor:
    modo = "gmail_api"

    def __init__(self):
        self.enviados = []

    def enviar(self, para, asunto, cuerpo, adjuntos=None, **_):
        archivos = {}
        for ruta in adjuntos or []:
            with open(ruta, "rb") as fh:
                archivos[os.path.basename(ruta)] = fh.read()
        self.enviados.append({"para": para, "asunto": asunto, "cuerpo": cuerpo, "adjuntos": archivos})
        return {"ok": True}


def _sugeridas(repo):
    return [json.loads(a["payload"]) for a in repo.listar_acciones(estado="sugerida")]


def test_al_llegar_no_sale_nada_y_los_reintentos_van_al_mismo_ticket(repo):
    _llegan(repo)
    assert _sugeridas(repo) == []
    pend = repo.listar_acciones(estado=cr.EN_RESUMEN)
    assert len(pend) == 5
    assert len({a["ticket_id"] for a in pend}) == 4          # 437821: 2 avisos, 1 ticket
    assert len(repo.listar_tickets(cobranza=True)) == 4


def test_diario_correo_con_excel_a_yans_y_whatsapp_a_ceci_con_los_sin_asesor(repo):
    _llegan(repo)
    res = cr.armar_resumen(repo, ahora=HOY, emisor=_Emisor(), pagadas=NINGUNA)
    assert res == {"polizas": 4, "avisos": 5, "asesores": 2, "pagadas": 0, "sin_asesor": 1,
                   "whatsapp_encolados": 1, "correo_equipo": False}   # sandbox: el correo queda en vista previa
    # Al asesor no le sale nada en el diario (va martes y jueves); a Ceci, solo lo sin asesor.
    pays = _sugeridas(repo)
    assert [p["rol"] for p in pays] == ["ceci"]
    assert pays[0]["resumen_de"] == ["PLU3-999999"] and pays[0]["params"]["plantilla"] == "cobranza"
    assert pays[0]["params"]["cantidad"] == "1 póliza sin asesor tuvo"
    previa = json.loads(repo.leer_valor(cr.CLAVE_PREVIA))
    assert previa["enviado"] is False and previa["para"] == ["yans@babilonia.ai"] and previa["excel"] is True
    assert "Asesor Uno: 2" in previa["cuerpo"] and "Bruno Dos: 1" in previa["cuerpo"]
    assert "Sin asesor: 1" in previa["cuerpo"] and cr.SESENTA in previa["cuerpo"]
    # Todo quedó resumido: el siguiente resumen no repite nada.
    assert repo.listar_acciones(estado=cr.EN_RESUMEN) == []
    assert cr.armar_resumen(repo)["motivo"] == "nada acumulado"


def test_el_excel_lleva_telefono_y_aportacion_y_al_final_la_lista_sin_asesor(repo):
    from openpyxl import load_workbook
    _llegan(repo)
    filas = cr.ordenar(cr._por_poliza(repo.listar_acciones(estado=cr.EN_RESUMEN)), HOY.date())
    grupos, sin = cr.agrupar(filas)
    ws = load_workbook(io.BytesIO(cr.excel(grupos, sin))).active
    filas_xl = [[c.value for c in r] for r in ws.iter_rows()]
    assert filas_xl[0][:12] == list(cr.COLUMNAS)
    # Asesor Uno: primero el de más atraso (26/10 → 23 días), después el de 9/11 (9 días).
    assert filas_xl[1][:9] == ["Asesor Uno", "Luisa Prueba Soto", "5533334444", "OptiMaxx Plus", "PLU3-437821",
                               "1", "$2,000.00", 23, "26/10/2026"]
    assert filas_xl[1][11] == 2                                   # 2 avisos
    assert filas_xl[2][1] == "Pedro Dos" and filas_xl[2][7] == 9
    assert filas_xl[3][0] == "Bruno Dos"
    i = next(n for n, f in enumerate(filas_xl) if f[0] == cr.SIN_ASESOR)
    assert filas_xl[i + 2][3] == "PLU3-999999" and "No pude identificar" in filas_xl[i + 2][-1]


def test_con_cobranza_en_vivo_sale_el_correo_con_el_excel_y_el_whatsapp_a_ceci(repo, monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", False)
    monkeypatch.setattr(config, "CECI_WHATSAPP", "5500000000")
    interruptor.cambiar(repo, "cobranza", True)
    _llegan(repo)
    em = _Emisor()
    assert cr.armar_resumen(repo, ahora=HOY, emisor=em, pagadas=NINGUNA)["correo_equipo"] is True
    assert em.enviados[0]["para"] == ["yans@babilonia.ai"]
    assert list(em.enviados[0]["adjuntos"]) == ["cobranza_2026-11-18.xlsx"]
    enviados = []

    class _Wati:
        modo = "wati"

        def enviar_plantilla(self, numero, plantilla, params=None):
            enviados.append((numero, plantilla, params))
            return {"ok": True}
    monkeypatch.setattr("app.wati.wati_desde_config", lambda: _Wati())
    assert despacho.despachar_pendientes(repo, em)["conteo"] == {"enviada": 1}
    assert enviados[0][0] == "5500000000" and enviados[0][1] == config.WATI_PLANTILLA_COBRANZA
    assert set(enviados[0][2]) == {"cantidad", "clientes", "indicacion"}


def test_las_polizas_con_el_pago_aplicado_no_salen(repo):
    _llegan(repo)
    res = cr.armar_resumen(repo, ahora=HOY, emisor=_Emisor(), pagadas=lambda ps: {"PLU3-500001"})
    assert res["polizas"] == 3 and res["pagadas"] == 1
    previa = json.loads(repo.leer_valor(cr.CLAVE_PREVIA))
    assert "Asesor Uno: 1" in previa["cuerpo"] and "1 con el pago ya aplicado" in previa["cuerpo"]


def test_si_notion_falla_el_resumen_sale_igual_con_todas(repo):
    _llegan(repo)

    def rompe(_):
        raise RuntimeError("Notion caído")
    assert cr.armar_resumen(repo, ahora=HOY, emisor=_Emisor(), pagadas=rompe)["polizas"] == 4


def test_martes_y_jueves_a_cada_asesor_correo_con_sus_clientes_y_whatsapp_con_la_cantidad(repo):
    _llegan(repo)
    cr.armar_resumen(repo, ahora=HOY, emisor=_Emisor(), pagadas=NINGUNA)   # el diario no le quita nada
    # Las acciones se guardan con la hora real (created_at de la base): "lo nuevo desde el último envío" se mide
    # contra el reloj de verdad, no contra HOY, o el test depende del día en que corre.
    ahora = datetime.now(timezone.utc) + timedelta(minutes=5)
    res = cr.armar_resumen_asesores(repo, ahora=ahora, emisor=_Emisor(), pagadas=NINGUNA)
    assert res == {"asesores": 2, "polizas": 4, "pagadas": 0, "correos_enviados": 0, "correos": 2,
                   "whatsapp_encolados": 2}
    wa = {p["numero"]: p for p in _sugeridas(repo) if p["rol"] == "asesor"}
    assert sorted(wa) == ["5511112222", "5598765432"]
    uno = wa["5598765432"]
    assert uno["params"]["plantilla"] == "cobranza_asesor"
    assert uno["params"]["nombre"] == "Asesor" and uno["params"]["cantidad"] == "2 clientes"
    assert uno["mensaje"].startswith("Hola Asesor 👋 Tienes 2 clientes con cargo rechazado por Allianz.")
    detalle = json.loads(repo.leer_valor(f"{cr.CLAVE_ASESORES}:detalle"))
    assert {c["para"] for c in detalle["correos"]} == {"asesor1@babilonia.ai", "asesor2@babilonia.ai"}
    # El siguiente envío solo lleva lo nuevo.
    otra = cr.armar_resumen_asesores(repo, ahora=ahora + timedelta(days=2), emisor=_Emisor(), pagadas=NINGUNA)
    assert otra["asesores"] == 0 and otra["whatsapp_encolados"] == 0


def test_asesores_en_vivo_cada_uno_recibe_solo_sus_clientes(repo, monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", False)
    interruptor.cambiar(repo, "cobranza", True)
    _llegan(repo)
    em = _Emisor()
    res = cr.armar_resumen_asesores(repo, ahora=HOY, emisor=em, pagadas=NINGUNA)
    assert res["correos_enviados"] == 2
    por = {e["para"][0]: e for e in em.enviados}
    assert "Luisa Prueba Soto" in por["asesor1@babilonia.ai"]["cuerpo"]
    assert "Ana Tres" not in por["asesor1@babilonia.ai"]["cuerpo"]
    assert "Ana Tres" in por["asesor2@babilonia.ai"]["cuerpo"]
    assert por["asesor2@babilonia.ai"]["adjuntos"]                           # con el Excel
    enviados = []

    class _Wati:
        modo = "wati"

        def enviar_plantilla(self, numero, plantilla, params=None):
            enviados.append((numero, plantilla, params))
            return {"ok": True}
    monkeypatch.setattr("app.wati.wati_desde_config", lambda: _Wati())
    despacho.despachar_pendientes(repo, em)
    asesores = [e for e in enviados if e[1] == config.WATI_PLANTILLA_COBRANZA_ASESOR]
    assert len(asesores) == 2 and all(set(p) == {"nombre", "cantidad"} for _, _, p in asesores)


def test_ceci_recibe_las_6_con_mas_atraso_y_el_resto_queda_en_el_correo():
    hoy = date(2026, 11, 18)
    filas = [{"cliente": f"Cliente {i}", "plan": "OptiMaxx Plus", "poliza": f"PLU3-{i:06d}", "intentos": 1,
              "detalle": {}, "primer_intento": date(2026, 11, 1 + i).isoformat()} for i in range(9)]
    filas.append({"cliente": "Sin fecha", "plan": "OptiMaxx Plus", "poliza": "PLU3-999998", "intentos": 1,
                  "detalle": {}, "primer_intento": None})
    orden = cr.ordenar(filas, hoy)
    assert [f["poliza"] for f in orden][:3] == ["PLU3-000000", "PLU3-000001", "PLU3-000002"]
    assert orden[0]["dias_atraso"] == 17 and orden[-1]["cliente"] == "Sin fecha"
    v = cr.variables_ceci(orden)
    assert v["clientes"].startswith("Cliente 0 (OptiMaxx Plus PLU3-000000): 17 días de atraso; Cliente 1")
    assert "Cliente 5 " in v["clientes"] and "Cliente 6 " not in v["clientes"]
    assert v["clientes"].endswith("y 4 más en el correo de cobranza")
    assert len(cr.texto_ceci(v)) < 900


def test_fecha_del_correo_de_allianz():
    assert cr.fecha_es("26 de octubre de 2026") == date(2026, 10, 26)
    assert cr.fecha_es("el pasado 4 de Setiembre de 2026 hicimos") == date(2026, 9, 4)
    assert cr.fecha_es("31 de febrero de 2026") is None and cr.fecha_es(None) is None


def test_el_atraso_cuenta_desde_el_primer_rechazo_aunque_ya_se_haya_resumido(repo):
    from test_cobranza import CUERPO
    g = construir_grafo(repo)
    _aviso(g, 1, "PLU3-437821")
    cr.armar_resumen(repo, ahora=HOY, emisor=_Emisor(), pagadas=NINGUNA)
    # Allianz reintenta y vuelve a avisar con una fecha posterior: el atraso sigue contando desde el 26/10.
    _aviso(g, 2, "PLU3-437821", CUERPO.replace("26 de octubre", "4 de noviembre"))
    pend = [json.loads(a["payload"]) for a in repo.listar_acciones(estado=cr.EN_RESUMEN)]
    assert [p["primer_intento"] for p in pend] == ["2026-10-26"]


def test_pagos_aplicados_desde_la_tabla_de_cobranzas(monkeypatch):
    from app.rieles import notion as N
    monkeypatch.setattr(config, "NOTION_TOKEN", "x")
    monkeypatch.setattr(N, "descubrir_db", lambda clave: "db-cobranzas")
    monkeypatch.setattr(N, "mapear_campos", lambda db, d: {"poliza": "Póliza", "pago": "Pago hecho"})

    def pagina(poliza, pago):
        return {"properties": {"Póliza": {"type": "rich_text", "rich_text": [{"plain_text": poliza}]},
                               "Pago hecho": {"type": "multi_select", "multi_select": [{"name": x} for x in pago]}}}
    monkeypatch.setattr(N, "_query_todo", lambda db, filt: [pagina("PLU3/500001", ["Aplicado"]),
                                                            pagina("PLU3-437821", ["Pendiente"])])
    assert N.polizas_pagadas(["PLU3-437821", "PLU3-500001", "PLU3-600001"]) == {"PLU3-500001"}


def test_api_muestra_lo_acumulado(repo, monkeypatch):
    from fastapi.testclient import TestClient

    from app import api
    _llegan(repo)
    monkeypatch.setattr(api, "_repo", repo)
    r = TestClient(api.app).get("/api/tickets-allianz/cobranza/resumen").json()
    assert r["modo"] == "resumen" and r["acumulado"] == {"avisos": 5, "polizas": 4, "asesores": 2, "sin_asesor": 1}
    assert "Bruno Dos: 1" in r["vista_previa"] and r["ultimo"] is None
