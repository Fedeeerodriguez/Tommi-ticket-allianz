"""Tercer camino de la solicitud firmada (Ceci, 17/11): llega por correo a integraciones@."""
import base64
import json
from email.message import EmailMessage

from app import config
from app.acciones import abrir_tramite, solicitud_correo, solicitud_tramite
from app.grafo import construir_grafo
from app.intake.reader import normalizar_desde_bytes

from test_abrir_tramite import POLIZA, cli, repo  # noqa: F401 — fixtures

ASESOR = "asesor1@babilonia.ai"      # el asesor de la póliza en Notion (fila() de test_abrir_tramite)


def correo(remitente=ASESOR, asunto=f"Cambio de conducto de cobro póliza {POLIZA}",
           cuerpo="Hola, les mando la solicitud firmada del cliente y su INE para cambiar la tarjeta.",
           adjuntos=(("solicitud_firmada.pdf", "application/pdf"), ("ine.jpg", "image/jpeg")), mid="m1"):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = remitente, "integraciones@babilonia.ai", asunto, f"<{mid}@x>"
    m.set_content(cuerpo)
    for nombre, tipo in adjuntos:
        principal, sub = tipo.split("/")
        m.add_attachment(f"contenido de {nombre}".encode(), maintype=principal, subtype=sub, filename=nombre)
    return normalizar_desde_bytes(m.as_bytes(), origen=f"gmail:{mid}")


def correr(repo, c):
    return construir_grafo(repo).invoke({"correo": c, "despachar": False})


def acciones(repo, tid, tipo=None):
    return [a for a in repo.listar_acciones(tid) if tipo is None or a["tipo_accion"] == tipo]


def test_el_lector_guarda_pdf_e_imagenes_pero_no_otros_adjuntos():
    c = correo(adjuntos=(("a.pdf", "application/pdf"), ("b.png", "image/png"), ("c.zip", "application/zip")))
    assert [a["nombre"] for a in c.adjuntos_datos] == ["a.pdf", "b.png"]
    assert base64.b64decode(c.adjuntos_datos[0]["base64"]) == b"contenido de a.pdf"


def test_el_asesor_la_manda_completa_y_queda_la_solicitud_para_ceci(repo):
    out = correr(repo, correo())
    assert out["fin"] == "solicitud_correo"
    t = repo.obtener_ticket(out["ticket_id"])
    assert (t["estado"], t["proceso"], t["poliza"]) == ("solicitud", "tramite", POLIZA)
    s = solicitud_tramite.leer(repo, t["id"])
    assert (s["tramite"], s["origen"], s["quien"], s["archivos"]) == ("cambio_conducto_cobro", "correo", "asesor", 2)
    assert [a["nombre"] for a in solicitud_correo.leer_adjuntos(repo, t["id"])] == ["solicitud_firmada.pdf", "ine.jpg"]
    (aviso,) = acciones(repo, t["id"], "avisar_ceci")
    assert "Llegó por correo a integraciones@" in aviso["payload"] and "⚠️" not in aviso["payload"]
    assert not acciones(repo, t["id"], "abrir_tramite")             # nada a Allianz sin Ceci
    # El mismo pedido otra vez no duplica la solicitud.
    otra = correr(repo, correo(mid="m2"))
    assert otra["fin"] == "solicitud_existente" and len(repo.listar_tickets()) == 1


def test_ceci_la_abre_con_los_adjuntos_del_correo(repo):
    tid = correr(repo, correo())["ticket_id"]
    adj = [{k: a[k] for k in ("nombre", "tipo", "base64")} for a in solicitud_correo.leer_adjuntos(repo, tid)]
    r = abrir_tramite.abrir(repo, "cambio_conducto_cobro", POLIZA, adjuntos=adj, solicitud_id=tid)
    assert r["ok"] and r["ticket_id"] == tid
    (a,) = acciones(repo, tid, "abrir_tramite")
    assert [x["nombre"] for x in json.loads(a["payload"])["adjuntos"]] == ["solicitud_firmada.pdf", "ine.jpg"]


def test_si_falta_un_adjunto_se_le_pide_al_asesor(repo):
    out = correr(repo, correo(adjuntos=(("solicitud_firmada.pdf", "application/pdf"),)))
    assert out["fin"] == "solicitud_correo_incompleta"
    assert repo.obtener_ticket(out["ticket_id"])["estado"] == "esperando_asesor"
    (ases,) = acciones(repo, out["ticket_id"], "avisar_asesor")
    assert "Reenvía el correo a integraciones@babilonia.ai" in ases["payload"]


def test_de_un_remitente_desconocido_queda_con_advertencia(repo):
    out = correr(repo, correo(remitente="alguien@gmail.com"))
    assert out["fin"] == "solicitud_correo"
    (aviso,) = acciones(repo, out["ticket_id"], "avisar_ceci")
    assert "⚠️" in aviso["payload"] and "alguien@gmail.com" in aviso["payload"]


def test_no_se_dispara_con_correos_de_allianz_nuestros_o_sin_poliza(repo):
    assert correr(repo, correo(remitente="Allianz.Mexico@allianz.com.mx", mid="a"))["fin"] != "solicitud_correo"
    assert correr(repo, correo(remitente=config.BUZON, mid="b"))["fin"] != "solicitud_correo"
    sin_poliza = correo(asunto="Cambio de conducto de cobro", mid="c")
    assert correr(repo, sin_poliza)["fin"] != "solicitud_correo"
    assert not [t for t in repo.listar_tickets() if t["estado"] == "solicitud"]


def test_el_panel_ve_de_donde_vino_y_trae_los_adjuntos(cli, repo, monkeypatch):
    monkeypatch.setattr(config, "TOMI_JWT_SECRET", "")
    tid = correr(repo, correo())["ticket_id"]
    item = cli.get("/api/tickets-allianz?filtro=para_ceci").json()["items"][0]
    assert item["solicitud"]["origen"] == "correo" and item["solicitud"]["remitente"] == ASESOR
    r = cli.get(f"/api/tickets-allianz/tramites/solicitud/{tid}/archivos").json()
    assert r["ok"] and [a["nombre"] for a in r["archivos"]] == ["solicitud_firmada.pdf", "ine.jpg"]
    assert r["archivos"][0]["base64"]
