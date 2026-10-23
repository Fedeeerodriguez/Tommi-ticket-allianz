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
