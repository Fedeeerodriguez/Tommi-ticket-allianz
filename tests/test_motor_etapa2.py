"""Etapa 2 — motor por etapa del proceso corto (guía de aportación + pago) y de los trámites."""
from datetime import datetime, timedelta, timezone

import pytest

from app import config
from app.acciones import aprobaciones
from app.acciones.motor_etapas import decidir_por_etapa, ticket_para_emision, usa_motor_etapas
from app.acciones.recordatorios import escanear_recordatorios
from app.clasificador.etapas import detectar_etapa
from app.db.repo import RepositorioSQLite

LUNES = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)  # lunes 09:00 en CDMX
SISTEMA = "Allianz.Mexico@allianz.com.mx"
CALLCENTER = "Call Center Ahorro <callcenter.ahorro@allianz.com.mx>"
PIE = "\n Gracias,\n Allianz Mexico SA Compania de Seguros\n--- Este mensaje fue enviado desde el Service Management"

# ---------------------------------------------------------------- proceso corto (capturas de Ceci)
TK_C = "[Allianz México Ticket-2567479]"
TIT_C = "[EXT] Emisión póliza No. Póliza: SVIP-21799 No. Solicitud: 25287681"
# ---------------------------------------------------------------- trámite
TK_T = "[Allianz México Ticket-2587626]"
TIT_T = "[EXT] Aplicación de pago póliza OPPT-48211"


def mail(actor, msg, titulo):
    return (f"--- Por favor responda sobre esta línea ---\n Hola HOLA@BABILONIA.AI ,\n Nuevo mensaje\n"
            f" {actor} escribió un mensaje en {titulo}:\n\n{msg}\n{PIE}")


C2_CORTO = (f"{TK_C} Sistema escribió un mensaje", mail("SISTEMA", """Estimado cliente,
Le confirmamos que recibimos su solicitud para trámite que se describe a continuación:
 * OFICINA SOLICITANTE: Centro
 * NOMBRE DEL CONTRATANTE: GUILLERMO PRUEBA CASTRO
 * NÚMERO DE SOLICITUD: 25287681
 * TIPO DE SOLICITUD: SVIP, Nuevo negocio""", TIT_C))
PAGO_ELITE = (f"{TK_C} hola@babilonia.ai escribió un mensaje",
              mail("hola@babilonia.ai", "Buen día, anexo comprobante de pago y estado de cuenta.", TIT_C))
EMITIDA_CORTO = ("Aviso de emisión de póliza SVIP/21799 a nombre de Guillermo Prueba Castro.",
                 "Estimado(a) JOSE RAMON MIER, copia de la carátula de la póliza SVIP-21799-0")

T1 = (f"{TK_T} Sistema escribió un mensaje", mail(
    "SISTEMA", "Esta es una respuesta automática para confirmar que hemos recibido su solicitud.", TIT_T))
T2 = (f"{TK_T} OSBALDO PINEDA escribió un mensaje", mail(
    "OSBALDO PINEDA", "Buen día.\nRevisamos su pago y observamos que no incluye la fecha de pago.\n"
    "Por favor, envíenos el estado de cuenta.\nQuedamos atentos a su respuesta.", TIT_T))
T3 = (f"{TK_T} integraciones@babilonia.ai escribió un mensaje",
      mail("integraciones@babilonia.ai", "Buen día, anexo el estado de cuenta con la fecha de pago.", TIT_T))
T4 = (f"{TK_T} OSBALDO PINEDA escribió un mensaje",
      mail("OSBALDO PINEDA", "Le informamos que su solicitud fue atendida.", TIT_T))


def et(asunto_cuerpo, remitente=SISTEMA):
    return detectar_etapa(*asunto_cuerpo, remitente).como_dict()


