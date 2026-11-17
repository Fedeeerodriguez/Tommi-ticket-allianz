"""Cobranza en modo resumen: un WhatsApp por asesor por día y un correo a Ceci y Yans, no uno por aviso."""
import json

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
    res = cr.armar_resumen(repo, emisor=_Emisor())
    assert res == {"polizas": 4, "avisos": 5, "asesores": 2, "sin_asesor": 1, "whatsapp_encolados": 2,
                   "correo_equipo": False}                       # sandbox: el correo queda en vista previa
    wa = {json.loads(a["payload"])["numero"]: json.loads(a["payload"]) for a in repo.listar_acciones(estado="sugerida")}
    assert sorted(wa) == ["5511112222", "5598765432"]
    uno = wa["5598765432"]["mensaje"]
    assert uno.startswith("Cobranza · 2 clientes tuyos tuvieron un cargo rechazado por Allianz: ")
    assert "Luisa Prueba Soto (OptiMaxx Plus PLU3-437821): $2,000.00, fondos insuficientes, 2 avisos" in uno
    assert "Pedro Dos" in uno and "Ana Tres" not in uno
    assert wa["5511112222"]["params"]["cliente"] == "Ana Tres"
    previa = json.loads(repo.leer_valor(cr.CLAVE_PREVIA))
    assert previa["enviado"] is False and previa["para"] == ["ceci@babilonia.ai", "yans@babilonia.ai"]
    assert "Asesor Uno (2):" in previa["cuerpo"] and "Sin asesor para avisar (1)" in previa["cuerpo"]
    assert "PLU3-999999" in previa["cuerpo"] and "No pude identificar" in previa["cuerpo"]
    # Todo quedó resumido: el siguiente resumen no repite nada.
    assert repo.listar_acciones(estado=cr.EN_RESUMEN) == []
    assert cr.armar_resumen(repo)["motivo"] == "nada acumulado"


def test_con_cobranza_en_vivo_sale_el_correo_y_los_whatsapp(repo, monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", False)
    interruptor.cambiar(repo, "cobranza", True)
    _llegan(repo)
    em = _Emisor()
    assert cr.armar_resumen(repo, emisor=em)["correo_equipo"] is True
    assert em.enviados[0][0] == ["ceci@babilonia.ai", "yans@babilonia.ai"]
    enviados = []

    class _Wati:
        modo = "wati"

        def enviar_plantilla(self, numero, plantilla, params=None):
            enviados.append((numero, params))
            return {"ok": True}
    monkeypatch.setattr("app.wati.wati_desde_config", lambda: _Wati())
    assert despacho.despachar_pendientes(repo, em)["conteo"] == {"enviada": 2}
    assert sorted(n for n, _ in enviados) == ["5511112222", "5598765432"]
    assert all(len(p["mensaje"]) <= despacho._MAX_VARIABLE for _, p in enviados)


def test_muchos_clientes_de_un_asesor_no_pasan_el_largo_de_whatsapp():
    filas = [{"cliente": f"Cliente Con Nombre Largo {i}", "plan": "OptiMaxx Plus", "poliza": f"PLU3-{i:06d}",
              "intentos": 1, "detalle": {"monto": "$12,345.67", "motivo": "Fondos insuficientes"}} for i in range(40)]
    t = cr.texto_asesor(filas)
    assert "y 34 más (te los pasa Ceci)" in t and len(t) < 900


def test_api_muestra_lo_acumulado(repo, monkeypatch):
    from fastapi.testclient import TestClient

    from app import api
    _llegan(repo)
    monkeypatch.setattr(api, "_repo", repo)
    r = TestClient(api.app).get("/api/tickets-allianz/cobranza/resumen").json()
    assert r["modo"] == "resumen" and r["acumulado"] == {"avisos": 5, "polizas": 4, "asesores": 2, "sin_asesor": 1}
    assert "Asesor Dos (1):" in r["vista_previa"] and r["ultimo"] is None
