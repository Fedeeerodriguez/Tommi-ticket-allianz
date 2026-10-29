"""Etapa 3 (A) — abrir un trámite desde el panel, enviarlo y engancharle el acuse de Allianz."""
import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api, config
from app.acciones import abrir_tramite, despachar_pendientes
from app.db.repo import RepositorioSQLite
from app.enriquecimiento import identificar as ident_mod
from app.grafo import construir_grafo
from app.models import Correo

from test_motor_etapas import mail, notion

POLIZA = "PLU3-408444"
ALLIANZ = "Allianz.Mexico@allianz.com.mx"


def fila():
    return {"cliente_nombre": "ANA PRUEBA LOPEZ", "nro_solicitud": 25290002, "poliza": POLIZA,
            "telefono_cliente": "5512345678", "asesor_correo": "asesor1@babilonia.ai",
            "asesor_nombre": "Asesor Uno", "telefono_asesor": "5598765432"}


def adjunto(nombre="formato.pdf", datos=b"%PDF-1.4 prueba"):
    return {"nombre": nombre, "tipo": "application/pdf", "base64": base64.b64encode(datos).decode()}


# Cambio de conducto de cobro lleva el formato y la INE vigente del cliente (Ceci, 29/10).
FORMATO_E_INE = [adjunto("formato.pdf"), adjunto("ine.pdf")]


class EmisorQueLee:
    """Como el de laboratorio, pero lee los adjuntos mientras existen (son temporales)."""
    modo = "prueba"

    def __init__(self):
        self.enviados = []

    def enviar(self, destinatarios, asunto, cuerpo_texto, cc=None, adjuntos=None, hilo_id=None, in_reply_to=None):
        self.enviados.append({"para": destinatarios, "asunto": asunto, "cuerpo": cuerpo_texto, "cc": cc,
                              "adjuntos": {Path(p).name: Path(p).read_bytes() for p in adjuntos or []},
                              "hilo_id": hilo_id, "in_reply_to": in_reply_to})
        return {"ok": True, "modo": self.modo}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for k, v in (("MOTOR_ETAPAS", True), ("MOTOR_ETAPAS_PROCESOS", ["largo", "corto", "tramite"]),
                 ("MOTOR_ETAPAS_ROLES", ["ceci", "asesor", "cliente"]), ("TELEGRAM_APROBACIONES", False),
                 ("NOTION_TOKEN", ""), ("OPENAI_API_KEY", ""), ("DRY_RUN", True), ("PANEL_URL", ""),
                 ("API_TOKEN", ""), ("ALLIANZ_DEST", "tickets@allianz.com.mx"),
                 ("ALLIANZ_DIRECTORIO", json.dumps({"cambio_conducto_cobro": "cobranza@allianz.com.mx"}))):
        monkeypatch.setattr(config, k, v)
    monkeypatch.setattr(ident_mod, "_buscador_notion", lambda: notion(fila()))
    return RepositorioSQLite(str(tmp_path / "t.sqlite"))


# ---------------------------------------------------------------- armar
def test_vista_previa_identifica_la_poliza_y_arma_el_correo(repo):
    p = abrir_tramite.preparar("cambio_conducto_cobro", "plu3-408444", "El cliente cambia a la tarjeta terminación 1234.",
                               FORMATO_E_INE)
    assert p["ok"] and p["cliente"] == "ANA PRUEBA LOPEZ" and p["asesor"] == "Asesor Uno"
    assert p["asunto"] == "Cambio de conducto de cobro - Póliza PLU3-408444 - Ana Prueba Lopez"
    assert p["destino"] == "cobranza@allianz.com.mx"   # directorio por trámite
    assert "trámite de cambio de conducto de cobro para la póliza PLU3-408444, contratante Ana Prueba Lopez." in p["cuerpo"]
    assert "terminación 1234" in p["cuerpo"] and p["cuerpo"].endswith("Quedamos atentos.\nBabilonia")
    assert "Adjuntamos: formato.pdf, ine.pdf." in p["cuerpo"]


def test_cambio_de_conducto_sin_formato_e_ine_no_abre(repo):
    for adj in ([], [adjunto()]):
        p = abrir_tramite.preparar("cambio_conducto_cobro", POLIZA, adjuntos=adj)
        assert not p["ok"] and "el formato de cambio de conducto de cobro y la INE vigente del cliente" in p["motivo"]
    assert abrir_tramite.catalogo()[0]["requisitos"] == ["el formato de cambio de conducto de cobro",
                                                          "la INE vigente del cliente"]


