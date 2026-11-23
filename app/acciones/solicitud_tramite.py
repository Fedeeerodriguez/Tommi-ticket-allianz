"""Etapa 3B — el cliente le pide un trámite a Tommy por WhatsApp (reglas de Ceci, 17/11/2026).

Lo que devuelve está escrito para que Tommy se lo diga al cliente (`para_cliente`). Según el trámite:

  - PORTAL (contraseña, enviar a cobro, fecha de cobro, correo/teléfono, portafolio, retiro…): Tommy no abre nada,
    le pasa al cliente los pasos del portal y, si dio la póliza, le avisa a Ceci.
  - CORREO DEL CLIENTE (facturas, suspensión de aportaciones, periodo de descanso, suspensión de inflación):
    Tommy arma las instrucciones —a qué correo de Allianz escribir según el producto, con copia a integraciones@
    y el asunto "Trámite / Póliza / Nombre"— y quedan para que Ceci las autorice (Telegram o panel); recién ahí
    le salen al cliente por WhatsApp.
  - CANCELACIÓN: es delicada. No se le dan instrucciones al cliente: aviso a Ceci y al asesor para que lo contacte.
  - NOSOTROS (aumento/disminución de aportaciones, cambio de conducto de cobro): solo con la solicitud firmada.
    Si el cliente ya la mandó por WhatsApp, queda la solicitud en el panel y Ceci la abre con Allianz (con copia
    al ejecutivo del producto). Si no, se le pide al asesor que la consiga.

Siempre: la póliza se identifica en Notion Emisiones y el WhatsApp tiene que ser el del titular (si no,
cualquiera podría pedir un trámite sobre una póliza ajena).
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
ETAPA_INSTRUCCIONES = "instrucciones_tramite"
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


def _producto(poliza: str) -> str:
    """'PLU3-408444' → 'PLU3' (el prefijo de la póliza es el producto)."""
    return "".join(ch for ch in (poliza or "").upper() if ch.isalnum())[:4]


def _ticket(repo: Repositorio, d: dict, poliza: str, estado: str, **extra) -> int:
    return repo.crear_ticket({
        "poliza": poliza, "cliente_nombre": d.get("cliente_nombre"), "cliente_correo": d.get("cliente_correo"),
        "asesor_correo": d.get("asesor_correo"), "telefono_cliente": d.get("telefono_cliente"),
        "telefono_asesor": d.get("telefono_asesor"), "daf": d.get("daf_nombre"), "estado": estado,
        "delicado": False, "abierto_por": ABIERTO_POR, "proceso": "tramite", "identificado_por": "poliza",
        "producto": _producto(poliza), **extra})


def _params(t, cliente: str, poliza: str, etapa: str) -> dict:
    return {"ticket": "Solicitud", "tramite": t.nombre, "cliente": cliente, "etapa": etapa,
            "nombre": cliente.split(" ")[0], "poliza": poliza}


def _avisar_ceci(repo: Repositorio, tid: int, t, cliente: str, poliza: str, texto: str, etapa: str) -> None:
    if link_panel(tid):
        texto += f"\nPanel: {link_panel(tid)}"
    _encolar(repo, tid, "ceci", texto, etapa, 1, None, None, _params(t, cliente, poliza, etapa))


def solicitar(repo: Repositorio, tramite: str, poliza: str, wa_id: str, nota: Optional[str] = None,
              buscar: Optional[Buscador] = None, http=None) -> dict:
    t = por_clave((tramite or "").strip())
    if t is None:
        return _no("trámite desconocido",
                   "No tengo ese trámite en la lista. ¿Me cuentas qué necesitas cambiar en tu póliza?",
                   tramites=[x.clave for x in CATALOGO])
    poliza = (poliza or "").strip()
    if t.ruta == Ruta.CLIENTE_PORTAL:
        return _portal(repo, t, poliza, wa_id, buscar)
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
    poliza_ok = (d.get("poliza") or poliza).strip().upper()
    cliente = (d.get("cliente_nombre") or "el cliente").title()
    nota = (nota or "").strip()[:500] or None
    if t.delicado:
        return _cancelacion(repo, t, d, poliza_ok, cliente, nota)
    if t.ruta == Ruta.CLIENTE_MAIL:
        return _por_correo_del_cliente(repo, t, d, poliza_ok, cliente, nota)
    return _nosotros(repo, t, d, poliza_ok, cliente, nota, http)


# ─────────────────────────── portal ───────────────────────────
def _portal(repo: Repositorio, t, poliza: str, wa_id: str, buscar) -> dict:
    """El cliente lo hace solo en el portal: se le pasan los pasos y, si dio la póliza, se le avisa a Ceci."""
    ticket_id = None
    if poliza:
        ident = identificar(poliza=poliza, buscar=buscar)
        if ident.ok and mismo_telefono(wa_id, ident.datos.get("telefono_cliente")):
            d = ident.datos
            poliza_ok = (d.get("poliza") or poliza).strip().upper()
            cliente = (d.get("cliente_nombre") or "el cliente").title()
            ticket_id = _ticket(repo, d, poliza_ok, "resuelto", titulo_hilo=f"Portal: {t.nombre}")
            repo.agregar_evento(ticket_id, None, "solicitud_tommy",
                                f"Pidió por WhatsApp: {t.nombre} (se hace en el portal)"[:200])
            _avisar_ceci(repo, ticket_id, t, cliente, poliza_ok,
                         f"Tommy · {cliente} pidió por WhatsApp {t.nombre.lower()} de la póliza {poliza_ok}. Se hace "
                         f"desde el portal: ya le pasé los pasos.", ETAPA_AVISO)
    return _no("se hace en el portal", instrucciones_cliente(t), portal=True, ticket_id=ticket_id)


# ─────────────────────────── cancelación (delicada) ───────────────────────────
def _cancelacion(repo: Repositorio, t, d: dict, poliza: str, cliente: str, nota: Optional[str]) -> dict:
    """Ceci, 17/11: la cancelación que pide el cliente va a Ceci y al asesor; al cliente no se le dan pasos."""
    from app.tickets.engine import clave_cancelacion
    tid = _ticket(repo, d, poliza, "escalado_ceci", titulo_hilo=f"Cancelación pedida por WhatsApp · {poliza}")
    repo.actualizar_ticket(tid, delicado=True)
    repo.guardar_valor(clave_cancelacion(tid), "1")
    repo.agregar_evento(tid, None, "solicitud_tommy", f"Pidió por WhatsApp la cancelación de {poliza}"[:200])
    texto = f"Tommy · {cliente} pidió por WhatsApp cancelar su póliza {poliza}."
    if nota:
        texto += f" Escribió: {nota}"
    params = _params(t, cliente, poliza, "Cancelación")
    if d.get("telefono_asesor"):
        _encolar(repo, tid, "asesor", f"{texto} Contáctalo para ver qué necesita antes de que se cancele.",
                 ETAPA_AVISO, 1, str(d["telefono_asesor"]), None, params)
        _avisar_ceci(repo, tid, t, cliente, poliza, f"{texto} Ya le avisé al asesor.", ETAPA_AVISO)
    else:
        _avisar_ceci(repo, tid, t, cliente, poliza, f"{texto} ⚠️ Falta el teléfono del asesor en Notion: no se le "
                                                    f"avisó.", ETAPA_AVISO)
    return {"ok": True, "ticket_id": tid, "motivo": "cancelación: aviso a Ceci y al asesor", "delicado": True,
            "para_cliente": "Recibí tu solicitud. Tu asesor se va a poner en contacto contigo para ayudarte."}


# ─────────────────────────── lo pide el cliente por correo ───────────────────────────
def _por_correo_del_cliente(repo: Repositorio, t, d: dict, poliza: str, cliente: str, nota: Optional[str]) -> dict:
    """Instrucciones para que el cliente mande el correo a Allianz. Salen recién cuando Ceci las autoriza."""
    from app import config
    producto = _producto(poliza)
    tid = _ticket(repo, d, poliza, "abierto", titulo_hilo=f"{t.nombre} · {poliza}")
    repo.agregar_evento(tid, None, "solicitud_tommy", f"Pidió por WhatsApp: {t.nombre} (lo manda él por correo)"[:200])
    if not config.correo_clientes_allianz(producto):
        _avisar_ceci(repo, tid, t, cliente, poliza,
                     f"Tommy · {cliente} pidió por WhatsApp {t.nombre.lower()} de la póliza {poliza}. Ese producto no "
                     f"tiene correo de clientes cargado: atiéndelo tú.", ETAPA_AVISO)
        return {"ok": True, "ticket_id": tid, "motivo": "producto sin correo de clientes: a Ceci",
                "para_cliente": f"Ya le pasé tu solicitud de {t.nombre.lower()} al equipo. Te escribimos por aquí."}
    nombre = cliente.split(" ")[0]
    texto = instrucciones_cliente(t, nombre, poliza, cliente, producto)
    accion_id = repo.crear_accion(tid, "instruir_tramite", "wati", {
        "rol": "cliente", "numero": str(d.get("telefono_cliente") or ""), "destinatario": None, "mensaje": texto,
        "titulo": "Instrucciones para el cliente", "etapa": ETAPA_INSTRUCCIONES, "ronda": 1,
        "params": _params(t, cliente, poliza, "Instrucciones del trámite"), "nota_cliente": nota,
    }, estado="pendiente_ceci")
    return {"ok": True, "ticket_id": tid, "accion_id": accion_id, "motivo": "instrucciones para que Ceci las autorice",
            "para_cliente": f"¡Listo! En un momento te paso por aquí cómo pedir tu {t.nombre.lower()} a Allianz."}


# ─────────────────────────── lo hacemos nosotros (con la solicitud firmada) ───────────────────────────
def _nosotros(repo: Repositorio, t, d: dict, poliza: str, cliente: str, nota: Optional[str], http) -> dict:
    asunto = AT.asunto(t.clave, poliza, d.get("cliente_nombre"))
    previo = AT._abierto_igual(repo, asunto)
    if previo:
        return {"ok": True, "ya_existia": True, "ticket_id": previo["id"], "motivo": "ya hay uno igual en curso",
                "para_cliente": "Ya tenemos tu solicitud en curso. En cuanto Allianz la registre te llega "
                                "el número de seguimiento por aquí."}
    recibidos = 0
    if t.requisitos:
        from app.wati.archivos import archivos_del_cliente
        r = archivos_del_cliente(d.get("telefono_cliente"), dias=DIAS_ARCHIVOS, http=http)
        recibidos = len(r.get("archivos") or [])
        if recibidos < len(t.requisitos):
            return _falta_firma(repo, t, d, poliza, cliente, recibidos)
    tid = _ticket(repo, d, poliza, ESTADO, asunto_hilo=asunto, titulo_hilo=f"[EXT] {asunto}")
    repo.guardar_valor(clave_valor(tid), json.dumps(
        {"tramite": t.clave, "nota": nota, "archivos": recibidos, "dias": DIAS_ARCHIVOS}, ensure_ascii=False))
    repo.agregar_evento(tid, None, "solicitud_tommy", f"El cliente pidió por WhatsApp: {t.nombre}"[:200])
    texto = (f"Tommy · {cliente} pidió por WhatsApp el {t.nombre.lower()} de la póliza {poliza}"
             f"{f' y mandó {recibidos} archivo(s)' if recibidos else ''}. Revísalo en el panel y ábrelo con Allianz.")
    if nota:
        texto += f" Nota del cliente: {nota}"
    _avisar_ceci(repo, tid, t, cliente, poliza, texto, ETAPA_AVISO)
    return {"ok": True, "ticket_id": tid, "motivo": "solicitud creada: espera a Ceci",
            "para_cliente": f"¡Listo! Ya dejé tu solicitud de {t.nombre.lower()} con el equipo. La revisamos y "
                            f"la enviamos a Allianz; cuando la registren te llega por aquí el número de seguimiento."}


def _falta_firma(repo: Repositorio, t, d: dict, poliza: str, cliente: str, recibidos: int) -> dict:
    """Sin la solicitud firmada no se abre: se le pide al asesor que la consiga (Ceci, 17/11)."""
    from app import config
    req = " y ".join(t.requisitos)
    tid = _ticket(repo, d, poliza, "esperando_cliente", titulo_hilo=f"{t.nombre} · falta la solicitud firmada")
    repo.agregar_evento(tid, None, "solicitud_tommy",
                        f"Pidió por WhatsApp: {t.nombre} · falta la solicitud firmada ({recibidos} archivo(s))"[:200])
    texto = (f"Tommy · {cliente} pidió {t.nombre.lower()} de la póliza {poliza}, pero falta {req}. Consíguela y "
             f"mándala por WhatsApp a Tommy o por correo a {config.CC_TRAMITE_CLIENTE}: con eso abrimos el trámite.")
    params = _params(t, cliente, poliza, "Falta la solicitud firmada")
    if d.get("telefono_asesor"):
        _encolar(repo, tid, "asesor", texto, ETAPA_AVISO, 1, str(d["telefono_asesor"]), None, params)
    else:
        _avisar_ceci(repo, tid, t, cliente, poliza,
                     f"{texto} ⚠️ Falta el teléfono del asesor en Notion: no se le avisó.", ETAPA_AVISO)
    return _no(f"falta la solicitud firmada ({recibidos} de {len(t.requisitos)})",
               f"Para el {t.nombre.lower()} necesitamos {req}. Tu asesor te va a contactar para ayudarte con eso; "
               f"si ya la tienes, mándamela por aquí como foto o PDF.",
               requisitos=list(t.requisitos), recibidos=recibidos, ticket_id=tid)


def descartar(repo: Repositorio, ticket_id: int, usuario: str = "ceci", motivo: Optional[str] = None) -> dict:
    t = repo.obtener_ticket(ticket_id)
    if not t or t.get("estado") != ESTADO:
        return {"ok": False, "motivo": "no es una solicitud pendiente"}
    repo.actualizar_ticket(ticket_id, estado="resuelto")
    repo.agregar_evento(ticket_id, None, "solicitud_descartada",
                        f"Descartada por {usuario}{': ' + motivo.strip() if motivo and motivo.strip() else ''}"[:200])
    return {"ok": True, "motivo": "solicitud descartada"}
