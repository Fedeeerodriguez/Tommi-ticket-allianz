-- Migración Etapa 1 (proceso largo) — 2026-10-19
-- Para correr A MANO en el SQL Editor de Supabase (proyecto de Babilonia).
-- Es 100 % aditiva: agrega columnas y tablas, no modifica ni borra datos existentes.
-- Se puede correr dos veces sin romper nada (if not exists).
-- Orden: 1) respaldo · 2) migración · 3) verificación. La vuelta atrás (4) va comentada al final.

begin;

-- ───────────── 1) Respaldo de tickets (por si hay que volver atrás) ─────────────
create table if not exists tickets_allianz.tickets_respaldo_20261019 as
  table tickets_allianz.tickets;

-- ───────────── 2) Migración ─────────────
-- tickets: en qué etapa del proceso está cada ticket.
alter table tickets_allianz.tickets add column if not exists proceso       text;         -- largo / corto / tramite
alter table tickets_allianz.tickets add column if not exists producto      text;         -- GMMI, VIPP, OP3D, ...
alter table tickets_allianz.tickets add column if not exists etapa         text;         -- apertura, requerimiento, ...
alter table tickets_allianz.tickets add column if not exists etapa_desde   timestamptz;  -- cuándo entró a la etapa
alter table tickets_allianz.tickets add column if not exists etapa_ronda   integer default 1; -- sube si Allianz pide algo de nuevo después de C4
alter table tickets_allianz.tickets add column if not exists nro_solicitud text;         -- n° de solicitud de Allianz

-- avisos: un aviso por (ticket, etapa, ronda, destinatario). La clave única hace
-- imposible mandar el mismo aviso dos veces (la causa de los "4+ avisos").
create table if not exists tickets_allianz.avisos (
  id            bigint generated always as identity primary key,
  ticket_id     bigint not null,
  etapa         text   not null,
  ronda         integer not null default 1,
  destinatario  text   not null,               -- ceci / asesor / cliente
  canal         text,                          -- wati / email / panel
  texto         text,
  accion_id     bigint,                        -- la acción de la cola que lo manda
  correo_id     bigint,                        -- el correo de Allianz que lo disparó
  created_at    timestamptz not null default now(),
  constraint uq_avisos_unico unique (ticket_id, etapa, ronda, destinatario)
);

-- recordatorios: a lo sumo uno vivo por (ticket, motivo).
create table if not exists tickets_allianz.recordatorios (
  id             bigint generated always as identity primary key,
  ticket_id      bigint not null,
  motivo         text   not null,              -- requerimiento / esperando_allianz
  destinatarios  text[] not null default '{}', -- a quién se le recuerda
  vence_en       timestamptz not null,
  escala_en      timestamptz,                  -- vence_en + 24 h hábiles
  estado         text   not null default 'activo',  -- activo / escalado / cumplido / cancelado
  correo_id      bigint,                       -- el correo que lo arrancó
  recordado_en   timestamptz,
  escalado_en    timestamptz,
  cerrado_en     timestamptz,
  nota           text,
  created_at     timestamptz not null default now()
);

create index if not exists ix_tickets_etapa         on tickets_allianz.tickets (etapa);
create index if not exists ix_tickets_solicitud     on tickets_allianz.tickets (nro_solicitud);
create index if not exists ix_avisos_ticket         on tickets_allianz.avisos (ticket_id);
create index if not exists ix_recordatorios_vence   on tickets_allianz.recordatorios (estado, vence_en);
create unique index if not exists uq_recordatorio_vivo
  on tickets_allianz.recordatorios (ticket_id, motivo) where estado in ('activo', 'escalado');

commit;

-- ───────────── 3) Verificación (tiene que devolver 3 filas con "ok") ─────────────
select 'tickets: columnas nuevas' as chequeo,
       case when count(*) = 6 then 'ok' else 'FALTA' end as resultado
  from information_schema.columns
 where table_schema = 'tickets_allianz' and table_name = 'tickets'
   and column_name in ('proceso','producto','etapa','etapa_desde','etapa_ronda','nro_solicitud')
union all
select 'tabla avisos',        case when to_regclass('tickets_allianz.avisos') is not null then 'ok' else 'FALTA' end
union all
select 'tabla recordatorios', case when to_regclass('tickets_allianz.recordatorios') is not null then 'ok' else 'FALTA' end;

-- ───────────── 4) Vuelta atrás (solo si hace falta; sacar los "--" y correr) ─────────────
-- begin;
-- drop table if exists tickets_allianz.avisos;
-- drop table if exists tickets_allianz.recordatorios;
-- alter table tickets_allianz.tickets
--   drop column if exists proceso, drop column if exists producto, drop column if exists etapa,
--   drop column if exists etapa_desde, drop column if exists etapa_ronda, drop column if exists nro_solicitud;
-- commit;
-- El respaldo tickets_allianz.tickets_respaldo_20261019 se puede borrar cuando todo esté estable.
