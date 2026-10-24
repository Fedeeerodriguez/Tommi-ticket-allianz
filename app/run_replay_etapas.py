"""Prueba de las Etapas 1 y 2 juntas — un solo informe para que Ceci lo revise.

  1. SEMANA DE PRUEBA (app/escenarios_etapas.py): los 4 recorridos (largo, Elite, Patrimonial,
     trámite) armados con las capturas de Ceci, con sus aprobaciones de la guía y el "Pago
     enviado". Hace falta porque en hola@ todavía no hay C2 del corto ni trámites reales.
  2. CORREOS REALES: lee los correos guardados en la base (solo lectura) y los pasa en orden.

En los dos casos: grafo con MOTOR_ETAPAS (los tres procesos), base SQLite temporal, reloj
simulado (la fecha de cada correo) y recordatorios cada 30 min entre correo y correo. Así se ve
qué etapas se detectaron, qué avisos habrían salido (texto exacto y a quién) y qué recordatorios.

Nada sale: DRY_RUN forzado, no se despacha, no se escribe en Notion ni en la base real.
Notion se consulta en solo lectura para identificar cliente/asesor (igual que en producción).

El informe tiene datos personales (nombres, pedidos médicos): queda en `data/` (fuera de git).

Uso:  python -m app.run_replay_etapas [--desde 2026-09-01] [--salida data/replay_etapas.html] [--solo-prueba]
"""
from __future__ import annotations

import argparse
import html
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import config


def _forzar_sandbox() -> None:
    config.MOTOR_ETAPAS = True
    config.DRY_RUN = True
    config.OPENAI_API_KEY = ""          # sin LLM (el proceso largo no lo usa)
    config.NOTION_DB_TICKETS_ALLIANZ = ""  # no registrar en Notion
    config.NOTION_DB_SEGUIMIENTO = ""
    config.PANEL_URL = ""
    config.ESCALAR_A_ALLIANZ = True     # el informe muestra el encendido completo
    config.MOTOR_ETAPAS_ROLES = ["ceci", "asesor", "cliente"]
    config.MOTOR_ETAPAS_PROCESOS = ["largo", "corto", "tramite"]  # Etapa 1 + Etapa 2
    config.TELEGRAM_APROBACIONES = False  # la guía la "aprueba" Ceci en la semana de prueba (sin Telegram)


def _leer_correos(dsn: str, desde: datetime) -> list:
    import psycopg2
    c = psycopg2.connect(dsn)
    try:
        cur = c.cursor()
        cur.execute("select message_id, remitente, remitente_dominio, para, cc, asunto, cuerpo_texto, fecha "
                    "from tickets_allianz.correos where remitente ilike %s and (fecha is null or fecha >= %s) "
                    "order by fecha nulls first, id", ("%allianz%", desde))
        filas = cur.fetchall()
        cur.execute("select t.nro_ticket, count(a.id) from tickets_allianz.tickets t "
                    "join tickets_allianz.acciones a on a.ticket_id = t.id group by t.nro_ticket")
        viejo = {str(n): int(k) for n, k in cur.fetchall() if n}
        return filas, viejo
    finally:
        c.close()


def replay(desde: datetime, hasta: datetime) -> dict:
    """Los correos reales de la base."""
    _forzar_sandbox()
    filas, viejo = _leer_correos(config.DATABASE_URL, desde)
    return replay_correos(filas, desde, hasta, viejo)


def semana_de_prueba() -> dict:
    """Los 4 recorridos de app/escenarios_etapas.py (Notion de prueba, Ceci simulada)."""
    from app import escenarios_etapas as esc
    from app.enriquecimiento import identificar as ident_mod

    _forzar_sandbox()
    filas = [(f"prueba-{i}", rem, rem.split("@")[1], ["hola@babilonia.ai"], [], asu, cue, f)
             for i, (f, rem, asu, cue) in enumerate(esc.CORREOS)]
    original = ident_mod._buscador_notion
    ident_mod._buscador_notion = lambda: esc.buscar_notion
    try:
        return replay_correos(filas, esc.dia(19, 8), esc.HASTA, {}, esc.ACCIONES_CECI)
    finally:
        ident_mod._buscador_notion = original


