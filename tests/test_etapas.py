"""Etapas Allianz — un caso por cada tipo de correo de las capturas de Ceci y de los reales.

Formato copiado de los correos reales (sangrías, cortes de línea, mayúsculas); nombres cambiados.
"""
import pytest

from app.clasificador.etapas import Etapa, detectar_etapa

TK = "[Allianz México Ticket-2576612]"
SISTEMA = "Allianz.Mexico@allianz.com.mx"
PIE = """
 		Gracias,

 		Allianz Mexico SA Compania de Seguros

--------------- Este mensaje fue enviado desde el Service Management
---------------
--------------- {{#2576612-NGZkMD}} ---------------"""


def correo(actor, titulo, msg, verbo="escribió un mensaje en"):
    return f"""--------------- Por favor responda sobre esta línea ---------------

 		Hola HOLA@BABILONIA.AI ,

 		Nuevo mensaje

 		{actor} {verbo} {titulo}:

{msg}
{PIE}"""


def det(asunto, cuerpo, remitente=SISTEMA):
    return detectar_etapa(asunto, cuerpo, remitente)


# ============================================================ PROCESO LARGO (captura 1 a 5)
def test_c1_sistema_creo_la_solicitud():
    r = det(f"{TK} Sistema creó una nueva solicitud en su nombre", """
 		Hola HOLA@BABILONIA.AI ,
 		Nueva solicitud
 		SISTEMA creó 1945278 ANA PRUEBA SANCHEZ NUEVO NEGOCIO en tu
nombre:
 		Descripción del proceso""")
    assert r.etapa == Etapa.APERTURA and r.proceso == "largo"
    assert r.nro_ticket == "2576612" and r.nro_solicitud == "1945278" and r.cliente == "ANA PRUEBA SANCHEZ"
    assert set(r.accion.avisar) == {"ceci", "asesor", "cliente"} and not r.accion.responder_allianz


def test_c1_creada_por_una_persona_tambien_es_apertura():
    r = det(f"{TK} Nancy Galeana Salas creó una nueva solicitud en su nombre",
            " NANCY GALEANA SALAS creó NUEVO NEGOCIO EDUCACIÓN en tu nombre:\n Descripción")
    assert r.etapa == Etapa.APERTURA and r.producto == "OP3D"


def test_c1_gmm_con_prefijo_de_producto():
    r = det(f"{TK} Sistema creó una nueva solicitud en su nombre",
            " SISTEMA creó GMMI 98577 MARTA PRUEBA URIBE N en tu nombre:\n Emisión GMMI")
    assert (r.etapa, r.producto, r.proceso, r.nro_solicitud) == (Etapa.APERTURA, "GMMI", "largo", "98577")
    assert r.cliente == "MARTA PRUEBA URIBE"


def test_c2_confirmacion_de_datos_no_avisa():
    r = det(f"{TK} Sistema escribió un mensaje", correo("SISTEMA", "1945278 ANA PRUEBA SANCHEZ NUEVO NEGOCIO", """Estimado cliente,

Le confirmamos que recibimos su solicitud para trámite que se
describe a continuación:

 * OFICINA SOLICITANTE: (MER)
 * NÚMERO DE AGENTE: 18108
 * NÚMERO DE SOLICITUD: 1945278
 * TIPO DE SOLICITUD: OPTIMAXX PROTECCION, Nuevo negocio
 * DESCRIPCIÓN: ANA PRUEBA SANCHEZ

Saludos cordiales."""))
    assert r.etapa == Etapa.CONFIRMACION_DATOS and r.proceso == "largo"
    assert r.accion.avisar == () and not r.accion.recordatorio
    assert r.cliente == "ANA PRUEBA SANCHEZ" and r.nro_solicitud == "1945278"


