"""Etapa 3 (A) — abrir un trámite ante Allianz desde el panel.

Hoy los trámites se abren a mano desde integraciones@ y Allianz los responde ahí (el motor no los
ve). Desde el panel, Ceci elige póliza + trámite (+ nota y adjuntos) y el correo sale de hola@:

  1. Se identifica la póliza en Notion Emisiones (exacta). Sin coincidencia → no se abre (no se
     adivina a quién avisar después).
  2. Se crea el ticket `proceso=tramite`, ya identificado, con el asunto fijo
     `<Trámite> - Póliza <X> - <Cliente>`, y se encola el correo a Allianz (`abrir_tramite`,
     canal email). Sale en el próximo ciclo del worker, respetando DRY_RUN.
  3. Allianz abre su ticket y el acuse llega como "[EXT] <nuestro asunto>": `enlazar()` lo
     engancha a este ticket por el asunto. Desde ahí sigue el seguimiento normal de trámites
     (Etapa 2): el acuse avisa a los 3 con el n° de ticket, el requerimiento arranca el recordatorio, etc.

Al abrir NO se avisa al cliente: el aviso sale con el acuse, que ya trae el n° de ticket.
"""
from __future__ import annotations

import base64
import re
import unicodedata
from typing import Optional

from app import config
from app.db.repo import Repositorio
from app.enriquecimiento.identificar import Buscador, identificar
from app.tramites import CATALOGO, por_clave

TIPO_ACCION = "abrir_tramite"
ABIERTO_POR = "babilonia"
MAX_ADJUNTOS = 5
MAX_BYTES_ADJUNTOS = 8 * 1024 * 1024   # Gmail acepta 25 MB; nos quedamos lejos (va en la base)
_CERRADOS = ("resuelto", "cerrado")


def catalogo() -> list[dict]:
    """Trámites para el selector del panel. Los que hacemos nosotros por correo van primero."""
    return [{"clave": t.clave, "nombre": t.nombre, "nosotros": t.ruta.value == "nosotros_mail",
             "requisitos": list(t.requisitos)}
            for t in sorted(CATALOGO, key=lambda t: t.ruta.value != "nosotros_mail")]


def requisitos_de(tramite: str) -> tuple[str, ...]:
    """Lo que tiene que ir adjunto (cambio de conducto: formato + INE vigente). Texto libre: nada."""
    t = por_clave((tramite or "").strip())
    return t.requisitos if t else ()


def nombre_tramite(tramite: str) -> str:
    """Clave del catálogo → nombre; si no es del catálogo, el texto libre que escribió Ceci."""
    t = por_clave((tramite or "").strip())
    return t.nombre if t else re.sub(r"\s+", " ", (tramite or "").strip())[:80]


def asunto(tramite: str, poliza: str, cliente: Optional[str]) -> str:
    """Asunto fijo: Allianz titula su ticket "[EXT] <asunto>" y así lo reconocemos al volver.
    Separador ASCII (" - ") para que no se deforme en el sistema de Allianz."""
    partes = [nombre_tramite(tramite), f"Póliza {poliza.strip().upper()}"]
    if cliente:
        partes.append(re.sub(r"\s+", " ", cliente.strip()).title())
    return " - ".join(partes)


def cuerpo(tramite: str, poliza: str, cliente: Optional[str], nota: Optional[str],
           adjuntos: list[dict]) -> str:
    """Texto fijo (sin IA). La nota de Ceci va tal cual."""
    lineas = ["Buen día,", "",
              f"Solicitamos su apoyo con el trámite de {nombre_tramite(tramite).lower()} "
              f"para la póliza {poliza.strip().upper()}" + (f", contratante {cliente.strip().title()}." if cliente else "."),
              ]
    if nota and nota.strip():
        lineas += ["", nota.strip()]
    if adjuntos:
        lineas += ["", "Adjuntamos: " + ", ".join(a["nombre"] for a in adjuntos) + "."]
    lineas += ["", "Quedamos atentos.", "Babilonia"]
    return "\n".join(lineas)


def destino(tramite: str) -> str:
    """Directorio Allianz por trámite (ALLIANZ_DIRECTORIO); si no está, ALLIANZ_DEST."""
    return config.directorio_allianz((tramite or "").strip())


def _norm(s: Optional[str]) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^\s*\[ext\]\s*", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def mismo_asunto(nuestro: Optional[str], titulo_allianz: Optional[str]) -> bool:
    """El título de Allianz es "[EXT] <nuestro asunto>"; puede venir recortado o sin acentos."""
    a, b = _norm(nuestro), _norm(titulo_allianz)
    if len(a) < 12 or len(b) < 12:
        return a == b and bool(a)
    # Recorte por palabra entera: "… oppt 1" no es el principio de "… oppt 12 …".
    return a == b or (a + " ").startswith(b + " ") or (b + " ").startswith(a + " ")


