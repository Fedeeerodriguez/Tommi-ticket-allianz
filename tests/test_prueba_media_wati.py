"""Prueba F5 de WATI: reconoce los mensajes con archivo y el tipo real de lo bajado."""
from app.run_prueba_media_wati import mensajes_con_archivo, tipo_por_firma


def test_toma_solo_los_mensajes_con_archivo_en_las_dos_formas_de_wati():
    items = [{"type": "text", "text": "hola"},
             {"type": "image", "data": "data/images/a.jpg", "created": "2026-10-28", "owner": False},
             {"type": "document", "fileName": "b.pdf", "owner": True},
             {"type": "image"}]
    for resp in ({"messages": {"items": items}}, {"messages": items}):
        r = mensajes_con_archivo(resp)
        assert [(m["tipo"], m["archivo"], m["nuestro"]) for m in r] == [
            ("image", "data/images/a.jpg", False), ("document", "b.pdf", True)]
    assert mensajes_con_archivo("error") == []


def test_tipo_real_por_la_firma():
    assert tipo_por_firma(b"%PDF-1.7 ...") == "pdf"
    assert tipo_por_firma(b"\xff\xd8\xff\xe0") == "jpg"
    assert tipo_por_firma(b"\x00\x00\x00\x18ftypmp42") == "mp4"
    assert tipo_por_firma(b"<html>no autorizado") == "?"


class _Resp:
    def __init__(self, status, contenido=b"", json=None, tipo=""):
        self.status_code, self.content, self._json = status, contenido, json
        self.headers = {"content-type": tipo}
        self.text = contenido.decode("latin-1")

    def json(self):
        return self._json


class _Http:
    """Imita httpx: getMessages con 2 archivos; uno baja bien y el otro da 404."""

    def __init__(self):
        self.pedidos = []

    def get(self, url, params=None, headers=None, **_):
        self.pedidos.append((url, params, headers))
        if "getMessages" in url:
            return _Resp(200, json={"messages": {"items": [
                {"type": "document", "data": "data/docs/estado.pdf"},
                {"type": "image", "data": "https://wati.example/media/borrada.jpg"}]}})
        if "getMedia" in url:
            return _Resp(200, b"%PDF-1.4 contenido", tipo="application/pdf")
        return _Resp(404, b"not found")


def test_main_baja_lo_que_puede_y_lo_cuenta(monkeypatch, tmp_path, capsys):
    import sys
    http = _Http()
    monkeypatch.setitem(sys.modules, "httpx", http)
    monkeypatch.setenv("WATI_API_URL", "https://wati.example/")
    monkeypatch.setenv("WATI_API_TOKEN", "Bearer tok")
    monkeypatch.setattr(sys, "argv", ["x", "--numero", "+52 1 555", "--guardar", str(tmp_path)])
    from app import run_prueba_media_wati as p
    assert p.main() == 0
    salida = capsys.readouterr().out
    assert "1 de 2 archivos bajados enteros" in salida
    assert (tmp_path / "archivo_1.pdf").read_bytes().startswith(b"%PDF")
    assert http.pedidos[0][0] == "https://wati.example/api/v1/getMessages/521555"
    assert http.pedidos[1][1] == {"fileName": "data/docs/estado.pdf"}
    assert all(h == {"Authorization": "Bearer tok"} for _, _, h in http.pedidos)
