"""Paso 4 — motor por etapa del proceso largo: secuencias completas, nada se repite, nada a ciegas."""
from datetime import datetime, timezone

import pytest

from app import config
from app.acciones.motor_etapas import decidir_por_etapa, transicion, usa_motor_etapas
from app.clasificador.etapas import Etapa, detectar_etapa
from app.db.repo import RepositorioSQLite

LUNES = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)  # lunes 09:00 en CDMX
SISTEMA = "Allianz.Mexico@allianz.com.mx"
TK = "[Allianz México Ticket-2576612]"
TITULO = "1950110 HORTENCIA PRUEBA GAMA NUEVO NEGOCIO"
PIE = "\n Gracias,\n Allianz Mexico SA Compania de Seguros\n--- Este mensaje fue enviado desde el Service Management"


def mail(actor, msg, titulo=TITULO, verbo="escribió un mensaje en"):
    return f"--- Por favor responda sobre esta línea ---\n Hola HOLA@BABILONIA.AI ,\n Nuevo mensaje\n {actor} {verbo} {titulo}:\n\n{msg}\n{PIE}"


C1 = (f"{TK} Sistema creó una nueva solicitud en su nombre",
      "Sistema creó HORTENCIA PRUEBA GAMA en tu nombre\n NÚMERO DE SOLICITUD: 1950110\n "
      "NOMBRE DEL CONTRATANTE: HORTENCIA PRUEBA GAMA\n TIPO DE SOLICITUD: GMMI")
C2 = (f"{TK} Sistema escribió un mensaje", mail("SISTEMA", "Le confirmamos que recibimos su solicitud."))
C3 = (f"{TK} RAUL MARIN escribió un mensaje",
      mail("RAUL MARIN", "Buen día\nFavor de enviar la carta laboral firmada. Tiene 15 días hábiles.\nSaludos"))
C4 = (f"{TK} hola@babilonia.ai escribió un mensaje", mail("hola@babilonia.ai", "Anexo lo solicitado. Saludos"))
C5 = (f"{TK} RAUL MARIN escribió un mensaje", mail("RAUL MARIN", "Le informamos que su solicitud fue atendida.\nFolio cerrado."))
RECHAZO = (f"{TK} NANCY GALEANA escribió un mensaje",
           mail("NANCY GALEANA", "Se excedió el período de vigencia, se procede a rechazar el presente ticket."))


def et(asunto_cuerpo, remitente=SISTEMA):
    return detectar_etapa(*asunto_cuerpo, remitente).como_dict()


def fila(nombre="Hortencia Prueba Gama", sol=1950110, tel_asesor="5598765432", tel_cliente="5512345678"):
    return {"cliente_nombre": nombre, "nro_solicitud": sol, "poliza": None, "telefono_cliente": tel_cliente,
            "asesor_correo": "asesor1@babilonia.ai", "asesor_nombre": "Asesor Uno", "telefono_asesor": tel_asesor}


def notion(*filas):
    def buscar(campo, op, valor, n):
        if campo == "nro_solicitud":
            return [f for f in filas if str(f["nro_solicitud"]) == str(valor)], False
        return [f for f in filas if f.get(campo) and str(valor).lower() in f[campo].lower()], False
    return buscar


@pytest.fixture(autouse=True)
def aislado(monkeypatch):
    """Nada externo: sin Notion, sin LLM, DRY_RUN, motor por etapa prendido."""
    monkeypatch.setattr(config, "MOTOR_ETAPAS", True)
    monkeypatch.setattr(config, "NOTION_TOKEN", "")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(config, "DRY_RUN", True)
    monkeypatch.setattr(config, "PANEL_URL", "")


@pytest.fixture
def repo(tmp_path):
    return RepositorioSQLite(str(tmp_path / "t.sqlite"))


@pytest.fixture
def tk(repo):
    return repo.crear_ticket({"nro_ticket": "2576612", "estado": "abierto"})


def correr(repo, tk, ac, cid, buscar=None, ahora=LUNES):
    return decidir_por_etapa(repo, tk, et(ac), correo_id=cid, ahora=ahora, buscar=buscar or notion(fila()))


def roles(res):
    return sorted(a["rol"] for a in res["plan"])


def vivos(repo, tk):
    return {r["motivo"]: r for r in repo.listar_recordatorios(tk, estados=["activo", "escalado"])}


