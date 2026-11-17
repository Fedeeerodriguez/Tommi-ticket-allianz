"""Resumen diario de cobranza (COBRANZA_MODO=resumen) — un mensaje por asesor en vez de uno por aviso.

En integraciones@ llegan ~2.400 "Notificación de Cobranza" por mes, en ráfagas: 585 el domingo 08/11, 170 el
sábado 14/11. Con un WhatsApp al asesor y otro a Ceci por cada aviso (modo "aviso", el de hola@), eso son
cientos de mensajes en un día. En modo resumen:

  - cada aviso queda guardado como una acción `en_resumen`, con sus datos. No sale nada en ese momento.
    Los avisos de la misma póliza dentro de COBRANZA_AGRUPAR_DIAS van al mismo ticket (Allianz reintenta el
    cargo y avisa cada vez);
  - una vez por día hábil, a COBRANZA_RESUMEN_HORA_MX, `armar_resumen` junta lo acumulado desde el último
    resumen (el lunes incluye el fin de semana):
      · a cada asesor, UN WhatsApp (plantilla propia, WATI_PLANTILLA_COBRANZA) con sus clientes con cargo
        rechazado, los de más días de atraso primero: los 6 primeros y "consulta el resto con Ceci" (Ceci, 17/11).
        Pasa por el despacho, así que respeta DRY_RUN, el interruptor de cobranza y MOTOR_ETAPAS_ROLES;
      · a Ceci, UN WhatsApp con las pólizas sin asesor para avisar (no están en Notion o falta el teléfono),
        para que las asigne ella o Jime;
      · a Ceci y Yans (COBRANZA_RESUMEN_EMAILS), UN correo con la lista completa, incluidas las pólizas que
        no se pudieron identificar en Notion. Sale solo con el envío real de cobranza prendido; si no, queda
        la vista previa en el panel.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app import config
from app.db.repo import Repositorio

log = logging.getLogger(__name__)

EN_RESUMEN = "en_resumen"
RESUMIDA = "resumida"
TIPO = "resumen_cobranza"
CLAVE_PREVIA = "cobranza_resumen:ultimo"
MEXICO = timezone(timedelta(hours=-6))
MAX_CLIENTES_WHATSAPP = 6   # los 6 con más atraso; el resto, "consulta el resto con Ceci" (Ceci, 17/11)
INDICACION_ASESOR = "Contacta a cada uno para que tenga el monto disponible o se ponga al corriente."
INDICACION_CECI = "No encontré a quién avisarle: asígnalas en Notion o avísale tú al asesor."

_MESES = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                      "septiembre", "octubre", "noviembre", "diciembre"), 1)}
_RE_FECHA = re.compile(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", re.I)


def fecha_es(texto: Optional[str]) -> Optional[date]:
    """'12 de noviembre de 2026' → date(2026, 11, 12). None si no se entiende."""
    m = _RE_FECHA.search(texto or "")
    if not m:
        return None
    mes = _MESES.get(m.group(2).lower().replace("setiembre", "septiembre"))
    try:
        return date(int(m.group(3)), mes, int(m.group(1))) if mes else None
    except ValueError:
        return None


def _mas_vieja(*fechas: Optional[str]) -> Optional[str]:
    validas = [f for f in fechas if f]
    return min(validas) if validas else None


def primer_intento_de(repo: Repositorio, ticket_id: int) -> Optional[str]:
    """La fecha (ISO) del primer cargo rechazado ya guardado en ese ticket de cobranza, de resúmenes anteriores
    incluidos: es desde cuándo cuenta el atraso cuando Allianz reintenta."""
    return _mas_vieja(*(_payload(a).get("primer_intento") for a in repo.listar_acciones(ticket_id=ticket_id)
                        if a.get("tipo_accion") == TIPO))


def activo() -> bool:
    return (config.COBRANZA_MODO or "").strip().lower() == "resumen"


def guardar_aviso(repo: Repositorio, ticket_id: int, d: dict, cliente: str, plan: str, datos: dict,
                  omitidos: list[str], correo_id: Optional[int], primer_intento: Optional[str] = None) -> int:
    """Deja el aviso esperando el resumen del día (estado `en_resumen`: el despacho no lo toca).
    `primer_intento`: el primer cargo rechazado de la póliza que ya se conocía (reintentos de Allianz)."""
    este = fecha_es(d.get("fecha_intento"))
    payload = {"primer_intento": _mas_vieja(primer_intento, este.isoformat() if este else None),"rol": "resumen", "etapa": "cargo_rechazado", "poliza": d["poliza"], "producto": d["producto"],
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
        primero = _mas_vieja(f.get("primer_intento") if f else None, p.get("primer_intento"))
        filas[p.get("poliza") or f"accion-{a['id']}"] = {**p, "ticket_id": a["ticket_id"], "intentos": intentos,
                                                          "primer_intento": primero,
                                                          "acciones": (f["acciones"] if f else []) + [a["id"]]}
    return list(filas.values())


def dias_atraso(f: dict, hoy: date) -> Optional[int]:
    """Días desde el primer cargo rechazado que conocemos de la póliza. Allianz no manda la fecha de vencimiento:
    el primer intento fallido es la mejor aproximación."""
    if not f.get("primer_intento"):
        return None
    try:
        return max(0, (hoy - date.fromisoformat(f["primer_intento"])).days)
    except ValueError:
        return None


def ordenar(filas: list[dict], hoy: date) -> list[dict]:
    """Más días de atraso primero; las que no traen fecha, al final (en el orden en que llegaron)."""
    for f in filas:
        f["dias_atraso"] = dias_atraso(f, hoy)
    return sorted(filas, key=lambda f: -(f["dias_atraso"] if f["dias_atraso"] is not None else -1))


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
    if f.get("dias_atraso") is not None:
        partes.append(f"{f['dias_atraso']} día{'s' if f['dias_atraso'] != 1 else ''} de atraso")
    if d.get("monto"):
        partes.append(d["monto"])
    if d.get("motivo"):
        partes.append(d["motivo"].lower())
    if largo and d.get("proximo_intento"):
        partes.append(f"próximo intento {d['proximo_intento']}")
    if f["intentos"] > 1:
        partes.append(f"{f['intentos']} avisos")
    return partes[0] + (": " + ", ".join(partes[1:]) if len(partes) > 1 else "")


def variables(filas: list[dict], para: str = "asesor") -> dict[str, str]:
    """Las 3 variables de la plantilla de cobranza: {{cantidad}} {{clientes}} {{indicacion}}.
    Las filas ya vienen ordenadas por atraso (ver `ordenar`): van las 6 primeras y el resto se consulta con Ceci."""
    n = len(filas)
    lista = "; ".join(_renglon(f, largo=False) for f in filas[:MAX_CLIENTES_WHATSAPP])
    if n > MAX_CLIENTES_WHATSAPP:
        resto = n - MAX_CLIENTES_WHATSAPP
        lista += (f"; y {resto} más: consulta el resto con Ceci" if para == "asesor"
                  else f"; y {resto} más en el correo de cobranza")
    if para == "asesor":
        cantidad = "1 cliente tuyo tuvo" if n == 1 else f"{n} clientes tuyos tuvieron"
    else:
        cantidad = "1 póliza sin asesor para avisar tuvo" if n == 1 else f"{n} pólizas sin asesor para avisar tuvieron"
    return {"cantidad": cantidad, "clientes": lista,
            "indicacion": INDICACION_ASESOR if para == "asesor" else INDICACION_CECI}


def texto_plantilla(v: dict[str, str]) -> str:
    """El mensaje tal como lo arma la plantilla WATI_PLANTILLA_COBRANZA (para el panel y la vista previa)."""
    return (f"Cobranza Allianz · {v['cantidad']} un cargo rechazado: {v['clientes']}. {v['indicacion']} "
            f"A los 60 días de atraso Allianz puede cancelar el plan.")


def texto_asesor(filas: list[dict]) -> str:
    return texto_plantilla(variables(filas, "asesor"))


def texto_equipo(grupos: "OrderedDict[str, list[dict]]", sin_asesor: list[dict], hoy: str) -> tuple[str, str]:
    total = sum(len(v) for v in grupos.values()) + len(sin_asesor)
    asunto = f"[Tommi] Cobranza {hoy}: {total} póliza{'s' if total != 1 else ''} con cargo rechazado"
    lineas = [f"Cargos rechazados desde el último resumen: {total} pólizas, {len(grupos)} asesores avisados. "
              f"Cada lista va de más a menos días de atraso.", ""]
    for asesor, filas in grupos.items():
        lineas.append(f"{asesor} ({len(filas)}):")
        lineas += [f"  • {_renglon(f, largo=True)}" for f in filas]
        lineas.append("")
    if sin_asesor:
        lineas.append(f"Sin asesor para avisar ({len(sin_asesor)}): las asigna Ceci o Jime.")
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
    filas = ordenar(_por_poliza(pendientes), ahora.astimezone(MEXICO).date())
    grupos, sin_asesor = agrupar(filas)

    def encolar(rol: str, numero: Optional[str], fs: list[dict]) -> int:
        v = variables(fs, "asesor" if rol == "asesor" else "ceci")
        params = {"plantilla": "cobranza", **v, "ticket": "Cobranza", "tramite": "Cargos rechazados",
                  "cliente": fs[0].get("cliente") if len(fs) == 1 else f"{len(fs)} clientes"}
        return repo.crear_accion(fs[0]["ticket_id"], TIPO_ACCION[rol], "wati", {
            "rol": rol, "numero": numero, "destinatario": None, "mensaje": texto_plantilla(v),
            "etapa": "cargo_rechazado", "ronda": 1, "params": params, "resumen_de": [p["poliza"] for p in fs]})

    encoladas = []
    if rol_activo("asesor"):
        encoladas += [encolar("asesor", numero, fs) for numero, fs in grupos.items()]
    # Las que no tienen a quién avisarle: un WhatsApp a Ceci para que las asigne ella o Jime.
    if sin_asesor and rol_activo("ceci"):
        encoladas.append(encolar("ceci", None, sin_asesor))

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
