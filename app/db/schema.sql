-- Esquema aislado del sistema de tickets Allianz, en la misma Supabase de Tommy.
-- Adjuntos: el binario va a Supabase Storage; acá solo texto extraído + referencia.
-- created_at en todo para la purga/compresión cada 6 meses (RETENCION_DIAS).

create schema if not exists tickets_allianz;

-- ---------- Correos (idempotente por message_id) ----------
create table if not exists tickets_allianz.correos (
    id              bigint generated always as identity primary key,
    message_id      text unique not null,
    remitente       text,
    remitente_dominio text,
    para            text[],
    cc              text[],
    asunto          text,
    cuerpo_texto    text,
    fecha           timestamptz,
    -- clasificación
    tipo            text,          -- TipoCorreo (A_..., B_..., etc.)
    confianza       real,
    motivo          text,
    necesita_llm    boolean default false,
    entidades       jsonb default '{}'::jsonb,   -- nº ticket, póliza, cliente...
    ticket_id       bigint,        -- FK lógica a tickets (se setea en enriquecimiento)
    origen          text,          -- imap:<uid> / nombre .eml
    created_at      timestamptz default now()
);
create index if not exists idx_correos_created on tickets_allianz.correos (created_at);
create index if not exists idx_correos_tipo on tickets_allianz.correos (tipo);

-- ---------- Adjuntos (referencia a Storage; texto extraído en DB) ----------
create table if not exists tickets_allianz.adjuntos (
    id              bigint generated always as identity primary key,
    correo_id       bigint references tickets_allianz.correos(id) on delete cascade,
    nombre          text,
    mime            text,
    tamano_bytes    bigint,
    storage_path    text,          -- path en el bucket de Supabase Storage
    texto_extraido  text,          -- texto del PDF para clasificar/buscar/reenviar
    created_at      timestamptz default now()
);

-- ---------- Tickets ----------
create table if not exists tickets_allianz.tickets (
    id              bigint generated always as identity primary key,
    nro_ticket      text,          -- folio/ticket de Allianz (cuando se conoce)
    poliza          text,
    cliente_nombre  text,
    cliente_correo  text,
    asesor_correo   text,          -- resuelto vía Notion
    daf             text,          -- resuelto vía Notion
    estado          text default 'abierto',   -- EstadoTicket
    delicado        boolean default false,    -- si va forzosamente con Ceci
    autorizado      boolean default false,    -- autorización del prospecto para actuar
    abierto_por     text,          -- cliente / asesor / allianz / tommy
    notion_page_id  text,          -- página en la base Tickets Allianz de Notion (write-back)
    ultima_actividad timestamptz default now(),
    created_at      timestamptz default now(),
    unique (nro_ticket)
);
create index if not exists idx_tickets_estado on tickets_allianz.tickets (estado);
create index if not exists idx_tickets_actividad on tickets_allianz.tickets (ultima_actividad);

-- ---------- Bitácora de eventos por ticket ----------
create table if not exists tickets_allianz.ticket_eventos (
    id              bigint generated always as identity primary key,
    ticket_id       bigint references tickets_allianz.tickets(id) on delete cascade,
    correo_id       bigint references tickets_allianz.correos(id) on delete set null,
    tipo_evento     text,          -- respuesta_allianz / pedido_cliente / nudge / escalado_ceci...
    resumen         text,          -- resumen coloquial (Haiku)
    created_at      timestamptz default now()
);
create index if not exists idx_eventos_ticket on tickets_allianz.ticket_eventos (ticket_id, created_at);

-- ---------- Cola de acciones (sugerida → aprobada → enviada) ----------
create table if not exists tickets_allianz.acciones (
    id              bigint generated always as identity primary key,
    ticket_id       bigint references tickets_allianz.tickets(id) on delete cascade,
    tipo_accion     text,          -- avisar_cliente / avisar_asesor / correo_allianz / recordatorio...
    canal           text,          -- wati / email
    estado          text default 'sugerida',   -- sugerida / aprobada / enviada / fallida
    payload         jsonb default '{}'::jsonb,
    resultado       jsonb,
    programada_para timestamptz,   -- para recordatorios/inactividad
    created_at      timestamptz default now()
);
create index if not exists idx_acciones_estado on tickets_allianz.acciones (estado, programada_para);
