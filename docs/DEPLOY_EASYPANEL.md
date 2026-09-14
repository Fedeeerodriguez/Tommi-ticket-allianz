# Deploy en EasyPanel

El sistema corre como **un servicio tipo *worker*** (no expone HTTP): el proceso principal es
el **scheduler** (`python -m app.run_scheduler`), que hace polling del buzón por Gmail API,
escanea inactividad y purga a 6 meses. Se construye desde el `Dockerfile` del repo.

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
| `GOOGLE_TOKEN` | *(contenido de google_token.json)* | Autorización Gmail API |
| `DATABASE_URL` | `postgresql://…` (Supabase de Tommy) | Mismo pooler que el backend principal |
| `DB_SCHEMA` | `tickets_allianz` | Esquema aislado |
| `OPENAI_API_KEY` | `sk-…` | L2 + redactor |
| `NOTION_TOKEN` | `ntn_…` | Write-back a Notion |
| `NOTION_DB_TICKETS_ALLIANZ` (+ demás `NOTION_DB_*`) | ids | Bases de Notion |
| `ALLIANZ_DEST` | correo del Directorio Allianz | Sin esto, los envíos a Allianz quedan bloqueados |
| `GMAIL_QUERY` | `is:unread` | Qué correos levanta el polling |
| `POLL_SEGUNDOS` | `90` | Frecuencia del polling |
| `RETENCION_DIAS` | `180` | Purga a 6 meses |
| `DRY_RUN` | `true` para validar / `false` para ir en vivo | **Empezar en `true`** |

## 4. Puesta en marcha segura

1. Primer deploy con **`DRY_RUN=true`**: el servicio lee la casilla real, clasifica y arma todo,
   pero **no envía ni escribe nada**. Revisar logs.
2. Cuando esté validado y con `ALLIANZ_DEST` real + Zapier viejo desactivado → **`DRY_RUN=false`**
   y redeploy. Recién ahí envía correos y escribe en Notion.

## 5. Persistencia

Todo el estado vive en la **Supabase** (esquema `tickets_allianz`), no en el contenedor. El
contenedor es efímero (se puede recrear sin perder nada). No requiere volumen.
