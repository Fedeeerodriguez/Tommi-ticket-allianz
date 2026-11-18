"""Etapa 3B (opción 2): el cliente pide el trámite a Tommy por WhatsApp y Ceci lo abre desde el panel."""
import json

from app import config
from app.acciones import abrir_tramite, solicitud_tramite
from app.wati import archivos

from test_abrir_tramite import FORMATO_E_INE, POLIZA, cli, repo  # noqa: F401 — fixtures

WA = "5215512345678"   # el WhatsApp del titular (Notion lo tiene como 5512345678)


def con_archivos(monkeypatch, n):
    monkeypatch.setattr(archivos, "archivos_del_cliente",
                        lambda tel, dias=14, http=None: {"ok": True, "archivos": [{"nombre": f"a{i}"} for i in range(n)]})


def pedir(repo, **kw):
    datos = {"tramite": "cambio_conducto_cobro", "poliza": POLIZA, "wa_id": WA, **kw}
    return solicitud_tramite.solicitar(repo, datos.pop("tramite"), datos.pop("poliza"), datos.pop("wa_id"), **datos)


def test_con_formato_e_ine_deja_la_solicitud_y_avisa_a_ceci(repo, monkeypatch):
    con_archivos(monkeypatch, 2)
    r = pedir(repo, nota="Cambio a mi nueva tarjeta BBVA")
    assert r["ok"] and "Ya dejé tu solicitud" in r["para_cliente"]
    t = repo.obtener_ticket(r["ticket_id"])
    assert (t["estado"], t["abierto_por"], t["proceso"], t["poliza"]) == ("solicitud", "tommy", "tramite", POLIZA)
    assert solicitud_tramite.leer(repo, t["id"])["tramite"] == "cambio_conducto_cobro"
    (aviso,) = [a for a in repo.listar_acciones(t["id"]) if a["tipo_accion"] == "avisar_ceci"]
    assert "pidió por WhatsApp el cambio de conducto de cobro" in aviso["payload"] \
        and "nueva tarjeta BBVA" in aviso["payload"]
    # Nada para Allianz hasta que Ceci lo abra.
    assert not [a for a in repo.listar_acciones(t["id"]) if a["tipo_accion"] == "abrir_tramite"]
    # Si lo vuelve a pedir, no se duplica.
    otra = pedir(repo)
    assert otra["ya_existia"] and otra["ticket_id"] == t["id"] and len(repo.listar_tickets()) == 1


def test_sin_la_solicitud_firmada_se_la_pide_al_asesor(repo, monkeypatch):
    # Ceci, 17/11: sin la solicitud firmada no se abre; se le pide al asesor que la consiga.
    con_archivos(monkeypatch, 1)
    r = pedir(repo)
    assert not r["ok"] and r["recibidos"] == 1
    assert "el formato de cambio de conducto de cobro y la INE vigente del cliente" in r["para_cliente"]
    assert "Tu asesor te va a contactar" in r["para_cliente"]
    (ases,) = [a for a in repo.listar_acciones(r["ticket_id"]) if a["tipo_accion"] == "avisar_asesor"]
    assert "falta el formato de cambio de conducto de cobro" in ases["payload"]
    assert not [a for a in repo.listar_acciones(r["ticket_id"]) if a["tipo_accion"] == "abrir_tramite"]
    # Cuando llega la firma, la solicitud se crea igual (no la frena el ticket de "falta la firma").
    con_archivos(monkeypatch, 2)
    assert pedir(repo)["motivo"] == "solicitud creada: espera a Ceci"


def test_tramite_del_portal_le_avisa_a_ceci(repo):
    r = pedir(repo, tramite="cambio_fecha_pago")
    assert r["portal"] and "Entra a tu portal" in r["para_cliente"]           # tuteo mexicano
    (aviso,) = [a for a in repo.listar_acciones(r["ticket_id"]) if a["tipo_accion"] == "avisar_ceci"]
    assert "Se hace desde el portal" in aviso["payload"]


def test_el_cliente_lo_pide_por_correo_y_las_instrucciones_esperan_a_ceci(repo):
    r = pedir(repo, tramite="suspension_aportaciones")
    assert r["ok"] and "En un momento te paso" in r["para_cliente"]
    (a,) = repo.listar_acciones(r["ticket_id"])
    assert (a["tipo_accion"], a["canal"], a["estado"]) == ("instruir_tramite", "wati", "pendiente_ceci")
    msg = json.loads(a["payload"])["mensaje"]
    # PLU3 → cliente.optimaxx@, con copia a integraciones@ y el asunto "Trámite / Póliza / Nombre" (Ceci, 17/11).
    assert "a cliente.optimaxx@allianz.com.mx con copia a integraciones@babilonia.ai" in msg
    assert f"En el asunto pon: Suspensión de aportaciones / {POLIZA} /" in msg


def test_la_cancelacion_va_a_ceci_y_al_asesor_sin_instrucciones(repo):
    r = pedir(repo, tramite="cancelacion_poliza", nota="ya no puedo pagar")
    assert r["ok"] and r["delicado"] and "Tu asesor se va a poner en contacto" in r["para_cliente"]
    roles = sorted(json.loads(a["payload"])["rol"] for a in repo.listar_acciones(r["ticket_id"]))
    assert roles == ["asesor", "ceci"]
    assert repo.obtener_ticket(r["ticket_id"])["delicado"]


def test_el_tramite_abierto_va_con_copia_al_ejecutivo_sin_penny():
    assert abrir_tramite.copias("SVIP-21799") == ["jose.monterrosa@allianz.com.mx"]
    assert abrir_tramite.copias("GMMI-101770") == ["blanca.xuluc@allianz.com.mx"]
    assert abrir_tramite.copias("XXXX-1") == []


