"""Etapa 3B (opción 2) — el cliente le pide un trámite a Tommy por WhatsApp.

Tommy junta lo que hace falta (póliza + los requisitos del trámite, que el cliente manda como foto
o PDF por el mismo WhatsApp) y deja la **solicitud** en el panel. Nada sale a Allianz sin Ceci:
ella la revisa y aprieta "Abrir trámite" (sigue el flujo de la Etapa 3A) o la descarta.

  1. El trámite tiene que ser de los que hacemos nosotros por correo. Los del portal no se
     abren: se le devuelven a Tommy las instrucciones para el cliente.
  2. La póliza se identifica en Notion Emisiones y el WhatsApp desde el que escribe tiene que ser
     el del titular (si no, cualquiera podría pedir un trámite sobre una póliza ajena).
  3. Tiene que haber mandado al menos tantos archivos como requisitos tiene el trámite.
  4. Se crea el ticket `proceso=tramite`, estado `solicitud`, y se le avisa a Ceci.

Lo que devuelve está escrito para que Tommy se lo diga al cliente (`para_cliente`).
"""
from __future__ import annotations

import json
from typing import Optional

from app.acciones import abrir_tramite as AT
from app.acciones.mensajes_etapa import link_panel
from app.acciones.motor_etapas import _encolar
from app.db.repo import Repositorio
from app.enriquecimiento.identificar import Buscador, identificar
from app.tramites import CATALOGO, por_clave
from app.tramites.catalogo import Ruta, instrucciones_cliente

ESTADO = "solicitud"
ABIERTO_POR = "tommy"
ETAPA_AVISO = "solicitud_tramite"
DIAS_ARCHIVOS = 14


def clave_valor(ticket_id: int) -> str:
    return f"solicitud_tramite:{ticket_id}"


def _digitos(v) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def mismo_telefono(a, b) -> bool:
    """WhatsApp (521…/52…) contra el de Notion (10 dígitos): se comparan los últimos 10."""
    da, db = _digitos(a), _digitos(b)
    return len(da) >= 10 and len(db) >= 10 and da[-10:] == db[-10:]


def _no(motivo: str, para_cliente: str, **extra) -> dict:
    return {"ok": False, "motivo": motivo, "para_cliente": para_cliente, **extra}


def leer(repo: Repositorio, ticket_id: int) -> Optional[dict]:
    try:
        v = repo.leer_valor(clave_valor(ticket_id))
        return json.loads(v) if v else None
    except Exception:  # noqa: BLE001
        return None


