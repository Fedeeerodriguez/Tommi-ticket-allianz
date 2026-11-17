"""Intake desde integraciones@ (17/11): casilla de lectura aparte, paginación y envío a Allianz desde ahí."""
import base64

from app import config
from app.envio import EmisorLaboratorio, emisor_allianz
from app.envio import gmail_api as envio_gmail
from app.intake import gmail_api, lector_desde_config


class _Req:
    def __init__(self, r=None, ex=None):
        self.r, self.ex = r, ex

    def execute(self):
        if self.ex:
            raise self.ex
        return self.r


def _raw(i):
    return base64.urlsafe_b64encode(
        f"From: a@allianz.com.mx\r\nSubject: s{i}\r\nMessage-ID: <m{i}@x>\r\n\r\nc".encode()).decode()


class _GmailPaginado:
    """250 correos en la ventana, en páginas de 100 (más nuevo primero, como Gmail)."""

    def __init__(self, n=250):
        self.ids = [str(i) for i in range(n, 0, -1)]
        self.pedidos, self.bajados = [], []

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, pageToken=None, **kw):
        self.pedidos.append(pageToken)
        ini = int(pageToken or 0)
        pag = self.ids[ini:ini + 100]
        r = {"messages": [{"id": i, "threadId": "t" + i} for i in pag]}
        if ini + 100 < len(self.ids):
            r["nextPageToken"] = str(ini + 100)
        return _Req(r)

    def get(self, id, **_):  # noqa: A002
        self.bajados.append(id)
        return _Req({"raw": _raw(id)})


def test_pagina_toda_la_ventana_y_baja_los_mas_viejos_primero(monkeypatch):
    gmail = _GmailPaginado()
    pedidas = []
    monkeypatch.setattr(gmail_api, "construir_servicio", lambda buzon="envio": pedidas.append(buzon) or gmail)
    lector = gmail_api.LectorGmail(query="newer_than:2d", carpeta="", marcar_leidos=False, pausa_ms=0,
                                   limite=40, ya_procesados=lambda o: set(), buzon="lectura")
    correos = list(lector.leer())
    assert pedidas == ["lectura"]
    assert gmail.pedidos == [None, "100", "200"]            # 3 páginas: antes veía solo las 100 más nuevas
    assert gmail.bajados[:3] == ["1", "2", "3"] and len(correos) == 40


def test_corta_en_max_paginas(monkeypatch):
    gmail = _GmailPaginado(n=1000)
    monkeypatch.setattr(gmail_api, "construir_servicio", lambda *a: gmail)
    lector = gmail_api.LectorGmail(query="q", carpeta="", marcar_leidos=False, pausa_ms=0, limite=5,
                                   ya_procesados=lambda o: set(), max_paginas=2)
    list(lector.leer())
    assert len(gmail.pedidos) == 2


def test_no_vuelve_a_bajar_un_correo_que_la_base_descarto_por_duplicado(monkeypatch):
    # Un aviso que ya entró por hola@ tiene otro id en integraciones@: la base lo descarta por Message-ID
    # sin guardar este origen. Sin memoria se volvía a bajar cada 90 s durante 2 días (cuota de octubre).
    gmail = _GmailPaginado(n=3)
    monkeypatch.setattr(gmail_api, "construir_servicio", lambda *a: gmail)

    def lector():
        return gmail_api.LectorGmail(query="q", carpeta="", marcar_leidos=False, pausa_ms=0,
                                     ya_procesados=lambda o: set(), buzon="lectura")
    assert len(list(lector().leer())) == 3
    assert list(lector().leer()) == [] and gmail.bajados == ["1", "2", "3"]


def test_el_que_fallo_se_reintenta(monkeypatch):
    gmail = _GmailPaginado(n=2)
    monkeypatch.setattr(gmail_api, "construir_servicio", lambda *a: gmail)

    def lector():
        return gmail_api.LectorGmail(query="q", carpeta="", marcar_leidos=False, pausa_ms=0,
                                     ya_procesados=lambda o: set())
    for c in lector().leer():
        c.fallo = c.message_id == "<m1@x>"
    assert [c.message_id for c in lector().leer()] == ["<m1@x>"]


def test_con_token_de_integraciones_lee_solo_esa_casilla(monkeypatch, tmp_path):
    tok = tmp_path / "tok.json"
    tok.write_text("{}")
    monkeypatch.setattr(config, "GMAIL_LECTURA_TOKEN_JSON", str(tok))
    lector, fuente = lector_desde_config()
    assert lector.buzon == "lectura" and fuente == "Gmail API integraciones@babilonia.ai"
    assert lector.max_paginas == config.GMAIL_MAX_PAGINAS == 10
    assert lector.query.endswith('-subject:"Codigo de Seguridad"')   # los códigos de acceso no se bajan


def test_sin_token_de_integraciones_sigue_leyendo_hola(monkeypatch, tmp_path):
    tok = tmp_path / "tok.json"
    tok.write_text("{}")
    monkeypatch.setattr(config, "GOOGLE_TOKEN", "")
    monkeypatch.setattr(config, "GOOGLE_TOKEN_JSON", str(tok))
    lector, fuente = lector_desde_config()
    assert lector.buzon == "envio" and fuente == f"Gmail API {config.BUZON}"
    assert lector.query == config.GMAIL_QUERY


