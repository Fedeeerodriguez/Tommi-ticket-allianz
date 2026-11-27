"""Solicitud firmada que llega por CORREO a integraciones@ (Ceci, 17/11: "los 3 caminos").

Los trámites que hacemos nosotros (cambio de conducto de cobro, aumento o disminución de aportaciones) necesitan
la solicitud firmada. Puede llegar por WhatsApp del cliente (`solicitud_tramite`), desde el panel, o por un correo
del asesor (o del cliente, o de alguien del equipo) a integraciones@. Este módulo es el camino del correo:

  - Se dispara solo si el correo menciona uno de esos trámites, trae la póliza y no es de Allianz ni nuestro.
  - Con los adjuntos completos → queda una SOLICITUD en el panel (igual que la de WhatsApp) con los archivos del
    correo, y se le avisa a Ceci. Nada sale a Allianz hasta que Ceci la revisa y la abre.
  - Si faltan adjuntos y lo mandó el asesor → se le pide por WhatsApp que reenvíe el correo con todo.
  - Si el remitente no es el asesor ni el cliente de la póliza (ni del equipo), la solicitud queda igual, pero
    con la advertencia para Ceci.

Si no se reconoce la póliza en Notion o el correo no trae una, sigue el camino de siempre (no se adivina).
"""
from __future__ import annotations

import json
from typing import Optional

from app import config
from app.acciones import abrir_tramite as AT
from app.acciones import solicitud_tramite as ST
from app.clasificador.allianz import es_correo_allianz
from app.db.repo import Repositorio
from app.enriquecimiento.identificar import Buscador, identificar
from app.models import Correo
from app.tramites import identificar_tramite
from app.tramites.catalogo import Ruta

ORIGEN = "correo"
DOMINIO_EQUIPO = "babilonia.ai"
TIPOS_ARCHIVO = ("application/pdf", "image/")


def clave_adjuntos(ticket_id: int) -> str:
    return f"solicitud_tramite_adjuntos:{ticket_id}"


