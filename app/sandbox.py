"""Sandbox de análisis de correos de Allianz — SOLO LECTURA, no envía ni escribe nada.

Lee los correos reales de la casilla por Gmail API y, por cada uno, extrae/infiere todo lo que
el sistema necesita para clasificar y hacer seguimiento, según las reglas de negocio de Babilonia:

  - nº de ticket (Ticket-XXXX)  ·  nº de solicitud/emisión
  - subtipo real del correo (apertura / asignación / respuesta de participante / recordatorio /
    cierre / notificación DAF-emisión-cobranza)
  - actor que escribió (nombre = viene de Allianz; correo = no participante) y su identidad
  - datos de hilo para responder EN EL MISMO HILO (threadId, Message-ID, References)
  - plazos detectados en el cuerpo (días/horas hábiles)
  - banderas: acción crítica (requiere Ceci), Message-ID roto (SMTPIN_ADDED_BROKEN)

No toca la base ni manda correos. Sirve para iterar el clasificador contra datos reales.
"""
from __future__ import annotations

import base64
import email
import email.policy
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from app.clasificador.allianz import clasificar_allianz, nfc
from app.google_auth import construir_servicio


def _ejecutar(req, reintentos: int = 4):
    """Ejecuta un request de la Gmail API con backoff ante rate limit (429/403)."""
    from googleapiclient.errors import HttpError

    for intento in range(reintentos):
        try:
            return req.execute()
        except HttpError as ex:
            code = getattr(getattr(ex, "resp", None), "status", None)
            if code in (429, 403) and intento < reintentos - 1:
                espera = 15 * (intento + 1)
                print(f"   (rate limit; espero {espera}s y reintento…)")
                time.sleep(espera)
                continue
            raise

# Los patrones y la clasificación viven en app/clasificador/allianz.py (fuente única de verdad).


@dataclass
class Analisis:
    gmail_id: str
    thread_id: str
    fecha: str
    remitente: str
    asunto: str
    subtipo: str
    es_ticket: bool
    nro_ticket: Optional[str] = None
    nro_solicitud: Optional[str] = None
    poliza: Optional[str] = None
    actor: Optional[str] = None            # quién "escribió un mensaje"
    actor_tipo: Optional[str] = None       # 'nombre' (viene de Allianz) | 'correo' (no participante)
    plazos: list[str] = field(default_factory=list)
    critico: bool = False
    message_id: Optional[str] = None
    message_id_roto: bool = False
    en_hilo: bool = False                  # tiene In-Reply-To/References → es respuesta dentro de un hilo
    accion_sugerida: str = ""


def _texto_plano(msg) -> str:
    if msg.is_multipart():
        for p in msg.walk():
            if p.get_content_type() == "text/plain" and "attachment" not in str(p.get("Content-Disposition") or ""):
                try:
                    return p.get_content()
                except Exception:  # noqa: BLE001
                    continue
        for p in msg.walk():
            if p.get_content_type() == "text/html":
                try:
                    return re.sub(r"<[^>]+>", " ", p.get_content())
                except Exception:  # noqa: BLE001
                    continue
        return ""
    try:
        c = msg.get_content()
        return re.sub(r"<[^>]+>", " ", c) if msg.get_content_type() == "text/html" else c
    except Exception:  # noqa: BLE001
        return ""


def _accion(a: "Analisis") -> str:
    if a.critico:
        return "→ CECI primero (acción crítica; confirmación desde correo del cliente)"
    return {
        "apertura_nuestra": "avisar al cliente el nº de ticket (WATI si asesor / mail si requiere acción)",
        "asignacion_ticket": "avisar al cliente el nº de ticket asignado",
        "recordatorio": "URGENTE: responder en el hilo antes de que Allianz cierre el ticket",
        "respuesta_participante": "leer la respuesta; si Allianz pide algo → pedírselo al cliente/asesor",
        "cierre": "marcar ticket como resuelto/cerrado",
        "notif_daf": "(fase 2) registrar notificación DAF",
        "notif_emision": "(fase 2) registrar emisión (nº solicitud/póliza)",
        "notif_cobranza": "(fase 2) registrar cobranza",
        "notif_sistema": "(fase 2) registrar notificación",
    }.get(a.subtipo, "revisar manualmente")


def analizar(query: str = "from:allianz.com.mx", limite: int = 60) -> list[Analisis]:
    """Lee correos de Allianz por Gmail API y devuelve el análisis de cada uno. Solo lectura."""
    svc = construir_servicio()
    if svc is None:
        raise RuntimeError("Gmail API sin credenciales/token — autorizá con app.google_oauth_setup")

    resp = _ejecutar(svc.users().messages().list(userId="me", q=query, maxResults=min(limite, 500)))
    out: list[Analisis] = []
    for meta in resp.get("messages", []):
        full = _ejecutar(svc.users().messages().get(userId="me", id=meta["id"], format="raw"))
        raw = base64.urlsafe_b64decode(full["raw"].encode("utf-8"))
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        asunto = nfc((msg.get("Subject") or "").strip())
        remitente = (msg.get("From") or "").strip()
        cuerpo = nfc(_texto_plano(msg))
        mid = (msg.get("Message-ID") or "").strip() or None

        info = clasificar_allianz(asunto, cuerpo, remitente)  # fuente única de verdad
        a = Analisis(
            gmail_id=meta["id"],
            thread_id=full.get("threadId", ""),
            fecha=(msg.get("Date") or "").strip(),
            remitente=remitente[:60],
            asunto=asunto[:80],
            subtipo=info.subtipo.value,
            es_ticket=info.es_ticket,
            nro_ticket=info.nro_ticket,
            nro_solicitud=info.nro_solicitud,
            poliza=info.poliza,
            actor=info.actor,
            actor_tipo=info.actor_tipo,
            plazos=info.plazos,
            critico=info.critico,
            message_id=mid,
            message_id_roto=bool(mid and "SMTPIN_ADDED_BROKEN" in mid),
            en_hilo=bool(msg.get("In-Reply-To") or msg.get("References")),
        )
        a.accion_sugerida = _accion(a)
        out.append(a)
    return out


def resumen(items: list[Analisis]) -> dict:
    from collections import Counter
    return {
        "total": len(items),
        "por_subtipo": dict(Counter(i.subtipo for i in items).most_common()),
        "tickets": sum(1 for i in items if i.es_ticket),
        "con_nro_ticket": sum(1 for i in items if i.nro_ticket),
        "criticos": sum(1 for i in items if i.critico),
        "message_id_roto": sum(1 for i in items if i.message_id_roto),
        "en_hilo": sum(1 for i in items if i.en_hilo),
    }


def como_dicts(items: list[Analisis]) -> list[dict]:
    return [asdict(i) for i in items]
