"""Paso 3 — identificar cliente y asesor sin adivinar. Casos sacados del sondeo real de Notion (19/10)."""
import pytest

from app.db.repo import RepositorioSQLite
from app.enriquecimiento.identificar import identificar, identificar_y_guardar, mismo_nombre, nombres_compatibles
from app.rieles.notion import misma_poliza, norm_poliza, numero_poliza


def fila(nombre, sol=None, poliza=None, tel="5512345678", asesor="asesor1@babilonia.ai", asesor_nombre="Asesor Uno"):
    return {"cliente_nombre": nombre, "nro_solicitud": sol, "poliza": poliza, "telefono_cliente": tel,
            "asesor_correo": asesor, "asesor_nombre": asesor_nombre, "telefono_asesor": "5598765432"}


EMISIONES = [
    fila("José Daniel Rosas Rayas", sol=25232752),
    fila("José Daniel Rosas Rayas", poliza="PLU3-431963"),
    fila("Hortencia Gonzalez Gama", sol=1950110, poliza="PLU3-111111"),
    fila("Hortencia  Gonzalez Gama", poliza="PLU3-222222"),            # misma persona, otra póliza
    fila("Liliana Berenice Mena Gonzalez", tel="5511111111", asesor="a@b.ai"),
    fila("Liliana Berenice Mena Gonzalez", tel="5522222222", asesor="otro@b.ai"),  # homónima
    fila("Angeles Montserrat Oropeza Camacho", poliza="PLU3-421131"),
    fila("Diana Castor Fariña", poliza="PLU3-221131"),
    fila("Rodrigo Schiavon Banck", poliza="GMLI-1131", asesor="gm@b.ai"),
    fila("Francisco Javier Rodríguez Cruz", sol=25254376),
    fila("Cliente Equivocado Perez", sol=999001),
]


def notion_falso(filas=EMISIONES, max_por_pagina=None):
    """Como Notion: contains ignora mayúsculas pero NO acentos; equals numérico."""
    def buscar(campo, op, valor, n):
        if campo == "nro_solicitud":
            res = [f for f in filas if f["nro_solicitud"] is not None and str(f["nro_solicitud"]) == str(valor)]
        else:
            res = [f for f in filas if f.get(campo) and str(valor).lower() in f[campo].lower()]
        tope = max_por_pagina or n
        return res[:tope], len(res) > tope
    return buscar


B = notion_falso()


def test_por_solicitud_y_el_nombre_coincide_sin_acentos():
    r = identificar(nro_solicitud="25232752", cliente="JOSE DANIEL ROSAS RAYAS", buscar=B)
    assert r.ok and r.via == "solicitud" and r.datos["telefono_asesor"] == "5598765432"


def test_solicitud_de_otro_cliente_no_se_usa():
    r = identificar(nro_solicitud="999001", cliente="MARTHA ZARATE URIBE", buscar=B)
    assert r.estado == "ambiguo" and "otro cliente" in r.motivo


def test_por_poliza_exacta_no_por_contiene():
    # 'contains 1131' trae PLU3-421131 y PLU3-221131 (clientes ajenos): tiene que quedarse con GMLI-1131.
    r = identificar(poliza="GMLI_1131_0", cliente="RODRIGO SCHIAVON BANCK", buscar=B)
    assert r.ok and r.via == "poliza" and r.datos["asesor_correo"] == "gm@b.ai"


def test_poliza_inexistente_no_matchea_parecidas():
    r = identificar(poliza="PLU3-1131", buscar=B)
    assert not r.ok and r.estado == "sin_coincidencia"


def test_por_nombre_con_acentos_en_notion():
    # 'rodriguez' no matchea 'Rodríguez' en Notion; se prueba con otras palabras ('francisco', 'javier').
    r = identificar(cliente="FRANCISCO JAVIER RODRIGUEZ CRUZ", buscar=B)
    assert r.ok and r.via == "nombre"


def test_misma_persona_varias_polizas_es_una_sola():
    r = identificar(cliente="HORTENCIA GONZALEZ GAMA", buscar=B)
    assert r.ok and r.candidatos == 2


