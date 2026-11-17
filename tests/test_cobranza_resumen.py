"""Cobranza en modo resumen: un WhatsApp por asesor por día y un correo a Ceci y Yans, no uno por aviso."""
import json
from datetime import date, datetime, timezone

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


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for k, v in (("MOTOR_ETAPAS", True), ("MOTOR_ETAPAS_ROLES", ["ceci", "asesor", "cliente"]),
                 ("COBRANZA_AVISOS", True), ("TELEGRAM_APROBACIONES", False), ("NOTION_TOKEN", ""),
                 ("OPENAI_API_KEY", ""), ("DRY_RUN", True), ("PANEL_URL", ""), ("COBRANZA_MODO", "resumen"),
                 ("COBRANZA_RESUMEN_EMAILS", ["ceci@babilonia.ai", "yans@babilonia.ai"]), ("ENVIO_REAL", [])):
        monkeypatch.setattr(config, k, v)
    filas = [fila("PLU3-437821"), {**fila("PLU3-500001"), "cliente_nombre": "PEDRO DOS"},
             {**fila("PLU3-600001"), "cliente_nombre": "ANA TRES", "asesor_nombre": "Asesor Dos",
              "asesor_correo": "asesor2@babilonia.ai", "telefono_asesor": "5511112222"}]
    monkeypatch.setattr(ident_mod, "_buscador_notion", lambda: notion(*filas))
    return RepositorioSQLite(str(tmp_path / "t.sqlite"))


def _aviso(grafo, n, poliza):
    prod, num = poliza.split("-")
    return grafo.invoke({"correo": correo(mid=f"c{n}", asunto=ASUNTO.replace("PLU3 / 437821", f"{prod} / {num}")),
                         "despachar": False})


def _llegan(repo):
    g = construir_grafo(repo)
    # El 437821 avisa dos veces (Allianz reintenta); el 999999 no está en Notion.
    for n, p in enumerate(["PLU3-437821", "PLU3-500001", "PLU3-437821", "PLU3-600001", "PLU3-999999"]):
        _aviso(g, n, p)


HOY = datetime(2026, 11, 18, 16, 0, tzinfo=timezone.utc)   # 10:00 en México; el cargo fue el 26/10 → 23 días


class _Emisor:
    modo = "gmail_api"

    def __init__(self):
        self.enviados = []

    def enviar(self, para, asunto, cuerpo, **_):
        self.enviados.append((para, asunto, cuerpo))
        return {"ok": True}


def test_al_llegar_no_sale_nada_y_los_reintentos_van_al_mismo_ticket(repo):
    _llegan(repo)
    assert [a for a in repo.listar_acciones() if a["estado"] == "sugerida"] == []
    pend = repo.listar_acciones(estado=cr.EN_RESUMEN)
    assert len(pend) == 5
    assert len({a["ticket_id"] for a in pend}) == 4          # 437821: 2 avisos, 1 ticket
    assert len(repo.listar_tickets(cobranza=True)) == 4


def test_un_whatsapp_por_asesor_y_un_correo_al_equipo(repo):
    _llegan(repo)
    res = cr.armar_resumen(repo, ahora=HOY, emisor=_Emisor())
    assert res == {"polizas": 4, "avisos": 5, "asesores": 2, "sin_asesor": 1, "whatsapp_encolados": 3,
                   "correo_equipo": False}                       # sandbox: el correo queda en vista previa
    pays = [json.loads(a["payload"]) for a in repo.listar_acciones(estado="sugerida")]
    wa = {p["numero"]: p for p in pays if p["rol"] == "asesor"}
    assert sorted(wa) == ["5511112222", "5598765432"]
    uno = wa["5598765432"]["mensaje"]
    assert uno.startswith("Cobranza Allianz · 2 clientes tuyos tuvieron un cargo rechazado: ")
    assert ("Luisa Prueba Soto (OptiMaxx Plus PLU3-437821): 23 días de atraso, $2,000.00, fondos insuficientes, "
            "2 avisos") in uno
    assert "Pedro Dos" in uno and "Ana Tres" not in uno
    assert wa["5511112222"]["params"]["cliente"] == "Ana Tres"
    assert wa["5511112222"]["params"]["plantilla"] == "cobranza"
    # La póliza que no está en Notion: un WhatsApp a Ceci para que la asigne ella o Jime.
    ceci = [p for p in pays if p["rol"] == "ceci"]
    assert len(ceci) == 1 and ceci[0]["resumen_de"] == ["PLU3-999999"]
    assert ceci[0]["params"]["cantidad"] == "1 póliza sin asesor para avisar tuvo"
    assert ceci[0]["params"]["indicacion"] == cr.INDICACION_CECI
    previa = json.loads(repo.leer_valor(cr.CLAVE_PREVIA))
    assert previa["enviado"] is False and previa["para"] == ["ceci@babilonia.ai", "yans@babilonia.ai"]
    assert "Asesor Uno (2):" in previa["cuerpo"] and "Sin asesor para avisar (1): las asigna Ceci o Jime" in previa["cuerpo"]
    assert "PLU3-999999" in previa["cuerpo"] and "No pude identificar" in previa["cuerpo"]
    # Todo quedó resumido: el siguiente resumen no repite nada.
    assert repo.listar_acciones(estado=cr.EN_RESUMEN) == []
    assert cr.armar_resumen(repo)["motivo"] == "nada acumulado"


