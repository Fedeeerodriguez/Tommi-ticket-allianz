# Deploy en EasyPanel

El sistema corre como **un servicio tipo *worker*** (no expone HTTP): el proceso principal es
el **scheduler** (`python -m app.run_scheduler`), que hace polling del buzón por Gmail API,
escanea inactividad + SLA y purga a 6 meses. Se construye desde el `Dockerfile` del repo.

> **Seguro por default:** con `DRY_RUN=true` el servicio lee, clasifica, cruza Notion y **arma**
> los correos/avisos, pero **no envía ni escribe nada**. Recién con `DRY_RUN=false` actúa en vivo.

## 0. Opción recomendada: Docker Compose

El repo trae un **`docker-compose.yml`** listo (worker, `restart: unless-stopped`, logs rotados,
todas las env vars con defaults seguros). En EasyPanel:

1. Nuevo servicio → **Compose** → origen: este repositorio (rama `main`). EasyPanel usa el
   `docker-compose.yml` del repo.
2. En la pestaña **Environment** del servicio, cargá las variables de la tabla de abajo. Se
   **interpolan** en los `${VAR}` del compose (los secretos NUNCA se hornean en la imagen).
3. Deploy. En **Logs** debería verse `Scheduler listo | DB=Supabase/Postgres | … | DRY_RUN=…`.

Local (para probar antes): `cp .env.example .env`, completar, y `docker compose up -d --build`
(compose lee el `.env` automáticamente). `docker compose logs -f` para ver el arranque.

La otra vía (build por Dockerfile como servicio "App") sigue siendo válida y se describe abajo.

## 1. El token de Gmail (clave del deploy)

El servidor es headless: **no** puede abrir el navegador para autorizar. Por eso el token se
genera **una sola vez en tu máquina** y su contenido se pega como variable de entorno.

En local (con `data/google_credentials.json` ya descargado, ver `docs/…` / README):

```bash
python -m app.google_oauth_setup      # abre el navegador, autorizás con hola@babilonia.ai
# genera data/google_token.json
```

Después, copiá **todo el contenido** de `data/google_token.json` (una línea de JSON con
`refresh_token`, `client_id`, `client_secret`, etc.) y pegalo en EasyPanel como la env var
**`GOOGLE_TOKEN`**. Con eso el servicio se autentica y **se refresca solo** — el token no vence
mientras exista el `refresh_token`.

> El token es un secreto: no se commitea (está en `.gitignore` y `.dockerignore`). Solo vive
> como variable de entorno en EasyPanel.

## 2. Crear el servicio en EasyPanel

1. Nuevo servicio → **App** → origen: este repositorio (rama `main`), build por **Dockerfile**.
2. Es un worker: **no** hace falta exponer puerto ni dominio.
3. Cargar las **variables de entorno** (abajo).
4. Deploy. Los logs deberían mostrar `Scheduler listo | DB=Supabase/Postgres | …`.

## 3. Variables de entorno

| Variable | Valor | Notas |
|---|---|---|
| `GOOGLE_TOKEN` | *(contenido de google_token.json)* | Autorización Gmail API (headless) |
| `DATABASE_URL` | `postgresql://…` (Supabase de Tommy) | Mismo pooler que el backend principal. Vacío → SQLite efímero (no usar en prod) |
| `DB_SCHEMA` | `tickets_allianz` | Esquema aislado |
| `OPENAI_API_KEY` | `sk-…` | **Orquestador** + redactor + L2. Sin esto, corre con plantillas |
| `MODELO_L2` | `gpt-4.1-mini` | Modelo del orquestador/redactor |
| `NOTION_TOKEN` | `ntn_…` | Rieles Fase F + registro |
| `NOTION_DB_EMISIONES` | id | **Fase F**: de acá salen cliente/asesor + teléfonos para WATI |
| `NOTION_DB_TICKETS_ALLIANZ` (+ `NOTION_DB_ASESORES/CLIENTES/DAF/COBRANZAS`) | ids | Bases de Notion |
| `ALLIANZ_DEST` | correo del Directorio Allianz | Sin esto, los envíos a Allianz quedan **bloqueados** |
| `ALLIANZ_DIRECTORIO` | JSON por trámite | Opcional; cae a `ALLIANZ_DEST` |
| `WATI_API_URL` / `WATI_API_TOKEN` | de WATI | Sin credenciales, WhatsApp corre en modo laboratorio (no envía → `pendiente_wati`) |
| `WATI_PLANTILLA_ASESOR` / `_CLIENTE` / `_CECI` | nombres de plantilla | Plantillas aprobadas en WATI |
| `CECI_WHATSAPP` | `+52…` | Número fijo de Ceci (visto bueno de críticas, Fase E) |
| `SLA_DEFAULT_HORAS` / `SLA_AVISO_HORAS` | `72` / `24` | SLA hábiles (Fase C) |
| `GMAIL_QUERY` | `is:unread` | Qué correos levanta el polling |
| `POLL_SEGUNDOS` | `90` | Frecuencia del polling |
| `RETENCION_DIAS` | `180` | Purga a 6 meses |
| `TZ` | `America/Mexico_City` | Zona horaria (SLA/logs) |
| `DRY_RUN` | `true` para validar / `false` para ir en vivo | **Empezar en `true`** |

> **Migración de DB (una vez, antes del primer `DRY_RUN=false`):** correr `app/db/migrations.sql`
> en la Supabase de prod (agrega columnas de hilo, SLA y teléfonos). SQLite las crea solo.

## 4. Puesta en marcha segura

1. Primer deploy con **`DRY_RUN=true`**: el servicio lee la casilla real, clasifica y arma todo,
   pero **no envía ni escribe nada**. Revisar logs.
2. Cuando esté validado y con `ALLIANZ_DEST` real + Zapier viejo desactivado → **`DRY_RUN=false`**
   y redeploy. Recién ahí envía correos y escribe en Notion.

## 5. Persistencia

Todo el estado vive en la **Supabase** (esquema `tickets_allianz`), no en el contenedor. El
contenedor es efímero (se puede recrear sin perder nada). No requiere volumen.