def test_c3_requerimiento_adicional_con_plazo():
    r = det(f"{TK} RAUL MARIN escribió un mensaje", correo("RAUL MARIN", "1945278 ANA PRUEBA\nSANCHEZ NUEVO NEGOCIO", """Buen día.

Por este medio le pedimos nos envíe cuestionario laboral requisitado por el solicitante, especificando las
actividades que realiza en su ocupación.

Sin más por el momento, quedamos a la espera de la información; para evitar que su solicitud caduque, a partir
de este momento tiene 15 días hábiles para enviar lo solicitado.

Favor de enviar la información requerida respondiendo a este correo.

Atentamente

Selección de riesgos."""))
    assert r.etapa == Etapa.REQUERIMIENTO and r.actor_tipo == "allianz"
    assert r.plazo == (15, "dias_habiles")
    assert r.que_piden.startswith("Por este medio le pedimos nos envíe cuestionario laboral")
    assert r.accion.recordatorio and r.accion.responder_allianz and len(r.accion.avisar) == 3


@pytest.mark.parametrize("msg", [
    "Para que su solicitud sea atendida, favor de enviar la identificación oficial vigente.",
    "Una vez autorizado el trámite se procede al cobro. Favor de enviar la carta firmada.",
    "Para poder ser autorizada la solicitud requerimos la carta de no adeudo.",
])
def test_c3_pedido_que_nombra_atendida_o_autorizado_sigue_siendo_requerimiento(msg):
    # "sea atendida" / "una vez autorizado" es una condición, no un aviso: no se cierra el ticket.
    r = det(f"{TK} RAUL MARIN escribió un mensaje", correo("RAUL MARIN", "1945278 ANA PRUEBA", msg))
    assert r.etapa == Etapa.REQUERIMIENTO


def test_c3_requerimiento_gmm_historia_clinica():
    r = det(f"{TK} SILVIA LILIAN GARCIA escribió un mensaje", correo("SILVIA LILIAN GARCIA", "GMMI 98577 MARTA\nPRUEBA URIBE N", """Buen día
Favor de enviar Historia clínica completa y actualizada (por parte de
especialista en medicina interna). Adicional, anexar reporte de química sanguínea.
Sin más por el momento y para evitar que su solicitud caduque, a
partir de este momento tiene 15 días hábiles para enviar lo
solicitado.
Favor de enviar la información requerida respondiendo a este correo.
Atentamente
Selección de riesgos."""))
    assert r.etapa == Etapa.REQUERIMIENTO and r.producto == "GMMI" and r.plazo == (15, "dias_habiles")
    assert "Historia clínica" in r.que_piden


def test_c3_requerimiento_plazo_en_dias_corridos():
    r = det(f"{TK} FRANCISCA MONDRAGON escribió un mensaje", correo("FRANCISCA MONDRAGON", "GMLI 15964 PEDRO PRUEBA N", """Buen Día:
Le informamos que recibimos su solicitud, para continuar con el
trámite favor de enviar en PDF los documentos solicitados POR ESTE
MEDIO, cuenta con 10 días a partir de la recepción de este
mensaje.
Enviar:
 * Carta de ANTIGUEDAD para antiguedad solicitada,
Saludos."""))
    assert r.etapa == Etapa.REQUERIMIENTO and r.plazo == (10, "dias")


def test_c3_proveedor_externo_de_allianz_pide_comprobante():
    r = det(f"{TK} EXTERNO GLORIA PRUEBA MARTINEZ escribió un mensaje", correo(
        "EXTERNO GLORIA PRUEBA MARTINEZ", "1950110 HORTENSIA PRUEBA GAMA NUEVO NEGOCIO", """Hola buen día.
La dirección en el comprobante de domicilio no coincide con la
proporcionada en el formato de identificación, favor de
proporcionar comprobante de domicilio para terminar proceso.
Saludos cordiales"""))
    assert r.etapa == Etapa.REQUERIMIENTO and r.actor_tipo == "allianz" and r.plazo is None