def test_correos_a_allianz_salen_desde_integraciones(monkeypatch, tmp_path):
    lab = EmisorLaboratorio("hola@babilonia.ai")
    assert emisor_allianz(lab) is lab                         # sin casilla de lectura: igual que antes
    monkeypatch.setattr(config, "GMAIL_LECTURA_TOKEN", '{"x": 1}')
    em = emisor_allianz(lab)
    assert em.enviar(["mesa@allianz.com.mx"], "a", "b")["de"] == "integraciones@babilonia.ai"
    real = emisor_allianz(envio_gmail.EmisorGmail("hola@babilonia.ai"))
    assert real.buzon == "lectura" and real.remitente == "integraciones@babilonia.ai"
    monkeypatch.setattr(config, "ALLIANZ_DESDE_LECTURA", False)
    assert emisor_allianz(lab) is lab


class _GmailEnvio:
    def __init__(self):
        self.cuerpos = []

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):  # noqa: N803
        self.cuerpos.append(dict(body))
        if "threadId" in body:
            return _Req(ex=RuntimeError("<HttpError 404 ... Requested entity was not found.>"))
        return _Req({"id": "nuevo", "threadId": "t-nuevo"})


def test_hilo_de_otra_casilla_sale_igual_sin_threadid(monkeypatch):
    gmail = _GmailEnvio()
    monkeypatch.setattr(envio_gmail, "construir_servicio", lambda buzon="envio": gmail)
    res = envio_gmail.EmisorGmail("integraciones@babilonia.ai", buzon="lectura").enviar(
        ["mesa@allianz.com.mx"], "[Allianz México Ticket-1] x", "cuerpo", hilo_id="hilo-de-hola", in_reply_to="<m@x>")
    assert res["ok"] and not res["en_hilo"]
    assert "threadId" in gmail.cuerpos[0] and "threadId" not in gmail.cuerpos[1]


def test_una_rafaga_de_cobranza_no_saca_a_los_tickets_del_panel(tmp_path, monkeypatch):
    # En integraciones@ la cobranza llega en ráfagas (585 avisos el 08/11): mezclada, dejaba a los tickets
    # fuera de los 500 más recientes que mira el panel.
    from fastapi.testclient import TestClient

    from app import api
    from app.db.repo import RepositorioSQLite
    repo = RepositorioSQLite(str(tmp_path / "t.sqlite"))
    tk = repo.crear_ticket({"nro_ticket": "77", "estado": "abierto", "proceso": "largo"})
    for i in range(510):
        repo.crear_ticket({"estado": "resuelto", "proceso": "cobranza", "poliza": f"PLU3-{i}"})
    assert [t["id"] for t in repo.listar_tickets(limite=500, cobranza=False)] == [tk]
    assert len(repo.listar_tickets(limite=500, cobranza=True)) == 500
    monkeypatch.setattr(api, "_repo", repo)
    r = TestClient(api.app).get("/api/tickets-allianz").json()
    assert [t["id"] for t in r["items"]] == [tk] and r["resumen"]["cobranzas"] == 510


def test_el_pie_de_allianz_no_marca_el_ticket_como_delicado():
    from app.models import Correo
    from app.tickets.engine import es_delicado
    pie = ("El tiempo de respuesta puede variar dependiendo del tipo de trámite, consulta y/o reclamación que "
           "solicite, siempre y cuando conte con la documentación completa.")
    c = Correo("<m@x>", "a@allianz.com.mx", "allianz.com.mx", [], [], "[Allianz México Ticket-2601234] Sistema escribió un mensaje",
               "Recibimos su trámite de cambio de conducto de cobro.\n" + pie)
    assert not es_delicado(c)
    c.cuerpo_texto = ("Su solicitud ha sido resuelto y por lo tanto no es posible realizar ningún cambio o cancelación "
                      "después de haber recibido este correo.")
    assert not es_delicado(c)
    c.asunto = "[Allianz México Ticket-2601234] Sistema escribió un mensaje en [EXT] CANCELACIÓN DE POLIZA"
    assert es_delicado(c)


def test_cierres_de_la_mesa_de_servicio_e_inactividad():
    from app.clasificador.etapas import Etapa, detectar_etapa
    r = detectar_etapa("[Service Desk Ticket-2610001] MONICA SANCHEZ resolvió su solicitud",
                       "Hola,\nSolicitud atendida\nMONICA SANCHEZ resolvió su solicitud [EXT] CAMBIO CONDUCTO", "x@allianz.com.mx")
    assert r.etapa == Etapa.ATENDIDA and r.nro_ticket == "2610001" and r.actor
    r = detectar_etapa("[Allianz MéxicoTicket-2610002] Su solicitud ha sido cerrada por inactividad",
                       "Estimado cliente.", "allianz.mexico@allianz.com.mx")
    assert r.etapa == Etapa.CERRADO_INACTIVIDAD and r.nro_ticket == "2610002"
