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
- Todo corre en **`DRY_RUN`** (no envía nada) hasta la Fase 4.
- Lectores (`LectorIMAP` real / `LectorEmlLocal` dev) cumplen la misma interfaz → se cambian por config.