def test_c3_agendar_pruebas_medicas_es_requerimiento():
    r = det(f"{TK} GEOVANNA VICTORIA BECERRA escribió un mensaje", correo(
        "GEOVANNA VICTORIA BECERRA", "1950110 HORTENSIA PRUEBA GAMA NUEVO NEGOCIO", """Buen día.
Nos ponemos en contacto con usted con el fin de apoyar en la
programación de las pruebas médicas del cliente. Para ello, le
solicitamos de la manera más atenta nos proporcione la siguiente
información completa:
 * Nombre completo:
 * 3 posibles fechas para agendar cita (indicar horarios):
Sin más por el momento, quedamos atentos a su información."""))
    assert r.etapa == Etapa.REQUERIMIENTO


def test_c4_eco_de_nuestro_envio():
    r = det(f"{TK} integraciones@babilonia.ai escribió un mensaje", correo(
        "integraciones@babilonia.ai", "1945278 ANA PRUEBA SANCHEZ\nNuevo Negocio",
        "Buen día,\n\nEnvio el cuestionario laboral solicitado.\n\nQuedo al pendiente de sus comentarios. Saludos."))
    assert r.etapa == Etapa.DOCUMENTOS_ENVIADOS and r.actor_tipo == "propio"
    assert r.accion.cancela_recordatorio and r.accion.recordatorio and not r.accion.responder_allianz


def test_c4_la_ejecutiva_sube_lo_solicitado():
    r = det(f"{TK} BLANCA ISABEL XULUC escribió un mensaje", correo(
        "BLANCA ISABEL XULUC", "GMLI 15964 PEDRO\nPRUEBA N", "@F. MONDRAGON ANEXO LO SOLICITADO. Saludos"))
    assert r.etapa == Etapa.DOCUMENTOS_ENVIADOS and r.actor_tipo == "ejecutiva"


def test_c4_el_asesor_responde_desde_su_gmail():
    r = det(f"{TK} 81asesor@gmail.com escribió un mensaje", correo(
        "81asesor@gmail.com", "1945278 ANA PRUEBA SANCHEZ Nuevo Negocio", "Adjunto la carta laboral. Saludos"))
    assert r.etapa == Etapa.DOCUMENTOS_ENVIADOS and r.actor_tipo == "externo"


def test_c5_atendida_en_proceso_de_cobro_cierra():
    r = det(f"{TK} FRANCISCA MONDRAGON escribió un mensaje", correo("FRANCISCA MONDRAGON", "GMLI 15964 PEDRO\nPRUEBA N", """Estimado agente,
Le informamos que su solicitud fue atendida y se encuentra en proceso
de cobro.
Folio cerrado.
Saludos cordiales."""))
    assert r.etapa == Etapa.ATENDIDA and r.accion.cerrar and len(r.accion.avisar) == 3


def test_c5_atendida_minima_con_poliza():
    r = det(f"{TK} NATALY VICTORIA VELAZQUEZ escribió un mensaje",
            correo("NATALY VICTORIA VELAZQUEZ", "NUEVO NEGOCIO\nEDUCACIÓN", "ATENDIDA\nOP3D-14798"))
    assert r.etapa == Etapa.ATENDIDA and r.poliza == "OP3D-14798" and r.producto == "OP3D"


def test_c5_cierre_escrito_por_el_sistema():
    r = det(f"{TK} Sistema escribió un mensaje", correo("SISTEMA", "NUEVO NEGOCIO EDUCACIÓN", """Estimado agente:
“Se informa que la solicitud se encuentra atendida, por lo tanto, el
presente ticket queda cerrado”."""))
    assert r.etapa == Etapa.ATENDIDA and r.accion.cerrar


@pytest.mark.parametrize("msg", [
    "Buen día, la solicitud ha sido autorizada. Saludos.",
    "Se informa que su solicitud pasa a cobro.",
    "Le informamos que la solicitud se encuentra en proceso de cobro.",
])
def test_c3_autorizado_para_cobro_corta_recordatorio(msg):
    r = det(f"{TK} RAUL MARIN escribió un mensaje", correo("RAUL MARIN", "1945278 ANA PRUEBA SANCHEZ NUEVO NEGOCIO", msg))
    assert r.etapa == Etapa.AUTORIZADO and len(r.accion.avisar) == 3
    assert r.accion.cancela_recordatorio and not r.accion.cerrar and "cobro" in r.accion.nota


