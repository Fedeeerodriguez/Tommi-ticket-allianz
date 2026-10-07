-- Limpieza 2026-10-07 — tickets Allianz (esquema tickets_allianz)
-- Correr en Supabase → SQL Editor, TODO junto (es una sola transacción).
-- 1) Respalda las 4 tablas.  2) Borra recordatorios/reactivaciones duplicados (deja el primero
--    de cada grupo y NUNCA toca lo que el equipo calificó o editó).  3) Borra los 4 tickets de
--    prueba que salieron de los .eml de ejemplo (445566, 778899, 445570 y "Juan Perez").

begin;
set local search_path to tickets_allianz;

create table if not exists acciones_backup_20261007       as table acciones;
create table if not exists tickets_backup_20261007        as table tickets;
create table if not exists correos_backup_20261007        as table correos;
create table if not exists ticket_eventos_backup_20261007 as table ticket_eventos;

-- Duplicados (mismo ticket + tipo + contenido), sin calificar ni editar.
delete from acciones where id in (
  select id from (
    select id, veredicto, borrador_editado,
           row_number() over (partition by ticket_id, tipo_accion, md5(coalesce(payload::text, ''))
                              order by created_at, id) as rn
    from acciones
    where tipo_accion in ('recordatorio_sla', 'reactivacion', 'recordatorio')
  ) x
  where rn > 1 and coalesce(veredicto, 'pendiente') = 'pendiente' and borrador_editado is null
);

-- Tickets de prueba (ids 2, 3, 4, 5: correos 01_…04_….eml de ejemplo).
delete from acciones       where ticket_id in (2, 3, 4, 5);
delete from ticket_eventos where ticket_id in (2, 3, 4, 5);
delete from adjuntos       where correo_id in (select id from correos where ticket_id in (2, 3, 4, 5));
delete from correos        where ticket_id in (2, 3, 4, 5);
delete from tickets        where id in (2, 3, 4, 5);

commit;

-- Verificación (debería dar: 11 tickets y 0 grupos duplicados):
select (select count(*) from tickets_allianz.acciones) as acciones,
       (select count(*) from tickets_allianz.tickets)  as tickets,
       (select count(*) from (select 1 from tickets_allianz.acciones
                              group by ticket_id, tipo_accion, md5(coalesce(payload::text, ''))
                              having count(*) > 1) d) as grupos_duplicados;
