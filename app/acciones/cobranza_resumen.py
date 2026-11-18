"""Cobranza en resumen (COBRANZA_MODO=resumen): pocos mensajes con todo el detalle, en vez de uno por aviso.

En integraciones@ llegan ~2.400 "Notificación de Cobranza" por mes, en ráfagas: 585 el domingo 08/11, 170 el
sábado 14/11. Lo acordado con Yans y Ceci (17/11/2026):

  - Cada aviso queda guardado como una acción `en_resumen`, con sus datos. No sale nada en ese momento.
    Los avisos de la misma póliza dentro de COBRANZA_AGRUPAR_DIAS van al mismo ticket (Allianz reintenta el
    cargo y avisa cada vez). El atraso se cuenta desde la fecha del intento de cobro del PRIMER correo.
  - Todos los días hábiles a COBRANZA_RESUMEN_HORA_MX (`armar_resumen`), con lo acumulado desde el último:
      · a Yans (y quien esté en COBRANZA_RESUMEN_EMAILS), UN correo con un Excel adjunto: todas las pólizas,
        por asesor y de más a menos atraso, y al final una lista aparte "Sin asesor";
      · a Ceci, UN WhatsApp con las pólizas sin asesor (no están en Notion o no tienen asesor), para asignarlas.
  - Martes y jueves a COBRANZA_ASESOR_HORA_MX (`armar_resumen_asesores`), con lo acumulado desde el último:
      · a cada asesor, UN correo con el detalle de SUS clientes (mismo Excel) y UN WhatsApp con la cantidad.
  - Las pólizas que Yans ya marcó en la tabla de Cobranzas de Notion ("Pago hecho" = aplicado) no salen.
  - Al cliente no se le escribe: lo contacta cobranza por su WATI.

Los correos salen solo con el envío real de cobranza prendido (interruptor del panel); si no, queda la vista
previa. Los WhatsApp pasan por el despacho: respetan DRY_RUN, el interruptor y MOTOR_ETAPAS_ROLES.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

from app import config
from app.db.repo import Repositorio

log = logging.getLogger(__name__)

EN_RESUMEN = "en_resumen"
RESUMIDA = "resumida"
TIPO = "resumen_cobranza"
CLAVE_PREVIA = "cobranza_resumen:ultimo"
CLAVE_ASESORES = "cobranza_asesores:ultimo"
MEXICO = timezone(timedelta(hours=-6))
MAX_CLIENTES_WHATSAPP = 6   # WhatsApp a Ceci: las 6 con más atraso; el resto está en el correo
PRIMERA_VEZ_DIAS = 7        # el primer resumen a asesores mira la última semana
SESENTA = "Recuerda que luego de 60 días de atraso se puede cancelar el plan en cualquier momento."  # Yans, 17/11
INDICACION_CECI = "No encontré a quién avisarle: asígnalas en Notion o avísale tú al asesor."
SIN_ASESOR = "Sin asesor"

_MESES = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                      "septiembre", "octubre", "noviembre", "diciembre"), 1)}
_RE_FECHA = re.compile(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", re.I)

# Pólizas ya pagadas (tabla de Cobranzas de Notion). Se puede reemplazar en tests.
Pagadas = Callable[[list[str]], set]


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


def _payload(a: dict) -> dict:
    p = a.get("payload")
    return json.loads(p) if isinstance(p, str) else (p or {})


def primer_intento_de(repo: Repositorio, ticket_id: int) -> Optional[str]:
    """La fecha (ISO) del primer cargo rechazado ya guardado en ese ticket de cobranza, de resúmenes anteriores
    incluidos: es desde cuándo cuenta el atraso cuando Allianz reintenta."""
    return _mas_vieja(*(_payload(a).get("primer_intento") for a in repo.listar_acciones(ticket_id=ticket_id)
                        if a.get("tipo_accion") == TIPO))


def activo() -> bool:
    return (config.COBRANZA_MODO or "").strip().lower() == "resumen"


def guardar_aviso(repo: Repositorio, ticket_id: int, d: dict, cliente: str, plan: str, datos: dict,
                  omitidos: list[str], correo_id: Optional[int], primer_intento: Optional[str] = None) -> int:
    """Deja el aviso esperando el resumen (estado `en_resumen`: el despacho no lo toca).
    `primer_intento`: el primer cargo rechazado de la póliza que ya se conocía (reintentos de Allianz)."""
    este = fecha_es(d.get("fecha_intento"))
    payload = {"rol": "resumen", "etapa": "cargo_rechazado", "poliza": d["poliza"], "producto": d["producto"],
               "plan": plan, "cliente": cliente, "detalle": d, "omitidos": omitidos, "correo_id": correo_id,
               "primer_intento": _mas_vieja(primer_intento, este.isoformat() if este else None),
               "telefono_cliente": str(datos["telefono_cliente"]) if datos.get("telefono_cliente") else None,
               "asesor_numero": str(datos["telefono_asesor"]) if datos.get("telefono_asesor") else None,
               "asesor_correo": datos.get("asesor_correo"), "asesor_nombre": datos.get("asesor_nombre")}
    return repo.crear_accion(ticket_id, TIPO, "resumen", payload, estado=EN_RESUMEN)


def _por_poliza(acciones: list[dict]) -> list[dict]:
    """Un renglón por póliza (el aviso más nuevo manda; se cuentan los avisos)."""
    filas: "OrderedDict[str, dict]" = OrderedDict()
    for a in sorted(acciones, key=lambda x: x["id"]):  # de la más vieja a la más nueva
        p = _payload(a)
        clave = p.get("poliza") or f"accion-{a['id']}"
        f = filas.pop(clave, None)
        filas[clave] = {**p, "ticket_id": a["ticket_id"], "intentos": (f["intentos"] if f else 0) + 1,
                        "primer_intento": _mas_vieja(f.get("primer_intento") if f else None, p.get("primer_intento")),
                        "acciones": (f["acciones"] if f else []) + [a["id"]]}
    return list(filas.values())


def dias_atraso(f: dict, hoy: date) -> Optional[int]:
    """Días desde la fecha del intento de cobro del primer correo de cobranza de la póliza (Yans, 17/11)."""
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


def tiene_asesor(f: dict) -> bool:
    return bool(f.get("asesor_correo") or f.get("asesor_numero"))


def agrupar(filas: list[dict]) -> tuple["OrderedDict[str, list[dict]]", list[dict]]:
    """(por asesor —su correo, o su WhatsApp si no tiene correo—, sin asesor)."""
    grupos: "OrderedDict[str, list[dict]]" = OrderedDict()
    sin_asesor = []
    for f in filas:
        if tiene_asesor(f):
            grupos.setdefault((f.get("asesor_correo") or f.get("asesor_numero")).lower(), []).append(f)
        else:
            sin_asesor.append(f)
    return grupos, sin_asesor


def nombre_asesor(fs: list[dict]) -> str:
    f0 = fs[0]
    return f0.get("asesor_nombre") or f0.get("asesor_correo") or f"Asesor {f0.get('asesor_numero')}"


def quitar_pagadas(filas: list[dict], pagadas: Optional[Pagadas] = None) -> tuple[list[dict], list[dict]]:
    """(siguen, ya pagadas). Las pagadas son las que Yans marcó en Notion como "Pago hecho: aplicado"."""
    if not filas:
        return [], []
    from app.rieles import notion
    try:
        hechas = (pagadas or notion.polizas_pagadas)([f["poliza"] for f in filas if f.get("poliza")])
    except Exception:  # noqa: BLE001 — sin Notion el resumen sale igual, con todas
        log.exception("cobranza: no pude leer los pagos aplicados de Notion")
        hechas = set()
    hechas = {notion.norm_poliza(p) for p in hechas}
    siguen = [f for f in filas if notion.norm_poliza(f.get("poliza")) not in hechas]
    return siguen, [f for f in filas if notion.norm_poliza(f.get("poliza")) in hechas]


# ─────────────────────────── textos ───────────────────────────
def _renglon(f: dict, largo: bool) -> str:
    d = f.get("detalle") or {}
    partes = [f"{f.get('cliente') or 'Cliente sin identificar'} ({f.get('plan') or d.get('producto')} {f['poliza']})"]
    if f.get("dias_atraso") is not None:
        partes.append(f"{f['dias_atraso']} día{'s' if f['dias_atraso'] != 1 else ''} de atraso")
    if d.get("monto"):
        partes.append(d["monto"])
    if largo and d.get("aportacion"):
        partes.append(f"aportación {d['aportacion']}")
    if d.get("motivo"):
        partes.append(d["motivo"].lower())
    if largo and d.get("proximo_intento"):
        partes.append(f"próximo intento {d['proximo_intento']}")
    if f["intentos"] > 1:
        partes.append(f"{f['intentos']} avisos")
    return partes[0] + (": " + ", ".join(partes[1:]) if len(partes) > 1 else "")


def variables_ceci(filas: list[dict]) -> dict[str, str]:
    """Plantilla de cobranza para Ceci (pólizas sin asesor): {{cantidad}} {{clientes}} {{indicacion}}."""
    n = len(filas)
    lista = "; ".join(_renglon(f, largo=False) for f in filas[:MAX_CLIENTES_WHATSAPP])
    if n > MAX_CLIENTES_WHATSAPP:
        lista += f"; y {n - MAX_CLIENTES_WHATSAPP} más en el correo de cobranza"
    cantidad = "1 póliza sin asesor tuvo" if n == 1 else f"{n} pólizas sin asesor tuvieron"
    return {"cantidad": cantidad, "clientes": lista, "indicacion": INDICACION_CECI}


def texto_ceci(v: dict[str, str]) -> str:
    """El mensaje tal como lo arma la plantilla WATI_PLANTILLA_COBRANZA (para el panel y la vista previa)."""
    return f"Cobranza Allianz · {v['cantidad']} un cargo rechazado: {v['clientes']}. {v['indicacion']} {SESENTA}"


def variables_asesor(fs: list[dict]) -> dict[str, str]:
    """Plantilla del asesor (WATI_PLANTILLA_COBRANZA_ASESOR): {{nombre}} {{cantidad}}."""
    nombre = (fs[0].get("asesor_nombre") or "").strip().split(" ")[0].title() or "de nuevo"
    return {"nombre": nombre, "cantidad": "1 cliente" if len(fs) == 1 else f"{len(fs)} clientes"}


def texto_asesor(v: dict[str, str]) -> str:
    return (f"Hola {v['nombre']} 👋 Tienes {v['cantidad']} con cargo rechazado por Allianz. Te mandé el detalle a "
            f"tu correo: contacta a cada uno para que tenga el monto disponible o se ponga al corriente. {SESENTA}")


def texto_equipo(grupos: "OrderedDict[str, list[dict]]", sin_asesor: list[dict], hoy: str,
                 pagadas: int = 0, con_excel: bool = True) -> tuple[str, str]:
    total = sum(len(v) for v in grupos.values()) + len(sin_asesor)
    asunto = f"[Tommi] Cobranza {hoy}: {total} póliza{'s' if total != 1 else ''} con cargo rechazado"
    lineas = [f"Cargos rechazados desde el último resumen: {total} pólizas de {len(grupos)} asesores."]
    if pagadas:
        lineas.append(f"No incluye {pagadas} con el pago ya aplicado en Notion.")
    lineas += ["", "El detalle (cliente, teléfono, póliza, aportación, monto, días de atraso) va en el Excel adjunto, "
                   "de más a menos atraso." if con_excel else "Detalle, de más a menos atraso:", ""]
    for _, fs in grupos.items():
        lineas.append(f"{nombre_asesor(fs)}: {len(fs)}")
        if not con_excel:
            lineas += [f"  • {_renglon(f, largo=True)}" for f in fs]
    if sin_asesor:
        lineas += ["", f"{SIN_ASESOR}: {len(sin_asesor)} (se las mandé a Ceci para que las asigne)."]
        if not con_excel:
            for f in sin_asesor:
                motivo = "; ".join(f.get("omitidos") or []) or "sin asesor en Notion"
                lineas.append(f"  • {_renglon(f, largo=True)} — {motivo}")
    lineas += ["", SESENTA, "— Tommi"]
    return asunto, "\n".join(lineas)


def texto_correo_asesor(fs: list[dict], hoy: str, con_excel: bool = True) -> tuple[str, str]:
    n = len(fs)
    asunto = f"[Tommi] Cobranza {hoy}: {n} cliente{'s' if n != 1 else ''} tuyo{'s' if n != 1 else ''} con cargo rechazado"
    nombre = (fs[0].get("asesor_nombre") or "").strip().split(" ")[0].title()
    lineas = [f"Hola{' ' + nombre if nombre else ''},", "",
              f"Allianz rechazó el cargo de {n} cliente{'s' if n != 1 else ''} tuyo{'s' if n != 1 else ''} desde el "
              f"último resumen. Contacta a cada uno para que tenga el monto disponible o se ponga al corriente.", ""]
    lineas += [f"  • {_renglon(f, largo=True)}" for f in fs]
    if con_excel:
        lineas += ["", "Va el mismo detalle en el Excel adjunto (con el teléfono de cada cliente)."]
    lineas += ["", SESENTA, "— Tommi · Babilonia"]
    return asunto, "\n".join(lineas)


# ─────────────────────────── Excel ───────────────────────────
COLUMNAS = ("Asesor", "Cliente", "Teléfono del cliente", "Plan", "Póliza", "N° de aportación", "Monto",
            "Días de atraso", "Fecha del primer cargo rechazado", "Motivo del banco", "Próximo intento", "Avisos")


def _fila_excel(f: dict, asesor: str) -> list:
    d = f.get("detalle") or {}
    primero = f.get("primer_intento")
    return [asesor, f.get("cliente") or "Cliente sin identificar", f.get("telefono_cliente") or "",
            f.get("plan") or d.get("producto") or "", f.get("poliza") or "", d.get("aportacion") or "",
            d.get("monto") or "", f.get("dias_atraso") if f.get("dias_atraso") is not None else "",
            date.fromisoformat(primero).strftime("%d/%m/%Y") if primero else "", d.get("motivo") or "",
            d.get("proximo_intento") or "", f.get("intentos") or 1]


def excel(grupos: "OrderedDict[str, list[dict]]", sin_asesor: list[dict]) -> Optional[bytes]:
    """Una hoja: las pólizas por asesor (de más a menos atraso) y al final la lista aparte "Sin asesor".
    None si openpyxl no está instalado (el correo sale con el detalle en el cuerpo)."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        return None
    import io
    wb = Workbook()
    ws = wb.active
    ws.title = "Cobranza"
    negrita, fondo = Font(bold=True), PatternFill("solid", fgColor="E8EEF5")
    ws.append(list(COLUMNAS))
    for c in ws[1]:
        c.font, c.fill = negrita, fondo
    for _, fs in grupos.items():
        for f in fs:
            ws.append(_fila_excel(f, nombre_asesor(fs)))
    if sin_asesor:
        ws.append([])
        ws.append([SIN_ASESOR])
        ws.cell(ws.max_row, 1).font = Font(bold=True, size=12)
        ws.append([*COLUMNAS[1:], "Por qué no tiene asesor"])
        for c in ws[ws.max_row]:
            c.font, c.fill = negrita, fondo
        for f in sin_asesor:
            ws.append([*_fila_excel(f, "")[1:], "; ".join(f.get("omitidos") or []) or "sin asesor en Notion"])
    for col, ancho in zip("ABCDEFGHIJKLM", (24, 30, 16, 16, 14, 10, 12, 10, 14, 22, 22, 8, 40)):
        ws.column_dimensions[col].width = ancho
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _enviar(emisor, para: list[str], asunto: str, cuerpo: str, xlsx: Optional[bytes], nombre_xlsx: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="cobranza_") as carpeta:
        adjuntos = []
        if xlsx:
            ruta = os.path.join(carpeta, nombre_xlsx)
            with open(ruta, "wb") as fh:
                fh.write(xlsx)
            adjuntos.append(ruta)
        res = emisor.enviar(para, asunto, cuerpo, adjuntos=adjuntos or None)
    return {"enviado": bool(res.get("ok") and not res.get("simulado")),
            "resultado": {k: res.get(k) for k in ("ok", "error", "simulado")}}


