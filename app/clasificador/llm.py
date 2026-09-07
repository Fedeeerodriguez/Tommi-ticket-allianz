"""Clasificación L2 con OpenAI (gpt-4.1-mini, reusado del backend principal de Tommy).

SOLO para los correos que L1 marcó como ambiguos. Defensivo: si no hay API key o falla,
devuelve None y el sistema se queda con lo de L1 (nunca rompe el pipeline por el LLM).
"""
from __future__ import annotations

import json
import logging

from app import config
from app.models import Clasificacion, Correo, TipoCorreo

log = logging.getLogger(__name__)

_TIPOS = [t.value for t in TipoCorreo]

_SYSTEM = (
    "Sos un clasificador de correos de una correduría de seguros (Babilonia) que opera con "
    "Allianz. Clasificá el correo en UNO de estos tipos y devolvé SOLO un JSON.\n"
    f"Tipos válidos: {_TIPOS}\n"
    "Significado: A_respuesta_ticket=Allianz responde un ticket existente; "
    "B_acuse_ticket=Allianz acusa/crea un ticket nuevo; C_allianz_pide=Allianz pide algo al "
    "cliente; D_reenvio_asesor=un asesor reenvía pidiendo abrir un trámite; "
    "E_cc_cliente=un cliente escribió a Allianz y copió a Babilonia; "
    "F_consulta_producto=un asesor pregunta sobre producto/proceso; "
    "G_sistema=2FA/códigos/notificaciones automáticas; H_publicidad=newsletter/spam; "
    "I_no_clasificable=no se puede determinar.\n"
    'Formato EXACTO: {"tipo":"<uno_de_los_tipos>","confianza":<0-1>,"motivo":"<breve>"}'
)


def clasificar_l2(correo: Correo) -> Clasificacion | None:
    if not config.hay_llm():
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        contenido = (
            f"De: {correo.remitente}\nPara: {', '.join(correo.para)}\n"
            f"CC: {', '.join(correo.cc)}\nAsunto: {correo.asunto}\n\n"
            f"{correo.cuerpo_texto[:4000]}"
        )
        resp = client.chat.completions.create(
            model=config.MODELO_L2,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": contenido},
            ],
        )
        datos = json.loads(resp.choices[0].message.content)
        tipo = TipoCorreo(datos["tipo"])
        return Clasificacion(
            tipo=tipo,
            confianza=float(datos.get("confianza", 0.7)),
            motivo="L2/" + config.MODELO_L2 + ": " + str(datos.get("motivo", "")),
            necesita_llm=False,
        )
    except Exception as ex:  # noqa: BLE001
        log.warning("L2 (%s) falló, se mantiene L1: %s", config.MODELO_L2, ex)
        return None