def test_tramite_libre_va_al_destino_general(repo):
    p = abrir_tramite.preparar("Aplicación de pago", POLIZA, adjuntos=[adjunto()])
    assert p["ok"] and p["destino"] == "tickets@allianz.com.mx"
    assert p["asunto"].startswith("Aplicación de pago - Póliza") and "Adjuntamos: formato.pdf." in p["cuerpo"]


@pytest.mark.parametrize("tramite,poliza,adj,motivo", [
    ("", POLIZA, [], "falta el trámite"),
    ("cambio_conducto_cobro", "", [], "falta la póliza"),
    ("cambio_conducto_cobro", "PLU3-999999", [], "No se pudo identificar la póliza PLU3-999999"),
    ("cambio_conducto_cobro", POLIZA, [{"nombre": "x.pdf", "base64": "no es base64!"}], "no se pudo leer"),
    ("cambio_conducto_cobro", POLIZA, [adjunto(f"{i}.pdf") for i in range(6)], "máximo 5 adjuntos"),
])
def test_no_abre_sin_datos_o_sin_identificar(repo, tramite, poliza, adj, motivo):
    r = abrir_tramite.abrir(repo, tramite, poliza, adjuntos=adj)
    assert not r["ok"] and motivo in r["motivo"]
    assert repo.listar_tickets() == []


# ---------------------------------------------------------------- abrir + enviar
def test_abrir_crea_el_ticket_y_encola_el_correo(repo):
    r = abrir_tramite.abrir(repo, "cambio_conducto_cobro", POLIZA, "Nota.", FORMATO_E_INE, usuario="Ceci")
    assert r["ok"] and not r["sin_destino"]
    t = repo.obtener_ticket(r["ticket_id"])
    assert (t["proceso"], t["abierto_por"], t["identificado_por"], t["nro_ticket"]) == ("tramite", "babilonia", "poliza", None)
    assert t["telefono_cliente"] == "5512345678" and t["titulo_hilo"] == f"[EXT] {r['asunto']}"
    (a,) = repo.listar_acciones(r["ticket_id"])
    assert (a["tipo_accion"], a["canal"], a["estado"]) == ("abrir_tramite", "email", "sugerida")
    # No se avisa al cliente al abrir: el aviso sale con el acuse (trae el n° de ticket).
    assert repo.listar_avisos(r["ticket_id"]) == []


def test_mismo_tramite_abierto_no_se_duplica(repo):
    assert abrir_tramite.abrir(repo, "cambio_conducto_cobro", POLIZA, adjuntos=FORMATO_E_INE)["ok"]
    r = abrir_tramite.abrir(repo, "cambio_conducto_cobro", POLIZA.lower(), adjuntos=FORMATO_E_INE)
    assert not r["ok"] and r["duplicado"] and len(repo.listar_tickets()) == 1


def test_el_despacho_lo_manda_al_directorio_con_adjuntos(repo, monkeypatch):
    # Un trámite de "año de descanso" es tema crítico, pero lo abrió Ceci: no se vuelve a retener.
    r = abrir_tramite.abrir(repo, "periodo_descanso", POLIZA, adjuntos=[adjunto("solicitud.pdf", b"PDF!")])
    em = EmisorQueLee()
    assert despachar_pendientes(repo, em)["conteo"] == {"enviada": 1}
    (env,) = em.enviados
    assert env["para"] == ["tickets@allianz.com.mx"] and env["asunto"] == r["asunto"]
    assert env["adjuntos"] == {"solicitud.pdf": b"PDF!"} and env["hilo_id"] is None
    assert repo.listar_acciones(r["ticket_id"])[0]["estado"] == "enviada"


def test_sin_destino_queda_bloqueado(repo, monkeypatch):
    monkeypatch.setattr(config, "ALLIANZ_DEST", "")
    r = abrir_tramite.abrir(repo, "Aplicación de pago", POLIZA)
    assert r["ok"] and r["sin_destino"]
    assert despachar_pendientes(repo, EmisorQueLee())["conteo"] == {"bloqueada": 1}
    assert "escalacion_bloqueada" in api.motivos_para_ceci(repo, repo.obtener_ticket(r["ticket_id"]))