def test_secuencia_completa_c1_a_c5(repo, tk):
    r1 = correr(repo, tk, C1, 1)
    assert r1["aplicada"] and roles(r1) == ["asesor", "ceci", "cliente"]
    cli = next(a for a in r1["plan"] if a["rol"] == "cliente")
    assert cli["numero"] == "5512345678" and "proceso de autorización" in cli["mensaje"]
    assert cli["mensaje"].startswith("Hola Hortencia,")  # nombre de Notion, con mayúscula inicial
    t = repo.obtener_ticket(tk)
    assert (t["etapa"], t["proceso"], t["producto"], t["nro_solicitud"], t["identificado_por"]) == \
        ("apertura", "largo", "GMMI", "1950110", "solicitud")

    r2 = correr(repo, tk, C2, 2)
    assert r2["aplicada"] and r2["plan"] == [] and repo.obtener_ticket(tk)["estado"] == "esperando_allianz"

    r3 = correr(repo, tk, C3, 3)
    assert roles(r3) == ["asesor", "ceci", "cliente"]
    ases = next(a for a in r3["plan"] if a["rol"] == "asesor")
    assert "carta laboral" in ases["mensaje"] and "15 días hábiles" in ases["mensaje"]
    rec = vivos(repo, tk)["requerimiento"]
    assert rec["destinatarios"] == ["cliente", "asesor"] and rec["vence_en"].startswith("2026-10-22")  # 72 h hábiles < 15 días
    assert repo.obtener_ticket(tk)["estado"] == "esperando_cliente"

    r4 = correr(repo, tk, C4, 4)
    assert roles(r4) == ["asesor", "ceci", "cliente"]
    assert set(vivos(repo, tk)) == {"esperando_allianz"}
    assert repo.listar_recordatorios(tk, estados=["cumplido"])[0]["motivo"] == "requerimiento"

    r5 = correr(repo, tk, C5, 5)
    assert roles(r5) == ["asesor", "ceci", "cliente"] and "cobrada" in next(
        a for a in r5["plan"] if a["rol"] == "cliente")["mensaje"]
    t = repo.obtener_ticket(tk)
    assert t["estado"] == "resuelto" and t["etapa"] == "atendida" and vivos(repo, tk) == {}
    # 4 etapas con aviso × 3 destinatarios: ni uno de más.
    assert len(repo.listar_avisos(tk)) == 12 and len(repo.listar_acciones(tk)) == 12


def test_correo_repetido_no_repite_avisos(repo, tk):
    correr(repo, tk, C1, 1)
    r = correr(repo, tk, C1, 99)  # otro correo con la misma etapa (ej. reenvío)
    assert not r["aplicada"] and r["plan"] == []
    assert len(repo.listar_avisos(tk)) == 3


def test_correo_viejo_no_hace_retroceder(repo, tk):
    for i, c in enumerate((C1, C3, C4), 1):
        correr(repo, tk, c, i)
    r = correr(repo, tk, C2, 9)
    assert not r["aplicada"] and "anterior" in r["motivo"]
    t = repo.obtener_ticket(tk)
    assert t["etapa"] == "documentos_enviados" and t["estado"] == "esperando_allianz"
    assert "etapa_ignorada" in [e["tipo_evento"] for e in repo.listar_eventos(tk)]


def test_estado_lo_manda_la_etapa_aunque_otro_lo_pise(repo, tk):
    correr(repo, tk, C1, 1)
    correr(repo, tk, C5, 2)
    repo.actualizar_ticket(tk, estado="esperando_cliente")  # lo que haría el motor viejo al upsertear
    correr(repo, tk, C3, 3)  # requerimiento tardío: ignorado…
    assert repo.obtener_ticket(tk)["estado"] == "resuelto"  # …y el estado vuelve a 'resuelto'


def test_nuevo_requerimiento_despues_de_c4_es_otra_ronda(repo, tk):
    for i, c in enumerate((C1, C3, C4), 1):
        correr(repo, tk, c, i)
    otro = (C3[0], mail("RAUL MARIN", "Favor de enviar el cuestionario médico."))
    r = correr(repo, tk, otro, 4)
    assert r["aplicada"] and r["ronda"] == 2 and roles(r) == ["asesor", "ceci", "cliente"]
    assert "cuestionario médico" in r["plan"][0]["mensaje"]
    assert set(vivos(repo, tk)) == {"requerimiento"}  # 'esperando a Allianz' cortado


def test_dos_requerimientos_seguidos_reemplazan_el_recordatorio(repo, tk):
    correr(repo, tk, C1, 1)
    correr(repo, tk, C3, 2)
    otro = (C3[0], mail("RAUL MARIN", "Le solicitamos también la identificación oficial."))
    r = correr(repo, tk, otro, 3)
    assert r["ronda"] == 2 and len(r["plan"]) == 3
    assert len(vivos(repo, tk)) == 1 and repo.listar_recordatorios(tk, estados=["cancelado"])