def _accion_ceci(repo, que: str, nro: str, campos: Optional[dict]) -> tuple[Optional[int], dict]:
    """Lo que Ceci haría a mano en el panel o en Telegram."""
    from app.acciones import aprobaciones
    from app.acciones.motor_etapas import decidir_por_etapa
    t = repo.buscar_ticket(nro, None, None)
    if not t:
        return None, {}
    if que == "aprobar_guia":
        ap = next(iter(repo.listar_aprobaciones(t["id"], estados=["pendiente"])), None)
        res = aprobaciones.aprobar(repo, ap["id"], "panel:Ceci (simulada)", **(campos or {})) if ap else \
            {"ok": False, "motivo": "no había guía pendiente", "plan": []}
        return t["id"], {"titulo": "Ceci aprueba la guía de aportación", "res": res}
    res = decidir_por_etapa(repo, t["id"], {"etapa": "documentos_enviados", "proceso": t.get("proceso"),
                                            "motivo": "marcado a mano en el panel"})
    return t["id"], {"titulo": "Ceci marca «Pago enviado» en el panel",
                     "res": {"ok": res.get("aplicada"), "motivo": res.get("motivo"), "plan": res["plan"],
                             "recordatorios": res.get("recordatorios")}}


def replay_correos(filas: list, desde: datetime, hasta: datetime, viejo: dict,
                   acciones_ceci: Optional[list] = None) -> dict:
    from app.acciones import motor_etapas
    from app.acciones.recordatorios import escanear_recordatorios
    from app.db.repo import RepositorioSQLite
    from app.grafo import construir_grafo
    from app.models import Correo

    pendientes_ceci = sorted(acciones_ceci or [], key=lambda x: x[0])
    repo = RepositorioSQLite(os.path.join(tempfile.mkdtemp(), "replay.sqlite"))
    grafo = construir_grafo(repo)
    reloj = [desde]
    motor_etapas.reloj = lambda: reloj[0]

    linea: dict[int, list] = defaultdict(list)   # ticket_id → [(fecha, tipo, detalle)]
    sin_ticket, errores, rutas = [], [], Counter()

    def ceci_hasta(hasta_t: datetime) -> None:
        while pendientes_ceci and pendientes_ceci[0][0] <= hasta_t:
            cuando, que, nro, campos = pendientes_ceci.pop(0)
            reloj[0] = max(reloj[0], cuando)
            tid, d = _accion_ceci(repo, que, nro, campos)
            if tid:
                linea[tid].append((cuando, "ceci", d))

    def avanzar(hasta_t: datetime) -> None:
        t = reloj[0]
        while t + timedelta(minutes=30) <= hasta_t:
            t += timedelta(minutes=30)
            ceci_hasta(t)
            r = escanear_recordatorios(repo, t)
            for a in r["plan"]:
                linea[a["ticket_id"]].append((t, "recordatorio", a))
        ceci_hasta(hasta_t)
        reloj[0] = max(reloj[0], hasta_t)

    for mid, rem, dom, para, cc, asu, cue, fe in filas:
        fecha = fe if (fe and fe.tzinfo) else (fe.replace(tzinfo=timezone.utc) if fe else reloj[0])
        avanzar(fecha)
        reloj[0] = fecha
        correo = Correo(mid, rem or "", dom or "", para or [], cc or [], asu or "", cue or "", fecha=fecha)
        try:
            out = grafo.invoke({"correo": correo, "despachar": False})
        except Exception as ex:  # noqa: BLE001
            errores.append((fecha, asu, repr(ex)))
            continue
        ruta = out.get("ruta", [])
        clave = ("etapa" if "decidir_etapa" in ruta else "emision" if "emision" in ruta
                 else "motor_viejo" if "decidir" in ruta else out.get("fin") or "?")
        rutas[clave] += 1
        tid = out.get("ticket_id")
        if tid and clave in ("etapa", "emision", "motor_viejo"):
            linea[tid].append((fecha, "correo", {"asunto": asu, "ruta": clave, "res": out.get("etapa_resultado"),
                                                 "acciones": out.get("acciones") or []}))
        elif clave not in ("no_ticket", "duplicado"):
            sin_ticket.append((fecha, asu, clave))
    avanzar(hasta)
    motor_etapas.reloj = None
    return {"repo": repo, "linea": linea, "rutas": rutas, "errores": errores, "sin_ticket": sin_ticket,
            "viejo": viejo, "correos": len(filas), "desde": desde, "hasta": hasta}


