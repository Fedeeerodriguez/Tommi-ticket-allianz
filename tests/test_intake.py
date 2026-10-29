"""Intake: un correo que falla al procesarse queda sin leer en Gmail para reintentarlo."""
import base64

from app import scheduler
from app.intake import gmail_api

RAW = b"From: a@allianz.com.mx\r\nSubject: hola\r\nMessage-ID: <m1@x>\r\n\r\ncuerpo"


class _Req:
    def __init__(self, r):
        self.r = r

    def execute(self):
        return self.r


class _Gmail:
    """Imita users().messages() de la Gmail API con dos correos sin leer."""

    def __init__(self):
        self.marcados = []

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **_):
        return _Req({"messages": [{"id": "1", "threadId": "t1"}, {"id": "2", "threadId": "t2"}]})

    def get(self, id, **_):  # noqa: A002
        return _Req({"raw": base64.urlsafe_b64encode(RAW.replace(b"m1", b"m" + id.encode())).decode()})

    def modify(self, id, **_):  # noqa: A002
        self.marcados.append(id)
        return _Req({})


class _Grafo:
    def invoke(self, estado):
        if estado["correo"].message_id == "<m1@x>":
            raise RuntimeError("se rompió")
        return {}


def test_el_correo_que_falla_no_se_marca_leido(monkeypatch):
    gmail = _Gmail()
    monkeypatch.setattr(gmail_api, "construir_servicio", lambda: gmail)
    monkeypatch.setattr(scheduler, "despachar_pendientes", lambda repo, emisor: {"conteo": {}})
    lector = gmail_api.LectorGmail(pausa_ms=0)
    r = scheduler.job_intake(None, _Grafo(), None, lector=lector, fuente="test")
    assert r["correos"] == 1
    assert gmail.marcados == ["2"]  # el 1 falló → queda sin leer y entra en el próximo ciclo


class _GmailConLeidos(_Gmail):
    """Tres correos en la casilla: el 1 ya está en la base; el 2 y el 3 no (leídos o no, da igual)."""

    def __init__(self):
        super().__init__()
        self.pedidos_list, self.bajados = [], []

    def list(self, **kw):
        self.pedidos_list.append(kw)
        return _Req({"messages": [{"id": "3", "threadId": "t3"}, {"id": "2", "threadId": "t2"},
                                  {"id": "1", "threadId": "t1"}]})

    def get(self, id, **kw):  # noqa: A002
        self.bajados.append(id)
        return super().get(id, **kw)


def test_saltea_los_ya_procesados_y_no_depende_de_leidos(monkeypatch):
    # 29/10: los tickets se abren a mano en hola@ (quedan leídos) y el filtro los reenvía: con
    # "is:unread" en INBOX el sistema casi no los veía. Ahora busca por fecha y saltea por id.
    gmail = _GmailConLeidos()
    monkeypatch.setattr(gmail_api, "construir_servicio", lambda: gmail)
    vistos = []
    lector = gmail_api.LectorGmail(query="newer_than:2d", carpeta="", marcar_leidos=False, pausa_ms=0,
                                   ya_procesados=lambda origenes: vistos.append(origenes) or {"gmail:1"})
    correos = list(lector.leer())
    assert gmail.pedidos_list[0]["labelIds"] is None and gmail.pedidos_list[0]["q"] == "newer_than:2d"
    assert vistos == [["gmail:3", "gmail:2", "gmail:1"]]
    assert gmail.bajados == ["2", "3"]            # el 1 ni se baja; los nuevos, del más viejo al más nuevo
    assert [c.origen for c in correos] == ["gmail:2", "gmail:3"] and gmail.marcados == []


class _Gmail429(_Gmail):
    """Gmail con la cuota agotada: contesta 429 con la hora hasta la que hay que esperar."""

    def __init__(self):
        super().__init__()
        self.llamadas = 0

    def list(self, **_):
        gm = self

        class _R:
            def execute(self):
                gm.llamadas += 1
                raise RuntimeError("<HttpError 429 ... User-rate limit exceeded.  Retry after 2099-01-01T00:00:00.000Z"
                                   " ... 'reason': 'rateLimitExceeded'>")
        return _R()


def test_rate_limit_espera_lo_que_pide_gmail(monkeypatch):
    # 29/10: con la cuota agotada reintentaba 4 veces cada 90 s y cada llamada le corría la espera.
    gmail = _Gmail429()
    monkeypatch.setattr(gmail_api, "construir_servicio", lambda: gmail)
    monkeypatch.setattr(gmail_api, "_pausa_hasta", 0.0)
    lector = gmail_api.LectorGmail(pausa_ms=0)
    assert list(lector.leer()) == [] and gmail.llamadas == 1   # no reintenta
    assert list(lector.leer()) == [] and gmail.llamadas == 1   # el ciclo siguiente ni llama


def test_query_vieja_del_servidor_se_ignora(monkeypatch):
    import importlib

    from app import config
    monkeypatch.setenv("GMAIL_QUERY", "is:unread")
    try:
        assert importlib.reload(config).GMAIL_QUERY == "newer_than:2d -in:sent -in:drafts -in:chats"
    finally:
        monkeypatch.delenv("GMAIL_QUERY")
        importlib.reload(config)


def test_origenes_conocidos(tmp_path):
    from app.db.repo import RepositorioSQLite
    from app.models import Clasificacion, Correo, TipoCorreo
    repo = RepositorioSQLite(str(tmp_path / "t.sqlite"))
    c = Correo("<a@x>", "a@allianz.com.mx", "allianz.com.mx", [], [], "hola", "cuerpo")
    c.origen = "gmail:abc"
    repo.guardar_correo(c, Clasificacion(TipoCorreo.G_SISTEMA, 0.9, "x"), {})
    assert repo.origenes_conocidos(["gmail:abc", "gmail:zzz"]) == {"gmail:abc"}
    assert repo.origenes_conocidos([]) == set()