def test_con_cobranza_en_vivo_sale_el_correo_y_los_whatsapp(repo, monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", False)
    monkeypatch.setattr(config, "CECI_WHATSAPP", "5500000000")
    interruptor.cambiar(repo, "cobranza", True)
    _llegan(repo)
    em = _Emisor()
    assert cr.armar_resumen(repo, emisor=em)["correo_equipo"] is True
    assert em.enviados[0][0] == ["ceci@babilonia.ai", "yans@babilonia.ai"]
    enviados = []

    class _Wati:
        modo = "wati"

        def enviar_plantilla(self, numero, plantilla, params=None):
            enviados.append((numero, plantilla, params))
            return {"ok": True}
    monkeypatch.setattr("app.wati.wati_desde_config", lambda: _Wati())
    assert despacho.despachar_pendientes(repo, em)["conteo"] == {"enviada": 3}
    assert sorted(n for n, _, _ in enviados) == ["5500000000", "5511112222", "5598765432"]
    # Plantilla propia de cobranza, con sus 3 variables (Ceci, 17/11).
    assert {pl for _, pl, _ in enviados} == {config.WATI_PLANTILLA_COBRANZA}
    assert all(set(p) == {"cantidad", "clientes", "indicacion"} for _, _, p in enviados)
    assert all(len(v) <= despacho._MAX_VARIABLE for _, _, p in enviados for v in p.values())


def test_muchos_clientes_de_un_asesor_no_pasan_el_largo_de_whatsapp():
    filas = [{"cliente": f"Cliente Con Nombre Largo {i}", "plan": "OptiMaxx Plus", "poliza": f"PLU3-{i:06d}",
              "intentos": 1, "detalle": {"monto": "$12,345.67", "motivo": "Fondos insuficientes"}} for i in range(40)]
    t = cr.texto_asesor(filas)
    assert "y 34 más: consulta el resto con Ceci" in t and len(t) < 900


def test_van_primero_los_6_con_mas_dias_de_atraso():
    hoy = date(2026, 11, 18)
    filas = [{"cliente": f"Cliente {i}", "plan": "OptiMaxx Plus", "poliza": f"PLU3-{i:06d}", "intentos": 1,
              "detalle": {}, "primer_intento": date(2026, 11, 1 + i).isoformat()} for i in range(9)]
    filas.append({"cliente": "Sin fecha", "plan": "OptiMaxx Plus", "poliza": "PLU3-999998", "intentos": 1,
                  "detalle": {}, "primer_intento": None})
    orden = cr.ordenar(filas, hoy)
    assert [f["poliza"] for f in orden][:3] == ["PLU3-000000", "PLU3-000001", "PLU3-000002"]
    assert orden[0]["dias_atraso"] == 17 and orden[-1]["cliente"] == "Sin fecha"
    v = cr.variables(orden, "asesor")
    assert v["clientes"].startswith("Cliente 0 (OptiMaxx Plus PLU3-000000): 17 días de atraso; Cliente 1")
    assert "Cliente 5 " in v["clientes"] and "Cliente 6 " not in v["clientes"]
    assert v["clientes"].endswith("y 4 más: consulta el resto con Ceci")


def test_fecha_del_correo_de_allianz():
    assert cr.fecha_es("26 de octubre de 2026") == date(2026, 10, 26)
    assert cr.fecha_es("el pasado 4 de Setiembre de 2026 hicimos") == date(2026, 9, 4)
    assert cr.fecha_es("31 de febrero de 2026") is None and cr.fecha_es(None) is None


def test_el_atraso_cuenta_desde_el_primer_rechazo_aunque_ya_se_haya_resumido(repo):
    g = construir_grafo(repo)
    _aviso(g, 1, "PLU3-437821")
    cr.armar_resumen(repo, ahora=HOY, emisor=_Emisor())
    # Allianz reintenta y vuelve a avisar con una fecha posterior: el atraso sigue contando desde el 26/10.
    cuerpo = __import__("test_cobranza").CUERPO.replace("26 de octubre", "4 de noviembre")
    from app.models import Correo
    from test_cobranza import REMITENTE
    g.invoke({"correo": Correo("c2", REMITENTE, "allianz.com.mx", ["hola@babilonia.ai"], [], ASUNTO, cuerpo),
              "despachar": False})
    pend = [json.loads(a["payload"]) for a in repo.listar_acciones(estado=cr.EN_RESUMEN)]
    assert [p["primer_intento"] for p in pend] == ["2026-10-26"]


def test_api_muestra_lo_acumulado(repo, monkeypatch):
    from fastapi.testclient import TestClient

    from app import api
    _llegan(repo)
    monkeypatch.setattr(api, "_repo", repo)
    r = TestClient(api.app).get("/api/tickets-allianz/cobranza/resumen").json()
    assert r["modo"] == "resumen" and r["acumulado"] == {"avisos": 5, "polizas": 4, "asesores": 2, "sin_asesor": 1}
    assert "Asesor Dos (1):" in r["vista_previa"] and r["ultimo"] is None
