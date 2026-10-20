"""Repositorio enchufable.

- `RepositorioPostgres`: la MISMA Supabase de Tommy, esquema aislado `tickets_allianz`.
  Driver-flexible (psycopg v3 o psycopg2). Tablas calificadas con el esquema para no
  depender de search_path (el pooler de Supabase corre en modo transacción).
- `RepositorioSQLite`: backend local para dev/tests sin credenciales.

`get_repo()` elige Postgres si hay DATABASE_URL, si no SQLite.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Protocol

from app import config
from app.models import Clasificacion, Correo

_COLS_TICKET = ["nro_ticket", "poliza", "cliente_nombre", "cliente_correo", "asesor_correo",
                "daf", "estado", "delicado", "autorizado", "abierto_por",
                "gmail_thread_id", "asunto_hilo", "ultimo_message_id", "vence_en",
                "telefono_cliente", "telefono_asesor"]
# Etapa 1 (docs/migracion_etapa1_2026-10-19.sql). Solo se insertan si vienen con valor: así el
# código no rompe en una base donde todavía no se corrió la migración.
_COLS_TICKET_ETAPA = ["proceso", "producto", "etapa", "etapa_desde", "etapa_ronda", "nro_solicitud",
                      "identificado_por",
                      # Etapa 2 (docs/migracion_etapa2_2026-10-20.sql): asunto del trámite ("[EXT] …").
                      "titulo_hilo"]
RECORDATORIO_VIVO = ("activo", "escalado")


def _cols_ticket(datos: dict) -> list[str]:
    return _COLS_TICKET + [c for c in _COLS_TICKET_ETAPA if datos.get(c) is not None]


class Repositorio(Protocol):
    def guardar_correo(self, correo: Correo, clf: Clasificacion, entidades: dict) -> tuple[int, bool]: ...
    def buscar_ticket(self, nro_ticket: Optional[str], poliza: Optional[str],
                      cliente_correo: Optional[str]) -> Optional[dict]: ...
    def crear_ticket(self, datos: dict) -> int: ...
    def actualizar_ticket(self, ticket_id: int, **campos: Any) -> None: ...
    def vincular_correo(self, correo_id: int, ticket_id: int) -> None: ...
    def agregar_evento(self, ticket_id: int, correo_id: Optional[int],
                       tipo_evento: str, resumen: str) -> int: ...
    def crear_accion(self, ticket_id: int, tipo_accion: str, canal: str, payload: dict,
                     programada_para: Optional[str] = None) -> int: ...
    def actualizar_accion(self, accion_id: int, estado: str,
                          resultado: Optional[dict] = None) -> None: ...
    def set_veredicto(self, accion_id: int, veredicto: str, nota: Optional[str] = None) -> int: ...
    def set_borrador(self, accion_id: int, borrador: str) -> int: ...
    def listar_acciones(self, ticket_id: Optional[int] = None, estado: Optional[str] = None) -> list[dict]: ...
    def listar_tickets(self, limite: int = 100) -> list[dict]: ...
    def obtener_ticket(self, ticket_id: int) -> Optional[dict]: ...
    def listar_eventos(self, ticket_id: int) -> list[dict]: ...
    def listar_correos(self, ticket_id: int, limite: int = 20) -> list[dict]: ...
    def purgar_antiguos(self, dias: int, dry: bool = False) -> dict: ...
    # --- Etapa 1: etapa del ticket, avisos únicos, recordatorios ---
    def buscar_ticket_por_solicitud(self, nro_solicitud: str) -> Optional[dict]: ...
    def registrar_aviso(self, ticket_id: int, etapa: str, destinatario: str, ronda: int = 1,
                        canal: Optional[str] = None, texto: Optional[str] = None,
                        accion_id: Optional[int] = None, correo_id: Optional[int] = None) -> Optional[int]: ...
    def listar_avisos(self, ticket_id: int) -> list[dict]: ...
    def crear_recordatorio(self, ticket_id: int, motivo: str, destinatarios: Iterable[str],
                           vence_en: datetime, escala_en: Optional[datetime] = None,
                           correo_id: Optional[int] = None, nota: Optional[str] = None) -> Optional[int]: ...
    def listar_recordatorios(self, ticket_id: Optional[int] = None,
                             estados: Optional[Iterable[str]] = None) -> list[dict]: ...
    def actualizar_recordatorio(self, recordatorio_id: int, **campos: Any) -> None: ...
    def cerrar_recordatorios(self, ticket_id: int, estado: str, motivo: Optional[str] = None,
                             nota: Optional[str] = None) -> int: ...
    # --- Etapa 2: aprobaciones de Ceci (guía de aportación) + valores del worker ---
    def crear_aprobacion(self, ticket_id: int, tipo: str, texto: str, ronda: int = 1,
                         correo_id: Optional[int] = None, datos: Optional[dict] = None) -> Optional[int]: ...
    def obtener_aprobacion(self, aprobacion_id: int) -> Optional[dict]: ...
    def listar_aprobaciones(self, ticket_id: Optional[int] = None,
                            estados: Optional[Iterable[str]] = None) -> list[dict]: ...
    def actualizar_aprobacion(self, aprobacion_id: int, **campos: Any) -> None: ...
    def resolver_aprobacion(self, aprobacion_id: int, estado: str, por: str,
                            texto: Optional[str] = None) -> bool: ...
    def leer_valor(self, clave: str) -> Optional[str]: ...
    def guardar_valor(self, clave: str, valor: str) -> None: ...


# ------------------------------------------------------------------ Postgres
class RepositorioPostgres:
    def __init__(self, dsn: str, schema: str = "tickets_allianz"):
        self.schema = schema
        self.conn, self.driver = self._connect(dsn)

    @staticmethod
    def _connect(dsn: str):
        try:
            import psycopg  # v3
            # prepare_threshold=None desactiva los prepared statements: el pooler de
            # Supabase corre en modo transacción y no los mantiene entre conexiones
            # del pool → si no, revienta con InvalidSqlStatementName ("_pg3_0" ...).
            return psycopg.connect(dsn, autocommit=True, prepare_threshold=None), "psycopg"
        except ImportError:
            import psycopg2
            c = psycopg2.connect(dsn)
            c.autocommit = True
            return c, "psycopg2"

    def _t(self, nombre: str) -> str:
        return f"{self.schema}.{nombre}"

    def guardar_correo(self, correo: Correo, clf: Clasificacion, entidades: dict) -> tuple[int, bool]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""insert into {self._t('correos')}
                    (message_id, remitente, remitente_dominio, para, cc, asunto, cuerpo_texto,
                     fecha, tipo, confianza, motivo, necesita_llm, entidades, origen)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                    on conflict (message_id) do nothing
                    returning id""",
                (correo.message_id, correo.remitente, correo.remitente_dominio,
                 correo.para, correo.cc, correo.asunto, correo.cuerpo_texto, correo.fecha,
                 clf.tipo.value, clf.confianza, clf.motivo, clf.necesita_llm,
                 json.dumps(entidades, ensure_ascii=False), correo.origen),
            )
            fila = cur.fetchone()
            if fila:
                return int(fila[0]), True
            cur.execute(f"select id from {self._t('correos')} where message_id=%s", (correo.message_id,))
            return int(cur.fetchone()[0]), False

    def buscar_ticket(self, nro_ticket, poliza, cliente_correo) -> Optional[dict]:
        with self.conn.cursor() as cur:
            if nro_ticket:
                cur.execute(f"select * from {self._t('tickets')} where nro_ticket=%s limit 1", (nro_ticket,))
                r = self._row(cur)
                if r:
                    return r
            if poliza:
                cur.execute(f"select * from {self._t('tickets')} where poliza=%s order by created_at desc limit 1", (poliza,))
                r = self._row(cur)
                if r:
                    return r
            if cliente_correo:
                cur.execute(
                    f"select * from {self._t('tickets')} where cliente_correo=%s and estado not in ('resuelto') "
                    f"order by created_at desc limit 1", (cliente_correo,))
                return self._row(cur)
        return None

    def crear_ticket(self, datos: dict) -> int:
        cols = _cols_ticket(datos)
        vals = [datos.get(c) for c in cols]
        ph = ",".join(["%s"] * len(cols))
        with self.conn.cursor() as cur:
            cur.execute(f"insert into {self._t('tickets')} ({','.join(cols)}) values ({ph}) returning id", vals)
            return int(cur.fetchone()[0])

    def actualizar_ticket(self, ticket_id: int, **campos: Any) -> None:
        if not campos:
            return
        sets = ", ".join(f"{k}=%s" for k in campos)
        sets += ", ultima_actividad=now()"
        with self.conn.cursor() as cur:
            cur.execute(f"update {self._t('tickets')} set {sets} where id=%s", [*campos.values(), ticket_id])

    def vincular_correo(self, correo_id: int, ticket_id: int) -> None:
        with self.conn.cursor() as cur:
            cur.execute(f"update {self._t('correos')} set ticket_id=%s where id=%s", (ticket_id, correo_id))

    def agregar_evento(self, ticket_id, correo_id, tipo_evento, resumen) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                f"insert into {self._t('ticket_eventos')} (ticket_id, correo_id, tipo_evento, resumen) "
                f"values (%s,%s,%s,%s) returning id", (ticket_id, correo_id, tipo_evento, resumen))
            return int(cur.fetchone()[0])

    def crear_accion(self, ticket_id, tipo_accion, canal, payload, programada_para=None) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                f"insert into {self._t('acciones')} (ticket_id, tipo_accion, canal, estado, payload, programada_para) "
                f"values (%s,%s,%s,'sugerida',%s::jsonb,%s) returning id",
                (ticket_id, tipo_accion, canal, json.dumps(payload, ensure_ascii=False), programada_para))
            return int(cur.fetchone()[0])

    def actualizar_accion(self, accion_id, estado, resultado=None) -> None:
        res = json.dumps(resultado, ensure_ascii=False) if resultado is not None else None
        with self.conn.cursor() as cur:
            cur.execute(f"update {self._t('acciones')} set estado=%s, resultado=%s::jsonb where id=%s",
                        (estado, res, accion_id))

    def set_veredicto(self, accion_id, veredicto, nota=None) -> int:
        with self.conn.cursor() as cur:
            cur.execute(f"update {self._t('acciones')} set veredicto=%s, nota_revision=%s where id=%s",
                        (veredicto, nota, accion_id))
            return cur.rowcount

    def set_borrador(self, accion_id, borrador) -> int:
        with self.conn.cursor() as cur:
            cur.execute(f"update {self._t('acciones')} set borrador_editado=%s where id=%s",
                        (borrador, accion_id))
            return cur.rowcount

    def listar_acciones(self, ticket_id=None, estado=None) -> list[dict]:
        cond, args = [], []
        if ticket_id is not None:
            cond.append("ticket_id=%s"); args.append(ticket_id)
        if estado is not None:
            cond.append("estado=%s"); args.append(estado)
        where = (" where " + " and ".join(cond)) if cond else ""
        with self.conn.cursor() as cur:
            cur.execute(f"select * from {self._t('acciones')}{where} order by created_at", args)
            return self._rows(cur)

    def listar_tickets(self, limite: int = 100) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(f"select * from {self._t('tickets')} order by ultima_actividad desc limit %s", (limite,))
            return self._rows(cur)

    def obtener_ticket(self, ticket_id: int) -> Optional[dict]:
        with self.conn.cursor() as cur:
            cur.execute(f"select * from {self._t('tickets')} where id=%s", (ticket_id,))
            return self._row(cur)

    def listar_eventos(self, ticket_id: int) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(f"select * from {self._t('ticket_eventos')} where ticket_id=%s order by created_at", (ticket_id,))
            return self._rows(cur)

    def listar_correos(self, ticket_id: int, limite: int = 20) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(f"select * from {self._t('correos')} where ticket_id=%s "
                        f"order by fecha desc nulls last, id desc limit %s", (ticket_id, limite))
            return self._rows(cur)

    def purgar_antiguos(self, dias: int, dry: bool = False) -> dict:
        """Retención (6 meses): borra correos viejos y tickets resueltos viejos con su historial.
        Con `dry=True` solo cuenta lo que se borraría (no toca nada)."""
        corte = "now() - (%s || ' days')::interval"
        with self.conn.cursor() as cur:
            # Tickets resueltos más viejos que el corte → se van con sus eventos/acciones.
            cur.execute(f"select id from {self._t('tickets')} "
                        f"where estado='resuelto' and created_at < {corte}", (dias,))
            ids_tk = [r[0] for r in cur.fetchall()]
            cur.execute(f"select count(*) from {self._t('correos')} where created_at < {corte}", (dias,))
            n_correos = int(cur.fetchone()[0])
            resumen = {"correos": n_correos, "tickets_resueltos": len(ids_tk), "dry": dry}
            if dry or (n_correos == 0 and not ids_tk):
                return resumen
            if ids_tk:
                ph = ",".join(["%s"] * len(ids_tk))
                cur.execute(f"delete from {self._t('acciones')} where ticket_id in ({ph})", ids_tk)
                cur.execute(f"delete from {self._t('ticket_eventos')} where ticket_id in ({ph})", ids_tk)
                cur.execute(f"delete from {self._t('tickets')} where id in ({ph})", ids_tk)
            cur.execute(f"delete from {self._t('correos')} where created_at < {corte}", (dias,))
        return resumen

    # --- Etapa 1 ---
    def buscar_ticket_por_solicitud(self, nro_solicitud):
        if not nro_solicitud:
            return None
        with self.conn.cursor() as cur:
            cur.execute(f"select * from {self._t('tickets')} where nro_solicitud=%s "
                        f"order by created_at desc limit 1", (nro_solicitud,))
            return self._row(cur)

    def registrar_aviso(self, ticket_id, etapa, destinatario, ronda=1, canal=None, texto=None,
                        accion_id=None, correo_id=None):
        """Devuelve el id, o None si ese aviso ya se había registrado (no se repite)."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"insert into {self._t('avisos')} "
                f"(ticket_id, etapa, ronda, destinatario, canal, texto, accion_id, correo_id) "
                f"values (%s,%s,%s,%s,%s,%s,%s,%s) "
                f"on conflict (ticket_id, etapa, ronda, destinatario) do nothing returning id",
                (ticket_id, etapa, ronda, destinatario, canal, texto, accion_id, correo_id))
            fila = cur.fetchone()
            return int(fila[0]) if fila else None

    def listar_avisos(self, ticket_id):
        with self.conn.cursor() as cur:
            cur.execute(f"select * from {self._t('avisos')} where ticket_id=%s order by created_at, id", (ticket_id,))
            return self._rows(cur)

    def crear_recordatorio(self, ticket_id, motivo, destinatarios, vence_en, escala_en=None,
                           correo_id=None, nota=None):
        """Devuelve el id, o None si ya hay uno vivo (activo/escalado) para ese ticket y motivo."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"insert into {self._t('recordatorios')} "
                f"(ticket_id, motivo, destinatarios, vence_en, escala_en, correo_id, nota) "
                f"values (%s,%s,%s,%s,%s,%s,%s) "
                f"on conflict (ticket_id, motivo) where estado in ('activo', 'escalado') do nothing returning id",
                (ticket_id, motivo, list(destinatarios), vence_en, escala_en, correo_id, nota))
            fila = cur.fetchone()
            return int(fila[0]) if fila else None

    def listar_recordatorios(self, ticket_id=None, estados=None):
        cond, args = [], []
        if ticket_id is not None:
            cond.append("ticket_id=%s"); args.append(ticket_id)
        if estados:
            cond.append("estado = any(%s)"); args.append(list(estados))
        where = (" where " + " and ".join(cond)) if cond else ""
        with self.conn.cursor() as cur:
            cur.execute(f"select * from {self._t('recordatorios')}{where} order by vence_en, id", args)
            return self._rows(cur)

    def actualizar_recordatorio(self, recordatorio_id, **campos):
        if not campos:
            return
        sets = ", ".join(f"{k}=%s" for k in campos)
        with self.conn.cursor() as cur:
            cur.execute(f"update {self._t('recordatorios')} set {sets} where id=%s",
                        [*campos.values(), recordatorio_id])

    def cerrar_recordatorios(self, ticket_id, estado, motivo=None, nota=None):
        """Corta los recordatorios vivos del ticket (todos, o solo los de `motivo`)."""
        cond, args = "", [estado, nota, ticket_id, list(RECORDATORIO_VIVO)]
        if motivo:
            cond = " and motivo=%s"; args.append(motivo)
        with self.conn.cursor() as cur:
            cur.execute(f"update {self._t('recordatorios')} set estado=%s, nota=coalesce(%s, nota), "
                        f"cerrado_en=now() where ticket_id=%s and estado = any(%s){cond}", args)
            return cur.rowcount

    # --- Etapa 2 ---
    def crear_aprobacion(self, ticket_id, tipo, texto, ronda=1, correo_id=None, datos=None):
        """Devuelve el id, o None si ya existe la de ese (ticket, tipo, ronda): no se pide dos veces."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"insert into {self._t('aprobaciones')} (ticket_id, tipo, ronda, texto, correo_id, datos) "
                f"values (%s,%s,%s,%s,%s,%s::jsonb) on conflict (ticket_id, tipo, ronda) do nothing returning id",
                (ticket_id, tipo, ronda, texto, correo_id, json.dumps(datos or {}, ensure_ascii=False)))
            fila = cur.fetchone()
            return int(fila[0]) if fila else None

    def obtener_aprobacion(self, aprobacion_id):
        with self.conn.cursor() as cur:
            cur.execute(f"select * from {self._t('aprobaciones')} where id=%s", (aprobacion_id,))
            return self._row(cur)

    def listar_aprobaciones(self, ticket_id=None, estados=None):
        cond, args = [], []
        if ticket_id is not None:
            cond.append("ticket_id=%s"); args.append(ticket_id)
        if estados:
            cond.append("estado = any(%s)"); args.append(list(estados))
        where = (" where " + " and ".join(cond)) if cond else ""
        with self.conn.cursor() as cur:
            cur.execute(f"select * from {self._t('aprobaciones')}{where} order by created_at, id", args)
            return self._rows(cur)

    def actualizar_aprobacion(self, aprobacion_id, **campos):
        if not campos:
            return
        if "datos" in campos:
            campos["datos"] = json.dumps(campos["datos"] or {}, ensure_ascii=False)
        sets = ", ".join(f"{k}=%s::jsonb" if k == "datos" else f"{k}=%s" for k in campos)
        with self.conn.cursor() as cur:
            cur.execute(f"update {self._t('aprobaciones')} set {sets}, actualizado_en=now() where id=%s",
                        [*campos.values(), aprobacion_id])

    def resolver_aprobacion(self, aprobacion_id, estado, por, texto=None):
        """Atómico: solo resuelve si sigue pendiente (Telegram y el panel no la aprueban dos veces)."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"update {self._t('aprobaciones')} set estado=%s, resuelto_por=%s, resuelto_en=now(), "
                f"actualizado_en=now(), texto=coalesce(%s, texto), "
                f"version=version + (case when %s::text is null then 0 else 1 end) "
                f"where id=%s and estado='pendiente'", (estado, por, texto, texto, aprobacion_id))
            return cur.rowcount == 1

    def leer_valor(self, clave):
        with self.conn.cursor() as cur:
            cur.execute(f"select valor from {self._t('valores')} where clave=%s", (clave,))
            fila = cur.fetchone()
            return fila[0] if fila else None

    def guardar_valor(self, clave, valor):
        with self.conn.cursor() as cur:
            cur.execute(f"insert into {self._t('valores')} (clave, valor) values (%s,%s) "
                        f"on conflict (clave) do update set valor=excluded.valor, actualizado_en=now()",
                        (clave, valor))

    @staticmethod
    def _row(cur) -> Optional[dict]:
        fila = cur.fetchone()
        if not fila:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, fila))

    @staticmethod
    def _rows(cur) -> list[dict]:
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, f)) for f in cur.fetchall()]


