# Decisiones de arquitectura

Registro de las decisiones tomadas (para no re-discutirlas y que quede la trazabilidad).

## Stack (elegido con Fede)
- **Orquestación:** todo en **Python**, modelada como **grafo de LangGraph**; los pasos con
  LLM son **agentes LangChain**. Sin n8n como dependencia. Ver `docs/ARQUITECTURA_GRAFO.md`.
  (El pipeline lineal `run_pipeline.py` queda como legacy; el camino oficial es `run_grafo.py`.)
- **Ingesta:** el buzón `hola@babilonia.ai` está en **Google Workspace**. Se conecta por
  **Gmail API (OAuth)** — *Plan B* — porque el Workspace tiene bloqueadas las App Passwords
  (IMAP/SMTP con contraseña quedan como fallback). Ver `app/google_auth.py`,
  `app/intake/gmail_api.py`, `app/envio/gmail_api.py`; autorización one-shot con
  `python -m app.google_oauth_setup`. Los lectores/emisores son enchufables:
  `intake.lector_desde_config()` y `envio.emisor_desde_config()` eligen Gmail API → IMAP → local.
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

## Fase 5 — Scheduler (servicio autónomo 24/7)
- `app/scheduler.py` corre sobre **APScheduler** (un solo proceso, sin cron externo). Tres jobs:
  1. **intake** (cada `POLL_SEGUNDOS`): lee correos nuevos por IMAP → invoca el grafo por cada
     uno → despacha las acciones vencidas. Idempotente por `message_id` (re-ver no reprocesa).
  2. **inactividad** (03:00 → 08:00 UTC): `escanear_inactividad` encola recordatorios de
     reactivación para tickets estancados y los despacha.
  3. **retención** (03:30 UTC): `repo.purgar_antiguos(RETENCION_DIAS)` borra correos y tickets
     resueltos más viejos que 6 meses (con su historial). En `DRY_RUN` solo **cuenta**, no borra.
- Runner de producción: `python -m app.run_scheduler` (es el proceso a levantar en EasyPanel).
- Modo seguro intacto: sin credenciales / `DRY_RUN=true` no sale nada por SMTP ni se purga nada,
  así el mismo binario corre igual en dev y en prod — solo cambian las variables de entorno.

## Catálogo de trámites Allianz (indicaciones de Ceci)
Fuente: capturas + explicación de Ceci. Vive en `app/tramites/catalogo.py` y se dispara en las
consultas de trámite (`F_CONSULTA_PRODUCTO`). Portal del cliente:
`https://clientes.allianz.com.mx/portal-clientes-web/home` → pestaña **Trámites** → póliza + trámite.

Dos rutas de atención:
- **`CLIENTE_PORTAL`** (el cliente lo hace solo) → Tommy le responde con las **instrucciones**
  paso a paso (canal `email_cliente`, va a quien preguntó, sin guardarraíl de Allianz).
  - Self-service: Asesoría sobre endosos · Cambio de beneficiario · Cambio de fecha de pago ·
    Redistribución de aportaciones · Retiro desde alternativas · Traspaso entre alternativas.
  - **Período de descanso (año de descanso):** self-service pero con instrucciones detalladas
    (trámite "Asesoría para endosos" + Observaciones pidiendo pausar cobros → confirmar por
    correo; condiciones: estar al corriente y no aportar durante el descanso).
- **`NOSOTROS_MAIL`** (lo gestionamos nosotros por correo) → acción `gestionar_tramite`
  (canal `email` → Directorio Allianz, con los guardarraíles) + aviso al cliente.
  - Requiere apoyo: **Cambio de conducto de cobro**.
- Consulta sin trámite reconocido → queda para Ceci (canal `interno`).

**Beneficiario (decidido con Fede):** "Cambio de beneficiario" es self-service → se auto-instruye
como los demás (se sacó `beneficiari` del guardarraíl `_RE_DELICADO`). Pero un beneficiario en
contexto sensible (p. ej. "por fallecimiento") **sigue** cayendo en delicado por sus otras raíces
(`fallecimiento`, `defunci`, etc.) y va a Ceci.