def _email(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def _propio(remitente: str) -> bool:
    return remitente in {x for x in (config.BUZON, _email(config.SMTP_REMITENTE)) if x}


def archivos_utiles(correo: Correo) -> list[dict]:
    """PDF e imágenes adjuntos (la firma, la INE, el formato). Los logos de la firma de correo no cuentan."""
    return [a for a in (correo.adjuntos_datos or [])
            if any((a.get("tipo") or "").startswith(t) for t in TIPOS_ARCHIVO)]


def quien_lo_manda(remitente: str, d: dict) -> str:
    """asesor | cliente | equipo | otro, contra los correos de la póliza en Notion."""
    if remitente and remitente == _email(d.get("asesor_correo")):
        return "asesor"
    if remitente and remitente == _email(d.get("cliente_correo")):
        return "cliente"
    if remitente.endswith("@" + DOMINIO_EQUIPO):
        return "equipo"
    return "otro"


def leer_adjuntos(repo: Repositorio, ticket_id: int) -> list[dict]:
    try:
        v = repo.leer_valor(clave_adjuntos(ticket_id))
        return json.loads(v) if v else []
    except Exception:  # noqa: BLE001
        return []


def procesar(repo: Repositorio, correo: Correo, correo_id: Optional[int], entidades: Optional[dict],
             buscar: Optional[Buscador] = None) -> Optional[dict]:
    """Si el correo es una solicitud firmada de un trámite nuestro, la deja en el panel. Si no, None."""
    t = identificar_tramite(correo)
    if t is None or t.ruta != Ruta.NOSOTROS_MAIL:
        return None
    remitente = _email(correo.remitente)
    if not remitente or es_correo_allianz(remitente) or _propio(remitente):
        return None
    poliza = ((entidades or {}).get("poliza") or "").strip()
    if not poliza:
        return None
    ident = identificar(poliza=poliza, buscar=buscar)
    if not ident.ok:
        return None
    d = ident.datos
    poliza_ok = (d.get("poliza") or poliza).strip().upper()
    cliente = (d.get("cliente_nombre") or "el cliente").title()
    quien = quien_lo_manda(remitente, d)
    archivos = archivos_utiles(correo)
    asunto = AT.asunto(t.clave, poliza_ok, d.get("cliente_nombre"))

    previo = AT._abierto_igual(repo, asunto)
    if previo:
        if correo_id:
            repo.vincular_correo(correo_id, previo["id"])
        repo.agregar_evento(previo["id"], correo_id, "solicitud_correo",
                            f"Llegó otro correo de {remitente} pidiendo {t.nombre.lower()} (ya estaba en curso)"[:200])
        return {"fin": "solicitud_existente", "ticket_id": previo["id"]}

    if len(archivos) < len(t.requisitos):
        return _faltan_adjuntos(repo, t, d, poliza_ok, cliente, remitente, quien, len(archivos), correo_id)

    tid = ST._ticket(repo, d, poliza_ok, ST.ESTADO, asunto_hilo=asunto, titulo_hilo=f"[EXT] {asunto}")
    if correo_id:
        repo.vincular_correo(correo_id, tid)
    repo.guardar_valor(clave_adjuntos(tid), json.dumps(archivos, ensure_ascii=False))
    repo.guardar_valor(ST.clave_valor(tid), json.dumps(
        {"tramite": t.clave, "nota": None, "archivos": len(archivos), "origen": ORIGEN, "remitente": remitente,
         "quien": quien, "asunto_correo": (correo.asunto or "")[:200]}, ensure_ascii=False))
    repo.agregar_evento(tid, correo_id, "solicitud_correo",
                        f"Llegó por correo de {remitente} ({quien}): {t.nombre}, {len(archivos)} adjunto(s)"[:200])
    rol = {"asesor": "el asesor", "cliente": "el cliente", "equipo": "alguien del equipo"}.get(quien, remitente)
    texto = (f"Tommy · Llegó por correo a integraciones@ la solicitud de {t.nombre.lower()} de {cliente} "
             f"(póliza {poliza_ok}), enviada por {rol}, con {len(archivos)} adjunto(s). Revísala en el panel y "
             f"ábrela con Allianz.")
    if quien == "otro":
        texto += (f" ⚠️ La mandó {remitente}, que no es el asesor ni el cliente registrados en Notion: confirma "
                  f"que sea legítima antes de abrirla.")
    ST._avisar_ceci(repo, tid, t, cliente, poliza_ok, texto, ST.ETAPA_AVISO)
    return {"fin": "solicitud_correo", "ticket_id": tid}


def _faltan_adjuntos(repo: Repositorio, t, d: dict, poliza: str, cliente: str, remitente: str, quien: str,
                     recibidos: int, correo_id: Optional[int]) -> dict:
    """Sin la solicitud firmada no se abre (Ceci, 17/11): se le pide al asesor que reenvíe el correo completo."""
    req = " y ".join(t.requisitos)
    tid = ST._ticket(repo, d, poliza, "esperando_asesor", titulo_hilo=f"{t.nombre} · faltan adjuntos del correo")
    if correo_id:
        repo.vincular_correo(correo_id, tid)
    repo.agregar_evento(tid, correo_id, "solicitud_correo",
                        f"Llegó por correo de {remitente} ({quien}): {t.nombre}, pero faltan adjuntos "
                        f"({recibidos} de {len(t.requisitos)})"[:200])
    params = ST._params(t, cliente, poliza, "Faltan adjuntos")
    texto = (f"Tommy · Recibí el correo con la solicitud de {t.nombre.lower()} de {cliente} (póliza {poliza}), "
             f"pero falta {req}. Reenvía el correo a {config.CC_TRAMITE_CLIENTE} con todo adjunto (PDF o foto) "
             f"y con eso abrimos el trámite.")
    if d.get("telefono_asesor"):
        from app.acciones.motor_etapas import _encolar
        _encolar(repo, tid, "asesor", texto, ST.ETAPA_AVISO, 1, str(d["telefono_asesor"]), None, params)
        ST._avisar_ceci(repo, tid, t, cliente, poliza,
                        f"{texto} (Se lo pedí al asesor por WhatsApp; lo mandó {remitente}.)", ST.ETAPA_AVISO)
    else:
        ST._avisar_ceci(repo, tid, t, cliente, poliza,
                        f"{texto} ⚠️ Falta el teléfono del asesor en Notion: no se le avisó. Lo mandó {remitente}.",
                        ST.ETAPA_AVISO)
    return {"fin": "solicitud_correo_incompleta", "ticket_id": tid}