def fila(nombre="Guillermo Prueba Castro", sol=25287681, poliza="SVIP-21799",
         tel_asesor="5598765432", tel_cliente="5512345678"):
    return {"cliente_nombre": nombre, "nro_solicitud": sol, "poliza": poliza, "telefono_cliente": tel_cliente,
            "asesor_correo": "asesor1@babilonia.ai", "asesor_nombre": "Asesor Uno", "telefono_asesor": tel_asesor}


def notion(*filas):
    def buscar(campo, op, valor, n):
        if campo == "nro_solicitud":
            return [f for f in filas if str(f["nro_solicitud"]) == str(valor)], False
        return [f for f in filas if f.get(campo) and str(valor).lower() in str(f[campo]).lower()], False
    return buscar


ANA = fila(nombre="Ana Prueba Ruiz", sol=25290001, poliza="OPPT-48211", tel_cliente="5511112222")


@pytest.fixture(autouse=True)
def aislado(monkeypatch):
    monkeypatch.setattr(config, "MOTOR_ETAPAS", True)
    monkeypatch.setattr(config, "MOTOR_ETAPAS_PROCESOS", ["largo", "corto", "tramite"])
    monkeypatch.setattr(config, "MOTOR_ETAPAS_ROLES", ["ceci", "asesor", "cliente"])
    monkeypatch.setattr(config, "TELEGRAM_APROBACIONES", False)
    monkeypatch.setattr(config, "NOTION_TOKEN", "")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(config, "DRY_RUN", True)
    monkeypatch.setattr(config, "PANEL_URL", "")


@pytest.fixture
def repo(tmp_path):
    return RepositorioSQLite(str(tmp_path / "t.sqlite"))


def correr(repo, tk, ac, cid, buscar=None, ahora=LUNES, remitente=SISTEMA):
    return decidir_por_etapa(repo, tk, et(ac, remitente), correo_id=cid, ahora=ahora,
                             buscar=buscar or notion(fila(), ANA))


def roles(res):
    return sorted(a["rol"] for a in res["plan"])


def vivos(repo, tk):
    return {r["motivo"]: r for r in repo.listar_recordatorios(tk, estados=["activo", "escalado"])}


CAMPOS = {"monto": "$50,000 MXN", "datos_deposito": "CLABE 012345678901234567 a nombre de Allianz"}


def guia_lista(repo, tk):
    """C2 corto → guía pendiente → Ceci completa monto y datos para depositar."""
    correr(repo, tk, C2_CORTO, 1)
    ap = repo.listar_aprobaciones(tk)[0]
    aprobaciones.corregir(repo, ap["id"], "panel:ceci", **CAMPOS)
    return ap["id"], repo.obtener_aprobacion(ap["id"])["texto"]


# ================================================================ interruptor por proceso
def test_interruptor_por_proceso(monkeypatch):
    corto, tramite = et(C2_CORTO), et(T1, CALLCENTER)
    assert usa_motor_etapas(corto) and usa_motor_etapas(tramite)
    monkeypatch.setattr(config, "MOTOR_ETAPAS_PROCESOS", ["largo"])  # la Etapa 1 sola
    assert not usa_motor_etapas(corto) and not usa_motor_etapas(tramite)
    assert usa_motor_etapas({"etapa": "copia_ejecutiva"})  # sin proceso → como el largo


