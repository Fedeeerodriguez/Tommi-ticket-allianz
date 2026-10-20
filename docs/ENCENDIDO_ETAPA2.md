# Encendido de la Etapa 2 (proceso corto y trámites)

Va **después** de la Etapa 1 (`docs/ENCENDIDO_ETAPA1.md`), sobre el mismo interruptor `MOTOR_ETAPAS`. Cada proceso se suma por separado con `MOTOR_ETAPAS_PROCESOS`. Sacar un proceso de la lista (y reiniciar el worker) lo devuelve al motor de hoy, sin tocar código.

## Antes de prender
1. **Que los correos lleguen a hola@.** Sin esto, el motor no los ve:
   - **Proceso corto:** el C2 (`[EXT] Emisión póliza No. Póliza: …`) le llega al Gmail del asesor (en la captura, `jose.mier.montero@gmail.com`). Hace falta un filtro en ese Gmail: remitente `Allianz.Mexico@allianz.com.mx` y asunto con "Emisión póliza" → reenviar a hola@.
   - **Trámites:** le llegan a `integraciones@babilonia.ai`. Hace falta reenviar a hola@ los de `allianz.com.mx` que traen "Ticket-".
   - Hoy, entre los 781 correos guardados, no hay ninguno de los dos.
2. **Correr el SQL** `docs/migracion_etapa2_2026-10-20.sql` en el SQL Editor de Supabase, **después** del de la Etapa 1.
   - Es aditivo y se puede correr dos veces.
   - La verificación tiene que dar 3 filas `ok`.
   - Lo probé en un Postgres 16 igual al de producción: corre dos veces sin error y la vuelta atrás no toca nada de la Etapa 1.
3. **Deploy** de las mismas dos ramas de la Etapa 1:
   - `feat/etapas-allianz` (worker + api);
   - `tomi-babilonia` → `feat/panel-etapas-allianz` (pantalla).
4. **Aprobar los textos:** `docs/TEXTOS_ETAPA2.md`.
5. **Plantilla de la guía aprobada en WATI** (`tommy_guia_aportacion`). Ceci completa el monto y los datos para depositar de cada guía antes de aprobarla.
6. **Telegram** (opcional; sin Telegram, la guía se aprueba desde el panel):
   1. crear el bot con BotFather → `TELEGRAM_BOT_TOKEN`;
   2. prender `TELEGRAM_APROBACIONES=true` con el token puesto;
   3. Ceci le escribe `/start` al bot y el bot le contesta su chat id → `TELEGRAM_CECI_CHAT_ID`;
   4. reiniciar el worker.
7. **Revisar el informe:** `python -m app.run_replay_etapas` → `data/replay_etapas.html`.
   - Trae la semana de prueba (los 4 recorridos) y los correos reales.
   - Tiene datos personales: no se sube ni se reenvía.
   - Con `--solo-prueba` sale solo la semana de prueba, que no tiene datos reales.

## Variables (EasyPanel → worker y api)
| Variable | Valor | Para qué |
|---|---|---|
| `MOTOR_ETAPAS_PROCESOS` | `largo` → `largo,tramite` → `largo,tramite,corto` | Qué procesos maneja el motor por etapa |
| `WATI_PLANTILLA_GUIA` | `tommy_guia_aportacion` (default) | Plantilla de la guía de aportación |
| `RECORDATORIO_PAGO_HORAS_HABILES` | `72` | Cuándo se le recuerda el pago al cliente (desde que Ceci aprueba la guía) |
| `TELEGRAM_APROBACIONES` | `false` → `true` | La guía le llega a Ceci por Telegram con botones |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CECI_CHAT_ID` | del bot / de Ceci | Solo acepta botones y correcciones de ese chat |

Las de la Etapa 1 (`MOTOR_ETAPAS_ROLES`, `ESCALAR_A_ALLIANZ`, `DRY_RUN`, …) valen igual para los dos procesos nuevos.

## Orden sugerido (junto con la Etapa 1)
1. **Semana 1:**
   - `MOTOR_ETAPAS=true`, `MOTOR_ETAPAS_PROCESOS=largo`, `MOTOR_ETAPAS_ROLES=ceci,asesor`;
   - con `DRY_RUN=true` primero.
2. **Semana 2:**
   - sumar `cliente` a los roles;
   - sumar `tramite` (son los mismos avisos del largo, con el asunto).
3. **Semana 3:**
   - sumar `corto`, con la guía aprobada desde el panel o por Telegram;
   - `ESCALAR_A_ALLIANZ=true`.

## Qué cambia respecto de hoy
- **Proceso corto:**
  - el C2 deja la guía **pendiente** y no sale nada hasta que Ceci la aprueba;
  - al aprobarla, la guía va al cliente, el asesor recibe aviso y arranca el recordatorio de pago;
  - **Elite:** el pago en el hilo corta el recordatorio.
  - **Patrimonial:** se marca **Pago enviado** en el panel.
  - el aviso de emisión cierra el ticket.
- **Trámites:** los avisos del largo, siempre con n° de ticket + cliente + asunto.
  - Si el asunto no trae la póliza, el aviso va a Ceci para que asigne al cliente.
  - Conviene poner la póliza en el asunto de los trámites que abrimos.
- **También en el largo:** si Allianz responde mientras el correo de escalación espera a Ceci, ese correo se descarta solo.
- **Queda para después:**
  - que Tommy mande solo el comprobante o el documento del cliente al correo: depende de la descarga de archivos de WATI (F5);
  - el autollenado de PDFs de los trámites (F7).