def test_no_autorizado_no_avanza():
    r = det(f"{TK} RAUL MARIN escribió un mensaje", correo(
        "RAUL MARIN", "1945278 ANA NUEVO NEGOCIO", "Aún no autorizado: favor de enviar el cuestionario médico."))
    assert r.etapa == Etapa.REQUERIMIENTO


def test_c5_largo_es_cobrado():
    r = det(f"{TK} RAUL MARIN escribió un mensaje", correo("RAUL MARIN", "1945278 ANA NUEVO NEGOCIO", "Solicitud atendida."))
    assert r.proceso == "largo" and "cobrada" in r.accion.nota


def test_que_piden_no_se_corta_en_quedamos_en_espera():
    # Real (ticket 2582367): el pedido arranca con "Quedamos en espera de la información faltante".
    r = det(f"{TK} RAUL MARIN escribió un mensaje", correo("RAUL MARIN", "1945278 ANA NUEVO NEGOCIO", """Buen día.

Gracias por el envío de la quimica sanguienea.

Quedamos en espera de la información faltante:

1.- Historia clínica completa y actualizada, por su médico
tratante, indicando antecedente de cirugías.

Sin más por el momento y para evitar que su solicitud caduque, a
partir de este momento tiene 09 días hábiles para enviar lo
solicitado.

Atentamente
Selección de riesgos."""))
    assert r.etapa == Etapa.REQUERIMIENTO and r.plazo == (9, "dias_habiles")
    assert r.que_piden.startswith("1.- Historia clínica completa") and "química" not in r.que_piden


def test_no_atendida_no_cierra():
    r = det(f"{TK} RAUL MARIN escribió un mensaje", correo(
        "RAUL MARIN", "1945278 ANA PRUEBA SANCHEZ NUEVO NEGOCIO",
        "Su solicitud aún no atendida: favor de enviar la identificación oficial."))
    assert r.etapa == Etapa.REQUERIMIENTO


def test_rechazo_por_plazo_vencido():
    r = det(f"{TK} Nancy Galeana Salas escribió un mensaje", correo("NANCY GALEANA SALAS", "1920997 HORTENSIA\nPRUEBA GAMA NUEVO NEGOCIO", """Buen día:
Debido a que no se contó con respuesta del complemento solicitado y
se excedió el período de vigencia de 30 días, se procede a rechazar
el presente ticket. Si requiere continuar con la emisión, deberá
ingresar una cotización nueva."""))
    assert r.etapa == Etapa.RECHAZADO and r.accion.cerrar and r.accion.delicado
    assert "cliente" not in r.accion.avisar


def test_riesgo_declinado():
    r = det(f"{TK} SILVIA LILIAN GARCIA escribió un mensaje", correo("SILVIA LILIAN GARCIA", "1931655 CINTIA PRUEBA\nHERNANDEZ NUEVO NEGOCIO", """Buen día
Se informa que el riesgo propuesto ha sido declinado en virtud de no
poder ofrecer las coberturas solicitadas.
Atentamente
Selección de riesgos."""))
    assert r.etapa == Etapa.DECLINADO and r.accion.delicado and "cliente" not in r.accion.avisar
    assert "contacta al cliente" in r.accion.nota


def test_persona_sin_patron_va_a_revision():
    r = det(f"{TK} RAUL MARIN escribió un mensaje", correo("RAUL MARIN", "1945278 ANA NUEVO NEGOCIO", "Buen día, le comento que seguimos revisando."))
    assert r.etapa == Etapa.REVISAR and r.accion.avisar == ()


# ============================================================ PROCESO CORTO (SVIP / OPPT)
def test_corto_c1_emision_registrada_html():
    r = det("Emisión póliza No. Póliza: SVIP-21799 No. Solicitud: 25287681", """<html><body>
<table><tr><td>¡Felicidades, su solicitud se registró correctamente!</td></tr></table>
<p>Número de póliza: SVIP-21799.</p>
<p>Estimado(a) GUILLERMO PRUEBA CASTRO le agradecemos la confianza depositada en nosotros para administrar su
plan de inversión OPTIMAXX ELITE ART. 93, del cual recibimos su solicitud.</p></body></html>""",
            "notificaciones.optimaxx@allianz.com.mx")
    assert (r.etapa, r.proceso, r.producto, r.poliza) == (Etapa.EMISION_REGISTRADA, "corto", "SVIP", "SVIP-21799")
    assert r.nro_solicitud == "25287681" and r.accion.avisar == ()


