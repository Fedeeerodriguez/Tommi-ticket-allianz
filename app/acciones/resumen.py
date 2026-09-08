"""Mensajes coloquiales para clientes/asesores (M4).

Genera un texto breve y cálido con OpenAI (si USAR_LLM_RESUMEN y hay key); si no, cae a una
plantilla fija. Pensado para WhatsApp: corto, claro, sin tecnicismos.
"""
from __future__ import annotations

import logging

from app import config

log = logging.getLogger(__name__)


def _plantilla(rol: str, ctx: dict) -> str:
    nombre = (ctx.get("cliente_nombre") or "").split()[0] if ctx.get("cliente_nombre") else None
    hola = f"Hola {nombre}! " if (rol == "cliente" and nombre) else "Hola! "
    tk = ctx.get("nro_ticket")
    ref = f" (ticket {tk})" if tk else ""
    tipo = ctx.get("tipo")
    if tipo == "A_respuesta_ticket":
        return f"{hola}Allianz respondió sobre tu trámite{ref}. Te dejamos el detalle y cualquier cosa te acompañamos. 💛"
    if tipo == "B_acuse_ticket":
        return f"{hola}Ya abrimos tu trámite con Allianz{ref}. Le vamos a dar seguimiento y te avisamos de cada avance."
    if tipo == "C_allianz_pide":
        return f"{hola}Allianz necesita un dato/documento para avanzar con tu trámite{ref}. Te contamos qué falta y te ayudamos a enviarlo."
    if tipo == "E_cc_cliente":
        return f"{hola}Recibimos tu solicitud a Allianz{ref}. Quedamos atentos a su respuesta y te avisamos apenas contesten."
    if rol == "asesor":
        return f"Novedad en un ticket de tu cliente{ref}. Revisá el detalle en el panel."
    return f"{hola}Tenemos una novedad de tu trámite con Allianz{ref}."


def generar(rol: str, ctx: dict) -> str:
    """rol: 'cliente' | 'asesor' | 'ceci'. ctx trae tipo, nombres, nro_ticket, resumen_allianz."""
    if not (config.USAR_LLM_RESUMEN and config.hay_llm()):
        return _plantilla(rol, ctx)
    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        sistema = (
            "Sos Tommy, asistente de Babilonia (correduría de seguros con Allianz). Escribí un "
            "mensaje de WhatsApp BREVE (máx 3 frases), cálido y claro, en español rioplatense "
            "neutro, sin tecnicismos ni datos sensibles. No inventes datos que no estén en el contexto."
        )
        usuario = (
            f"Destinatario: {rol}. Contexto del ticket: {ctx}. "
            "Redactá SOLO el mensaje, sin comillas ni encabezados."
        )
        resp = client.chat.completions.create(
            model=config.MODELO_L2, temperature=0.4, max_tokens=180,
            messages=[{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
        )
        return resp.choices[0].message.content.strip()
    except Exception as ex:  # noqa: BLE001
        log.warning("resumen LLM falló, uso plantilla: %s", ex)
        return _plantilla(rol, ctx)
