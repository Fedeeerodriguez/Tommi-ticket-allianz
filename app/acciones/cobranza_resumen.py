"""Resumen diario de cobranza (COBRANZA_MODO=resumen) — un mensaje por asesor en vez de uno por aviso.

En integraciones@ llegan ~2.400 "Notificación de Cobranza" por mes, en ráfagas: 585 el domingo 08/11, 170 el
sábado 14/11. Con un WhatsApp al asesor y otro a Ceci por cada aviso (modo "aviso", el de hola@), eso son
cientos de mensajes en un día. En modo resumen:

  - cada aviso queda guardado como una acción `en_resumen`, con sus datos. No sale nada en ese momento.
    Los avisos de la misma póliza dentro de COBRANZA_AGRUPAR_DIAS van al mismo ticket (Allianz reintenta el
    cargo y avisa cada vez);
  - una vez por día hábil, a COBRANZA_RESUMEN_HORA_MX, `armar_resumen` junta lo acumulado desde el último
    resumen (el lunes incluye el fin de semana):
      · a cada asesor, UN WhatsApp con todos sus clientes con cargo rechazado. Pasa por el despacho, así
        que respeta DRY_RUN, el interruptor de cobranza y MOTOR_ETAPAS_ROLES;
      · a Ceci y Yans (COBRANZA_RESUMEN_EMAILS), UN correo con la lista completa, incluidas las pólizas que
        no se pudieron identificar en Notion. Sale solo con el envío real de cobranza prendido; si no, queda
        la vista previa en el panel.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import config
from app.db.repo import Repositorio

log = logging.getLogger(__name__)

EN_RESUMEN = "en_resumen"
RESUMIDA = "resumida"
TIPO = "resumen_cobranza"
CLAVE_PREVIA = "cobranza_resumen:ultimo"
MEXICO = timezone(timedelta(hours=-6))
MAX_CLIENTES_WHATSAPP = 6   # una variable de plantilla de WhatsApp tiene un largo máximo: el resto, "y N más"


def activo() -> bool:
    return (config.COBRANZA_MODO or "").strip().lower() == "resumen"


def guardar_aviso(repo: Repositorio, ticket_id: int, d: dict, cliente: str, plan: str, datos: dict,
                  omitidos: list[str], correo_id: Optional[int]) -> int:
    """Deja el aviso esperando el resumen del día (estado `en_resumen`: el despacho no lo toca)."""
    payload = {"rol": "resumen", "etapa": "cargo_rechazado", "poliza": d["poliza"], "producto": d["producto"],
               "plan": plan, "cliente": cliente, "detalle": d, "omitidos": omitidos, "correo_id": correo_id,
               "asesor_numero": str(datos["telefono_asesor"]) if datos.get("telefono_asesor") else None,
               "asesor_correo": datos.get("asesor_correo"), "asesor_nombre": datos.get("asesor_nombre")}
    return repo.crear_accion(ticket_id, TIPO, "resumen", payload, estado=EN_RESUMEN)


def _payload(a: dict) -> dict:
    import json
    p = a.get("payload")
    return json.loads(p) if isinstance(p, str) else (p or {})


def _por_poliza(acciones: list[dict]) -> list[dict]:
    """Un renglón por póliza (el aviso más nuevo manda; se cuentan los intentos)."""
    filas: "OrderedDict[str, dict]" = OrderedDict()
    for a in acciones:  # vienen de la más vieja a la más nueva
        p = _payload(a)
        f = filas.pop(p.get("poliza") or f"accion-{a['id']}", None)
        intentos = (f["intentos"] if f else 0) + 1
        filas[p.get("poliza") or f"accion-{a['id']}"] = {**p, "ticket_id": a["ticket_id"], "intentos": intentos,
                                                          "acciones": (f["acciones"] if f else []) + [a["id"]]}
    return list(filas.values())


def agrupar(filas: list[dict]) -> tuple["OrderedDict[str, list[dict]]", list[dict]]:
    """(por número de WhatsApp del asesor, sin asesor para avisar)."""
    grupos: "OrderedDict[str, list[dict]]" = OrderedDict()
    sin_asesor = []
    for f in filas:
        if f.get("asesor_numero"):
            grupos.setdefault(f["asesor_numero"], []).append(f)
        else:
            sin_asesor.append(f)
    return grupos, sin_asesor


def por_nombre(grupos: "OrderedDict[str, list[dict]]") -> "OrderedDict[str, list[dict]]":
    """Los mismos grupos con el nombre (o correo) del asesor, para que el correo del equipo se lea."""
    salida: "OrderedDict[str, list[dict]]" = OrderedDict()
    for numero, fs in grupos.items():
        f0 = fs[0]
        salida[f0.get("asesor_nombre") or f0.get("asesor_correo") or f"Asesor {numero}"] = fs
    return salida


def _renglon(f: dict, largo: bool) -> str:
    d = f.get("detalle") or {}
    partes = [f"{f.get('cliente') or 'Cliente sin identificar'} ({f.get('plan') or d.get('producto')} {f['poliza']})"]
    if d.get("monto"):
        partes.append(d["monto"])
    if d.get("motivo"):
        partes.append(d["motivo"].lower())
    if largo and d.get("proximo_intento"):
        partes.append(f"próximo intento {d['proximo_intento']}")
    if f["intentos"] > 1:
        partes.append(f"{f['intentos']} avisos")
    return partes[0] + (": " + ", ".join(partes[1:]) if len(partes) > 1 else "")


def texto_asesor(filas: list[dict]) -> str:
    n = len(filas)
    lista = "; ".join(_renglon(f, largo=False) for f in filas[:MAX_CLIENTES_WHATSAPP])
    if n > MAX_CLIENTES_WHATSAPP:
        lista += f"; y {n - MAX_CLIENTES_WHATSAPP} más (te los pasa Ceci)"
    quien = "1 cliente tuyo tuvo" if n == 1 else f"{n} clientes tuyos tuvieron"
    return (f"Cobranza · {quien} un cargo rechazado por Allianz: {lista}. Contacta a cada uno para que tenga el "
            f"monto disponible o se ponga al corriente. A los 60 días de atraso Allianz puede cancelar el plan.")


def texto_equipo(grupos: "OrderedDict[str, list[dict]]", sin_asesor: list[dict], hoy: str) -> tuple[str, str]:
    total = sum(len(v) for v in grupos.values()) + len(sin_asesor)
    asunto = f"[Tommi] Cobranza {hoy}: {total} póliza{'s' if total != 1 else ''} con cargo rechazado"
    lineas = [f"Cargos rechazados desde el último resumen: {total} pólizas, {len(grupos)} asesores avisados.", ""]
    for asesor, filas in grupos.items():
        lineas.append(f"{asesor} ({len(filas)}):")
        lineas += [f"  • {_renglon(f, largo=True)}" for f in filas]
        lineas.append("")
    if sin_asesor:
        lineas.append(f"Sin asesor para avisar ({len(sin_asesor)}): hay que revisarlas a mano.")
        for f in sin_asesor:
            motivo = "; ".join(f.get("omitidos") or []) or "sin teléfono del asesor"
            lineas.append(f"  • {_renglon(f, largo=True)} — {motivo}")
        lineas.append("")
    lineas.append("A los 60 días de atraso Allianz puede cancelar el plan.\n— Tommi")
    return asunto, "\n".join(lineas)


def armar_resumen(repo: Repositorio, ahora: Optional[datetime] = None, emisor=None) -> dict:
    """Junta los avisos `en_resumen`, encola un WhatsApp por asesor y manda (o deja en vista previa) el correo
    del equipo. Los avisos quedan `resumida`. Devuelve qué hizo."""
    from app.acciones.motor_etapas import TIPO_ACCION, rol_activo
    from app.envio import interruptor
    ahora = ahora or datetime.now(timezone.utc)
    pendientes = repo.listar_acciones(estado=EN_RESUMEN)
    if not pendientes:
        return {"polizas": 0, "asesores": 0, "motivo": "nada acumulado"}
    filas = _por_poliza(pendientes)
    grupos, sin_asesor = agrupar(filas)

    encoladas = []
    for numero, fs in grupos.items():
        if not rol_activo("asesor"):
            break
        ultimo = fs[-1]
        n = len(fs)
        params = {"ticket": "Cobranza", "tramite": "Cargos rechazados", "etapa": "Cargo rechazado",
                  "cliente": ultimo.get("cliente") if n == 1 else f"{n} clientes", "nombre": "",
                  "poliza": ultimo["poliza"] if n == 1 else f"{n} pólizas"}
        aid = repo.crear_accion(ultimo["ticket_id"], TIPO_ACCION["asesor"], "wati", {
            "rol": "asesor", "numero": numero, "destinatario": None, "mensaje": texto_asesor(fs),
            "etapa": "cargo_rechazado", "ronda": 1, "params": params, "resumen_de": [p["poliza"] for p in fs]})
        encoladas.append(aid)

    hoy = ahora.astimezone(MEXICO).strftime("%d/%m")
    asunto, cuerpo = texto_equipo(por_nombre(grupos), sin_asesor, hoy)
    destinos = [x for x in config.COBRANZA_RESUMEN_EMAILS if x]
    correo = {"asunto": asunto, "cuerpo": cuerpo, "para": destinos, "enviado": False}
    if destinos and interruptor.es_real(repo, "cobranza"):
        from app.resumen_equipo import _emisor_real
        res = (emisor or _emisor_real()).enviar(destinos, asunto, cuerpo)
        correo["enviado"] = bool(res.get("ok") and not res.get("simulado"))
        correo["resultado"] = {k: res.get(k) for k in ("ok", "error", "simulado")}
    import json
    repo.guardar_valor(CLAVE_PREVIA, json.dumps({"en": ahora.isoformat(timespec="seconds"), **correo},
                                                 ensure_ascii=False))

    for f in filas:
        for aid in f["acciones"]:
            repo.actualizar_accion(aid, RESUMIDA, {"resumen": ahora.isoformat(timespec="seconds")})
    salida = {"polizas": len(filas), "avisos": len(pendientes), "asesores": len(grupos),
              "sin_asesor": len(sin_asesor), "whatsapp_encolados": len(encoladas), "correo_equipo": correo["enviado"]}
    log.info("cobranza_resumen: %s", salida)
    return salida