def test_corto_c2_confirmacion_dispara_guia_de_aportacion():
    r = det("[Allianz México Ticket-2567479] Sistema escribió un mensaje", correo(
        "SISTEMA", "[EXT] Emisión póliza No. Póliza: SVIP-21799 No. Solicitud: 25287681", """Estimado cliente,
Le confirmamos que recibimos su solicitud para trámite que se describe a continuación:
 * OFICINA SOLICITANTE: Centro
 * NOMBRE DEL CONTRATANTE: GUILLERMO PRUEBA CASTRO
 * NÚMERO DE SOLICITUD: 25287681
 * TIPO DE SOLICITUD: SVIP, Nuevo negocio
 * REGIONAL Centro"""))
    assert (r.etapa, r.proceso, r.producto) == (Etapa.CONFIRMACION_DATOS, "corto", "SVIP")
    assert r.accion.aprobacion_telegram and r.accion.avisar == ("ceci",)
    assert r.cliente == "GUILLERMO PRUEBA CASTRO" and r.poliza == "SVIP-21799"


def test_corto_c3_aviso_de_emision_cierra():
    r = det("Aviso de emisión de póliza SVIP/21799 a nombre de Guillermo Prueba Castro.",
            "Estimado(a) JOSE RAMON MIER, ... copia de la carátula correspondiente a la póliza SVIP-21799-0 de Guillermo",
            "notificaciones.optimaxx@allianz.com.mx")
    assert (r.etapa, r.poliza, r.cliente) == (Etapa.POLIZA_EMITIDA, "SVIP-21799", "Guillermo Prueba Castro")
    assert r.accion.cerrar


@pytest.mark.parametrize("asunto,remitente,poliza,proceso", [
    ("Aviso de emisión de póliza VIPP-145029-0 DANIEL PRUEBA JUAREZ", "aviso.electronico@allianz.com.mx", "VIPP-145029", "largo"),
    ("Aviso de emisión de póliza GMLI_1131_0 de RODRIGO PRUEBA BANCK", "comunicados.agentes@allianz.com.mx", "GMLI-1131", "largo"),
    # PLU3 va por el proceso corto (Ceci, 20/10: sin requisitos extra).
    ("Aviso de emisión de póliza PLU3/436663 a nombre de Margarita Prueba Ruiz.", "notificaciones.optimaxx@allianz.com.mx", "PLU3-436663", "corto"),
])
def test_avisos_de_emision_de_otros_remitentes(asunto, remitente, poliza, proceso):
    r = det(asunto, "Estimado(a) BABILONIA SEGUROS ...", remitente)
    assert r.etapa == Etapa.POLIZA_EMITIDA and r.poliza == poliza and r.proceso == proceso


# ============================================================ TRÁMITES (los abrimos nosotros)
def test_tramite_c1_acuse_automatico():
    r = det("[Allianz México Ticket-2587626] Sistema escribió un mensaje", correo(
        "SISTEMA", "[EXT] Aplicaciónes de mensualidad", """Estimado cliente,

Esta es una respuesta automática para confirmar que hemos recibido su solicitud, la cual será canalizada a la
brevedad para su atención.

Es importante mencionar que, si este correo es recibido en día hábil antes de las 12.00 hrs el tiempo de
resolución empezará a contar a partir de la fecha de recepción."""), "Call Center Ahorro <callcenter.ahorro@allianz.com.mx>")
    assert (r.etapa, r.proceso, r.nro_ticket) == (Etapa.APERTURA, "tramite", "2587626")
    assert r.titulo_hilo == "[EXT] Aplicaciónes de mensualidad" and len(r.accion.avisar) == 3