# ───────────────────────────────── informe ─────────────────────────────────
_PARA = {"ceci": "Ceci", "asesor": "Asesor", "cliente": "Cliente", "allianz": "Allianz (correo)"}


def _mx(d: datetime) -> str:
    return (d.astimezone(timezone.utc) + timedelta(hours=config.UTC_OFFSET_MX)).strftime("%d/%m %H:%M")


def _tel(v) -> str:
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return f"…{s[-4:]}" if s else "—"


def _aviso_html(a: dict) -> str:
    rol = a.get("rol") or a.get("destinatario") or "?"
    texto = a.get("cuerpo") if a.get("tipo_accion") == "escalar_allianz" else a.get("mensaje")
    extra = f" · cc {', '.join(a.get('cc') or [])} · <b>queda para que Ceci lo apruebe</b>" \
        if a.get("tipo_accion") == "escalar_allianz" else (f" · WhatsApp {_tel(a.get('numero'))}" if a.get("numero") else "")
    return (f'<div class="aviso"><span class="para {rol}">{_PARA.get(rol, rol)}</span>'
            f'<span class="meta">{extra}</span><div class="txt">{html.escape(texto or "").replace(chr(10), "<br>")}</div></div>')


_PROCESO = {"largo": "Proceso largo", "corto": "Proceso corto", "tramite": "Trámite"}


def informe_html(r: dict, prueba: Optional[dict] = None) -> str:
    """Página completa: la semana de prueba (si vino) y los correos reales."""
    partes = [_ESTILO, "<main>", "<h1>Prueba de las etapas 1 y 2</h1>",
              '<p class="sub">Simulación: no salió nada. Para cada ticket: qué detectó el sistema en cada correo y qué '
              'avisos y recordatorios habría mandado, con el texto exacto y a quién. Marca lo que esté mal.</p>']
    if prueba:
        partes += _seccion(prueba, "1. Semana de prueba (capturas de Ceci)",
                           "Los cuatro recorridos de punta a punta, del lunes 19 al martes 27 de octubre: proceso largo, "
                           "Elite, Patrimonial y un trámite, con lo que Ceci haría a mano (aprobar la guía, «Pago "
                           "enviado»). Nombres y teléfonos de prueba. Hace falta porque en hola@ todavía no llegan los "
                           "correos del proceso corto ni los trámites.", real=False)
    if r:
        partes += _seccion(r, ("2. " if prueba else "") + "Correos reales de hola@",
                           f"Del {r['desde']:%d/%m/%Y} al {r['hasta']:%d/%m/%Y}.", real=True)
    partes.append("</main>")
    return "\n".join(partes)


