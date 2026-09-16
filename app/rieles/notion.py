"""Rieles de Notion (Fase F): autodescubren las bases y MAPEAN los campos necesarios por
nombre aproximado, para no hardcodear nombres de columnas ni IDs.

Motivación: la base **Emisiones** de Babilonia tiene ~100 columnas y las renombran seguido.
En vez de clavar `props["Correo Cliente"]`, el riel:
  1. Descubre el ID de la base (de `NOTION_DB_*`; si falta, la busca por título con /search).
  2. Lee el esquema y **mapea cada campo lógico** (poliza, cliente_correo, asesor_telefono…)
     al nombre real de la propiedad, comparando **sin acentos y case-insensitive** por una
     lista de alias. Si mañana renombran "Correo Cliente" → "Email del Cliente", el riel lo
     reencuentra por alias sin tocar código.
  3. Extrae el valor sin importar el tipo (rich_text, number, select, people, rollup con
     teléfono/persona, formula, email, phone_number).

Solo LECTURA. urllib de la stdlib (sin dependencias nuevas). Cachea esquema y mapeo en memoria.
"""
from __future__ import annotations

import json
import logging
import unicodedata
import urllib.request

from app import config

log = logging.getLogger(__name__)

_API = "https://api.notion.com/v1"


# ───────────────────────── HTTP mínimo ─────────────────────────
def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


def _get(url: str) -> dict:
    try:
        req = urllib.request.Request(url, headers=_headers())
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception as ex:  # noqa: BLE001
        log.warning("Notion GET falló (%s): %s", url[-24:], ex)
        return {}


def _post(url: str, body: dict) -> dict:
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     method="POST", headers=_headers())
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception as ex:  # noqa: BLE001
        log.warning("Notion POST falló (%s): %s", url[-24:], ex)
        return {}