def test_tramite_c2_requisito_adicional():
    r = det("[Allianz México Ticket-2587626] OSBALDO PINEDA escribió un mensaje", correo(
        "OSBALDO PINEDA", "[EXT] Aplicaciónes de mensualidad", """Buen día, estimado cliente. Espero que se encuentre bien.

Revisamos la información de su pago y observamos que no incluye la fecha de pago. Además, el estado de
cuenta no viene adjunto.

Por favor, envíenos esta información para que podamos aplicarla de manera correcta en el ticket.

Quedamos atentos a su respuesta."""), "Call Center Ahorro <callcenter.ahorro@allianz.com.mx>")
    assert (r.etapa, r.proceso) == (Etapa.REQUERIMIENTO, "tramite")
    assert r.accion.recordatorio and r.plazo is None  # sin plazo → 72 h hábiles


# ============================================================ EJECUTIVAS Y REBOTES
_RV = """Internal

Hola buen día,
{propio}

Saludos.

Penny Yamili Ortiz Levinson
Ejecutivo Comercial Pleno

De: Allianz.Mexico@allianz.com.mx <Allianz.Mexico@allianz.com.mx>
Asunto: [EXT] [Allianz México Ticket-2584224] GEOVANNA VICTORIA BECERRA escribió un mensaje
Hola PENNY YAMILI ORTIZ,
Nuevo mensaje
GEOVANNA VICTORIA BECERRA escribió un mensaje en 1950110 X Nuevo Negocio<https://x>:
Favor de enviar comprobante.
"""


def test_reenvio_de_penny_es_copia_y_no_avisa_de_nuevo():
    r = det("RV: [Allianz México Ticket-2584224] GEOVANNA VICTORIA BECERRA escribió un mensaje",
            _RV.format(propio="Comparto para su conocimiento."), "penny.ortiz@allianz.com.mx")
    assert r.etapa == Etapa.COPIA_EJECUTIVA and r.accion.avisar == ()


def test_reenvio_de_penny_pidiendo_respuesta_alerta_a_ceci():
    r = det("RV: [Allianz México Ticket-2582367] RAUL MARIN escribió un mensaje",
            _RV.format(propio="Comparto para su conocimiento, su apoyo para brindar respuesta directamente al ticket con copia a una servidora."),
            "penny.ortiz@allianz.com.mx")
    assert r.etapa == Etapa.COPIA_EJECUTIVA and r.accion.avisar == ("ceci",)


def test_ejecutiva_con_comentario_propio():
    r = det("RV: [Allianz México Ticket-2582367]GMMI 98341 MARIA PRUEBA", """Internal
Buenos dias
Para su conocimiento y atención
La historia clínica se puede extender por parte del medico tratante en una hoja membretada.
saludos
Blanca Isabel Xuluc Pérez
Ejecutivo Comercial Sureste
De: Allianz.Mexico@allianz.com.mx""", "blanca.xuluc@allianz.com.mx")
    assert r.etapa == Etapa.NOTA_EJECUTIVA and "hoja membretada" in r.mensaje
    assert set(r.accion.avisar) == {"ceci", "asesor"}


def test_rebote_ticket_ya_cerrado_alerta_a_ceci():
    r = det("Solicitud finalizada Ticket 2533643 Asunto GMLI 15964 PEDRO PRUEBA N",
            "<p>Su mensaje corresponde a un ticket que ya se encuentra cerrado, por lo que no es posible continuar</p>")
    assert r.etapa == Etapa.REBOTE_TICKET_CERRADO and r.nro_ticket == "2533643"
    assert r.titulo_hilo == "GMLI 15964 PEDRO PRUEBA N"  # para que Ceci sepa qué hilo rebotó
    assert r.accion.avisar == ("ceci",) and not r.accion.cerrar


# ============================================================ RUIDO
def test_marketing_de_allianz_no_aplica():
    assert det("Mantente prevenido ante el paso de los huracanes", "Recibes este mail porque...").etapa == Etapa.NO_APLICA


