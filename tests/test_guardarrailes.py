"""Reglas duras anti-alucinación, probadas con los casos REALES que el equipo calificó "mala".

No llaman a la IA: verifican los guardarraíles determinísticos y la lógica del motor.
"""
from app.acciones import motor, resumen
from app.agentes import guardarrailes as g

ASUNTO_SILVIA = "[Allianz México Ticket-2564730] SILVIA LILIAN GARCIA escribió un mensaje"
CORREO_ATENDIDA = (
    "--------------- Por favor responda sobre esta línea --------------- Hola HOLA@BABILONIA.AI , "
    "Nuevo mensaje NATALY VICTORIA VELAZQUEZ escribió un mensaje en NUEVO NEGOCIO EDUCACIÓN: "
    "ATENDIDA OP3D-14798 Gracias, Allianz Mexico SA Compania de Seguros")


def _ctx(**kw):
    base = {"tipo": "A_respuesta_ticket", "nro_ticket": "2564730", "cliente_nombre": None,
            "autor_mensaje_allianz": g.autor_del_asunto(ASUNTO_SILVIA),
            "novedad_allianz": "Para su conocimiento y atención por favor."}
    base.update(kw)
    return base


# ------------------------------------------------------------------ autor y limpieza
def test_autor_del_asunto_es_quien_escribio_en_allianz():
    assert g.autor_del_asunto(ASUNTO_SILVIA) == "SILVIA LILIAN GARCIA"
    assert g.autor_del_asunto("[Allianz México Ticket-1] Sistema escribió un mensaje") is None
    assert g.autor_del_asunto("Confirmación de solicitud") is None


def test_limpiar_mensaje_saca_avisos_del_sistema_e_hilo_citado():
    cuerpo = ("Internal Hola buen día Si la pre póliza VIPP 144045 se consideró a cobro en la remesa "
              "de hoy. Saludos.\nDe: Allianz.Mexico@allianz.com.mx\nEnviado el: jueves\nAsunto: viejo")
    limpio = g.limpiar_mensaje_allianz(cuerpo)
    assert "se consideró a cobro" in limpio
    assert "Internal" not in limpio and "Enviado el" not in limpio
    assert g.limpiar_mensaje_allianz(CORREO_ATENDIDA).startswith("Nuevo mensaje NATALY")


# ------------------------------------------------------------------ R1 nombres
def test_cliente_no_puede_ser_saludado_con_el_nombre_del_autor_de_allianz():
    # Caso real acc#314: "Hola Silvia" en el ticket de Martha Zárate.
    motivo = g.validar_whatsapp("cliente", "Hola Silvia, gracias por tu mensaje.", _ctx())
    assert motivo and "autor" in motivo


def test_cliente_saludo_sin_nombre_pasa():
    assert g.validar_whatsapp("cliente", "Hola, Allianz confirmó que tu póliza está en proceso de cobro.",
                              _ctx()) is None


def test_cliente_con_su_propio_nombre_pasa():
    assert g.validar_whatsapp("cliente", "Hola Martha, Allianz confirmó tu trámite.",
                              _ctx(cliente_nombre="Martha Zarate Uribe")) is None


def test_asesor_puede_nombrar_al_autor_de_allianz():
    assert g.validar_whatsapp("asesor", "En el ticket 2564730 respondió Silvia Lilian Garcia de Allianz.",
                              _ctx()) is None


def test_nombre_inventado_se_rechaza():
    motivo = g.validar_whatsapp("asesor", "Novedad del ticket 2564730 de Roberto Gómez.", _ctx())
    assert motivo and "Roberto" in motivo


# ------------------------------------------------------------------ R2 envíos
def test_correo_a_allianz_no_puede_afirmar_envios():
    # Caso real acc#316: "reiteramos que ya hemos enviado la historia clínica completa…"
    cuerpo = ("Estimados,\n\nEn relación con el ticket 2564730, reiteramos que ya hemos enviado la "
              "historia clínica completa y actualizada.")
    motivo = g.validar_cuerpo_allianz(cuerpo, _ctx(asunto=ASUNTO_SILVIA), "Para su conocimiento.")
    assert motivo and "envi" in motivo


