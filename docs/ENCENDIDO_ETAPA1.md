# Encendido de la Etapa 1 (proceso largo)

Todo lo nuevo está detrás de `MOTOR_ETAPAS`. Apagarlo (`MOTOR_ETAPAS=false` + reiniciar el worker) vuelve al comportamiento de hoy sin tocar código.

## Antes de prender
1. **Correr el SQL** `docs/migracion_etapa1_2026-10-19.sql` en el SQL Editor de Supabase.
   - Es aditivo y tiene respaldo, verificación y vuelta atrás.
   - La verificación tiene que dar 3 filas `ok`.
2. **Deploy** de la rama `feat/etapas-allianz` (worker + api) y de `tomi-babilonia` rama `feat/panel-etapas-allianz` (pantalla del panel; se rebuildea el front).
3. **Ceci revisa el replay**: `python -m app.run_replay_etapas` → `data/replay_etapas.html`.
   - Tiene datos personales: no se sube ni se reenvía.
   - Lo que marque como error se convierte en test antes de seguir.
4. **Aprobar los textos**: `docs/TEXTOS_ETAPA1.md`.

## Variables (EasyPanel → worker y api)
| Variable | Valor | Para qué |
|---|---|---|
| `MOTOR_ETAPAS` | `true` | Prende el motor por etapa (solo el proceso largo) |
| `MOTOR_ETAPAS_ROLES` | `ceci,asesor` → después `ceci,asesor,cliente` | Encendido gradual |
| `ESCALAR_A_ALLIANZ` | `false` → después `true` | Correo de escalación a Allianz con copia a la ejecutiva (Ceci lo aprueba uno por uno) |
| `ESCALA_CC` | `penny.ortiz@allianz.com.mx` | ⚠️ Confirmar con Fede |
| `ALLIANZ_DEST` | dirección del ticket en Allianz | Sin esto, la escalación queda bloqueada (se ve en "Para Ceci") |
| `WATI_PLANTILLA_AVISO_EQUIPO` / `_AVISO_CLIENTE` / `WATI_PLANTILLA_GUIA` | ya traen `tommy_aviso_equipo`, `tommy_actualizacion_cliente` y `tommy_guia_aportacion` | Solo si en WATI quedaron con otro nombre. Ver `docs/TEXTOS_ETAPA1.md` |
| `CECI_WHATSAPP` | número de Ceci | Sin esto, los avisos a Ceci quedan en el panel |
| `PANEL_URL` | URL del panel (opcional) | Link en los avisos a Ceci |
| `DRY_RUN` | `true` hasta el OK final | Con `true` nada sale: se compone y se ve en el panel |

## Orden
1. **Semana 1:** `MOTOR_ETAPAS=true`, `MOTOR_ETAPAS_ROLES=ceci,asesor`, `ESCALAR_A_ALLIANZ=false` (con `DRY_RUN=true` primero, después `false`). Ceci mira la pestaña **Para Ceci**.
2. **Semana 2:** sumar `cliente` a `MOTOR_ETAPAS_ROLES`.
3. **Semana 3:** `ESCALAR_A_ALLIANZ=true` (cada correo a Allianz espera el visto bueno de Ceci).

## Qué cambia respecto de hoy (con el motor prendido)
- **Avisos:** el proceso largo avisa por etapa, una vez por etapa y destinatario. Se terminan los "4+ avisos".
- **Sin identificar:** si no se identifica sin dudas al cliente o al asesor, el aviso va solo a Ceci, que lo asigna desde el panel.
- **Recordatorios:** pasan a días hábiles de México y solo en horario de oficina. La reactivación diaria y el SLA viejo dejan de tocar esos tickets.
- **Avisos automáticos sin ticket:** DAF, cobranzas y recordatorios de pago ya no crean tickets.
- **Avisos de emisión:** los de clientes que no seguimos tampoco crean tickets.
- **Proceso corto y trámites:** siguen con el motor de hoy hasta que se sumen a `MOTOR_ETAPAS_PROCESOS` (Etapa 2, `docs/ENCENDIDO_ETAPA2.md`).