def _limpiar_adjuntos(adjuntos: Optional[list[dict]]) -> list[dict]:
    """[{nombre, tipo, base64}] → validados. Error de usuario → ValueError con el motivo."""
    salida, total = [], 0
    for a in adjuntos or []:
        nombre = re.sub(r"[\\/:*?\"<>|]+", "_", (a.get("nombre") or "").strip())[:120]
        if not nombre:
            raise ValueError("un adjunto no tiene nombre")
        try:
            datos = base64.b64decode(a.get("base64") or "", validate=True)
        except Exception as ex:  # noqa: BLE001
            raise ValueError(f"el adjunto {nombre} no se pudo leer") from ex
        if not datos:
            raise ValueError(f"el adjunto {nombre} está vacío")
        total += len(datos)
        salida.append({"nombre": nombre, "tipo": a.get("tipo") or "application/octet-stream",
                       "base64": base64.b64encode(datos).decode()})
    if len(salida) > MAX_ADJUNTOS:
        raise ValueError(f"máximo {MAX_ADJUNTOS} adjuntos")
    if total > MAX_BYTES_ADJUNTOS:
        raise ValueError(f"los adjuntos pasan de {MAX_BYTES_ADJUNTOS // (1024 * 1024)} MB")
    return salida


def preparar(tramite: str, poliza: str, nota: Optional[str] = None,
             adjuntos: Optional[list[dict]] = None, buscar: Optional[Buscador] = None) -> dict:
    """Vista previa: identifica la póliza y arma el correo. No guarda nada.
    Devuelve {ok, motivo, asunto, cuerpo, destino, cliente, asesor, identificacion}."""
    tramite, poliza = (tramite or "").strip(), (poliza or "").strip()
    if not tramite or not nombre_tramite(tramite):
        return {"ok": False, "motivo": "falta el trámite"}
    if not poliza:
        return {"ok": False, "motivo": "falta la póliza"}
    try:
        limpios = _limpiar_adjuntos(adjuntos)
    except ValueError as ex:
        return {"ok": False, "motivo": str(ex)}
    ident = identificar(poliza=poliza, buscar=buscar)
    if not ident.ok:
        return {"ok": False, "motivo": f"No se pudo identificar la póliza {poliza.upper()} en Notion "
                                       f"Emisiones ({ident.motivo}). Revisala o abrí el trámite a mano.",
                "identificacion": ident.estado}
    requisitos = requisitos_de(tramite)
    if len(limpios) < len(requisitos):
        return {"ok": False, "motivo": f"Este trámite lleva adjuntos {' y '.join(requisitos)}. "
                                       f"Adjúntalos para poder abrirlo."}
    d = ident.datos
    cliente = d.get("cliente_nombre")
    poliza_ok = (d.get("poliza") or poliza).strip().upper()
    return {
        "ok": True, "motivo": "listo para abrir",
        "tramite": nombre_tramite(tramite), "poliza": poliza_ok,
        "asunto": asunto(tramite, poliza_ok, cliente),
        "cuerpo": cuerpo(tramite, poliza_ok, cliente, nota, limpios),
        "destino": destino(tramite) or None,
        "cliente": cliente, "asesor": d.get("asesor_nombre") or d.get("asesor_correo"),
        "adjuntos": [a["nombre"] for a in limpios],
        "_datos": d, "_adjuntos": limpios,
    }


def archivos_whatsapp(poliza: str, dias: int = 14, buscar: Optional[Buscador] = None, http=None) -> dict:
    """Etapa 3B: las fotos y documentos que el cliente de esta póliza mandó por WhatsApp en los
    últimos `dias` (transferencia, estado de cuenta), para que Ceci elija cuáles adjuntar."""
    from app.wati.archivos import archivos_del_cliente
    poliza = (poliza or "").strip()
    if not poliza:
        return {"ok": False, "motivo": "falta la póliza", "archivos": []}
    ident = identificar(poliza=poliza, buscar=buscar)
    if not ident.ok:
        return {"ok": False, "motivo": f"No se pudo identificar la póliza {poliza.upper()} en Notion "
                                       f"Emisiones ({ident.motivo}).", "archivos": []}
    tel = ident.datos.get("telefono_cliente")
    r = archivos_del_cliente(tel, dias=max(1, min(int(dias or 14), 60)), http=http)
    digitos = "".join(ch for ch in str(tel or "") if ch.isdigit())
    return {**r, "cliente": ident.datos.get("cliente_nombre"),
            "telefono": f"…{digitos[-4:]}" if digitos else None}


