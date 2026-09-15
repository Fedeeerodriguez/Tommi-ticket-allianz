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
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Optional

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

# --- Patrones de negocio (según respuestas del equipo) ---
RE_TICKET = re.compile(r"ticket[-\s#]*([0-9]{4,})", re.I)
RE_SOLICITUD = re.compile(r"solicitud[:\s#]*([0-9]{4,})", re.I)
RE_POLIZA = re.compile(r"\b([A-Z]{2,4}[0-9][A-Z0-9]*-?[0-9]{3,}(?:-[0-9])?)\b")
RE_CIERRE = re.compile(r"(solicitud\s+(?:cerrada|atendida|finalizada)|se\s+ha\s+cerrad|ticket\s+cerrad|caso\s+cerrad|finalizad\w*\s+ticket)", re.I)
RE_RECORDATORIO = re.compile(r"(recordatorio|por\s+cerrar|pr[oó]xim\w*\s+a\s+cerrar|falta\s+de\s+respuesta|sin\s+respuesta)", re.I)
RE_CREO_SOLICITUD = re.compile(r"cre[oó]\s+una\s+nueva\s+solicitud", re.I)
RE_SISTEMA_MSG = re.compile(r"sistema\s+escrib\w*\s+un\s+mensaje", re.I)
RE_ESCRIBIO = re.compile(r"escrib\w*\s+un\s+mensaje", re.I)
RE_DEADLINE = re.compile(r"(\d+\s*(?:d[ií]as?|horas?|h[aá]biles?)(?:\s*h[aá]biles?)?)", re.I)
# Acciones críticas → confirmación desde el correo del cliente + revisión de Ceci.
RE_CRITICO = re.compile(
    r"(cancelaci[oó]n\s+de\s+p[oó]liza|cancelar\s+(?:la\s+)?p[oó]liza|"
    r"suspensi[oó]n\s+de\s+aportaci|suspender\s+aportaci|"
    r"per[ií]odo\s+de\s+descanso|a[ñn]o\s+de\s+descanso|"
    r"rescate|retiro\s+total|cambio\s+de\s+beneficiari|fallecimiento|defunci)", re.I)

# Remitentes reales observados (para mapear el tipo por origen).
_SUBJETO_NOTIF = {
    "daf": re.compile(r"\bDAF\b", re.I),
    "emision": re.compile(r"emisi[oó]n", re.I),
    "cobranza": re.compile(r"cobranza", re.I),
}


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


def _actor_desde_asunto(asunto: str) -> tuple[Optional[str], Optional[str]]:
    """De '[Allianz México Ticket-XXXX] <ACTOR> escribió un mensaje' saca el actor y su tipo."""
    m = re.search(r"\]\s*(.+?)\s+escrib\w*\s+un\s+mensaje", asunto, re.I)
    if not m:
        return None, None
    actor = m.group(1).strip()
    tipo = "correo" if "@" in actor else "nombre"
    return actor, tipo


def _clasificar_subtipo(remitente: str, asunto: str, cuerpo: str) -> tuple[str, bool]:
    """Devuelve (subtipo, es_ticket) según las reglas de negocio reales."""
    s, b = asunto or "", cuerpo or ""
    dom = remitente.split("@")[-1].lower()
    local = remitente.split("@")[0].lower()

    # Cierre (prioridad alta: cambia el estado del ticket).
    if RE_CIERRE.search(s) or RE_CIERRE.search(b):
        return "cierre", True
    # Correos del sistema de tickets (Allianz.Mexico@ con "Ticket-XXXX").
    if RE_TICKET.search(s):
        if RE_CREO_SOLICITUD.search(s):
            return "apertura_nuestra", True          # nosotros abrimos el ticket del cliente
        if RE_SISTEMA_MSG.search(s):
            return ("recordatorio" if RE_RECORDATORIO.search(b) else "asignacion_ticket"), True
        if RE_ESCRIBIO.search(s):
            return "respuesta_participante", True     # cliente / agente Allianz / asesor Babilonia
        return "ticket_otro", True
    # Notificaciones (fase 2: se ingieren para conocimiento, no accionan todavía).
    if "allianz" in dom:
        for clave, rx in _SUBJETO_NOTIF.items():
            if rx.search(s):
                return f"notif_{clave}", False
        if any(t in local for t in ("noreply", "no-reply", "notif", "aviso", "mailer")):
            return "notif_sistema", False
    return "otro", False


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
        # Allianz manda el texto en Unicode descompuesto (NFD): "creó" = "cre"+"o"+"́".
        # Normalizamos a NFC para que los patrones con acentos matcheen.
        asunto = unicodedata.normalize("NFC", (msg.get("Subject") or "").strip())
        remitente = (msg.get("From") or "").strip()
        # Solo la dirección del remitente para las heurísticas por dominio/local.
        m_addr = re.search(r"<([^>]+)>", remitente)
        addr = (m_addr.group(1) if m_addr else remitente).strip().lower()
        cuerpo = unicodedata.normalize("NFC", _texto_plano(msg))
        texto = f"{asunto}\n{cuerpo}"

        subtipo, es_ticket = _clasificar_subtipo(addr, asunto, cuerpo)
        actor, actor_tipo = _actor_desde_asunto(asunto)
        mid = (msg.get("Message-ID") or "").strip() or None

        a = Analisis(
            gmail_id=meta["id"],
            thread_id=full.get("threadId", ""),
            fecha=(msg.get("Date") or "").strip(),
            remitente=remitente[:60],
            asunto=asunto[:80],
            subtipo=subtipo,
            es_ticket=es_ticket,
            nro_ticket=(RE_TICKET.search(asunto) or RE_TICKET.search(cuerpo) or [None, None])[1]
            if (RE_TICKET.search(asunto) or RE_TICKET.search(cuerpo)) else None,
            nro_solicitud=(RE_SOLICITUD.search(texto).group(1) if RE_SOLICITUD.search(texto) else None),
            poliza=(RE_POLIZA.search(texto).group(1) if RE_POLIZA.search(texto) else None),
            actor=actor,
            actor_tipo=actor_tipo,
            plazos=list(dict.fromkeys(m.strip() for m in RE_DEADLINE.findall(cuerpo)))[:4],
            critico=bool(RE_CRITICO.search(texto)),
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