def test_otro_numero_no_puede_pedir_por_la_poliza(repo, monkeypatch):
    con_archivos(monkeypatch, 2)
    r = pedir(repo, wa_id="5219999999999")
    assert not r["ok"] and "titular" in r["para_cliente"] and repo.listar_tickets() == []


def test_tramite_del_portal_devuelve_las_instrucciones(repo):
    r = pedir(repo, tramite="cambio_beneficiario")
    assert not r["ok"] and r["portal"] and "clientes.allianz.com.mx" in r["para_cliente"]


def test_poliza_que_no_existe(repo):
    r = pedir(repo, poliza="PLU3-999999")
    assert not r["ok"] and "No encontré esa póliza" in r["para_cliente"]


def test_ceci_la_abre_sobre_el_mismo_ticket(repo, monkeypatch):
    con_archivos(monkeypatch, 2)
    tid = pedir(repo)["ticket_id"]
    r = abrir_tramite.abrir(repo, "cambio_conducto_cobro", POLIZA, adjuntos=FORMATO_E_INE, solicitud_id=tid)
    assert r["ok"] and r["ticket_id"] == tid and len(repo.listar_tickets()) == 1
    t = repo.obtener_ticket(tid)
    assert (t["estado"], t["abierto_por"]) == ("abierto", "tommy")
    assert [a for a in repo.listar_acciones(tid) if a["tipo_accion"] == "abrir_tramite"]
    # Ya no es una solicitud: no se puede abrir dos veces.
    assert not abrir_tramite.abrir(repo, "cambio_conducto_cobro", POLIZA, adjuntos=FORMATO_E_INE,
                                   solicitud_id=tid)["ok"]


def test_api_tommy_con_su_clave_y_ceci_la_ve_y_la_descarta(cli, repo, monkeypatch):
    con_archivos(monkeypatch, 2)
    monkeypatch.setattr(config, "TOMI_INTERNAL_KEY", "clave-tommy")
    monkeypatch.setattr(config, "TOMI_JWT_SECRET", "otra")
    body = {"tramite": "cambio_conducto_cobro", "poliza": POLIZA, "wa_id": WA}
    assert cli.post("/api/tickets-allianz/tramites/solicitud", json=body).status_code == 401
    assert cli.post("/api/tickets-allianz/tramites/solicitud", json=body,
                    headers={"X-Tomi-Key": "mala"}).status_code == 401
    r = cli.post("/api/tickets-allianz/tramites/solicitud", json=body, headers={"X-Tomi-Key": "clave-tommy"}).json()
    assert r["ok"]
    monkeypatch.setattr(config, "TOMI_JWT_SECRET", "")  # el panel, como en el resto de los tests
    item = cli.get("/api/tickets-allianz?filtro=para_ceci").json()["items"][0]
    assert "solicitud_tommy" in item["para_ceci"]
    assert item["solicitud"]["tramite"] == "cambio_conducto_cobro"
    assert item["solicitud"]["tramite_nombre"] == "Cambio de conducto de cobro"
    d = cli.post(f"/api/tickets-allianz/tramites/solicitud/{r['ticket_id']}/descartar", json={"motivo": "duplicada"})
    assert d.status_code == 200 and repo.obtener_ticket(r["ticket_id"])["estado"] == "resuelto"
    assert cli.post(f"/api/tickets-allianz/tramites/solicitud/{r['ticket_id']}/descartar", json={}).status_code == 409


def test_el_acuse_se_engancha_a_la_solicitud_abierta_y_no_a_una_sin_abrir(repo, monkeypatch):
    con_archivos(monkeypatch, 2)
    tid = pedir(repo)["ticket_id"]
    asunto = repo.obtener_ticket(tid)["asunto_hilo"]
    etapa = {"proceso": "tramite", "titulo_hilo": f"[EXT] {asunto}"}
    assert abrir_tramite.enlazar(repo, etapa) is None              # todavía no salió a Allianz
    abrir_tramite.abrir(repo, "cambio_conducto_cobro", POLIZA, adjuntos=FORMATO_E_INE, solicitud_id=tid)
    assert abrir_tramite.enlazar(repo, etapa)["id"] == tid


def test_ceci_autoriza_las_instrucciones_y_le_salen_al_cliente(repo, monkeypatch):
    from app.acciones.despacho import despachar_pendientes
    from app.rieles import telegram
    r = pedir(repo, tramite="periodo_descanso")
    (a,) = repo.listar_acciones(r["ticket_id"])
    despachar_pendientes(repo)                                    # nada: espera a Ceci
    assert repo.listar_acciones(r["ticket_id"])[0]["estado"] == "pendiente_ceci"
    enviados = []

    class _Wati:
        modo = "wati"

        def enviar_plantilla(self, numero, plantilla, params=None):
            enviados.append((numero, plantilla, params))
            return {"ok": True}
    monkeypatch.setattr(config, "DRY_RUN", False)
    monkeypatch.setattr(config, "ENVIO_REAL", ["tickets"])
    monkeypatch.setattr("app.wati.wati_desde_config", lambda: _Wati())
    from app.envio import interruptor
    interruptor.cambiar(repo, "tickets", True)
    assert telegram.autorizar_accion(repo, a["id"], "telegram:ceci", "Hola, manda el correo a cliente.optimaxx@…")["ok"]
    despachar_pendientes(repo)
    assert enviados and enviados[0][1] == config.WATI_PLANTILLA_AVISO_CLIENTE
    assert enviados[0][2]["mensaje"].startswith("Manda el correo a cliente.optimaxx@")   # el texto de Ceci
