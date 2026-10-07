"""Mensajes coloquiales para clientes/asesores (M4).

Genera un texto breve y cálido con OpenAI (si USAR_LLM_RESUMEN y hay key); si no, cae a una
plantilla fija. Pensado para WhatsApp: corto, claro, sin tecnicismos.
"""
from __future__ import annotations

import logging
from typing import Optional

from app import config

log = logging.getLogger(__name__)


def _plantilla(rol: str, ctx: dict) -> str:
    nombre = (ctx.get("cliente_nombre") or "").split()[0] if ctx.get("cliente_nombre") else None
    hola = f"Hola {nombre}! " if (rol == "cliente" and nombre) else "Hola! "
    tk = ctx.get("nro_ticket")
    ref = f" (ticket {tk})" if tk else ""
    tipo = ctx.get("tipo")
    if rol == "asesor":
        # Al asesor se le habla como asesor (antes recibía el texto del cliente: "tu trámite").
        autor = ctx.get("autor_mensaje_allianz")
        quien = f" ({autor} escribió en Allianz)" if autor else ""
        return f"Novedad en el ticket {tk or '—'}{quien}. Revisá el detalle en el panel de seguimiento."
    if tipo == "A_respuesta_ticket":
        return f"{hola}Allianz respondió sobre tu trámite{ref}. Te dejamos el detalle y cualquier cosa te acompañamos. 💛"
    if tipo == "B_acuse_ticket":
        return f"{hola}Ya abrimos tu trámite con Allianz{ref}. Le vamos a dar seguimiento y te avisamos de cada avance."
    if tipo == "C_allianz_pide":
        return f"{hola}Allianz necesita un dato/documento para avanzar con tu trámite{ref}. Te contamos qué falta y te ayudamos a enviarlo."
    if tipo == "E_cc_cliente":
        return f"{hola}Recibimos tu solicitud a Allianz{ref}. Quedamos atentos a su respuesta y te avisamos apenas contesten."
    return f"{hola}Tenemos una novedad de tu trámite con Allianz{ref}."


def generar(rol: str, ctx: dict) -> Optional[str]:
    """rol: 'cliente' | 'asesor' | 'ceci'. ctx trae tipo, nombres, nro_ticket, novedad_allianz.

    Redacta con el agente LangChain (`app.agentes.redactar`); si no está disponible, falla o el
    borrador rompe una regla dura, cae a la plantilla fija (sin costo).

    Devuelve None cuando al CLIENTE no hay nada concreto que decirle: la IA respondió
    SIN_NOVEDAD, o es una respuesta de Allianz y no hay borrador válido (la plantilla de
    "Allianz respondió" sin el contenido es justo el relleno que el equipo calificó como mala)."""
    try:
        from app.agentes import redactar
        from app.agentes.redactor import SIN_NOVEDAD

        texto = redactar(rol, ctx)
        if texto == SIN_NOVEDAD:
            return None
        if texto:
            return texto
    except Exception as ex:  # noqa: BLE001
        log.warning("agente redactor no disponible, uso plantilla: %s", ex)
    if rol == "cliente" and ctx.get("tipo") == "A_respuesta_ticket":
        return None
    return _plantilla(rol, ctx)