def test_el_recordatorio_va_a_los_3_dias_habiles_aunque_el_plazo_sea_otro(repo, tk):
    # Ceci (29/10): se recuerda a los 3 días hábiles, no al vencer el plazo del correo. Al cliente se le
    # dice el plazo que da Allianz.
    correr(repo, tk, C1, 1)
    corto = (C3[0], mail("RAUL MARIN", "Favor de enviar el RFC. Cuenta con 1 día para responder."))
    r = correr(repo, tk, corto, 2)
    assert vivos(repo, tk)["requerimiento"]["vence_en"].startswith("2026-10-22T15:00")
    assert "Tienes hasta el 20/10/2026" in next(a for a in r["plan"] if a["rol"] == "cliente")["mensaje"]


def test_rechazo_avisa_ceci_y_asesor_nunca_al_cliente(repo, tk):
    correr(repo, tk, C1, 1)
    correr(repo, tk, C3, 2)
    r = correr(repo, tk, RECHAZO, 3)
    assert roles(r) == ["asesor", "ceci"]
    plan = {a["rol"]: a["mensaje"] for a in r["plan"]}
    assert "Antes de contactar al cliente, comunícate con Ceci para revisarlo" in plan["asesor"]
    assert "que lo revise contigo antes de contactar al cliente" in plan["ceci"]
    assert repo.obtener_ticket(tk)["estado"] == "resuelto" and vivos(repo, tk) == {}
    assert repo.listar_recordatorios(tk, estados=["cancelado"])
    assert not correr(repo, tk, C4, 4)["aplicada"]  # terminado: no acepta nada más


def test_sin_identificar_va_solo_a_ceci(repo, tk):
    r = correr(repo, tk, C1, 1, buscar=notion())  # Notion no lo tiene
    assert roles(r) == ["ceci"]
    ceci = r["plan"][0]["mensaje"]
    assert "No pude identificar" in ceci and "asesor" in ceci and "cliente" in ceci
    assert repo.obtener_ticket(tk)["identificado_por"] is None


def test_homonimos_con_otro_asesor_van_a_ceci(repo, tk):
    b = notion(fila(sol=1), {**fila(sol=2), "asesor_correo": "otro@b.ai"})
    c1 = (C1[0], C1[1].replace("NÚMERO DE SOLICITUD: 1950110", "NÚMERO DE SOLICITUD: 777"))
    r = correr(repo, tk, c1, 1, buscar=b)
    assert roles(r) == ["ceci"] and "asesores distintos" in r["plan"][0]["mensaje"]


def test_falta_telefono_del_asesor(repo, tk):
    r = correr(repo, tk, C1, 1, buscar=notion(fila(tel_asesor=None)))
    assert roles(r) == ["ceci", "cliente"]
    assert "Falta el teléfono del asesor" in next(a for a in r["plan"] if a["rol"] == "ceci")["mensaje"]


def test_ticket_delicado_solo_ceci(repo, tk):
    repo.actualizar_ticket(tk, delicado=1)
    r = correr(repo, tk, C1, 1)
    assert roles(r) == ["ceci"] and "delicado" in r["plan"][0]["mensaje"]


def test_copia_de_penny_no_avisa_y_brindar_respuesta_alerta_a_ceci(repo, tk):
    correr(repo, tk, C1, 1)
    penny = "penny.ortiz@allianz.com.mx"
    copia = (f"RV: {TK} RAUL MARIN escribió un mensaje", "Comparto para su conocimiento\nDe: Allianz.Mexico\n...")
    r = decidir_por_etapa(repo, tk, detectar_etapa(*copia, penny).como_dict(), correo_id=2, ahora=LUNES)
    assert r["plan"] == [] and repo.obtener_ticket(tk)["etapa"] == "apertura"
    pide = (f"RV: {TK} RAUL MARIN escribió un mensaje", "Hola, favor de brindar respuesta en el ticket\nDe: Allianz.Mexico\n...")
    r = decidir_por_etapa(repo, tk, detectar_etapa(*pide, penny).como_dict(), correo_id=3, ahora=LUNES)
    assert roles(r) == ["ceci"] and "respondamos directo" in r["plan"][0]["mensaje"]


def test_rebote_alerta_a_ceci_aun_con_el_ticket_cerrado(repo, tk):
    correr(repo, tk, C1, 1)
    correr(repo, tk, C5, 2)
    reb = ("Solicitud finalizada Ticket 2576612", "Usted respondió a un ticket que ya se encuentra cerrado.")
    r = decidir_por_etapa(repo, tk, detectar_etapa(*reb, SISTEMA).como_dict(), correo_id=3, ahora=LUNES)
    assert roles(r) == ["ceci"] and "abrir uno nuevo" in r["plan"][0]["mensaje"]


