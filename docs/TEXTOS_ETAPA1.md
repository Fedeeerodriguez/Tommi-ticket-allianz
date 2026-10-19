# Textos de los avisos — Etapa 1 (proceso largo)

Estado: **para aprobar** (Fede / Ceci). Generado desde `app/acciones/mensajes_etapa.py`: lo que se lee acá es exactamente lo que sale.

- Textos **fijos**, sin IA. Lo único variable es lo que sale del correo de Allianz: el *qué piden* (recortado a 300 caracteres, sin saludo ni firma) y el plazo.
- **Tuteo mexicano** ("Tienes", "Mándamelo", "Contacta"): clientes y asesores son de México.
- **Ceci** recibe el texto del asesor + lo que no se pudo avisar (⚠️) + el link al panel (si se configura `PANEL_URL`).
- **Rechazado y declinado** no le escriben al cliente: lo contacta el asesor.
- La fecha del requerimiento es la del recordatorio: el plazo del correo o 3 días hábiles, lo que llegue antes.

Ejemplo: ticket 2576612 · Hortencia González Gama · Gastos médicos (GMMI) · solicitud 1950110.

## Solicitud abierta en Allianz

| Para | Texto |
|---|---|
| Asesor | Ticket 2576612 · Hortencia González Gama · Gastos médicos: Allianz abrió la solicitud 1950110. |
| Cliente | Hola Hortencia, tu solicitud de gastos médicos ya está en Allianz y está en proceso de autorización. Te avisamos cada avance. |
| Ceci | Ticket 2576612 · Hortencia González Gama · Gastos médicos: Allianz abrió la solicitud 1950110. |

## Allianz pide documentos

| Para | Texto |
|---|---|
| Asesor | Ticket 2576612 · Hortencia González Gama: Allianz pide → la carta laboral firmada. Plazo: 15 días hábiles. |
| Cliente | Hola Hortencia, para avanzar Allianz necesita: la carta laboral firmada. Tienes hasta el 22/10/2026. Mándamelo por aquí y yo lo envío. |
| Ceci | Ticket 2576612 · Hortencia González Gama: Allianz pide → la carta laboral firmada. Plazo: 15 días hábiles. |

## Documentos enviados a Allianz

| Para | Texto |
|---|---|
| Asesor | Ticket 2576612 · Hortencia González Gama: se enviaron los documentos a Allianz, esperamos respuesta. |
| Cliente | Hola Hortencia, ya enviamos tus documentos a Allianz. Te avisamos cuando respondan. |
| Ceci | Ticket 2576612 · Hortencia González Gama: se enviaron los documentos a Allianz, esperamos respuesta. |

## Autorizado para cobro

| Para | Texto |
|---|---|
| Asesor | Ticket 2576612 · Hortencia González Gama: autorizado, pasa a cobro. |
| Cliente | Hola Hortencia, ¡tu solicitud fue autorizada! Sigue el cobro. |
| Ceci | Ticket 2576612 · Hortencia González Gama: autorizado, pasa a cobro. |

## Atendida y cobrada

| Para | Texto |
|---|---|
| Asesor | Ticket 2576612 · Hortencia González Gama: atendido y cobrado. Ticket cerrado. |
| Cliente | Hola Hortencia, ¡listo! Tu solicitud quedó atendida y cobrada. |
| Ceci | Ticket 2576612 · Hortencia González Gama: atendido y cobrado. Ticket cerrado. |

## Póliza emitida

| Para | Texto |
|---|---|
| Asesor | Ticket 2576612 · Hortencia González Gama: póliza GMMI-101770 emitida. |
| Cliente | Hola Hortencia, ¡tu póliza GMMI-101770 ya está emitida! Te va a llegar el acceso al portal de Allianz. |
| Ceci | Ticket 2576612 · Hortencia González Gama: póliza GMMI-101770 emitida. |

## Rechazado por Allianz

| Para | Texto |
|---|---|
| Asesor | Ticket 2576612 · Hortencia González Gama: Allianz rechazó el ticket (venció el plazo). Contacta al cliente; para seguir hay que cotizar de nuevo. |
| Ceci | Ticket 2576612 · Hortencia González Gama: Allianz rechazó el ticket (venció el plazo). Contacta al cliente; para seguir hay que cotizar de nuevo. |

## Riesgo declinado

| Para | Texto |
|---|---|
| Asesor | Ticket 2576612 · Hortencia González Gama: Selección de riesgos declinó el riesgo. Contacta al cliente. |
| Ceci | Ticket 2576612 · Hortencia González Gama: Selección de riesgos declinó el riesgo. Contacta al cliente. |

## Cerrado por inactividad

| Para | Texto |
|---|---|
| Asesor | Ticket 2576612 · Hortencia González Gama: Allianz cerró el ticket por inactividad. Contacta al cliente para retomarlo. |
| Cliente | Hola Hortencia, Allianz cerró tu solicitud por falta de respuesta. Tu asesor te va a contactar para retomarla. |
| Ceci | Ticket 2576612 · Hortencia González Gama: Allianz cerró el ticket por inactividad. Contacta al cliente para retomarlo. |