def test_correo_que_no_es_de_allianz():
    assert det(f"{TK} X escribió un mensaje", "hola", "cliente@gmail.com").etapa == Etapa.NO_APLICA


def test_texto_en_nfd_de_allianz():
    import unicodedata
    asunto = unicodedata.normalize("NFD", f"{TK} Sistema escribió un mensaje")
    cuerpo = unicodedata.normalize("NFD", correo("SISTEMA", "NUEVO NEGOCIO EDUCACIÓN",
                                                 "Le confirmamos que recibimos su solicitud para trámite"))
    assert det(asunto, cuerpo).etapa == Etapa.CONFIRMACION_DATOS


# ============================================================ ETAPA 2 — recorridos completos de corto y trámite
_TR = "[Allianz México Ticket-2587626]"
_CC = "Call Center Ahorro <callcenter.ahorro@allianz.com.mx>"


def test_tramite_nuestra_respuesta_es_documentos_enviados():
    r = det(f"{_TR} integraciones@babilonia.ai escribió un mensaje", correo(
        "integraciones@babilonia.ai", "[EXT] Aplicaciónes de mensualidad",
        "Buen día, anexo el estado de cuenta con la fecha de pago.\nSaludos."), _CC)
    assert (r.etapa, r.proceso, r.actor_tipo) == (Etapa.DOCUMENTOS_ENVIADOS, "tramite", "propio")


@pytest.mark.parametrize("msg,etapa", [
    ("Buen día, le informamos que su solicitud fue atendida. Se aplicó la mensualidad.", Etapa.ATENDIDA),
    ("Estimado cliente, el ticket queda cerrado.", Etapa.ATENDIDA),
])
def test_tramite_c3_atendido_cierra(msg, etapa):
    r = det(f"{_TR} OSBALDO PINEDA escribió un mensaje",
            correo("OSBALDO PINEDA", "[EXT] Aplicaciónes de mensualidad", msg), _CC)
    assert (r.etapa, r.proceso) == (etapa, "tramite") and r.accion.cerrar


def test_tramite_c3_1_cerrado_por_inactividad():
    r = det(f"{_TR} Sistema escribió un mensaje", correo(
        "SISTEMA", "[EXT] Aplicaciónes de mensualidad",
        "Estimado cliente, su ticket fue cerrado por falta de respuesta."), _CC)
    assert (r.etapa, r.proceso) == (Etapa.CERRADO_INACTIVIDAD, "tramite") and r.accion.cerrar


def test_tramite_con_poliza_en_el_asunto():
    r = det(f"{_TR} Sistema escribió un mensaje", correo(
        "SISTEMA", "[EXT] Aplicación de pago póliza OPPT-48211 Ana Prueba",
        "Esta es una respuesta automática para confirmar que hemos recibido su solicitud."), _CC)
    assert (r.etapa, r.proceso, r.poliza, r.producto) == (Etapa.APERTURA, "tramite", "OPPT-48211", "OPPT")


def test_corto_pago_elite_en_el_hilo_es_documentos_enviados():
    r = det("[Allianz México Ticket-2567479] hola@babilonia.ai escribió un mensaje", correo(
        "hola@babilonia.ai", "[EXT] Emisión póliza No. Póliza: SVIP-21799 No. Solicitud: 25287681",
        "Buen día, anexo comprobante de pago y estado de cuenta del cliente."))
    assert (r.etapa, r.proceso, r.poliza) == (Etapa.DOCUMENTOS_ENVIADOS, "corto", "SVIP-21799")


def test_corto_requerimiento_de_allianz():
    r = det("[Allianz México Ticket-2567479] WENDY PRUEBA escribió un mensaje", correo(
        "WENDY PRUEBA", "[EXT] Emisión póliza No. Póliza: OPPT-51234 No. Solicitud: 25290001",
        "Buen día, no identificamos el depósito. Favor de enviar el comprobante con la referencia."))
    assert (r.etapa, r.proceso, r.producto) == (Etapa.REQUERIMIENTO, "corto", "OPPT")
    assert "comprobante" in r.que_piden
