-- Bootstrap + migraciones para la Supabase de producción de Babilonia.
-- Esquema AISLADO `tickets_allianz`: no toca ninguna tabla existente de Babilonia.
-- 100% idempotente (create ... if not exists / add column if not exists): se puede correr
-- varias veces sin romper nada. SQLite (dev) crea todo esto solo; esto es SOLO para Postgres.

create schema if not exists tickets_allianz;

-- ─────────────────────────── correos ───────────────────────────
create table if not exists tickets_allianz.correos (
  id                bigint generated always as identity primary key,
  message_id        text unique,
  remitente         text,
  remitente_dominio text,
  para              text[],
  cc                text[],
  asunto            text,
  cuerpo_texto      text,
  fecha             timestamptz,
  tipo              text,
  confianza         double precision,
  motivo            text,
  necesita_llm      boolean,
  entidades         jsonb,
  ticket_id         bigint,
  origen            text,
  created_at        timestamptz not null default now()
);

-- ─────────────────────────── tickets ───────────────────────────
create table if not exists tickets_allianz.tickets (
  id                bigint generated always as identity primary key,
  nro_ticket        text unique,
  poliza            text,
  cliente_nombre    text,
  cliente_correo    text,
  asesor_correo     text,
  daf               text,
  estado            text default 'abierto',
  delicado          boolean default false,
  autorizado        boolean default false,
  abierto_por       text,
  gmail_thread_id   text,
  asunto_hilo       text,
  ultimo_message_id text,
  vence_en          text,
  telefono_cliente  text,
  telefono_asesor   text,
  ultima_actividad  timestamptz not null default now(),
  created_at        timestamptz not null default now()
);

-- ────────────────────── ticket_eventos (bitácora) ──────────────────────
create table if not exists tickets_allianz.ticket_eventos (
  id          bigint generated always as identity primary key,
  ticket_id   bigint,
  correo_id   bigint,
  tipo_evento text,
  resumen     text,
  created_at  timestamptz not null default now()
);

-- ─────────────────────────── acciones ───────────────────────────
create table if not exists tickets_allianz.acciones (
  id              bigint generated always as identity primary key,
  ticket_id       bigint,
  tipo_accion     text,
  canal           text,
  estado          text default 'sugerida',
  payload         jsonb,
  resultado       jsonb,
  programada_para text,
  veredicto        text default 'pendiente',
  nota_revision    text,
  borrador_editado text,
  created_at      timestamptz not null default now()
);

-- ─────────── Migraciones sobre instalaciones previas (idempotentes) ───────────
-- Fase B — hilo de correo por ticket (responder en el mismo hilo).
alter table tickets_allianz.tickets add column if not exists gmail_thread_id   text;
alter table tickets_allianz.tickets add column if not exists asunto_hilo        text;
alter table tickets_allianz.tickets add column if not exists ultimo_message_id  text;
-- Fase C — SLA / vencimiento del ticket.
alter table tickets_allianz.tickets add column if not exists vence_en          text;
-- Fase F — teléfonos de cliente/asesor (de Notion Emisiones) para el ruteo por WATI.
alter table tickets_allianz.tickets add column if not exists telefono_cliente  text;
alter table tickets_allianz.tickets add column if not exists telefono_asesor   text;
-- Panel de revisión (sandbox): veredicto del equipo por acción + borrador editable a mano.
alter table tickets_allianz.acciones add column if not exists veredicto        text default 'pendiente';
alter table tickets_allianz.acciones add column if not exists nota_revision    text;
alter table tickets_allianz.acciones add column if not exists borrador_editado text;

-- Etapa 1 (proceso largo, 19/10) — etapa del ticket + avisos únicos + recordatorios.
-- Versión con respaldo y vuelta atrás: docs/migracion_etapa1_2026-10-19.sql
alter table tickets_allianz.tickets add column if not exists proceso       text;
alter table tickets_allianz.tickets add column if not exists producto      text;
alter table tickets_allianz.tickets add column if not exists etapa         text;
alter table tickets_allianz.tickets add column if not exists etapa_desde   timestamptz;
alter table tickets_allianz.tickets add column if not exists etapa_ronda   integer default 1;
alter table tickets_allianz.tickets add column if not exists nro_solicitud text;

create table if not exists tickets_allianz.avisos (
  id            bigint generated always as identity primary key,
  ticket_id     bigint not null,
  etapa         text   not null,
  ronda         integer not null default 1,
  destinatario  text   not null,
  canal         text,
  texto         text,
  accion_id     bigint,
  correo_id     bigint,
  created_at    timestamptz not null default now(),
  constraint uq_avisos_unico unique (ticket_id, etapa, ronda, destinatario)
);

create table if not exists tickets_allianz.recordatorios (
  id             bigint generated always as identity primary key,
  ticket_id      bigint not null,
  motivo         text   not null,
  destinatarios  text[] not null default '{}',
  vence_en       timestamptz not null,
  escala_en      timestamptz,
  estado         text   not null default 'activo',
  correo_id      bigint,
  recordado_en   timestamptz,
  escalado_en    timestamptz,
  cerrado_en     timestamptz,
  nota           text,
  created_at     timestamptz not null default now()
);

-- ─────────────────────────── índices ───────────────────────────
create index if not exists ix_tickets_etapa         on tickets_allianz.tickets (etapa);
create index if not exists ix_tickets_solicitud     on tickets_allianz.tickets (nro_solicitud);
create index if not exists ix_avisos_ticket         on tickets_allianz.avisos (ticket_id);
create index if not exists ix_recordatorios_vence   on tickets_allianz.recordatorios (estado, vence_en);
create unique index if not exists uq_recordatorio_vivo
  on tickets_allianz.recordatorios (ticket_id, motivo) where estado in ('activo', 'escalado');
create index if not exists ix_correos_ticket   on tickets_allianz.correos     (ticket_id);
create index if not exists ix_eventos_ticket    on tickets_allianz.ticket_eventos (ticket_id);
create index if not exists ix_acciones_ticket   on tickets_allianz.acciones    (ticket_id);
create index if not exists ix_acciones_estado   on tickets_allianz.acciones    (estado);
create index if not exists ix_tickets_poliza    on tickets_allianz.tickets     (poliza);
create index if not exists ix_tickets_cliente   on tickets_allianz.tickets     (cliente_correo);
create index if not exists ix_tickets_vence     on tickets_allianz.tickets     (vence_en);