# ---------------------------------------------------------------- vuelta de Allianz
def acuse(mid, asunto_nuestro, ticket="2601301", actor="Sistema", msg=None):
    msg = msg or "Esta es una respuesta automática para confirmar que hemos recibido su solicitud."
    return Correo(mid, ALLIANZ, "allianz.com.mx", ["hola@babilonia.ai"], [],
                  f"[Allianz México Ticket-{ticket}] {actor} escribió un mensaje",
                  mail(actor, msg, f"[EXT] {asunto_nuestro}"))


def test_el_acuse_se_engancha_al_tramite_que_abrimos(repo):
    r = abrir_tramite.abrir(repo, "cambio_conducto_cobro", POLIZA, adjuntos=FORMATO_E_INE)
    g = construir_grafo(repo)
    # Allianz a veces le saca los acentos al título: igual lo reconoce.
    out = g.invoke({"correo": acuse("m1", "Cambio de conducto de cobro - Poliza PLU3-408444 - Ana Prueba Lopez"),
                    "despachar": False})
    assert out["ticket_id"] == r["ticket_id"] and len(repo.listar_tickets()) == 1
    t = repo.obtener_ticket(r["ticket_id"])
    assert t["nro_ticket"] == "2601301" and t["etapa"] == "apertura"
    # Avisa a los 3 con el n° de ticket (ya estaba identificado desde que se abrió).
    assert sorted(a["rol"] for a in out["acciones"]) == ["asesor", "ceci", "cliente"]

    # El requerimiento siguiente llega por n° de ticket y arranca el recordatorio.
    out2 = g.invoke({"correo": acuse("m2", r["asunto"], actor="OSBALDO PINEDA",
                                     msg="Buen día. Favor de enviar el formato firmado por el contratante."),
                     "despachar": False})
    assert out2["ticket_id"] == r["ticket_id"]
    assert repo.obtener_ticket(r["ticket_id"])["etapa"] == "requerimiento"


def test_un_tramite_ajeno_no_se_engancha(repo):
    r = abrir_tramite.abrir(repo, "cambio_conducto_cobro", POLIZA, adjuntos=FORMATO_E_INE)
    out = construir_grafo(repo).invoke({"correo": acuse("m1", "Aplicaciónes de mensualidad"), "despachar": False})
    assert out["ticket_id"] != r["ticket_id"]
    assert repo.obtener_ticket(r["ticket_id"])["nro_ticket"] is None


@pytest.mark.parametrize("a,b,igual", [
    ("Cambio de conducto de cobro - Póliza PLU3-1 - Ana", "[EXT] Cambio de conducto de cobro - Poliza PLU3-1 - Ana", True),
    ("Cambio de conducto de cobro - Póliza PLU3-1 - Ana Prueba", "[EXT] Cambio de conducto de cobro - Póliza PLU3-1", True),
    ("Cambio de conducto de cobro - Póliza PLU3-1", "[EXT] Cambio de conducto de cobro - Póliza PLU3-2", False),
    ("Pago", "[EXT] Pago de póliza", False),
    # Recortado en medio del número: OPPT-1 no es OPPT-12.
    ("Cambio de conducto de cobro - Póliza OPPT-12 - Ana", "[EXT] Cambio de conducto de cobro - Póliza OPPT-1", False),
])
def test_mismo_asunto(a, b, igual):
    assert abrir_tramite.mismo_asunto(a, b) is igual


def test_titulo_recortado_que_sirve_para_dos_tramites_no_se_engancha(repo):
    base = "Cambio de conducto de cobro - Póliza PLU3-1"
    for cliente in ("Ana Prueba", "Ana Ruiz"):
        repo.crear_ticket({"proceso": "tramite", "abierto_por": "babilonia", "estado": "abierto",
                           "asunto_hilo": f"{base} - {cliente}"})
    etapa = {"proceso": "tramite", "titulo_hilo": f"[EXT] {base}"}
    assert abrir_tramite.enlazar(repo, etapa) is None  # ambiguo → Ceci lo engancha a mano
    assert abrir_tramite.enlazar(repo, {**etapa, "titulo_hilo": f"[EXT] {base} - Ana Ruiz"})["asunto_hilo"] \
        == f"{base} - Ana Ruiz"