def test_homonimos_con_otro_asesor_van_a_ceci():
    r = identificar(cliente="LILIANA BERENICE MENA GONZALEZ", buscar=B)
    assert r.estado == "ambiguo" and not r.ok


def test_no_esta_en_notion():
    r = identificar(nro_solicitud="98577", cliente="MARTHA ZARATE URIBE", buscar=B)
    assert r.estado == "sin_coincidencia"


def test_busqueda_incompleta_no_decide():
    # Cada palabra trae "hay más" → no hay lista completa para comparar → no se adivina.
    r = identificar(cliente="HORTENCIA GONZALEZ GAMA", buscar=notion_falso(max_por_pagina=1))
    assert not r.ok


def test_sin_datos_y_sin_notion(monkeypatch):
    assert identificar(buscar=B).estado == "sin_datos"
    from app import config
    monkeypatch.setattr(config, "hay_notion", lambda: False)
    assert identificar(cliente="ANA PEREZ LOPEZ").estado == "sin_notion"


def test_notion_que_falla_no_adivina():
    def roto(*a):
        raise TimeoutError("timeout")
    assert identificar(cliente="ANA PEREZ LOPEZ", buscar=roto).estado == "sin_coincidencia"


def test_guarda_en_el_ticket_y_despues_reusa(tmp_path):
    repo = RepositorioSQLite(str(tmp_path / "t.sqlite"))
    tid = repo.crear_ticket({"nro_ticket": "2576612", "estado": "abierto", "asesor_correo": "viejo@mal.ai"})
    t = repo.obtener_ticket(tid)
    # Lo que llenó el enriquecimiento viejo no se reusa: se verifica de nuevo.
    r = identificar_y_guardar(repo, t, {"nro_solicitud": "25232752", "cliente": "JOSE DANIEL ROSAS RAYAS"}, buscar=B)
    assert r.ok and r.via == "solicitud"
    t = repo.obtener_ticket(tid)
    assert t["identificado_por"] == "solicitud" and t["asesor_correo"] == "asesor1@babilonia.ai"
    assert t["telefono_cliente"] == "5512345678"
    assert [e["tipo_evento"] for e in repo.listar_eventos(tid)] == ["identificacion"]

    def no_llamar(*a):
        raise AssertionError("no debería consultar Notion")
    r2 = identificar_y_guardar(repo, t, {"cliente": "JOSE DANIEL ROSAS RAYAS"}, buscar=no_llamar)
    assert r2.ok and r2.via == "ticket" and len(repo.listar_eventos(tid)) == 1


def test_no_identificado_no_toca_el_ticket(tmp_path):
    repo = RepositorioSQLite(str(tmp_path / "t.sqlite"))
    tid = repo.crear_ticket({"nro_ticket": "1", "estado": "abierto"})
    r = identificar_y_guardar(repo, repo.obtener_ticket(tid), {"cliente": "LILIANA BERENICE MENA GONZALEZ"}, buscar=B)
    assert not r.ok and repo.obtener_ticket(tid)["identificado_por"] is None


@pytest.mark.parametrize("a,b,igual", [
    ("PLU3/429083", "PLU3-429083", True), ("GMLI_1131_0", "GMLI-1131", True), ("VIPP-145029-0", "VIPP-145029", True),
    ("429083", "PLU3-429083", True), ("PLU3-421131", "GMLI-1131", False), ("1131", "PLU3-421131", False),
])
def test_misma_poliza(a, b, igual):
    assert misma_poliza(a, b) is igual


def test_normalizaciones():
    assert norm_poliza("plu3/429083") == "PLU3429083" and numero_poliza("GMLI_1131_0") == "1131"
    assert mismo_nombre("José  Daniel Rosas Rayas", "JOSE DANIEL ROSAS RAYAS")
    assert mismo_nombre("ROSAS RAYAS JOSE DANIEL", "José Daniel Rosas Rayas")
    assert not mismo_nombre("JOSE ROSAS", "José Daniel Rosas Rayas")
    assert nombres_compatibles("JOSE ROSAS RAYAS", "José Daniel Rosas Rayas")
    assert not nombres_compatibles("MARTHA ZARATE URIBE", "Cliente Equivocado Perez")