def _emisor(emisor):
    if emisor is not None:
        return emisor
    from app.resumen_equipo import _emisor_real
    return _emisor_real()


# ─────────────────────────── resumen diario (Yans + Ceci) ───────────────────────────
def armar_resumen(repo: Repositorio, ahora: Optional[datetime] = None, emisor=None,
                  pagadas: Optional[Pagadas] = None) -> dict:
    """Junta los avisos `en_resumen`: correo con Excel a Yans (COBRANZA_RESUMEN_EMAILS) y WhatsApp a Ceci con
    las pólizas sin asesor. Los avisos quedan `resumida`. Devuelve qué hizo."""
    from app.acciones.motor_etapas import TIPO_ACCION, rol_activo
    from app.envio import interruptor
    ahora = ahora or datetime.now(timezone.utc)
    pendientes = repo.listar_acciones(estado=EN_RESUMEN)
    if not pendientes:
        return {"polizas": 0, "asesores": 0, "motivo": "nada acumulado"}
    todas = ordenar(_por_poliza(pendientes), ahora.astimezone(MEXICO).date())
    filas, ya_pagadas = quitar_pagadas(todas, pagadas)
    grupos, sin_asesor = agrupar(filas)

    encoladas = []
    if sin_asesor and rol_activo("ceci"):
        v = variables_ceci(sin_asesor)
        encoladas.append(repo.crear_accion(sin_asesor[0]["ticket_id"], TIPO_ACCION["ceci"], "wati", {
            "rol": "ceci", "numero": None, "destinatario": None, "mensaje": texto_ceci(v),
            "etapa": "cargo_rechazado", "ronda": 1, "resumen_de": [f["poliza"] for f in sin_asesor],
            "params": {"plantilla": "cobranza", **v, "ticket": "Cobranza", "tramite": "Cargos rechazados",
                       "cliente": f"{len(sin_asesor)} clientes"}}))

    hoy = ahora.astimezone(MEXICO).strftime("%d/%m")
    xlsx = excel(grupos, sin_asesor) if filas else None
    asunto, cuerpo = texto_equipo(grupos, sin_asesor, hoy, len(ya_pagadas), con_excel=bool(xlsx))
    destinos = [x for x in config.COBRANZA_RESUMEN_EMAILS if x]
    correo = {"asunto": asunto, "cuerpo": cuerpo, "para": destinos, "enviado": False, "excel": bool(xlsx)}
    if filas and destinos and interruptor.es_real(repo, "cobranza"):
        correo.update(_enviar(_emisor(emisor), destinos, asunto, cuerpo, xlsx,
                              f"cobranza_{ahora.astimezone(MEXICO):%Y-%m-%d}.xlsx"))
    repo.guardar_valor(CLAVE_PREVIA, json.dumps({"en": ahora.isoformat(timespec="seconds"), **correo},
                                                 ensure_ascii=False))

    for f in todas:
        for aid in f["acciones"]:
            repo.actualizar_accion(aid, RESUMIDA, {"resumen": ahora.isoformat(timespec="seconds")})
    salida = {"polizas": len(filas), "avisos": len(pendientes), "asesores": len(grupos), "pagadas": len(ya_pagadas),
              "sin_asesor": len(sin_asesor), "whatsapp_encolados": len(encoladas), "correo_equipo": correo["enviado"]}
    log.info("cobranza_resumen: %s", salida)
    return salida


