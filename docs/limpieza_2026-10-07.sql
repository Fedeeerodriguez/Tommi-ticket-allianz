-- Limpieza 2026-10-07 — tickets Allianz (esquema tickets_allianz)
-- Correr en Supabase → SQL Editor, TODO junto (es una sola transacción: si algo falla, no
-- cambia nada). Todas las tablas van con el esquema explícito (no depende de search_path).
-- 1) Respalda las 4 tablas.  2) Borra recordatorios/reactivaciones duplicados (deja el primero
--    de cada grupo y NUNCA toca lo que el equipo calificó o editó).  3) Borra los 4 tickets de
--    prueba que salieron de los .eml de ejemplo (445566, 778899, 445570 y "Juan Perez").

begin;

drop table if exists tickets_allianz.acciones_backup_20261007;
drop table if exists tickets_allianz.tickets_backup_20261007;
drop table if exists tickets_allianz.correos_backup_20261007;
drop table if exists tickets_allianz.ticket_eventos_backup_20261007;

create table tickets_allianz.acciones_backup_20261007       as select * from tickets_allianz.acciones;
create table tickets_allianz.tickets_backup_20261007        as select * from tickets_allianz.tickets;
create table tickets_allianz.correos_backup_20261007        as select * from tickets_allianz.correos;
create table tickets_allianz.ticket_eventos_backup_20261007 as select * from tickets_allianz.ticket_eventos;

-- Duplicados (mismo ticket + tipo + contenido), sin calificar ni editar.
delete from tickets_allianz.acciones where id in (
  select id from (
    select id, veredicto, borrador_editado,
           row_number() over (partition by ticket_id, tipo_accion, md5(coalesce(payload::text, ''))
                              order by created_at, id) as rn
    from tickets_allianz.acciones
    where tipo_accion in ('recordatorio_sla', 'reactivacion', 'recordatorio')
  ) x
  where rn > 1 and coalesce(veredicto, 'pendiente') = 'pendiente' and borrador_editado is null
);

-- Tickets de prueba (ids 2, 3, 4, 5: correos 01_…04_….eml de ejemplo).
delete from tickets_allianz.acciones       where ticket_id in (2, 3, 4, 5);
delete from tickets_allianz.ticket_eventos where ticket_id in (2, 3, 4, 5);
delete from tickets_allianz.adjuntos       where correo_id in (select id from tickets_allianz.correos where ticket_id in (2, 3, 4, 5));
delete from tickets_allianz.correos        where ticket_id in (2, 3, 4, 5);
delete from tickets_allianz.tickets        where id in (2, 3, 4, 5);

commit;

-- Verificación (debería dar: 11 tickets y 0 grupos duplicados; respaldo = 308 acciones aprox.):
select (select count(*) from tickets_allianz.acciones)                 as acciones,
       (select count(*) from tickets_allianz.tickets)                  as tickets,
       (select count(*) from tickets_allianz.acciones_backup_20261007) as respaldo_acciones,
       (select count(*) from (select 1 from tickets_allianz.acciones
                              group by ticket_id, tipo_accion, md5(coalesce(payload::text, ''))
                              having count(*) > 1) d)                  as grupos_duplicados;