def _abierto_igual(repo: Repositorio, asunto_nuevo: str) -> Optional[dict]:
    for t in repo.listar_tramites_abiertos():
        if t.get("estado") not in _CERRADOS and mismo_asunto(t.get("asunto_hilo"), asunto_nuevo):
            return t
    return None


def abrir(repo: Repositorio, tramite: str, poliza: str, nota: Optional[str] = None,
          adjuntos: Optional[list[dict]] = None, usuario: str = "ceci",
          buscar: Optional[Buscador] = None, solicitud_id: Optional[int] = None) -> dict:
    """Crea el ticket del trámite y encola el correo a Allianz. Devuelve {ok, motivo, ticket_id, …}.
    Con `solicitud_id` (la que dejó Tommy, Etapa 3B), usa ese ticket en vez de crear otro."""
    p = preparar(tramite, poliza, nota, adjuntos, buscar)
    if not p["ok"]:
        return p
    if solicitud_id is not None:
        sol = repo.obtener_ticket(solicitud_id)
        if not sol or sol.get("estado") != "solicitud":
            return {"ok": False, "motivo": "Esa solicitud ya no está pendiente."}
    previo = _abierto_igual(repo, p["asunto"])
    if previo and previo["id"] != solicitud_id:
        return {"ok": False, "motivo": f"Ya hay un trámite abierto igual (ticket interno {previo['id']}).",
                "ticket_id": previo["id"], "duplicado": True}
    d = p["_datos"]
    datos_ticket = {
        "poliza": p["poliza"], "cliente_nombre": d.get("cliente_nombre"),
        "cliente_correo": d.get("cliente_correo"), "asesor_correo": d.get("asesor_correo"),
        "telefono_cliente": d.get("telefono_cliente"), "telefono_asesor": d.get("telefono_asesor"),
        "daf": d.get("daf_nombre"), "estado": "abierto", "delicado": False,
        "abierto_por": ABIERTO_POR, "asunto_hilo": p["asunto"], "titulo_hilo": f"[EXT] {p['asunto']}",
        "proceso": "tramite", "identificado_por": "poliza",
    }
    if solicitud_id is not None:
        ticket_id = solicitud_id
        datos_ticket["abierto_por"] = "tommy"
        repo.actualizar_ticket(ticket_id, **datos_ticket)
    else:
        ticket_id = repo.crear_ticket(datos_ticket)
    repo.agregar_evento(ticket_id, None, "tramite_abierto",
                        f"Trámite abierto desde el panel por {usuario}: {p['asunto']}"[:200])
    accion_id = repo.crear_accion(ticket_id, TIPO_ACCION, "email", {
        "rol": "allianz", "destinatario": p["destino"], "asunto": p["asunto"], "cuerpo": p["cuerpo"],
        "mensaje": f"Abrir trámite: {p['asunto']}", "tramite": p["tramite"], "abierto_por": usuario,
        "adjuntos": p["_adjuntos"],
    })
    return {"ok": True, "motivo": "trámite abierto: el correo sale en el próximo ciclo",
            "ticket_id": ticket_id, "accion_id": accion_id, "asunto": p["asunto"],
            "destino": p["destino"], "sin_destino": not p["destino"]}


def enlazar(repo: Repositorio, etapa: Optional[dict]) -> Optional[dict]:
    """El acuse de Allianz ("[EXT] <nuestro asunto>") todavía no tiene ticket nuestro con ese
    número: si coincide con un trámite que abrimos desde el panel, es ese ticket."""
    if not etapa or etapa.get("proceso") != "tramite" or not etapa.get("titulo_hilo"):
        return None
    try:
        candidatos = repo.listar_tramites_abiertos(sin_ticket=True)
    except Exception:  # noqa: BLE001 — base sin la migración de etapas: no hay trámites nuestros
        return None
    # Una solicitud de Tommy que Ceci todavía no abrió no se mandó: no puede tener acuse.
    abiertos = [t for t in candidatos if t.get("estado") not in (*_CERRADOS, "solicitud")]
    exactos = [t for t in abiertos if _norm(t.get("asunto_hilo")) == _norm(etapa["titulo_hilo"])]
    if exactos:
        return exactos[0]
    # Título recortado: solo si apunta a un único trámite (si no, Ceci lo engancha a mano).
    parecidos = [t for t in abiertos if mismo_asunto(t.get("asunto_hilo"), etapa["titulo_hilo"])]
    return parecidos[0] if len(parecidos) == 1 else None
