"""Etapa 3B (opción 2): el cliente pide el trámite a Tommy por WhatsApp y Ceci lo abre desde el panel."""
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


def test_sin_los_archivos_le_pide_los_requisitos(repo, monkeypatch):
    con_archivos(monkeypatch, 1)
    r = pedir(repo)
    assert not r["ok"] and r["recibidos"] == 1
    assert "el formato de cambio de conducto de cobro y la INE vigente del cliente" in r["para_cliente"]
    assert repo.listar_tickets() == []


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