# ─────────────────────────── martes y jueves: a cada asesor ───────────────────────────
def _desde_ultimo(repo: Repositorio, ahora: datetime) -> datetime:
    from app.acciones.motor_etapas import _parse_ts
    previo = _parse_ts(repo.leer_valor(CLAVE_ASESORES))
    return previo or ahora - timedelta(days=PRIMERA_VEZ_DIAS)


def armar_resumen_asesores(repo: Repositorio, ahora: Optional[datetime] = None, emisor=None,
                           pagadas: Optional[Pagadas] = None) -> dict:
    """A cada asesor: un correo con el detalle de sus clientes con cargo rechazado desde el último envío (con el
    Excel) y un WhatsApp con la cantidad. Sin asesor no entra acá (ya lo tiene Ceci)."""
    from app.acciones.motor_etapas import TIPO_ACCION, _parse_ts, rol_activo
    from app.envio import interruptor
    ahora = ahora or datetime.now(timezone.utc)
    desde = _desde_ultimo(repo, ahora)
    avisos = [a for est in (EN_RESUMEN, RESUMIDA) for a in repo.listar_acciones(estado=est)
              if a.get("tipo_accion") == TIPO and (_parse_ts(a.get("created_at")) or ahora) > desde]
    filas, ya_pagadas = quitar_pagadas(ordenar(_por_poliza(avisos), ahora.astimezone(MEXICO).date()), pagadas)
    grupos, _ = agrupar(filas)
    real = interruptor.es_real(repo, "cobranza")
    hoy = ahora.astimezone(MEXICO).strftime("%d/%m")
    correos, whatsapp = [], 0
    for _, fs in grupos.items():
        para = fs[0].get("asesor_correo")
        if para:
            xlsx = excel(OrderedDict([(para, fs)]), [])
            asunto, cuerpo = texto_correo_asesor(fs, hoy, con_excel=bool(xlsx))
            c = {"para": para, "asunto": asunto, "polizas": len(fs), "enviado": False}
            if real:
                c.update(_enviar(_emisor(emisor), [para], asunto, cuerpo, xlsx,
                                 f"cobranza_{ahora.astimezone(MEXICO):%Y-%m-%d}.xlsx"))
            correos.append(c)
        if fs[0].get("asesor_numero") and rol_activo("asesor"):
            v = variables_asesor(fs)
            repo.crear_accion(fs[0]["ticket_id"], TIPO_ACCION["asesor"], "wati", {
                "rol": "asesor", "numero": fs[0]["asesor_numero"], "destinatario": None, "mensaje": texto_asesor(v),
                "etapa": "cargo_rechazado", "ronda": 1, "resumen_de": [f["poliza"] for f in fs],
                "params": {"plantilla": "cobranza_asesor", **v, "ticket": "Cobranza", "tramite": "Cargos rechazados",
                           "cliente": v["cantidad"]}})
            whatsapp += 1
    repo.guardar_valor(CLAVE_ASESORES, ahora.isoformat(timespec="seconds"))
    repo.guardar_valor(f"{CLAVE_ASESORES}:detalle", json.dumps(
        {"en": ahora.isoformat(timespec="seconds"), "desde": desde.isoformat(timespec="seconds"),
         "correos": correos, "whatsapp": whatsapp, "pagadas": len(ya_pagadas)}, ensure_ascii=False))
    salida = {"asesores": len(grupos), "polizas": len(filas), "pagadas": len(ya_pagadas),
              "correos_enviados": sum(1 for c in correos if c["enviado"]), "correos": len(correos),
              "whatsapp_encolados": whatsapp}
    log.info("cobranza_asesores: %s", salida)
    return salida
