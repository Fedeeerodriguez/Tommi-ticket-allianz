# Decisiones de arquitectura

Registro de las decisiones tomadas (para no re-discutirlas y que quede la trazabilidad).

## Stack (elegido con Fede)
- **Orquestación:** todo en **Python (FastAPI)**. Sin n8n como dependencia.
- **Ingesta:** **IMAP** (proveedor-agnóstico) para leer; **SMTP** para enviar (Fase 4).
- **Base de datos:** **misma Supabase de Tommy**, esquema aislado **`tickets_allianz`**.
- **LLM (L2 + resúmenes):** **Claude Haiku** (`claude-haiku-4-5`). Si no hay API key, cae a solo-L1.
- **Despliegue:** EasyPanel, servicio separado (no toca el backend principal de Tommy).
- **Scheduler:** APScheduler interno (recordatorios/inactividad + retención). Sin cron externo.

## Volumen (datos de Fede)
- Correos/día: ~3 hoy (manual) → estimado **x10** con el sistema automático. Todo es **Allianz in/out**.
- **~1000 tickets/mes** activos.
- Adjuntos: PDFs de ~4 hojas (~400 KB aprox).
- Retención: **comprimir/purgar cada 6 meses**.
- Picos: primeros 10 y últimos 10 días del mes.

## Decisiones que impone el volumen
1. **No** hace falta cola de mensajes ni push (Pub/Sub): el volumen es bajo. IMAP polling cada 1-2 min alcanza.
2. **Adjuntos → Supabase Storage**, NO en la DB. En Postgres guardamos solo **texto extraído + referencia (path/URL)**.
   Motivo: ~6 GB de PDFs por ventana de 6 meses harían la DB lenta y cara. Storage es barato y correcto.
3. **Job de retención a 6 meses** en el scheduler; tablas con `created_at` para purga barata.
4. **Idempotencia por `message_id`**: el polling puede re-ver mensajes; nunca reprocesar.

## Modo seguro
- Todo corre en **`DRY_RUN`** (no envía nada) por default.
- Lectores (`LectorIMAP` real / `LectorEmlLocal` dev) cumplen la misma interfaz → se cambian por config.
- **Emisores** (`EmisorSMTP` real / `EmisorLaboratorio` dry-run) cumplen la misma interfaz →
  `emisor_desde_config()` elige SMTP real **solo** con credenciales **y** `DRY_RUN=false`.

## Fase 4 — Envío (objetivo 2: enviar tickets a Allianz)
- El **despachador** (`app.acciones.despacho.despachar_pendientes`) toma las acciones que dejó
  el motor en estado `sugerida` y las ejecuta. Estados de salida: `enviada` / `simulada` /
  `fallida` / `bloqueada` / `pendiente_wati` / `omitida` / (queda `sugerida` si es `diferida`).
- Guardarraíles antes de mandar a Allianz:
  1. Ticket **delicado sin `autorizado`** → `bloqueada` (nunca sale solo; va a Ceci).
  2. Sin **`ALLIANZ_DEST`** (Directorio Allianz) → `bloqueada` (no adivina destinatario).
- Canal `wati` (WhatsApp) → `pendiente_wati`: lo envía la integración de WATI, no este despachador.
- Canal `interno` (Ceci/panel) → `omitida`: no requiere envío externo.
- Runner: `python -m app.run_despacho`.
- **Pendiente de accesos para ir en vivo:** SMTP de `hola@babilonia.ai`, `ALLIANZ_DEST` real,
  desactivar el Zapier viejo de José, y `DRY_RUN=false`.
