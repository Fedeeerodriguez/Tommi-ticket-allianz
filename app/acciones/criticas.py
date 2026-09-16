"""Fase E — Guardarraíl de acciones críticas (Ceci primero).

Una acción es CRÍTICA cuando lo que el bot va a EJECUTAR (mandar un correo a Allianz o al
cliente) toca un tema donde el cliente puede **perder dinero o derechos**: cancelación de
póliza, suspensión de aportaciones, período / año de descanso, rescate / retiro total,
siniestro / fallecimiento.

Ninguna acción crítica sale sola. El despachador, en vez de enviar:
  1. compone el **BORRADOR** exacto que iba a mandar (destino + asunto + cuerpo),
  2. deja la acción en estado ``pendiente_ceci`` con ese borrador guardado,
  3. encola (una sola vez por ticket) un mensaje a **Ceci por WATI** pidiéndole el
     **visto bueno** sobre ese borrador.

Recién cuando el ticket queda ``autorizado`` (Ceci aprobó) la acción se re-encola como
``sugerida`` y el siguiente despacho la envía de verdad. Si Ceci rechaza, queda
``rechazada`` y no se manda.

Este guardarraíl es transversal: se aplica desde el despacho, sin importar qué fase generó
la acción, así que cubre tanto los envíos a Allianz como las confirmaciones al cliente.
"""
from __future__ import annotations

import re

from app.db import Repositorio

# Canales que EJECUTAN un envío hacia afuera. Solo estos se frenan por críticos: los canales
# 'wati' (avisos) e 'interno' (panel/Ceci) no mandan nada irreversible.
CANALES_SALIENTES = {"email", "email_cliente"}

# Temas críticos (raíces, sin \b final). Superconjunto de `es_delicado` del motor MÁS
# suspensión de aportaciones y período/año de descanso: son trámites, pero críticos porque
# el cliente puede perder plata (por eso la confirmación al cliente pasa por Ceci).
_RE_CRITICO = re.compile(
    r"(cancelaci|cancelar|rescate|retiro\s+total|fallecimiento|defunci|deceso|"
    r"siniestro|reclamaci|fraude|demanda|devoluci[oó]n\s+de\s+prima|conducta|"
    r"suspensi[oó]n\s+de\s+aportaci|suspender\s+aportaci|"
    r"per[ií]odo\s+de\s+descanso|a[nñ]o\s+de\s+descanso)",
    re.I,
)


def texto_critico(texto: str) -> bool:
    return bool(_RE_CRITICO.search(texto or ""))


def es_accion_critica(ticket: dict, payload: dict) -> bool:
    """True si el ticket ya está marcado delicado o si el borrador/asunto toca un tema crítico.

    Miramos el propio contenido de la acción (mensaje/asunto/trámite) además del asunto del
    hilo, porque un trámite como «suspensión de aportaciones» no marca el ticket como delicado
    pero igual debe pasar por Ceci."""
    if ticket.get("delicado"):
        return True
    campos = " ".join(str(payload.get(k) or "") for k in ("mensaje", "asunto", "tramite"))
    campos += " " + str(ticket.get("asunto_hilo") or "")
    return texto_critico(campos)


def _ya_pidio_visto_bueno(repo: Repositorio, ticket_id: int) -> bool:
    """Evita spamear a Ceci: un solo pedido de visto bueno pendiente por ticket."""
    for a in repo.listar_acciones(ticket_id=ticket_id, estado="sugerida"):
        if a.get("tipo_accion") == "visto_bueno_ceci":
            return True
    return False


def encolar_visto_bueno_ceci(repo: Repositorio, ticket: dict, borrador: dict) -> int | None:
    """Encola el pedido de visto bueno a Ceci (WATI) con el borrador embebido. Idempotente."""
    tid = ticket.get("id")
    if tid is None:
        return None
    if _ya_pidio_visto_bueno(repo, tid):
        return None
    mensaje = (
        f"🔒 VISTO BUENO requerido — ticket {ticket.get('nro_ticket') or '—'}"
        + (f" · póliza {ticket['poliza']}" if ticket.get("poliza") else "")
        + (f"\nCliente: {ticket['cliente_nombre']}" if ticket.get("cliente_nombre") else "")
        + f"\n\nVoy a enviar a: {borrador.get('destino')}"
        + f"\nAsunto: {borrador.get('asunto')}"
        + f"\n\n--- BORRADOR ---\n{borrador.get('cuerpo')}\n---------------\n"
        + "\nRespondé APROBAR para que lo envíe, o RECHAZAR para no mandarlo."
    )
    return repo.crear_accion(tid, "visto_bueno_ceci", "wati",
                             {"rol": "ceci", "mensaje": mensaje, "borrador": borrador})


def retener_para_ceci(repo: Repositorio, accion: dict, ticket: dict, borrador: dict) -> None:
    """Deja la acción crítica en 'pendiente_ceci' con su borrador y pide el visto bueno."""
    repo.actualizar_accion(accion["id"], "pendiente_ceci",
                           {"motivo": "acción crítica: requiere visto bueno de Ceci",
                            "borrador": borrador})
    encolar_visto_bueno_ceci(repo, ticket, borrador)


def autorizar_ticket(repo: Repositorio, ticket_id: int, por: str = "ceci") -> list[int]:
    """Ceci dio el visto bueno: marca el ticket `autorizado` y re-encola como 'sugerida' las
    acciones que estaban `pendiente_ceci` para que el próximo despacho las envíe. Devuelve los
    ids de acciones reactivadas."""
    repo.actualizar_ticket(ticket_id, autorizado=True)
    reactivadas: list[int] = []
    for a in repo.listar_acciones(ticket_id=ticket_id, estado="pendiente_ceci"):
        repo.actualizar_accion(a["id"], "sugerida", {"aprobado_por": por})
        reactivadas.append(a["id"])
    return reactivadas


def rechazar_ticket(repo: Repositorio, ticket_id: int, por: str = "ceci",
                    motivo: str = "") -> list[int]:
    """Ceci rechazó el borrador: las acciones `pendiente_ceci` quedan `rechazada` (no se mandan)."""
    rechazadas: list[int] = []
    for a in repo.listar_acciones(ticket_id=ticket_id, estado="pendiente_ceci"):
        repo.actualizar_accion(a["id"], "rechazada", {"rechazado_por": por, "motivo": motivo})
        rechazadas.append(a["id"])
    return rechazadas
