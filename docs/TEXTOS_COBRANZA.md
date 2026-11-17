# Textos de cobranza — resumen diario

Estado: **para aprobar** (Ceci / Yans). Generado desde `app/acciones/cobranza_resumen.py`: lo que se lee acá es exactamente lo que sale.

Decidido con Ceci (18/11/2026):
- Un WhatsApp por asesor por día hábil, a las 10:00 de México. El lunes incluye el fin de semana.
- Van **los 6 clientes con más días de atraso**; si hay más, el mensaje dice "consulta el resto con Ceci".
- Las pólizas **sin asesor para avisar** (no están en Notion o falta el teléfono) le llegan a Ceci en un WhatsApp aparte, para que las asigne ella o Jime.
- Plantilla de WhatsApp **propia de cobranza** (no la de actualización de trámite).

**Días de atraso:** Allianz no manda la fecha de vencimiento. Se cuentan desde el **primer cargo rechazado** que conocemos de esa póliza en los últimos 30 días (si Allianz reintenta, sigue contando desde el primero).

## Plantilla de WhatsApp para crear en WATI

- Nombre: `tommy_cobranza` · Categoría: **Utility** · Idioma: **Spanish (MEX)**
- Variables (por nombre): `{{cantidad}}` `{{clientes}}` `{{indicacion}}`

```
🔔 *Cobranza Allianz*
{{cantidad}} un cargo rechazado:
{{clientes}}

{{indicacion}}
A los 60 días de atraso Allianz puede cancelar el plan.

— Tommy · Babilonia
```

Ejemplos para cargar en WATI al crearla (Meta los pide para aprobar):
- `cantidad`: 2 clientes tuyos tuvieron
- `clientes`: Luisa Prueba Soto (OptiMaxx Plus PLU3-437821): 23 días de atraso, $2,000.00, fondos insuficientes; Pedro Dos (OptiMaxx Plus PLU3-500001): 9 días de atraso, $1,500.00, fondos insuficientes
- `indicacion`: Contacta a cada uno para que tenga el monto disponible o se ponga al corriente.

Si en WATI le ponen otro nombre, se cambia con `WATI_PLANTILLA_COBRANZA` en EasyPanel.

## Al asesor

| Caso | `cantidad` | `clientes` | `indicacion` |
|---|---|---|---|
| 1 cliente | 1 cliente tuyo tuvo | Luisa Prueba Soto (OptiMaxx Plus PLU3-437821): 23 días de atraso, $2,000.00, fondos insuficientes, 2 avisos | Contacta a cada uno para que tenga el monto disponible o se ponga al corriente. |
| 9 clientes | 9 clientes tuyos tuvieron | los 6 con más atraso, separados por "; " … ; y 3 más: consulta el resto con Ceci | (igual) |

"2 avisos" aparece cuando Allianz avisó más de una vez de la misma póliza desde el último resumen.

## A Ceci (pólizas sin asesor para avisar)

| `cantidad` | `clientes` | `indicacion` |
|---|---|---|
| 2 pólizas sin asesor para avisar tuvieron | Cliente sin identificar (OptiMaxx Plus PLU3-999999): 12 días de atraso, $3,100.00; … | No encontré a quién avisarle: asígnalas en Notion o avísale tú al asesor. |

Si son más de 6: "y N más en el correo de cobranza".

## Correo de cobranza (Ceci, Yans y quien se agregue)

Un correo por día con **la lista completa**, agrupada por asesor y de más a menos atraso, más las pólizas sin asesor con el motivo. Destinatarios en `COBRANZA_RESUMEN_EMAILS`. Sale solo con el envío real de cobranza prendido en el panel; mientras tanto se ve como vista previa en la pestaña Cobranzas.

```
Asunto: [Tommi] Cobranza 18/11: 4 pólizas con cargo rechazado

Cargos rechazados desde el último resumen: 4 pólizas, 2 asesores avisados. Cada lista va de más a menos días de atraso.

Asesor Uno (2):
  • Luisa Prueba Soto (OptiMaxx Plus PLU3-437821): 23 días de atraso, $2,000.00, fondos insuficientes, próximo intento 04 de noviembre de 2026, 2 avisos
  • Pedro Dos (OptiMaxx Plus PLU3-500001): 9 días de atraso, $1,500.00, fondos insuficientes

Asesor Dos (1):
  • Ana Tres (OptiMaxx Plus PLU3-600001): 5 días de atraso, $900.00, fondos insuficientes

Sin asesor para avisar (1): las asigna Ceci o Jime.
  • Cliente sin identificar (OptiMaxx Plus PLU3-999999): 12 días de atraso, $3,100.00 — No pude identificar la póliza PLU3-999999 en Notion (no está en Emisiones).

A los 60 días de atraso Allianz puede cancelar el plan.
— Tommi
```