# ================================================================ proceso corto
def test_c2_corto_deja_la_guia_pendiente_y_no_le_escribe_al_cliente(repo):
    tk = repo.crear_ticket({"nro_ticket": "2567479", "estado": "abierto"})
    r = correr(repo, tk, C2_CORTO, 1)
    assert r["aplicada"] and roles(r) == ["ceci"]  # ni cliente ni asesor hasta que Ceci apruebe
    assert "guía de aportación está lista" in r["plan"][0]["mensaje"]
    t = repo.obtener_ticket(tk)
    assert (t["proceso"], t["producto"], t["etapa"], t["estado"], t["poliza"]) == \
           ("corto", "SVIP", "confirmacion_datos", "esperando_cliente", "SVIP-21799")
    assert t["identificado_por"] == "solicitud"
    ap = repo.listar_aprobaciones(tk)
    assert len(ap) == 1 and ap[0]["estado"] == "pendiente" and ap[0]["tipo"] == "guia_aportacion"
    assert ap[0]["texto"].startswith("Hola Guillermo 👋 Allianz ya confirmó tu solicitud de Elite (póliza SVIP-21799).")
    assert "• Monto: [completar]" in ap[0]["texto"]  # Ceci completa monto y datos de depósito
    assert ap[0]["datos"] == {"nombre": "Guillermo", "producto": "Elite", "poliza": "SVIP-21799",
                              "monto": "", "datos_deposito": ""}
    assert vivos(repo, tk) == {}  # el recordatorio de pago arranca recién con la aprobación


def test_c2_repetido_no_pide_otra_aprobacion(repo):
    tk = repo.crear_ticket({"nro_ticket": "2567479", "estado": "abierto"})
    correr(repo, tk, C2_CORTO, 1)
    r = correr(repo, tk, C2_CORTO, 2)
    assert not r["aplicada"] and r["plan"] == []
    assert len(repo.listar_aprobaciones(tk)) == 1