def test_correo_a_allianz_que_pide_confirmacion_pasa():
    cuerpo = ("Estimados,\n\nReferente al ticket 2564730, solicitamos confirmar si cuentan con la "
              "historia clínica actualizada y nos indiquen los siguientes pasos.\n\nQuedamos atentos.")
    assert g.validar_cuerpo_allianz(cuerpo, _ctx(asunto=ASUNTO_SILVIA), "Para su conocimiento.") is None


def test_variantes_de_afirmacion_de_envio():
    for frase in ("Adjuntamos la documentación.", "Ya se envió el formato.",
                  "Les hemos remitido el informe.", "Enviamos lo solicitado ayer."):
        assert g.afirma_envio(frase), frase
    assert not g.afirma_envio("Solicitamos nos envíen el estatus.")


# ------------------------------------------------------------------ R3 montos
def test_monto_que_no_esta_en_el_correo_se_rechaza():
    motivo = g.validar_whatsapp("cliente", "Hola, tu pago de $1,500 quedó aplicado.",
                                _ctx(novedad_allianz="El pago quedó aplicado."))
    assert motivo and "monto" in motivo


# ------------------------------------------------------------------ motor
def test_atendida_cierra_el_ticket():
    # Caso real acc#33/#361: Allianz respondió "ATENDIDA" y Tommy seguía re-exigiendo.
    assert motor._allianz_resuelto(CORREO_ATENDIDA)


def test_atendida_con_negacion_no_cierra():
    assert not motor._allianz_resuelto("La solicitud aún no ha sido atendida por el área.")
    assert not motor._allianz_resuelto("Queda pendiente, todavía no atendida.")


def test_sin_novedad_no_genera_mensaje_al_cliente(monkeypatch):
    from app.agentes import redactor
    monkeypatch.setattr(redactor, "redactar", lambda rol, ctx: redactor.SIN_NOVEDAD)
    monkeypatch.setattr("app.agentes.redactar", lambda rol, ctx: redactor.SIN_NOVEDAD)
    assert resumen.generar("cliente", _ctx()) is None


def test_respuesta_allianz_sin_ia_no_manda_relleno_al_cliente(monkeypatch):
    monkeypatch.setattr("app.agentes.redactar", lambda rol, ctx: None)
    assert resumen.generar("cliente", _ctx()) is None
    assert resumen.generar("asesor", _ctx())          # el asesor sí recibe la plantilla


def test_plantilla_a_allianz_no_filtra_la_nota_interna():
    from app.acciones import despacho
    cuerpo = despacho._cuerpo_allianz({"nro_ticket": "1"},
                                      {"mensaje": "Re-exigencia: Allianz respondió fuera de tema."})
    assert "Re-exigencia" not in cuerpo and "fuera de tema" not in cuerpo


def test_correo_a_allianz_no_trata_al_autor_como_cliente():
    # Caso real (replay con IA): "para avanzar con el trámite del cliente Silvia Lilian García".
    cuerpo = ("Buenas tardes,\n\nPara avanzar con el trámite del cliente Silvia Lilian García en el "
              "ticket 2564730, solicitamos confirmar si cuentan con la historia clínica.")
    motivo = g.validar_cuerpo_allianz(cuerpo, _ctx(asunto=ASUNTO_SILVIA), "Para su conocimiento.")
    assert motivo and "SILVIA" in motivo


def test_plantilla_del_asesor_le_habla_al_asesor():
    texto = resumen._plantilla("asesor", _ctx())
    assert "tu trámite" not in texto and "2564730" in texto and "SILVIA LILIAN GARCIA" in texto


def test_asesor_no_puede_presentar_al_autor_como_cliente():
    # Caso real (replay con IA): "El cliente Nataly Victoria Velazquez envió un nuevo mensaje".
    ctx = _ctx(autor_mensaje_allianz="NATALY VICTORIA VELAZQUEZ", nro_ticket="2462205")
    motivo = g.validar_whatsapp("asesor", "El cliente Nataly Victoria Velazquez envió un mensaje en el "
                                          "ticket 2462205.", ctx)
    assert motivo and "como cliente" in motivo
    assert g.validar_whatsapp("asesor", "En el ticket 2462205 respondió Nataly Victoria Velazquez "
                                        "(Allianz): ATENDIDA.", ctx) is None