def _seccion(r: dict, titulo: str, sub: str, real: bool) -> list[str]:
    from app.acciones.mensajes_etapa import contexto, etiqueta
    repo = r["repo"]
    tickets = {t["id"]: t for t in repo.listar_tickets(limite=1000)}
    total_avisos = Counter()
    for tid in tickets:
        for a in repo.listar_avisos(tid):
            total_avisos[a["destinatario"]] += 1
    con_etapa = [t for t in tickets.values() if t.get("etapa")]
    viejo_total = sum(r["viejo"].get(str(t.get("nro_ticket")), 0) for t in con_etapa)
    nuevo_total = sum(len(repo.listar_avisos(t["id"])) for t in con_etapa)

    por_proceso = Counter(t.get("proceso") or "largo" for t in con_etapa)
    procesos = " · ".join(f"{n} {_PROCESO.get(p, p).lower()}" for p, n in sorted(por_proceso.items())) or "—"
    comparacion = (f'<div class="cifra"><b>{viejo_total} → {nuevo_total}</b><span>acciones del motor viejo → avisos '
                   f'ahora (mismos tickets)</span></div>') if real else ""
    partes = [f"""<h2 class="seccion">{html.escape(titulo)}</h2><p class="sub">{html.escape(sub)}</p>
<div class="cifras">
<div class="cifra"><b>{r['correos']}</b><span>correos de Allianz leídos</span></div>
<div class="cifra"><b>{len(con_etapa)}</b><span>tickets en el motor ({procesos})</span></div>
<div class="cifra"><b>{sum(1 for t in con_etapa if t.get('identificado_por'))}</b><span>con cliente y asesor identificados</span></div>
<div class="cifra"><b>{total_avisos['cliente']} · {total_avisos['asesor']} · {total_avisos['ceci']}</b><span>avisos a cliente · asesor · Ceci</span></div>
{comparacion}
<div class="cifra"><b>{len(r['errores'])}</b><span>errores</span></div>
</div>"""]
    for tid, eventos in sorted(r["linea"].items(), key=lambda kv: min(e[0] for e in kv[1])):
        t = tickets.get(tid) or {}
        if not t.get("etapa"):
            continue
        ceci = [] if t.get("identificado_por") else ['<span class="chip alerta">cliente/asesor sin identificar → va a Ceci</span>']
        antes = r["viejo"].get(str(t.get("nro_ticket")))
        t = {**t, "cliente_nombre": contexto(t, {}).get("cliente")}  # mismo nombre limpio que en los avisos
        partes.append(f"""<section><div class="cab"><h2>Ticket {html.escape(str(t.get('nro_ticket') or 's/n'))}</h2>
<span>{html.escape(t.get('cliente_nombre') or '—')}</span><span class="chip">{html.escape(_PROCESO.get(t.get('proceso') or 'largo', ''))}</span>
<span class="chip">{html.escape(t.get('producto') or '—')}</span>{('<span class="motivo">«' + html.escape(t['titulo_hilo']) + '»</span>') if t.get('titulo_hilo') else ''}
<span class="chip">{html.escape(etiqueta(t.get('etapa'), t.get('proceso')))}</span>{''.join(ceci)}
<span class="comp">{'Motor viejo: ' + str(antes) + ' acciones · ' if antes else ''}ahora: {len(repo.listar_avisos(tid))} avisos</span></div>""")
        # Los recordatorios del mismo momento y etapa (cliente + asesor + Ceci) van en una sola fila.
        filas: list = []
        for fecha, tipo, d in sorted(eventos, key=lambda e: e[0]):
            if tipo == "recordatorio" and filas and filas[-1][1] == "recordatorio" \
                    and filas[-1][0] == fecha and filas[-1][2][0].get("etapa") == d.get("etapa"):
                filas[-1][2].append(d)
            else:
                filas.append((fecha, tipo, [d] if tipo == "recordatorio" else d))
        for fecha, tipo, d in filas:
            if tipo == "correo":
                res = d.get("res") or {}
                etapa = etiqueta(res.get("etapa"), t.get("proceso")) if res.get("etapa") else d["ruta"]
                motivo = res.get("motivo") or ""
                if res and not res.get("aplicada"):
                    motivo = f"sin cambios: {motivo}"
                omit = "".join(f'<div class="motivo">⚠️ {html.escape(o)}</div>' for o in res.get("avisos_omitidos") or [])
                recs = "".join(f'<div class="motivo">⏰ {html.escape(x)}</div>' for x in res.get("recordatorios") or [])
                avisos = "".join(_aviso_html(a) for a in d["acciones"]) if d["ruta"] != "motor_viejo" else \
                    '<div class="motivo">(motor viejo: proceso que todavía no está en el motor por etapa)</div>'
                if res.get("aprobacion"):
                    avisos += ('<div class="motivo">📝 La guía de aportación queda esperando a Ceci: no sale nada '
                               'al cliente ni al asesor hasta que la apruebe.</div>')
                partes.append(f"""<div class="fila"><div class="cuando">{_mx(fecha)}</div><div class="que">
<div><span class="etapa">{html.escape(etapa)}</span> <span class="motivo">· {html.escape(motivo)}</span></div>
<details><summary class="motivo">Correo: {html.escape((d['asunto'] or '')[:110])}</summary></details>{omit}{recs}{avisos}</div></div>""")
            elif tipo == "ceci":
                res = d.get("res") or {}
                recs = "".join(f'<div class="motivo">⏰ {html.escape(x)}</div>' for x in res.get("recordatorios") or [])
                if res.get("recordatorio_pago"):
                    recs += f'<div class="motivo">⏰ recordatorio de pago para el {_mx(res["recordatorio_pago"])}</div>'
                partes.append(f"""<div class="fila"><div class="cuando">{_mx(fecha)}</div><div class="que">
<div class="etapa">👩‍💼 {html.escape(d['titulo'])}</div><div class="motivo">{html.escape(res.get('motivo') or '')}</div>
{recs}{''.join(_aviso_html(a) for a in res.get('plan') or [])}</div></div>""")
            else:
                partes.append(f"""<div class="fila"><div class="cuando">{_mx(fecha)}</div><div class="que">
<div class="etapa">⏰ {html.escape(etiqueta(d[0].get('etapa'), t.get('proceso')) or 'Recordatorio')}</div>{''.join(_aviso_html(x) for x in d)}</div></div>""")
        partes.append("</section>")
    if r["errores"]:
        partes.append("<section><h2>Errores</h2>" + "".join(
            f'<div class="fila"><div class="cuando">{_mx(f)}</div><div>{html.escape(a or "")}<br>'
            f'<span class="motivo">{html.escape(e)}</span></div></div>' for f, a, e in r["errores"]) + "</section>")
    return partes