def solicitar(repo: Repositorio, tramite: str, poliza: str, wa_id: str, nota: Optional[str] = None,
              buscar: Optional[Buscador] = None, http=None) -> dict:
    t = por_clave((tramite or "").strip())
    if t is None:
        return _no("trámite desconocido",
                   "No tengo ese trámite en la lista. ¿Me cuentas qué necesitas cambiar en tu póliza?",
                   tramites=[x.clave for x in CATALOGO])
    if t.ruta != Ruta.NOSOTROS_MAIL:
        return _no("se hace en el portal", instrucciones_cliente(t), portal=True)
    poliza = (poliza or "").strip()
    if not poliza:
        return _no("falta la póliza", "¿Me compartes tu número de póliza? Lo encuentras en tu carátula.")
    ident = identificar(poliza=poliza, buscar=buscar)
    if not ident.ok:
        return _no(f"póliza no identificada ({ident.motivo})",
                   "No encontré esa póliza. ¿Me la confirmas tal como aparece en tu carátula?")
    d = ident.datos
    if not mismo_telefono(wa_id, d.get("telefono_cliente")):
        return _no("el WhatsApp no es el del titular",
                   "Por seguridad, este trámite lo tiene que pedir el titular desde el número registrado "
                   "en la póliza. Si cambiaste de número, avísale a tu asesor para actualizarlo.")
    asunto = AT.asunto(t.clave, (d.get("poliza") or poliza).upper(), d.get("cliente_nombre"))
    previo = AT._abierto_igual(repo, asunto)
    if previo:
        return {"ok": True, "ya_existia": True, "ticket_id": previo["id"], "motivo": "ya hay uno igual en curso",
                "para_cliente": "Ya tenemos tu solicitud en curso. En cuanto Allianz la registre te llega "
                                "el número de seguimiento por aquí."}
    if t.requisitos:
        from app.wati.archivos import archivos_del_cliente
        r = archivos_del_cliente(d.get("telefono_cliente"), dias=DIAS_ARCHIVOS, http=http)
        recibidos = len(r.get("archivos") or [])
        if recibidos < len(t.requisitos):
            return _no(f"faltan archivos ({recibidos} de {len(t.requisitos)})",
                       f"Para el {t.nombre.lower()} necesito que me mandes por aquí, como foto o PDF: "
                       f"{' y '.join(t.requisitos)}. Cuando los mandes, me avisas.",
                       requisitos=list(t.requisitos), recibidos=recibidos)
    else:
        recibidos = 0

    poliza_ok = (d.get("poliza") or poliza).strip().upper()
    tid = repo.crear_ticket({
        "poliza": poliza_ok, "cliente_nombre": d.get("cliente_nombre"),
        "cliente_correo": d.get("cliente_correo"), "asesor_correo": d.get("asesor_correo"),
        "telefono_cliente": d.get("telefono_cliente"), "telefono_asesor": d.get("telefono_asesor"),
        "daf": d.get("daf_nombre"), "estado": ESTADO, "delicado": False, "abierto_por": ABIERTO_POR,
        "asunto_hilo": asunto, "titulo_hilo": f"[EXT] {asunto}", "proceso": "tramite",
        "identificado_por": "poliza",
    })
    nota = (nota or "").strip()[:500] or None
    repo.guardar_valor(clave_valor(tid), json.dumps(
        {"tramite": t.clave, "nota": nota, "archivos": recibidos, "dias": DIAS_ARCHIVOS}, ensure_ascii=False))
    repo.agregar_evento(tid, None, "solicitud_tommy", f"El cliente pidió por WhatsApp: {t.nombre}"[:200])
    cliente = (d.get("cliente_nombre") or "el cliente").title()
    texto = (f"Tommy · {cliente} pidió por WhatsApp el {t.nombre.lower()} de la póliza {poliza_ok}"
             f"{f' y mandó {recibidos} archivo(s)' if recibidos else ''}. Revísalo en el panel y ábrelo con Allianz.")
    if nota:
        texto += f" Nota del cliente: {nota}"
    if link_panel(tid):
        texto += f"\nPanel: {link_panel(tid)}"
    _encolar(repo, tid, "ceci", texto, ETAPA_AVISO, 1, None, None,
             {"ticket": "Solicitud", "tramite": t.nombre, "cliente": cliente, "etapa": "Solicitud del cliente",
              "nombre": cliente.split(" ")[0], "poliza": poliza_ok})
    return {"ok": True, "ticket_id": tid, "motivo": "solicitud creada: espera a Ceci",
            "para_cliente": f"¡Listo! Ya dejé tu solicitud de {t.nombre.lower()} con el equipo. La revisamos y "
                            f"la enviamos a Allianz; cuando la registren te llega por aquí el número de seguimiento."}


def descartar(repo: Repositorio, ticket_id: int, usuario: str = "ceci", motivo: Optional[str] = None) -> dict:
    t = repo.obtener_ticket(ticket_id)
    if not t or t.get("estado") != ESTADO:
        return {"ok": False, "motivo": "no es una solicitud pendiente"}
    repo.actualizar_ticket(ticket_id, estado="resuelto")
    repo.agregar_evento(ticket_id, None, "solicitud_descartada",
                        f"Descartada por {usuario}{': ' + motivo.strip() if motivo and motivo.strip() else ''}"[:200])
    return {"ok": True, "motivo": "solicitud descartada"}