# ---------------------------------------------------------------- API
@pytest.fixture
def cli(repo, monkeypatch):
    monkeypatch.setattr(api, "_repo", repo)
    return TestClient(api.app)


def test_api_catalogo_vista_previa_y_abrir(cli, repo):
    cat = cli.get("/api/tickets-allianz/tramites/catalogo").json()["tramites"]
    assert cat[0] == {"clave": "cambio_conducto_cobro", "nombre": "Cambio de conducto de cobro", "nosotros": True,
                      "requisitos": ["el formato de cambio de conducto de cobro", "la INE vigente del cliente"]}
    body = {"tramite": "cambio_conducto_cobro", "poliza": POLIZA, "adjuntos": FORMATO_E_INE, "usuario": "Ceci"}
    vp = cli.post("/api/tickets-allianz/tramites/vista-previa", json=body).json()
    assert vp["ok"] and vp["adjuntos"] == ["formato.pdf", "ine.pdf"] and "_adjuntos" not in vp and repo.listar_tickets() == []
    r = cli.post("/api/tickets-allianz/tramites", json=body)
    assert r.status_code == 200 and r.json()["ticket_id"]
    assert cli.post("/api/tickets-allianz/tramites", json=body).status_code == 409
    mal = cli.post("/api/tickets-allianz/tramites", json={**body, "poliza": "PLU3-999999"})
    assert mal.status_code == 422 and "No se pudo identificar" in mal.json()["detail"]
    item = cli.get("/api/tickets-allianz").json()["items"][0]
    assert item["abierto_por"] == "babilonia" and item["proceso"] == "tramite"


def retenido(repo):
    """Una escalación a Allianz retenida para Ceci (como la arma recordatorios.py)."""
    tk = repo.crear_ticket({"nro_ticket": "2576612", "estado": "esperando_allianz", "asunto_hilo": "[Allianz] hilo",
                            "gmail_thread_id": "hilo-1", "ultimo_message_id": "<m@x>"})
    repo.crear_accion(tk, "escalar_allianz", "email", {"rol": "allianz", "cuerpo": "Original.",
                                                       "requiere_visto_bueno": True})
    despachar_pendientes(repo, EmisorQueLee())
    (a,) = [x for x in repo.listar_acciones(tk) if x["tipo_accion"] == "escalar_allianz"]
    assert a["estado"] == "pendiente_ceci"
    # Además se le pidió el visto bueno a Ceci por WhatsApp.
    assert any(x["tipo_accion"] == "visto_bueno_ceci" for x in repo.listar_acciones(tk))
    despachar_pendientes(repo, EmisorQueLee())  # ese aviso sale (simulado: sin WATI) y no estorba
    return tk, a["id"]


def test_api_enviar_un_retenido_con_el_borrador_editado(cli, repo):
    tk, aid = retenido(repo)
    item = next(i for i in cli.get("/api/tickets-allianz", params={"filtro": "para_ceci"}).json()["items"] if i["id"] == tk)
    assert "para_aprobar" in item["para_ceci"]
    cli.put(f"/api/tickets-allianz/accion/{aid}/borrador", json={"borrador": "Editado por Ceci."})
    r = cli.post(f"/api/tickets-allianz/accion/{aid}/aprobar", json={"decision": "enviar", "usuario": "Ceci"})
    assert r.json()["estado"] == "sugerida"
    em = EmisorQueLee()
    assert despachar_pendientes(repo, em)["conteo"] == {"enviada": 1}
    assert em.enviados[0]["cuerpo"] == "Editado por Ceci." and em.enviados[0]["hilo_id"] == "hilo-1"
    assert em.enviados[0]["in_reply_to"] == "<m@x>"


def test_api_descartar_un_retenido(cli, repo):
    tk, aid = retenido(repo)
    assert cli.post(f"/api/tickets-allianz/accion/{aid}/aprobar", json={"decision": "descartar"}).json()["estado"] == "rechazada"
    assert despachar_pendientes(repo, EmisorQueLee())["conteo"] == {}
    assert cli.post(f"/api/tickets-allianz/accion/{aid}/aprobar", json={"decision": "enviar"}).status_code == 404
    assert cli.post(f"/api/tickets-allianz/accion/{aid}/aprobar", json={"decision": "otra"}).status_code == 404