_ESTILO = """<title>Prueba etapas 1 y 2</title>
<style>
:root{--fondo:#f6f7f9;--tinta:#1d2733;--suave:#5b6675;--borde:#dde2e8;--acento:#1c496f;--ceci:#7a3e9d;--asesor:#1c6b4a;--cliente:#a15c00;--allianz:#a32638}
body{background:var(--fondo);color:var(--tinta);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;padding:24px 16px}
main{max-width:960px;margin:0 auto} h1{font-size:26px;margin:0 0 4px} h2{font-size:18px;margin:0}
h2.seccion{font-size:21px;margin:32px 0 2px;color:var(--acento)}
.sub{color:var(--suave);margin:0 0 20px} .cifras{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0 24px}
.cifra{background:#fff;border:1px solid var(--borde);border-radius:8px;padding:10px 12px} .cifra b{display:block;font-size:22px;font-variant-numeric:tabular-nums}
.cifra span{color:var(--suave);font-size:12px} section{background:#fff;border:1px solid var(--borde);border-radius:8px;padding:14px 16px;margin:0 0 14px}
.cab{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;margin-bottom:8px} .chip{font-size:12px;padding:1px 8px;border-radius:99px;background:#e8eef5;color:var(--acento)}
.alerta{background:#fbe9ec;color:var(--allianz)} .fila{border-top:1px solid var(--borde);padding:8px 0;display:grid;grid-template-columns:90px 1fr;gap:10px}
.cuando{color:var(--suave);font-size:13px;font-variant-numeric:tabular-nums} .que{font-size:14px} .etapa{font-weight:600}
.motivo{color:var(--suave);font-size:13px} .aviso{margin:6px 0 0;padding:6px 8px;background:var(--fondo);border-radius:6px}
.para{font-size:12px;font-weight:600;margin-right:6px} .para.ceci{color:var(--ceci)} .para.asesor{color:var(--asesor)}
.para.cliente{color:var(--cliente)} .para.allianz{color:var(--allianz)} .meta{font-size:12px;color:var(--suave)} .txt{font-size:14px;margin-top:2px}
.comp{font-size:13px;color:var(--suave)} details{margin-top:6px} @media (max-width:520px){.fila{grid-template-columns:1fr}}
</style>"""


def main() -> int:
    p = argparse.ArgumentParser(description="Prueba de las etapas 1 y 2: semana de prueba + correos reales "
                                             "(no envía nada).")
    p.add_argument("--desde", default="2026-09-01")
    p.add_argument("--salida", default=str(config.DATA_DIR / "replay_etapas.html"))
    p.add_argument("--solo-prueba", action="store_true", help="solo la semana de prueba (sin leer la base)")
    a = p.parse_args()
    prueba = semana_de_prueba()
    print(f"semana de prueba: correos={prueba['correos']} rutas={dict(prueba['rutas'])} errores={len(prueba['errores'])}")
    r = None
    if not a.solo_prueba:
        if not config.hay_db():
            print("Falta DATABASE_URL (la base de donde se leen los correos reales). Usa --solo-prueba.")
            return 1
        desde = datetime.fromisoformat(a.desde).replace(tzinfo=timezone.utc)
        r = replay(desde, datetime.now(timezone.utc))
        print(f"correos reales: correos={r['correos']} rutas={dict(r['rutas'])} errores={len(r['errores'])}")
    os.makedirs(os.path.dirname(os.path.abspath(a.salida)), exist_ok=True)
    with open(a.salida, "w", encoding="utf-8") as f:
        f.write(informe_html(r, prueba))
    print(f"→ {a.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
