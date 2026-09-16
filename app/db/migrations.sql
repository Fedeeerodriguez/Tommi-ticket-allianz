-- Migraciones para la Supabase de producción (esquema tickets_allianz).
-- SQLite (dev) crea el esquema completo solo; esto es SOLO para Postgres/Supabase.
-- Idempotente: se puede correr varias veces sin romper.

-- Fase B — hilo de correo por ticket (responder en el mismo hilo).
alter table tickets_allianz.tickets add column if not exists gmail_thread_id   text;
alter table tickets_allianz.tickets add column if not exists asunto_hilo        text;
alter table tickets_allianz.tickets add column if not exists ultimo_message_id  text;

-- Fase C — SLA / vencimiento del ticket (para recordar antes de que Allianz lo cierre).
alter table tickets_allianz.tickets add column if not exists vence_en          text;

-- Fase F — teléfonos de cliente/asesor (traídos de Notion Emisiones) para el ruteo por WATI.
alter table tickets_allianz.tickets add column if not exists telefono_cliente  text;
alter table tickets_allianz.tickets add column if not exists telefono_asesor   text;