def test_poliza_emitida_avisa_a_los_3_y_termina(repo, tk):
    for i, c in enumerate((C1, C5), 1):
        correr(repo, tk, c, i)
    aviso = ("Aviso de emisión de póliza GMMI-101770 Hortencia Prueba Gama", "<html><body>Aviso</body></html>")
    r = decidir_por_etapa(repo, tk, detectar_etapa(*aviso, "notificaciones.optimaxx@allianz.com.mx").como_dict(),
                          correo_id=3, ahora=LUNES, buscar=notion(fila()))
    assert r["aplicada"] and roles(r) == ["asesor", "ceci", "cliente"]
    assert "GMMI-101770" in r["plan"][0]["mensaje"]
    assert repo.obtener_ticket(tk)["poliza"] == "GMMI-101770"


def test_transicion():
    assert transicion(None, Etapa.REQUERIMIENTO, 1) == (True, 1, "primera etapa conocida del ticket")
    assert transicion("apertura", Etapa.AUTORIZADO, 1)[0]
    assert not transicion("atendida", Etapa.REQUERIMIENTO, 1)[0]
    assert transicion("autorizado", Etapa.REQUERIMIENTO, 1)[:2] == (True, 2)
    assert not transicion("declinado", Etapa.POLIZA_EMITIDA, 1)[0]


def test_solo_proceso_largo_y_con_el_interruptor(monkeypatch):
    assert usa_motor_etapas({"etapa": "apertura", "proceso": "largo"})
    assert usa_motor_etapas({"etapa": "copia_ejecutiva", "proceso": None}, {"proceso": "largo"})
    assert not usa_motor_etapas({"etapa": "apertura", "proceso": "corto"})
    assert not usa_motor_etapas({"etapa": "copia_ejecutiva"}, {"proceso": "tramite"})
    assert not usa_motor_etapas({"etapa": "no_aplica", "proceso": "largo"})
    monkeypatch.setattr(config, "MOTOR_ETAPAS", False)
    assert not usa_motor_etapas({"etapa": "apertura", "proceso": "largo"})


# ---------------- correcciones del replay con correos reales (paso 8) ----------------
def test_sin_identificar_igual_guarda_el_nombre_que_escribe_allianz(repo, tk):
    correr(repo, tk, C1, 1, buscar=notion())
    assert repo.obtener_ticket(tk)["cliente_nombre"] == "HORTENCIA PRUEBA GAMA"
    assert repo.obtener_ticket(tk)["identificado_por"] is None


def test_allianz_repite_el_mismo_pedido_no_avisa_de_nuevo(repo, tk):
    correr(repo, tk, C1, 1)
    correr(repo, tk, C3, 2)
    otra_persona = (C3[0].replace("RAUL MARIN", "GLORIA MORALES"), C3[1].replace("RAUL MARIN", "GLORIA MORALES"))
    r = correr(repo, tk, otra_persona, 3)
    assert not r["aplicada"] and "mismo pedido" in r["motivo"] and r["plan"] == []
    assert len(repo.listar_avisos(tk)) == 6


def test_nota_de_la_ejecutiva_lleva_lo_que_escribio(repo, tk):
    correr(repo, tk, C1, 1)
    nota = (f"RV: {TK} RAUL MARIN escribió un mensaje",
            "Hola, ya subí la hoja membretada al ticket.\nDe: Allianz.Mexico\n...")
    r = decidir_por_etapa(repo, tk, detectar_etapa(*nota, "blanca.xuluc@allianz.com.mx").como_dict(),
                          correo_id=2, ahora=LUNES, buscar=notion(fila()))
    ases = next(a for a in r["plan"] if a["rol"] == "asesor")
    assert ases["mensaje"].endswith("la ejecutiva de Allianz escribió: Hola, ya subí la hoja membretada al ticket")


def test_apertura_sin_producto_ni_solicitud_no_dice_tu_seguro(repo, tk):
    c1 = (C1[0], C1[1].replace(" TIPO DE SOLICITUD: GMMI", "").replace("NÚMERO DE SOLICITUD: 1950110\n", ""))
    r = correr(repo, tk, c1, 1, buscar=notion(fila(sol=None)))
    textos = {a["rol"]: a["mensaje"] for a in r["plan"]}
    assert textos["asesor"] == ("Ticket 2576612 · Hortencia Prueba Gama: Allianz abrió la solicitud, está en proceso "
                                "de autorización.")
    assert textos["cliente"].startswith("Hola Hortencia, tu solicitud ya está en Allianz")
