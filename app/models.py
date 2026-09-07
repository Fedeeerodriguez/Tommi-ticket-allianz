"""Modelo de dominio del sistema de tickets Allianz.

Por ahora son dataclasses puras (sin DB). En la Fase 2 se mapean a tablas de Supabase:
`correos`, `tickets`, `ticket_eventos`, `acciones`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class TipoCorreo(str, Enum):
    """Taxonomía de correos entrantes (ver README §5)."""

    A_RESPUESTA_TICKET = "A_respuesta_ticket"      # Allianz responde a un ticket existente
    B_ACUSE_TICKET = "B_acuse_ticket"              # Allianz acusa/abre un ticket nuevo
    C_ALLIANZ_PIDE = "C_allianz_pide"              # Allianz pide algo al cliente
    D_REENVIO_ASESOR = "D_reenvio_asesor"          # Asesor reenvía pidiendo abrir un trámite
    E_CC_CLIENTE = "E_cc_cliente"                  # Cliente copió a Babilonia al escribir a Allianz
    F_CONSULTA_PRODUCTO = "F_consulta_producto"    # Asesor pregunta de producto/proceso
    G_SISTEMA = "G_sistema"                        # 2FA, códigos, WATI, n8n, notificaciones
    H_PUBLICIDAD = "H_publicidad"                  # newsletter / spam / marketing
    I_NO_CLASIFICABLE = "I_no_clasificable"        # ninguna regla con confianza → humano (Ceci)


class EstadoTicket(str, Enum):
    ABIERTO = "abierto"
    ESPERANDO_ALLIANZ = "esperando_allianz"
    ESPERANDO_CLIENTE = "esperando_cliente"
    ESPERANDO_ASESOR = "esperando_asesor"
    RESUELTO = "resuelto"
    ESCALADO_CECI = "escalado_ceci"


@dataclass
class Correo:
    """Un correo entrante ya normalizado. `message_id` es la clave de idempotencia."""

    message_id: str
    remitente: str
    remitente_dominio: str
    para: list[str]
    cc: list[str]
    asunto: str
    cuerpo_texto: str
    fecha: Optional[datetime] = None
    headers: dict[str, str] = field(default_factory=dict)
    adjuntos: list[str] = field(default_factory=list)
    origen: Optional[str] = None  # ruta del .eml o id del mensaje en el buzón


@dataclass
class Clasificacion:
    """Resultado de clasificar un correo (capa L1 de reglas; L2 con LLM se agrega luego)."""

    tipo: TipoCorreo
    confianza: float                 # 0.0 - 1.0
    motivo: str                      # por qué se decidió (trazabilidad)
    necesita_llm: bool = False       # True si la confianza cae bajo el umbral → revisar con L2
    entidades: dict[str, Any] = field(default_factory=dict)  # nº ticket, póliza, etc. (extracción)