# ------------------------------------------------------------------ SQLite (dev)
class RepositorioSQLite:
    def __init__(self, ruta: str):
        # check_same_thread=False: la API (FastAPI) atiende en otro hilo. Es la base de dev/tests.
        self.conn = sqlite3.connect(ruta, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._crear()

    def _crear(self):
        self.conn.executescript(
            """
            create table if not exists correos(
              id integer primary key autoincrement, message_id text unique, remitente text,
              remitente_dominio text, para text, cc text, asunto text, cuerpo_texto text,
              fecha text, tipo text, confianza real, motivo text, necesita_llm int,
              entidades text, ticket_id int, origen text, created_at text default (datetime('now')));
            create table if not exists tickets(
              id integer primary key autoincrement, nro_ticket text unique, poliza text,
              cliente_nombre text, cliente_correo text, asesor_correo text, daf text,
              estado text default 'abierto', delicado int default 0, autorizado int default 0,
              abierto_por text, gmail_thread_id text, asunto_hilo text, ultimo_message_id text,
              vence_en text, telefono_cliente text, telefono_asesor text,
              ultima_actividad text default (datetime('now')),
              created_at text default (datetime('now')));
            create table if not exists ticket_eventos(
              id integer primary key autoincrement, ticket_id int, correo_id int,
              tipo_evento text, resumen text, created_at text default (datetime('now')));
            create table if not exists acciones(
              id integer primary key autoincrement, ticket_id int, tipo_accion text, canal text,
              estado text default 'sugerida', payload text, resultado text, programada_para text,
              veredicto text default 'pendiente', nota_revision text, borrador_editado text,
              created_at text default (datetime('now')));
            create table if not exists avisos(
              id integer primary key autoincrement, ticket_id int not null, etapa text not null,
              ronda int not null default 1, destinatario text not null, canal text, texto text,
              accion_id int, correo_id int, created_at text default (datetime('now')),
              unique (ticket_id, etapa, ronda, destinatario));
            create table if not exists recordatorios(
              id integer primary key autoincrement, ticket_id int not null, motivo text not null,
              destinatarios text not null default '[]', vence_en text not null, escala_en text,
              estado text not null default 'activo', correo_id int, recordado_en text,
              escalado_en text, cerrado_en text, nota text, created_at text default (datetime('now')));
            create unique index if not exists uq_recordatorio_vivo
              on recordatorios (ticket_id, motivo) where estado in ('activo', 'escalado');
            create table if not exists aprobaciones(
              id integer primary key autoincrement, ticket_id int not null, tipo text not null,
              ronda int not null default 1, texto text not null, version int not null default 1,
              estado text not null default 'pendiente', telegram_chat_id text, telegram_msg_id text,
              resuelto_por text, resuelto_en text, correo_id int, datos text default '{}',
              created_at text default (datetime('now')), actualizado_en text default (datetime('now')),
              unique (ticket_id, tipo, ronda));
            create table if not exists valores(
              clave text primary key, valor text, actualizado_en text default (datetime('now')));
            """
        )
        # Bases de dev creadas antes de la Etapa 1: sumar las columnas que falten.
        tiene = {r["name"] for r in self.conn.execute("pragma table_info(tickets)")}
        for col, tipo in (("proceso", "text"), ("producto", "text"), ("etapa", "text"),
                          ("etapa_desde", "text"), ("etapa_ronda", "int default 1"), ("nro_solicitud", "text"),
                          ("identificado_por", "text"), ("titulo_hilo", "text")):
            if col not in tiene:
                self.conn.execute(f"alter table tickets add column {col} {tipo}")
        if "datos" not in {r["name"] for r in self.conn.execute("pragma table_info(aprobaciones)")}:
            self.conn.execute("alter table aprobaciones add column datos text default '{}'")
        self.conn.commit()

    @staticmethod
    def _ts(v):
        """datetime → texto ISO en UTC (comparable como string en SQLite)."""
        if isinstance(v, datetime):
            v = (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()
        return v

    @staticmethod
    def _recordatorio(r) -> dict:
        d = dict(r)
        d["destinatarios"] = json.loads(d.get("destinatarios") or "[]")
        return d

    def guardar_correo(self, correo: Correo, clf: Clasificacion, entidades: dict) -> tuple[int, bool]:
        cur = self.conn.cursor()
        cur.execute("select id from correos where message_id=?", (correo.message_id,))
        r = cur.fetchone()
        if r:
            return int(r["id"]), False
        cur.execute(
            """insert into correos(message_id,remitente,remitente_dominio,para,cc,asunto,
               cuerpo_texto,fecha,tipo,confianza,motivo,necesita_llm,entidades,origen)
               values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (correo.message_id, correo.remitente, correo.remitente_dominio,
             json.dumps(correo.para), json.dumps(correo.cc), correo.asunto, correo.cuerpo_texto,
             str(correo.fecha) if correo.fecha else None, clf.tipo.value, clf.confianza, clf.motivo,
             int(clf.necesita_llm), json.dumps(entidades, ensure_ascii=False), correo.origen),
        )
        self.conn.commit()
        return int(cur.lastrowid), True

    def buscar_ticket(self, nro_ticket, poliza, cliente_correo) -> Optional[dict]:
        cur = self.conn.cursor()
        for campo, val, extra in (("nro_ticket", nro_ticket, ""), ("poliza", poliza, ""),
                                  ("cliente_correo", cliente_correo, " and estado!='resuelto'")):
            if val:
                cur.execute(f"select * from tickets where {campo}=?{extra} order by created_at desc limit 1", (val,))
                r = cur.fetchone()
                if r:
                    return dict(r)
        return None

    def crear_ticket(self, datos: dict) -> int:
        cols = _cols_ticket(datos)
        vals = [self._ts(datos.get(c)) for c in cols]
        cur = self.conn.cursor()
        cur.execute(f"insert into tickets({','.join(cols)}) values({','.join('?'*len(cols))})", vals)
        self.conn.commit()
        return int(cur.lastrowid)

    def actualizar_ticket(self, ticket_id: int, **campos: Any) -> None:
        if not campos:
            return
        sets = ", ".join(f"{k}=?" for k in campos) + ", ultima_actividad=datetime('now')"
        self.conn.execute(f"update tickets set {sets} where id=?",
                          [*(self._ts(v) for v in campos.values()), ticket_id])
        self.conn.commit()

    def vincular_correo(self, correo_id: int, ticket_id: int) -> None:
        self.conn.execute("update correos set ticket_id=? where id=?", (ticket_id, correo_id))
        self.conn.commit()

    def agregar_evento(self, ticket_id, correo_id, tipo_evento, resumen) -> int:
        cur = self.conn.cursor()
        cur.execute("insert into ticket_eventos(ticket_id,correo_id,tipo_evento,resumen) values(?,?,?,?)",
                    (ticket_id, correo_id, tipo_evento, resumen))
        self.conn.commit()
        return int(cur.lastrowid)

    def crear_accion(self, ticket_id, tipo_accion, canal, payload, programada_para=None) -> int:
        cur = self.conn.cursor()
        cur.execute("insert into acciones(ticket_id,tipo_accion,canal,estado,payload,programada_para) "
                    "values(?,?,?,'sugerida',?,?)",
                    (ticket_id, tipo_accion, canal, json.dumps(payload, ensure_ascii=False), programada_para))
        self.conn.commit()
        return int(cur.lastrowid)

    def actualizar_accion(self, accion_id, estado, resultado=None) -> None:
        res = json.dumps(resultado, ensure_ascii=False) if resultado is not None else None
        self.conn.execute("update acciones set estado=?, resultado=? where id=?", (estado, res, accion_id))
        self.conn.commit()

    def set_veredicto(self, accion_id, veredicto, nota=None) -> int:
        cur = self.conn.execute("update acciones set veredicto=?, nota_revision=? where id=?",
                                (veredicto, nota, accion_id))
        self.conn.commit()
        return cur.rowcount

    def set_borrador(self, accion_id, borrador) -> int:
        cur = self.conn.execute("update acciones set borrador_editado=? where id=?", (borrador, accion_id))
        self.conn.commit()
        return cur.rowcount

    def listar_acciones(self, ticket_id=None, estado=None) -> list[dict]:
        cond, args = [], []
        if ticket_id is not None:
            cond.append("ticket_id=?"); args.append(ticket_id)
        if estado is not None:
            cond.append("estado=?"); args.append(estado)
        where = (" where " + " and ".join(cond)) if cond else ""
        cur = self.conn.execute(f"select * from acciones{where} order by created_at", args)
        return [dict(r) for r in cur.fetchall()]

    def listar_tickets(self, limite: int = 100) -> list[dict]:
        cur = self.conn.execute("select * from tickets order by ultima_actividad desc limit ?", (limite,))
        return [dict(r) for r in cur.fetchall()]

    def obtener_ticket(self, ticket_id: int) -> Optional[dict]:
        cur = self.conn.execute("select * from tickets where id=?", (ticket_id,))
        r = cur.fetchone()
        return dict(r) if r else None

    def listar_eventos(self, ticket_id: int) -> list[dict]:
        cur = self.conn.execute("select * from ticket_eventos where ticket_id=? order by created_at", (ticket_id,))
        return [dict(r) for r in cur.fetchall()]

    def listar_correos(self, ticket_id: int, limite: int = 20) -> list[dict]:
        cur = self.conn.execute("select * from correos where ticket_id=? order by fecha desc, id desc limit ?",
                                (ticket_id, limite))
        return [dict(r) for r in cur.fetchall()]

    def purgar_antiguos(self, dias: int, dry: bool = False) -> dict:
        """Retención (6 meses): borra correos viejos y tickets resueltos viejos con su historial.
        Con `dry=True` solo cuenta lo que se borraría (no toca nada)."""
        corte = f"-{int(dias)} days"
        cur = self.conn.cursor()
        cur.execute("select id from tickets where estado='resuelto' and created_at < datetime('now', ?)", (corte,))
        ids_tk = [r["id"] for r in cur.fetchall()]
        cur.execute("select count(*) as n from correos where created_at < datetime('now', ?)", (corte,))
        n_correos = int(cur.fetchone()["n"])
        resumen = {"correos": n_correos, "tickets_resueltos": len(ids_tk), "dry": dry}
        if dry or (n_correos == 0 and not ids_tk):
            return resumen
        if ids_tk:
            ph = ",".join("?" * len(ids_tk))
            cur.execute(f"delete from acciones where ticket_id in ({ph})", ids_tk)
            cur.execute(f"delete from ticket_eventos where ticket_id in ({ph})", ids_tk)
            cur.execute(f"delete from tickets where id in ({ph})", ids_tk)
        cur.execute("delete from correos where created_at < datetime('now', ?)", (corte,))
        self.conn.commit()
        return resumen

    # --- Etapa 1 ---
    def buscar_ticket_por_solicitud(self, nro_solicitud):
        if not nro_solicitud:
            return None
        r = self.conn.execute("select * from tickets where nro_solicitud=? order by created_at desc, id desc limit 1",
                              (nro_solicitud,)).fetchone()
        return dict(r) if r else None

    def registrar_aviso(self, ticket_id, etapa, destinatario, ronda=1, canal=None, texto=None,
                        accion_id=None, correo_id=None):
        cur = self.conn.execute(
            "insert or ignore into avisos(ticket_id,etapa,ronda,destinatario,canal,texto,accion_id,correo_id) "
            "values(?,?,?,?,?,?,?,?)", (ticket_id, etapa, ronda, destinatario, canal, texto, accion_id, correo_id))
        self.conn.commit()
        return int(cur.lastrowid) if cur.rowcount else None

    def listar_avisos(self, ticket_id):
        cur = self.conn.execute("select * from avisos where ticket_id=? order by created_at, id", (ticket_id,))
        return [dict(r) for r in cur.fetchall()]

    def crear_recordatorio(self, ticket_id, motivo, destinatarios, vence_en, escala_en=None,
                           correo_id=None, nota=None):
        cur = self.conn.execute(
            "insert or ignore into recordatorios(ticket_id,motivo,destinatarios,vence_en,escala_en,correo_id,nota) "
            "values(?,?,?,?,?,?,?)",
            (ticket_id, motivo, json.dumps(list(destinatarios)), self._ts(vence_en), self._ts(escala_en),
             correo_id, nota))
        self.conn.commit()
        return int(cur.lastrowid) if cur.rowcount else None

    def listar_recordatorios(self, ticket_id=None, estados=None):
        cond, args = [], []
        if ticket_id is not None:
            cond.append("ticket_id=?"); args.append(ticket_id)
        if estados:
            estados = list(estados)
            cond.append(f"estado in ({','.join('?' * len(estados))})"); args.extend(estados)
        where = (" where " + " and ".join(cond)) if cond else ""
        cur = self.conn.execute(f"select * from recordatorios{where} order by vence_en, id", args)
        return [self._recordatorio(r) for r in cur.fetchall()]

    def actualizar_recordatorio(self, recordatorio_id, **campos):
        if not campos:
            return
        if "destinatarios" in campos:
            campos["destinatarios"] = json.dumps(list(campos["destinatarios"]))
        sets = ", ".join(f"{k}=?" for k in campos)
        self.conn.execute(f"update recordatorios set {sets} where id=?",
                          [*(self._ts(v) for v in campos.values()), recordatorio_id])
        self.conn.commit()

    def cerrar_recordatorios(self, ticket_id, estado, motivo=None, nota=None):
        cond, args = "", [estado, nota, self._ts(datetime.now(timezone.utc)), ticket_id, *RECORDATORIO_VIVO]
        if motivo:
            cond = " and motivo=?"; args.append(motivo)
        cur = self.conn.execute(
            f"update recordatorios set estado=?, nota=coalesce(?, nota), cerrado_en=? "
            f"where ticket_id=? and estado in (?, ?){cond}", args)
        self.conn.commit()
        return cur.rowcount

    # --- Etapa 2 ---
    def crear_aprobacion(self, ticket_id, tipo, texto, ronda=1, correo_id=None, datos=None):
        cur = self.conn.execute(
            "insert or ignore into aprobaciones(ticket_id,tipo,ronda,texto,correo_id,datos) values(?,?,?,?,?,?)",
            (ticket_id, tipo, ronda, texto, correo_id, json.dumps(datos or {}, ensure_ascii=False)))
        self.conn.commit()
        return int(cur.lastrowid) if cur.rowcount else None

    @staticmethod
    def _aprobacion(r) -> dict:
        d = dict(r)
        d["datos"] = json.loads(d.get("datos") or "{}")
        return d

    def obtener_aprobacion(self, aprobacion_id):
        r = self.conn.execute("select * from aprobaciones where id=?", (aprobacion_id,)).fetchone()
        return self._aprobacion(r) if r else None

    def listar_aprobaciones(self, ticket_id=None, estados=None):
        cond, args = [], []
        if ticket_id is not None:
            cond.append("ticket_id=?"); args.append(ticket_id)
        if estados:
            estados = list(estados)
            cond.append(f"estado in ({','.join('?' * len(estados))})"); args.extend(estados)
        where = (" where " + " and ".join(cond)) if cond else ""
        cur = self.conn.execute(f"select * from aprobaciones{where} order by created_at, id", args)
        return [self._aprobacion(r) for r in cur.fetchall()]

    def actualizar_aprobacion(self, aprobacion_id, **campos):
        if not campos:
            return
        if "datos" in campos:
            campos["datos"] = json.dumps(campos["datos"] or {}, ensure_ascii=False)
        sets = ", ".join(f"{k}=?" for k in campos)
        self.conn.execute(f"update aprobaciones set {sets}, actualizado_en=? where id=?",
                          [*(self._ts(v) for v in campos.values()), self._ts(datetime.now(timezone.utc)),
                           aprobacion_id])
        self.conn.commit()

    def resolver_aprobacion(self, aprobacion_id, estado, por, texto=None):
        ahora = self._ts(datetime.now(timezone.utc))
        cur = self.conn.execute(
            "update aprobaciones set estado=?, resuelto_por=?, resuelto_en=?, actualizado_en=?, "
            "texto=coalesce(?, texto), version=version + (case when ? is null then 0 else 1 end) "
            "where id=? and estado='pendiente'", (estado, por, ahora, ahora, texto, texto, aprobacion_id))
        self.conn.commit()
        return cur.rowcount == 1

    def leer_valor(self, clave):
        r = self.conn.execute("select valor from valores where clave=?", (clave,)).fetchone()
        return r["valor"] if r else None

    def guardar_valor(self, clave, valor):
        self.conn.execute("insert into valores(clave, valor) values(?,?) "
                          "on conflict(clave) do update set valor=excluded.valor", (clave, valor))
        self.conn.commit()


def get_repo() -> Repositorio:
    """Postgres/Supabase si hay DATABASE_URL; si no, SQLite local (dev)."""
    if config.hay_db():
        return RepositorioPostgres(config.DATABASE_URL, config.DB_SCHEMA)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return RepositorioSQLite(str(config.DATA_DIR / "tickets_allianz.sqlite"))