def test_con_telegram_ceci_no_recibe_ademas_el_whatsapp(repo, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_APROBACIONES", True)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setattr(config, "TELEGRAM_CECI_CHAT_ID", "1")
    tk = repo.crear_ticket({"nro_ticket": "2567479", "estado": "abierto"})
    r = correr(repo, tk, C2_CORTO, 1)
    assert r["plan"] == [] and len(repo.listar_aprobaciones(tk, estados=["pendiente"])) == 1


def test_la_guia_es_la_plantilla_de_wati(repo):
    tk = repo.crear_ticket({"nro_ticket": "2567479", "estado": "abierto"})
    aid, texto = guia_lista(repo, tk)
    assert texto == ("Hola Guillermo 👋 Allianz ya confirmó tu solicitud de Elite (póliza SVIP-21799). Para "
                     "activarla falta tu aportación inicial:\n\n• Monto: $50,000 MXN\n• Datos para depositar: CLABE "
                     "012345678901234567 a nombre de Allianz\n• Referencia: póliza SVIP-21799\n\nCuando deposites, "
                     "mándame por aquí el comprobante y tu estado de cuenta, y yo lo envío a Allianz.")
    ap = repo.obtener_aprobacion(aid)
    assert ap["version"] == 2 and ap["datos"]["monto"] == "$50,000 MXN"
    # Corregir solo uno de los dos campos deja el otro como estaba.
    aprobaciones.corregir(repo, aid, "panel:ceci", monto="$60,000 MXN")
    ap = repo.obtener_aprobacion(aid)
    assert (ap["version"], ap["datos"]["monto"], ap["datos"]["datos_deposito"]) == \
        (3, "$60,000 MXN", CAMPOS["datos_deposito"])
    # Lo mismo otra vez no crea versión nueva; vacío no vale.
    assert aprobaciones.corregir(repo, aid, "panel:ceci", monto="$60,000 MXN")["motivo"] == "Sin cambios."
    assert not aprobaciones.corregir(repo, aid, "panel:ceci", monto="  ")["ok"]


def test_no_se_aprueba_con_datos_sin_completar(repo):
    tk = repo.crear_ticket({"nro_ticket": "2567479", "estado": "abierto"})
    correr(repo, tk, C2_CORTO, 1)
    ap = repo.listar_aprobaciones(tk)[0]
    r = aprobaciones.aprobar(repo, ap["id"], "panel:ceci", ahora=LUNES)
    assert not r["ok"] and r["motivo"] == "Falta completar: monto y datos para depositar."
    r = aprobaciones.aprobar(repo, ap["id"], "panel:ceci", monto="$10", ahora=LUNES)
    assert not r["ok"] and r["motivo"] == "Falta completar: datos para depositar."
    assert repo.obtener_aprobacion(ap["id"])["estado"] == "pendiente"


def test_aprobar_manda_la_guia_y_arranca_el_recordatorio_de_pago(repo):
    tk = repo.crear_ticket({"nro_ticket": "2567479", "estado": "abierto"})
    aid, texto = guia_lista(repo, tk)
    r = aprobaciones.aprobar(repo, aid, "telegram:ceci", ahora=LUNES)
    assert r["ok"] and roles(r) == ["asesor", "cliente"]
    cli = next(a for a in r["plan"] if a["rol"] == "cliente")
    assert cli["mensaje"] == texto and cli["numero"] == "5512345678"  # exactamente lo aprobado
    assert cli["params"]["guia"]["monto"] == "$50,000 MXN"  # → plantilla tommy_guia_aportacion
    ase = next(a for a in r["plan"] if a["rol"] == "asesor")
    assert ase["mensaje"] == ("Ticket 2567479 · Guillermo Prueba Castro: le mandamos al cliente la guía de "
                              "aportación (aprobada por Ceci). Monto: $50,000 MXN · Datos para depositar: CLABE "
                              "012345678901234567 a nombre de Allianz.")
    ap = repo.obtener_aprobacion(aid)
    assert (ap["estado"], ap["resuelto_por"], ap["version"]) == ("aprobada", "telegram:ceci", 2)
    pago = vivos(repo, tk)["pago"]
    assert pago["destinatarios"] == ["cliente", "asesor"]
    assert pago["vence_en"].startswith("2026-10-22")  # 72 h hábiles = 3 días hábiles
    # Segunda vez (el panel después de Telegram): no sale nada de nuevo.
    r2 = aprobaciones.aprobar(repo, aid, "panel:ceci", ahora=LUNES)
    assert not r2["ok"] and r2["plan"] == []


def test_aprobar_completando_en_el_momento(repo):
    tk = repo.crear_ticket({"nro_ticket": "2567479", "estado": "abierto"})
    correr(repo, tk, C2_CORTO, 1)
    ap = repo.listar_aprobaciones(tk)[0]
    r = aprobaciones.aprobar(repo, ap["id"], "panel:ceci", monto="$10", datos_deposito="CLABE 1", ahora=LUNES)
    assert r["ok"] and "• Monto: $10\n• Datos para depositar: CLABE 1" in \
        next(a for a in r["plan"] if a["rol"] == "cliente")["mensaje"]
    assert repo.obtener_aprobacion(ap["id"])["version"] == 2


def test_sin_identificar_no_se_aprueba(repo):
    tk = repo.crear_ticket({"nro_ticket": "2567479", "estado": "abierto"})
    r = correr(repo, tk, C2_CORTO, 1, buscar=notion())  # Notion no lo encuentra
    assert roles(r) == ["ceci"] and "asígnalo en el panel antes de aprobar" in r["plan"][0]["mensaje"]
    ap = repo.listar_aprobaciones(tk)[0]
    aprobaciones.corregir(repo, ap["id"], "panel:ceci", **CAMPOS)
    res = aprobaciones.aprobar(repo, ap["id"], "panel:ceci", ahora=LUNES)
    assert not res["ok"] and "identificado" in res["motivo"]


def test_descartar_no_manda_nada(repo):
    tk = repo.crear_ticket({"nro_ticket": "2567479", "estado": "abierto"})
    aid, _ = guia_lista(repo, tk)
    assert aprobaciones.descartar(repo, aid, "panel:ceci")["ok"]
    assert repo.obtener_aprobacion(aid)["estado"] == "descartada"
    assert not aprobaciones.aprobar(repo, aid, "panel:ceci", ahora=LUNES)["ok"]
    assert vivos(repo, tk) == {}


def test_pago_elite_en_el_hilo_corta_el_recordatorio_de_pago(repo):
    tk = repo.crear_ticket({"nro_ticket": "2567479", "estado": "abierto"})
    aid, _ = guia_lista(repo, tk)
    aprobaciones.aprobar(repo, aid, "panel:ceci", ahora=LUNES)
    r = correr(repo, tk, PAGO_ELITE, 3, ahora=LUNES + timedelta(hours=5))
    assert r["aplicada"] and roles(r) == ["asesor", "ceci", "cliente"]
    assert "comprobante de pago" in next(a for a in r["plan"] if a["rol"] == "cliente")["mensaje"]
    assert set(vivos(repo, tk)) == {"esperando_allianz"}
    assert repo.listar_recordatorios(tk, estados=["cumplido"])[0]["motivo"] == "pago"


def test_aviso_de_emision_cierra_el_ticket_corto(repo):
    tk = repo.crear_ticket({"nro_ticket": "2567479", "estado": "abierto"})
    aid, _ = guia_lista(repo, tk)
    aprobaciones.aprobar(repo, aid, "panel:ceci", ahora=LUNES)
    emitida = et(EMITIDA_CORTO, "notificaciones.optimaxx@allianz.com.mx")
    assert ticket_para_emision(repo, emitida) == tk  # se engancha por la póliza
    r = decidir_por_etapa(repo, tk, emitida, correo_id=4, ahora=LUNES + timedelta(days=1),
                          buscar=notion(fila()))
    assert roles(r) == ["asesor", "ceci", "cliente"]
    assert repo.obtener_ticket(tk)["estado"] == "resuelto" and vivos(repo, tk) == {}


def test_emision_corto_no_engancha_si_el_corto_esta_apagado(repo, monkeypatch):
    tk = repo.crear_ticket({"nro_ticket": "2567479", "estado": "abierto"})
    correr(repo, tk, C2_CORTO, 1)
    monkeypatch.setattr(config, "MOTOR_ETAPAS_PROCESOS", ["largo"])
    assert ticket_para_emision(repo, et(EMITIDA_CORTO, "notificaciones.optimaxx@allianz.com.mx")) is None


def test_recordatorio_y_escalado_del_pago(repo):
    tk = repo.crear_ticket({"nro_ticket": "2567479", "estado": "abierto"})
    aid, _ = guia_lista(repo, tk)
    aprobaciones.aprobar(repo, aid, "panel:ceci", ahora=LUNES)
    jueves = datetime(2026, 10, 22, 16, 0, tzinfo=timezone.utc)
    r = escanear_recordatorios(repo, jueves)
    assert roles(r) == ["asesor", "cliente"]
    cli = next(a for a in r["plan"] if a["rol"] == "cliente")
    assert "falta tu aportación" in cli["mensaje"]
    ase = next(a for a in r["plan"] if a["rol"] == "asesor")
    assert "comprobante de pago" in ase["mensaje"] and "Ya le recordamos al cliente" in ase["mensaje"]
    assert escanear_recordatorios(repo, jueves + timedelta(minutes=30))["plan"] == []  # una sola vez
    r = escanear_recordatorios(repo, datetime(2026, 10, 23, 17, 0, tzinfo=timezone.utc))
    assert roles(r) == ["asesor", "ceci"] and all("sigue sin llegar" in a["mensaje"] for a in r["plan"])


# ================================================================ trámites
def tramite(repo):
    return repo.crear_ticket({"nro_ticket": "2587626", "estado": "abierto"})


def test_tramite_completo_siempre_con_ticket_cliente_y_asunto(repo):
    tk = tramite(repo)
    r1 = correr(repo, tk, T1, 1, remitente=CALLCENTER)
    assert roles(r1) == ["asesor", "ceci", "cliente"]
    ase = next(a for a in r1["plan"] if a["rol"] == "asesor")["mensaje"]
    assert ase == "Ticket 2587626 · Ana Prueba Ruiz · Aplicación de pago póliza OPPT-48211: Allianz recibió el trámite."
    cli = next(a for a in r1["plan"] if a["rol"] == "cliente")
    assert cli["numero"] == "5511112222" and "«Aplicación de pago póliza OPPT-48211»" in cli["mensaje"]
    t = repo.obtener_ticket(tk)
    assert (t["proceso"], t["titulo_hilo"], t["identificado_por"]) == \
           ("tramite", "Aplicación de pago póliza OPPT-48211", "poliza")

    r2 = correr(repo, tk, T2, 2, remitente=CALLCENTER, ahora=LUNES + timedelta(hours=2))
    assert roles(r2) == ["asesor", "ceci", "cliente"]
    ase = next(a for a in r2["plan"] if a["rol"] == "asesor")["mensaje"]
    assert "· Aplicación de pago póliza OPPT-48211: Allianz pide →" in ase and "estado de cuenta" in ase
    assert set(vivos(repo, tk)) == {"requerimiento"}
    assert repo.obtener_ticket(tk)["estado"] == "esperando_cliente"

    r3 = correr(repo, tk, T3, 3, remitente=CALLCENTER, ahora=LUNES + timedelta(hours=4))
    assert "le respondimos a Allianz" in next(a for a in r3["plan"] if a["rol"] == "asesor")["mensaje"]
    assert set(vivos(repo, tk)) == {"esperando_allianz"}

    r4 = correr(repo, tk, T4, 4, remitente=CALLCENTER, ahora=LUNES + timedelta(days=1))
    assert "¡listo! Allianz atendió tu trámite «Aplicación de pago póliza OPPT-48211»" in \
        next(a for a in r4["plan"] if a["rol"] == "cliente")["mensaje"]
    assert repo.obtener_ticket(tk)["estado"] == "resuelto" and vivos(repo, tk) == {}
    # Cada aviso salió una sola vez: 4 etapas × 3 destinatarios.
    assert len(repo.listar_avisos(tk)) == 12


def test_tramite_sin_poliza_va_a_ceci_con_el_asunto(repo):
    tk = tramite(repo)
    sin = (f"{TK_T} Sistema escribió un mensaje", mail(
        "SISTEMA", "Esta es una respuesta automática para confirmar que hemos recibido su solicitud.",
        "[EXT] Aplicaciónes de mensualidad"))
    r = correr(repo, tk, sin, 1, remitente=CALLCENTER)
    assert roles(r) == ["ceci"]
    msg = r["plan"][0]["mensaje"]
    assert msg.startswith("Ticket 2587626 · cliente sin identificar · Aplicaciónes de mensualidad:")
    assert "⚠️ No pude identificar" in msg


def test_recordatorio_del_tramite_lleva_el_asunto(repo):
    tk = tramite(repo)
    correr(repo, tk, T1, 1, remitente=CALLCENTER)
    correr(repo, tk, T2, 2, remitente=CALLCENTER)
    r = escanear_recordatorios(repo, datetime(2026, 10, 22, 16, 0, tzinfo=timezone.utc))
    ase = next(a for a in r["plan"] if a["rol"] == "asesor")["mensaje"]
    assert ase.startswith("Ticket 2587626 · Ana Prueba Ruiz · Aplicación de pago póliza OPPT-48211: sigue pendiente")


def test_escalacion_del_tramite_nombra_el_tramite(repo, monkeypatch):
    monkeypatch.setattr(config, "ESCALAR_A_ALLIANZ", True)
    tk = tramite(repo)
    correr(repo, tk, T1, 1, remitente=CALLCENTER)
    correr(repo, tk, T3, 2, remitente=CALLCENTER)  # le respondimos → esperando a Allianz
    escanear_recordatorios(repo, datetime(2026, 10, 22, 16, 0, tzinfo=timezone.utc))
    r = escanear_recordatorios(repo, datetime(2026, 10, 23, 17, 0, tzinfo=timezone.utc))
    correo = next(a for a in r["plan"] if a["tipo_accion"] == "escalar_allianz")
    assert "Damos seguimiento a el trámite" not in correo["cuerpo"]
    assert "al trámite «Aplicación de pago póliza OPPT-48211» de Ana Prueba Ruiz (ticket 2587626)" in correo["cuerpo"]


# ================================================================ textos (docs/TEXTOS_ETAPA2.md)
from app.acciones import mensajes_etapa as m  # noqa: E402


@pytest.mark.parametrize("prod,esperado", [("SVIP", "tu solicitud de Elite"), ("OPPT", "tu solicitud de Patrimonial"),
                                           ("PLU3", "tu solicitud de OptiMaxx Plus")])
def test_guia_respeta_la_marca_del_producto(prod, esperado):
    ctx = m.contexto({"producto": prod, "poliza": f"{prod}-1"}, {}, {"cliente_nombre": "Ana Ruiz"})
    assert esperado in m.texto_guia(m.datos_guia(ctx))


def test_el_largo_no_cambia_de_texto():
    ctx = {**m.contexto({"nro_ticket": "2576612", "proceso": "largo", "nro_solicitud": "1950110"},
                        {"cliente": "Hortencia Prueba Gama"}), "desde": "26/10", "cc": "x"}
    assert m.texto_recordatorio("ceci", "esperando_allianz", "recordatorio", ctx).startswith(
        "Ticket 2576612 · Hortencia Prueba Gama: Allianz no responde desde que mandamos los documentos (26/10).")
    assert ("Damos seguimiento a la solicitud 1950110 de Hortencia Prueba Gama (ticket 2576612). El 26/10 "
            "enviamos la documentación solicitada y a la fecha") in m.CORREO_ESCALACION.format(**ctx)
    assert m.contexto({"producto": "GMMI"}, {})["de_producto"] == " de gastos médicos"


def test_escalacion_del_corto_habla_del_pago():
    ctx = {**m.contexto({"nro_ticket": "2567479", "proceso": "corto", "poliza": "SVIP-21799"},
                        {"cliente": "GUILLERMO PRUEBA"}), "desde": "30/10"}
    assert "Damos seguimiento a la póliza SVIP-21799 de Guillermo Prueba (ticket 2567479). El 30/10 enviamos " \
           "el comprobante de pago" in m.CORREO_ESCALACION.format(**ctx)


def test_escalacion_pendiente_se_descarta_si_allianz_responde(repo, monkeypatch):
    """Encontrado en la prueba de todo junto: el correo de escalación esperaba a Ceci aunque Allianz
    ya hubiera respondido (Ceci podía aprobar una escalación sin sentido). Vale también para el largo."""
    monkeypatch.setattr(config, "ESCALAR_A_ALLIANZ", True)
    tk = tramite(repo)
    correr(repo, tk, T1, 1, remitente=CALLCENTER)
    correr(repo, tk, T3, 2, remitente=CALLCENTER)
    escanear_recordatorios(repo, datetime(2026, 10, 22, 16, 0, tzinfo=timezone.utc))
    escanear_recordatorios(repo, datetime(2026, 10, 23, 17, 0, tzinfo=timezone.utc))
    esc = [a for a in repo.listar_acciones(tk) if a["tipo_accion"] == "escalar_allianz"]
    assert [a["estado"] for a in esc] == ["sugerida"]
    r = correr(repo, tk, T4, 3, remitente=CALLCENTER, ahora=datetime(2026, 10, 23, 18, 0, tzinfo=timezone.utc))
    assert "se descartó la escalación pendiente" in r["recordatorios"]
    assert [a["estado"] for a in repo.listar_acciones(tk) if a["tipo_accion"] == "escalar_allianz"] == ["omitida"]
