# Plan Etapa 2 — Proceso corto (Elite · Patrimonial · OptiMaxx Plus) y trámites

Estado: **en desarrollo (20/10)**. Rama `feat/etapas-allianz`, sobre la Etapa 1.
Objetivo: que **todo** correo de Allianz pase por el motor por etapa (no solo el proceso largo) y probar las dos etapas juntas antes de encender.

## Los dos procesos
**Corto** (SVIP Elite, OPPT Patrimonial, PLU3 OptiMaxx Plus):
1. C1 Emisión registrada ("¡Felicidades, su solicitud se registró!"): no hay ticket todavía → solo se registra.
2. C2 Confirmación de datos + ticket (`[EXT] Emisión póliza No. Póliza: X No. Solicitud: N`): se arma la **guía de aportación**. Primero va a **Ceci por Telegram** con los botones [Aprobar] y [Descartar]; para editarla, Ceci responde al mensaje con el texto corregido. Recién con la aprobación sale al cliente y al asesor, y arranca el recordatorio de pago.
3. C3 Pago:
   - **Elite**: la respuesta en el hilo es nuestra (C4) y corta el recordatorio de pago.
   - **Patrimonial**: va un correo nuevo a "cliente inversión"; en el panel se marca **Pago enviado**.
   - En esta etapa el pago se sigue mandando a mano. Que Tommy lo mande solo depende de la descarga de archivos de WATI (F5).
4. Aviso de emisión: avisa a los 3 y cierra el ticket.

**Trámites** (los abrimos nosotros; el hilo se llama `[EXT] <nuestro asunto>`):
- C1, el acuse automático: avisa a los 3 con el n° de ticket, el cliente y el asunto.
- C2, requerimiento u observación: avisa a los 3 qué piden y arranca el recordatorio.
- Nuestra respuesta: pasa a esperar a Allianz, con recordatorio y escalación (igual que el largo).
- C3, atendido / cerrado, y C3.1, cerrado por inactividad: avisa a los 3 y cierra.
- El cliente se identifica por la póliza o el nombre si vienen en el asunto o en el mensaje. Si no vienen, el aviso va a Ceci, que lo asigna en el panel.

## Pasos
1. **Detector**: tests con las capturas de Ceci (C1/C2/aviso del corto; C1/C2 del trámite) y ajustes.
2. **Base**: tabla `aprobaciones` (guía de aportación: texto, versión, estado, mensaje de Telegram) y el offset de Telegram. Migración aditiva con respaldo: `docs/migracion_etapa2_*.sql`.
3. **Motor**:
   - Interruptor por proceso: `MOTOR_ETAPAS_PROCESOS=largo` → `largo,corto,tramite`.
   - Corto: C2 → guía pendiente de aprobación; recordatorio de **pago** (cliente+asesor, escala a asesor+Ceci). La emisión se engancha al ticket corto.
   - Trámite: los mismos avisos y recordatorios del largo, con el asunto del hilo.
4. **Telegram**:
   - `app/rieles/telegram.py` (Bot API, sin librerías nuevas).
   - Polling de los botones desde el worker. Solo acepta el chat de Ceci.
   - Aprobar → encola los avisos. Descartar → no sale nada. Respuesta → versión nueva.
   - Sin token, se aprueba desde el panel.
5. **Textos**: corto (guía provisoria hasta tener el speech) y trámite → `docs/TEXTOS_ETAPA2.md`.
6. **Panel**:
   - "Para Ceci" suma "guía por aprobar".
   - Aprobar, editar o descartar la guía desde el panel.
   - Botón **Pago enviado** (sirve para cualquier ticket como "marcar etapa a mano").
7. **Prueba de todo junto**:
   - Tests de punta a punta de los 4 recorridos (largo, Elite, Patrimonial, trámite), con reloj simulado y Telegram falso.
   - Un informe único: el replay real de la Etapa 1, más los recorridos armados con las capturas.
8. **Encendido**: guía (`docs/ENCENDIDO_ETAPA2.md`).

## Lo que necesito 📥
1. **Que los correos lleguen a hola@** (bloquea el uso real, no el desarrollo). Hoy los 781 correos guardados no traen ni un C2 del corto ni un trámite:
   - el C2 del corto le llega al Gmail del asesor (en la captura, `jose.mier.montero@gmail.com`);
   - los trámites le llegan a `integraciones@babilonia.ai`.
   Hace falta un filtro de reenvío a hola@ desde los dos.
2. **Speech de la guía de aportación** (mientras tanto, texto provisorio que Ceci corrige antes de aprobar).
3. **Bot de Telegram**: token (BotFather) + que Ceci le escriba `/start` al bot (así sale su chat id).
4. Plazo de pago del corto: por defecto, el mismo esquema de 72 h hábiles.