## Nota de la ejecutiva

| Para | Texto |
|---|---|
| Asesor | Ticket 2576612 · Hortencia González Gama: la ejecutiva de Allianz escribió: Te comparto la hoja membretada que pidió el área de suscripción |
| Ceci | Ticket 2576612 · Hortencia González Gama: la ejecutiva de Allianz escribió: Te comparto la hoja membretada que pidió el área de suscripción |

## La ejecutiva pide respuesta

| Para | Texto |
|---|---|
| Ceci | Ticket 2576612 · Hortencia González Gama: la ejecutiva pide que respondamos directo en el ticket (con copia a ella). |

Solo cuando la ejecutiva pide *brindar respuesta*; una copia "para su conocimiento" no avisa a nadie.

## Respuesta no entregada (ticket cerrado)

| Para | Texto |
|---|---|
| Ceci | Ticket 2576612: nuestra respuesta NO entró porque el ticket ya estaba cerrado en Allianz. Hay que abrir uno nuevo. |

## Cuando no se puede avisar a alguien

El aviso a Ceci agrega una línea por cada problema, por ejemplo:

| Caso | Línea que se agrega |
|---|---|
| No se encontró al cliente en Notion, o hay homónimos con asesores distintos | ⚠️ No pude identificar al cliente/asesor (no está en Notion Emisiones): no se le avisó al cliente. |
| Notion no tiene el teléfono | ⚠️ Falta el teléfono del asesor en Notion: no se le avisó. |
| Ticket delicado (cancelación, siniestro…) | ⚠️ Ticket delicado: no se le avisó al cliente. |

## WhatsApp (WATI)

Con `WATI_PLANTILLA_ETAPAS=<nombre de la plantilla "actualización de trámite">` los avisos salen por esa plantilla.
Los parámetros se mapean con `WATI_PARAMS_ETAPAS` (`nombre_en_WATI=dato`). Datos disponibles:

| Dato | Ejemplo |
|---|---|
| `ticket` | 2576612 |
| `tramite` | Gastos médicos · Allianz pide documentos |
| `etapa` | Allianz pide documentos |
| `cliente` | Hortencia González Gama |
| `telefono` | 5512345678 |
| `poliza` | GMMI-101770 |
| `solicitud` | 1950110 |
| `mensaje` | el texto de la tabla de arriba |

Default: `ticket=ticket,tramite=tramite,cliente=cliente,telefono=telefono,mensaje=mensaje`. Si la plantilla usa `{{1}}`, `{{2}}`… sería `1=ticket,2=tramite,…`.
Sin `WATI_PLANTILLA_ETAPAS`, salen por las plantillas de siempre (`WATI_PLANTILLA_ASESOR` / `_CLIENTE` / `_CECI`) con un solo parámetro `mensaje`.

## Recordatorios y escalamiento

Salen solo de lunes a viernes de 9 a 19 h (CDMX), sin feriados, y una sola vez cada uno.

| Cuándo | Para | Texto |
|---|---|---|
| Allianz pidió algo y venció el plazo (o 3 días hábiles) | Cliente | Hola Hortencia, te recuerdo que Allianz sigue esperando: la carta laboral firmada. Mándamelo por aquí y yo lo envío. |
| Allianz pidió algo y venció el plazo (o 3 días hábiles) | Asesor | Ticket 2576612 · Hortencia González Gama: sigue pendiente lo que pidió Allianz → la carta laboral firmada. Ya le recordamos al cliente. |
| 1 día hábil después, sigue sin llegar | Asesor | Ticket 2576612 · Hortencia González Gama: el cliente todavía no manda lo que pidió Allianz (la carta laboral firmada). Si vence el plazo, Allianz rechaza el ticket. Contacta al cliente. |
| 1 día hábil después, sigue sin llegar | Ceci | Ticket 2576612 · Hortencia González Gama: el cliente todavía no manda lo que pidió Allianz (la carta laboral firmada). Si vence el plazo, Allianz rechaza el ticket. |
| Mandamos lo pedido y Allianz no responde en 3 días hábiles | Ceci | Ticket 2576612 · Hortencia González Gama: Allianz no responde desde que mandamos los documentos (26/10). Si sigue sin responder, se escala con copia a la ejecutiva. |
| 1 día hábil después, Allianz sigue sin responder | Ceci | Ticket 2576612 · Hortencia González Gama: Allianz sigue sin responder. Dejé listo un correo en el hilo con copia a penny.ortiz@allianz.com.mx para que lo apruebes. |

**Correo de escalación a Allianz** (en el hilo del ticket, con copia a la ejecutiva; **queda para que Ceci lo apruebe**, uno por uno):

```
Buen día,

Damos seguimiento a la solicitud 1950110 de Hortencia González Gama (ticket 2576612). El 26/10 enviamos la documentación solicitada y a la fecha no hemos recibido respuesta.

¿Nos apoyan con el estatus, por favor?

Quedamos atentos.
Babilonia
```
