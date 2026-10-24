-- Migración Etapa 2 (proceso corto + trámites) — 2026-10-20
-- Para correr A MANO en el SQL Editor de Supabase, DESPUÉS de docs/migracion_etapa1_2026-10-19.sql.
-- Es 100 % aditiva: una columna y dos tablas nuevas. No toca ni borra datos existentes
-- (por eso no hace falta respaldo). Se puede correr dos veces (if not exists).

begin;

-- tickets: el asunto del trámite tal como lo abrimos ("[EXT] Aplicación de mensualidad …"). Va en
-- todos los avisos del trámite (n° de ticket + cliente + asunto) y en sus recordatorios.
alter table tickets_allianz.tickets add column if not exists titulo_hilo text;

-- aprobaciones: lo que Ceci tiene que aprobar antes de que salga (hoy: la guía de aportación
-- del proceso corto). Una por (ticket, tipo, ronda): no se le pide dos veces lo mismo.
create table if not exists tickets_allianz.aprobaciones (
  id                bigint generated always as identity primary key,
  ticket_id         bigint  not null,
  tipo              text    not null,                -- guia_aportacion
  ronda             integer not null default 1,
  texto             text    not null,                -- lo que va a salir (Ceci lo puede corregir)
  version           integer not null default 1,      -- sube cada vez que Ceci lo corrige
  estado            text    not null default 'pendiente',  -- pendiente / aprobada / descartada
  telegram_chat_id  text,
  telegram_msg_id   text,                            -- el mensaje con los botones
  resuelto_por      text,                            -- telegram:<usuario> / panel:<usuario>
  resuelto_en       timestamptz,
  correo_id         bigint,                          -- el correo de Allianz que la disparó
  datos             jsonb   not null default '{}',   -- guía: nombre, producto, póliza + monto y datos de depósito (Ceci)
  created_at        timestamptz not null default now(),
  actualizado_en    timestamptz not null default now(),
  constraint uq_aprobaciones_unica unique (ticket_id, tipo, ronda)
);
create index if not exists ix_aprobaciones_estado on tickets_allianz.aprobaciones (estado);

-- valores: datos chicos del worker (hoy: hasta qué mensaje de Telegram ya se leyó).
create table if not exists tickets_allianz.valores (
  clave           text primary key,
  valor           text,
  actualizado_en  timestamptz not null default now()
);

commit;

-- Verificación (tiene que devolver 3 filas con "ok")
select 'tickets.titulo_hilo' as chequeo,
       case when exists (select 1 from information_schema.columns where table_schema = 'tickets_allianz'
                          and table_name = 'tickets' and column_name = 'titulo_hilo') then 'ok' else 'FALTA' end as resultado
union all
select 'tabla aprobaciones',
       case when to_regclass('tickets_allianz.aprobaciones') is not null then 'ok' else 'FALTA' end
union all
select 'tabla valores', case when to_regclass('tickets_allianz.valores') is not null then 'ok' else 'FALTA' end;

-- Vuelta atrás (solo si hace falta; sacar los "--" y correr)
-- begin;
-- drop table if exists tickets_allianz.aprobaciones;
-- drop table if exists tickets_allianz.valores;
-- alter table tickets_allianz.tickets drop column if exists titulo_hilo;
-- commit;