def _norm(s: str) -> str:
    """minúsculas, sin acentos, espacios colapsados → para comparar nombres de columnas."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


# ───────────────────── descubrimiento de la base ─────────────────────
# Alias de título por base lógica (para /search cuando no hay ID en config).
_DB_ALIASES = {
    "emisiones": ("emisiones", "emision"),
    "asesores": ("asesores", "asesor"),
    "clientes": ("clientes", "cliente"),
    "tickets_allianz": ("tickets allianz", "tickets"),
    "daf": ("daf",),
    "cobranzas": ("cobranzas", "cobranza"),
}
_CONFIG_ATTR = {
    "emisiones": "NOTION_DB_EMISIONES", "asesores": "NOTION_DB_ASESORES",
    "clientes": "NOTION_DB_CLIENTES", "tickets_allianz": "NOTION_DB_TICKETS_ALLIANZ",
    "daf": "NOTION_DB_DAF", "cobranzas": "NOTION_DB_COBRANZAS",
}
_cache_db: dict[str, str] = {}


def _buscar_db_por_titulo(aliases: tuple[str, ...]) -> str:
    data = _post(f"{_API}/search", {"filter": {"value": "database", "property": "object"},
                                    "page_size": 100})
    for r in data.get("results", []):
        if r.get("object") != "database":
            continue
        titulo = _norm("".join(t.get("plain_text", "") for t in r.get("title", [])))
        if any(_norm(a) in titulo for a in aliases):
            return r.get("id", "")
    return ""


def descubrir_db(clave: str) -> str:
    """ID de una base lógica: primero de config (NOTION_DB_*), si no está la busca por título."""
    if clave in _cache_db:
        return _cache_db[clave]
    dbid = getattr(config, _CONFIG_ATTR.get(clave, ""), "") or ""
    if not dbid and config.NOTION_TOKEN:
        dbid = _buscar_db_por_titulo(_DB_ALIASES.get(clave, (clave,)))
    _cache_db[clave] = dbid
    return dbid


# ───────────────────── esquema + mapeo de campos ─────────────────────
_cache_schema: dict[str, dict] = {}
_cache_map: dict[tuple, dict] = {}


def esquema(db_id: str) -> dict:
    if not db_id:
        return {}
    if db_id not in _cache_schema:
        _cache_schema[db_id] = _get(f"{_API}/databases/{db_id}").get("properties", {}) or {}
    return _cache_schema[db_id]


def mapear_campos(db_id: str, deseados: dict[str, list[str]]) -> dict[str, str | None]:
    """{campo_logico: [alias...]} → {campo_logico: nombre_real | None}.

    Primero busca coincidencia exacta normalizada; si no, coincidencia por 'contiene' (el
    nombre más corto, para evitar arrastrar columnas largas)."""
    key = (db_id, tuple(sorted(deseados)))
    if key in _cache_map:
        return _cache_map[key]
    props = esquema(db_id)
    norm_a_real = {_norm(name): name for name in props}
    out: dict[str, str | None] = {}
    for logico, aliases in deseados.items():
        real = None
        for a in aliases:                                   # 1) exacto normalizado
            if _norm(a) in norm_a_real:
                real = norm_a_real[_norm(a)]
                break
        if real is None:                                    # 2) todos los tokens del alias ⊆ columna
            for a in aliases:                               #    (tolera palabras intercaladas: "del", etc.)
                at = set(_norm(a).split())
                cand = [orig for n, orig in norm_a_real.items() if at and at.issubset(set(n.split()))]
                if cand:
                    real = sorted(cand, key=len)[0]
                    break
        out[logico] = real
    _cache_map[key] = out
    return out


# ───────────────────── extracción de valores ─────────────────────
def valor(prop: dict | None):
    """Devuelve el valor 'plano' de una propiedad de Notion, sea del tipo que sea."""
    if not prop:
        return None
    t = prop.get("type")
    v = prop.get(t)
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in (v or [])) or None
    if t in ("select", "status"):
        return v.get("name") if v else None
    if t in ("number", "email", "phone_number", "url", "checkbox"):
        return v
    if t == "people":
        return (v[0].get("name") if v else None)
    if t == "formula":
        f = v or {}
        return f.get(f.get("type"))
    if t == "rollup":
        rt = (v or {}).get("type")
        if rt == "array":
            for item in ((v or {}).get("array") or []):     # primer item con dato útil
                iv = valor(item)
                if iv not in (None, ""):
                    return iv
            return None
        return (v or {}).get(rt)                             # rollup escalar (number/date/…)
    return None


# ───────────────────── API de alto nivel: Emisiones ─────────────────────
# Campo lógico → alias candidatos (sin acentos / mayúsc. da igual). Editar acá si cambia algo.
CAMPOS_EMISION = {
    "poliza": ["numero de poliza", "poliza", "no de poliza", "num poliza"],
    "nro_solicitud": ["numero de solicitud", "no de solicitud", "num solicitud"],
    "cliente_nombre": ["nombre cliente", "nombre del cliente", "cliente"],
    "cliente_correo": ["correo cliente", "correo del cliente", "email cliente", "mail cliente"],
    "cliente_telefono": ["telefono cliente", "telefono del cliente", "celular cliente",
                         "whatsapp cliente", "tel cliente"],
    "asesor_correo": ["correo asesor", "correo del asesor", "email asesor", "mail asesor"],
    "asesor_telefono": ["telefono del asesor", "telefono asesor", "celular asesor", "tel asesor"],
    "asesor_nombre": ["asesor 1", "asesor"],
    "daf_nombre": ["asesor daf", "daf"],
    "lider_nombre": ["lider 1", "lider", "líder"],
    "producto": ["producto (nombre)", "producto nombre", "producto"],
    "estado_poliza": ["estado"],
}


def _query(db_id: str, filt: dict, page_size: int = 1) -> list[dict]:
    if not (config.NOTION_TOKEN and db_id):
        return []
    body: dict = {"page_size": page_size}
    if filt:
        body["filter"] = filt
    return _post(f"{_API}/databases/{db_id}/query", body).get("results", []) or []


def _extraer(page: dict, mapa: dict) -> dict:
    props = page.get("properties", {})

    def g(logico):
        real = mapa.get(logico)
        return valor(props.get(real)) if real else None

    return {
        "found": True, "fuente": "emisiones", "emision_id": page.get("id"),
        "poliza": g("poliza"), "nro_solicitud": g("nro_solicitud"),
        "cliente_nombre": g("cliente_nombre"), "cliente_correo": g("cliente_correo"),
        "telefono_cliente": g("cliente_telefono"),
        "asesor_correo": g("asesor_correo"), "telefono_asesor": g("asesor_telefono"),
        "asesor_nombre": g("asesor_nombre"), "daf_nombre": g("daf_nombre"),
        "lider_nombre": g("lider_nombre"), "producto": g("producto"),
        "estado_poliza": g("estado_poliza"),
    }


def resolver_emision(poliza: str | None = None, nro_solicitud=None,
                     cliente_correo: str | None = None) -> dict:
    """Cruza la base Emisiones por póliza (preferido) → nº de solicitud → correo del cliente.
    Devuelve los datos de contacto de cliente y asesor (incluye teléfonos para WATI). {} si nada."""
    db = descubrir_db("emisiones")
    if not db:
        return {}
    mapa = mapear_campos(db, CAMPOS_EMISION)

    intentos = []
    if poliza and mapa.get("poliza"):
        intentos.append({"property": mapa["poliza"], "rich_text": {"contains": str(poliza)}})
    if nro_solicitud not in (None, "") and mapa.get("nro_solicitud"):
        try:
            intentos.append({"property": mapa["nro_solicitud"],
                             "number": {"equals": int(str(nro_solicitud).strip())}})
        except (ValueError, TypeError):
            pass
    if cliente_correo and mapa.get("cliente_correo"):
        intentos.append({"property": mapa["cliente_correo"],
                         "rich_text": {"contains": cliente_correo}})

    for filt in intentos:
        res = _query(db, filt)
        if res:
            return _extraer(res[0], mapa)
    return {}


def diagnostico() -> dict:
    """Reporte de los rieles: qué base se descubrió y a qué columnas reales mapeó cada campo.
    Sirve para verificar el mapeo contra Notion sin escribir nada."""
    db = descubrir_db("emisiones")
    mapa = mapear_campos(db, CAMPOS_EMISION) if db else {}
    faltantes = [k for k, v in mapa.items() if not v]
    return {"emisiones_db": db, "mapa": mapa, "faltantes": faltantes,
            "hay_notion": config.hay_notion()}
