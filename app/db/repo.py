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
from typing import Any, Optional, Protocol

from app import config
from app.models import Clasificacion, Correo


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
    def listar_acciones(self, ticket_id: Optional[int] = None, estado: Optional[str] = None) -> list[dict]: ...
    def listar_tickets(self, limite: int = 100) -> list[dict]: ...
    def obtener_ticket(self, ticket_id: int) -> Optional[dict]: ...
    def listar_eventos(self, ticket_id: int) -> list[dict]: ...


# ------------------------------------------------------------------ Postgres
class RepositorioPostgres:
    def __init__(self, dsn: str, schema: str = "tickets_allianz"):
        self.schema = schema
        self.conn, self.driver = self._connect(dsn)

    @staticmethod
    def _connect(dsn: str):
        try:
            import psycopg  # v3
            return psycopg.connect(dsn, autocommit=True), "psycopg"
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
        cols = ["nro_ticket", "poliza", "cliente_nombre", "cliente_correo", "asesor_correo",
                "daf", "estado", "delicado", "autorizado", "abierto_por"]
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
        self.conn = sqlite3.connect(ruta)
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
              abierto_por text, ultima_actividad text default (datetime('now')),
              created_at text default (datetime('now')));
            create table if not exists ticket_eventos(
              id integer primary key autoincrement, ticket_id int, correo_id int,
              tipo_evento text, resumen text, created_at text default (datetime('now')));
            create table if not exists acciones(
              id integer primary key autoincrement, ticket_id int, tipo_accion text, canal text,
              estado text default 'sugerida', payload text, resultado text, programada_para text,
              created_at text default (datetime('now')));
            """
        )
        self.conn.commit()

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
        cols = ["nro_ticket", "poliza", "cliente_nombre", "cliente_correo", "asesor_correo",
                "daf", "estado", "delicado", "autorizado", "abierto_por"]
        vals = [datos.get(c) for c in cols]
        cur = self.conn.cursor()
        cur.execute(f"insert into tickets({','.join(cols)}) values({','.join('?'*len(cols))})", vals)
        self.conn.commit()
        return int(cur.lastrowid)

    def actualizar_ticket(self, ticket_id: int, **campos: Any) -> None:
        if not campos:
            return
        sets = ", ".join(f"{k}=?" for k in campos) + ", ultima_actividad=datetime('now')"
        self.conn.execute(f"update tickets set {sets} where id=?", [*campos.values(), ticket_id])
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


def get_repo() -> Repositorio:
    """Postgres/Supabase si hay DATABASE_URL; si no, SQLite local (dev)."""
    if config.hay_db():
        return RepositorioPostgres(config.DATABASE_URL, config.DB_SCHEMA)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return RepositorioSQLite(str(config.DATA_DIR / "tickets_allianz.sqlite"))
