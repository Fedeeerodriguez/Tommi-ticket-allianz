# Plan Etapa 1 — Proceso largo (Auto · Vida · GMM · OP3D · HOFP)

Estado: **aprobado 19/10, en desarrollo**. ✅ Paso 1. Base: reglas de `app/clasificador/etapas.py` (rama `feat/etapas-allianz`), validadas contra 79 correos reales.

## Qué hay que lograr
Cada correo del proceso largo:
1. se reconoce en su etapa;
2. dispara **exactamente** los avisos que corresponden, una sola vez;
3. pone en marcha o corta los recordatorios;
4. cierra el ticket cuando toca.

Todo en sandbox (DRY_RUN) hasta que Ceci lo apruebe.

### Decisiones confirmadas (19/10)
- **C1:** al cliente se le dice "en proceso de autorización".
- **C3 Autorizado:** autorizan el cobro. **C5 Atendida:** ya se cobró.
- **Rechazado / declinado:** se le avisa al asesor para que contacte al cliente. Al cliente no le sale nada automático.
- **Póliza emitida:** aviso a los 3.
- **PLU3:** pendiente de Fede. Hasta entonces va por este proceso.

## Fuera de esta etapa
Quedan para después, porque cada una es una pieza propia del plan general:
- Que Tommy mande los documentos del cliente al correo (WhatsApp → correo): F5.
- El proceso corto y la aprobación por Telegram: F6.
- Los trámites que iniciamos nosotros: F7.

En esta etapa, cuando Allianz pide algo, el equipo lo manda a mano como hoy. El sistema avisa, recuerda y escala.

---

## Pasos

### 1. Ajustar las reglas con lo confirmado (½ día)
- Textos de C3 Autorizado ("autorizado para cobro") y C5 ("ya se cobró").
- Rechazado / declinado: la nota al asesor dice "contactá al cliente".
- **Hecho cuando:** los tests siguen verdes.

### 2. Base de datos (1 día)
Migración con respaldo, sin borrar nada:
- `tickets`: columnas nuevas `proceso`, `producto`, `etapa`, `etapa_desde`, `nro_solicitud`.
- `avisos`: un registro por (ticket, etapa, destinatario) **con clave única**. Así es imposible mandar el mismo aviso dos veces, que es la causa de los "4+ avisos".
- `recordatorios`: ticket, motivo, a quién, vence, escala_en, estado (`activo` / `cumplido` / `escalado` / `cancelado`).
- **Hecho cuando:** la migración corre en una copia y se puede volver atrás.

### 3. Encontrar al cliente y al asesor (1,5 días) ⚠️ el punto más delicado
Hoy el sistema busca en Notion solo por **póliza** o **correo del cliente**. Pero en C1–C5 los correos traen **n° de solicitud + nombre del cliente** (la póliza llega recién al final).
- Buscar en Notion (Emisiones / Clientes) por nombre completo del contratante y por n° de solicitud.
- Guardar en el ticket el cliente, el asesor y sus teléfonos la primera vez que se encuentran. Los correos siguientes del mismo ticket los reusan.
- Si hay **0 o más de 1** coincidencia → **no se adivina**: el aviso va solo a Ceci con "no pude identificar al cliente/asesor", y ella lo asigna desde el panel.
- **Hecho cuando:** sobre los tickets reales, se identifica a cliente y asesor o se manda a Ceci. Nunca a la persona equivocada.

### 4. Motor por etapa (2 días)
Una función nueva, `decidir_por_etapa`, reemplaza para el proceso largo la lógica actual por tipo de correo. Queda detrás de un interruptor (`MOTOR_ETAPAS=1`), así se puede apagar sin redeploy de código.

| Etapa | Avisos | Recordatorio | Ticket |
|---|---|---|---|
| C1 Apertura | Ceci, asesor, cliente | — | abierto |
| C2 Confirmación de datos | ninguno | — | igual |
| C3 Requerimiento | Ceci, asesor, cliente (qué piden) | arranca | esperando cliente |
| C3 Autorizado | Ceci, asesor, cliente | corta | en cobro |
| C4 Documentos enviados | Ceci, asesor, cliente | corta el del req. y arranca "esperando a Allianz" | esperando Allianz |
| C5 Atendida (cobrado) | Ceci, asesor, cliente | corta todos | **cerrado** |
| Rechazado / Declinado | Ceci, asesor | corta todos | **cerrado** |
| Póliza emitida | Ceci, asesor, cliente | — | cerrado (fin) |
| Copia de Penny/Blanca, recordatorio de Allianz | ninguno (copia que pide responder → alerta a Ceci) | — | igual |
| Revisar | ninguno, va al panel | — | igual |

Reglas duras:
- La etapa **solo avanza**. Un correo viejo o repetido no la hace retroceder ni repite avisos. Única excepción: un nuevo requerimiento después de C4, que reabre el C3.
- Ningún correo sale hacia Allianz desde este motor, salvo la escalación del paso 6.
- Rechazado y declinado nunca generan un mensaje al cliente.
- **Hecho cuando:** tests por etapa, más una secuencia completa C1→C5 y una con rechazo.

### 5. Mensajes (1 día) — los textos se aprueban antes de programarlos
Textos **fijos** por etapa, sin IA. Lo único variable es el "qué piden", que se copia del correo de Allianz recortado: sin saludo, sin firma, máx. 300 caracteres.

| Etapa | Asesor | Cliente |
|---|---|---|
| C1 | Ticket {tk} · {cliente} · {producto}: Allianz abrió la solicitud {sol}. | Hola {nombre}, tu solicitud de {producto} ya está en Allianz y está en proceso de autorización. Te avisamos cada avance. |
| C3 Req. | Ticket {tk} · {cliente}: Allianz pide → {qué piden}. Plazo: {plazo}. | Hola {nombre}, para avanzar Allianz necesita: {qué piden}. Tenés hasta el {fecha}. Mandámelo por acá y lo envío yo. |
| C3 Aut. | Ticket {tk} · {cliente}: autorizado, pasa a cobro. | Hola {nombre}, ¡tu solicitud fue autorizada! Sigue el cobro. |
| C4 | Ticket {tk} · {cliente}: se enviaron los documentos a Allianz, esperamos respuesta. | Hola {nombre}, ya enviamos tus documentos a Allianz. Te avisamos cuando respondan. |
| C5 | Ticket {tk} · {cliente}: atendido y cobrado. Ticket cerrado. | Hola {nombre}, ¡listo! Tu solicitud quedó atendida y cobrada. |
| Rechazado | Ticket {tk} · {cliente}: Allianz rechazó el ticket (venció el plazo). Contactá al cliente; para seguir hay que cotizar de nuevo. | — |
| Declinado | Ticket {tk} · {cliente}: Selección de riesgos declinó el riesgo. Contactá al cliente. | — |
| Póliza emitida | Ticket {tk} · {cliente}: póliza {póliza} emitida. | Hola {nombre}, ¡tu póliza {póliza} ya está emitida! Te va a llegar el acceso al portal de Allianz. |

- **Ceci** recibe el mismo texto que el asesor, más el link al ticket en el panel.
- **Canal:** la plantilla WATI "actualización de trámite" que ya usan (ticket, tipo de trámite, cliente, teléfono). 📥 Necesito su nombre exacto y sus parámetros.

### 6. Recordatorios y escalamiento (2 días)
- **Arranca:** con C3 Requerimiento (plazo = el del correo o 72 h hábiles, el que venza antes) y con C4 (esperando a Allianz: 72 h hábiles).
- **Al vencer:** se le recuerda a quien falte. En el requerimiento, al cliente y al asesor. Si esperamos a Allianz, a Ceci.
- **+24 h sin novedad:** se escala. Va un correo corto en el hilo **con copia a Penny** (`penny.ortiz@allianz.com.mx`, ya vista en los correos reales) y un aviso a Ceci. Como es un correo hacia Allianz, en el sandbox queda **para aprobar**.
- **Se corta solo** con C4, C3 Autorizado, C5, Rechazado, Declinado o el cierre.
- Usa los días hábiles y feriados de México que ya calcula `sla.py`.
- Reemplaza el recordatorio viejo de "2 días" y la reactivación diaria que hoy ensucia el panel.
- **Hecho cuando:** hay tests con reloj simulado (viernes→lunes, feriado, recordatorio cortado a tiempo, escalado) y ningún recordatorio sale dos veces.

### 7. Panel (1 día)
En el panel actual:
- columna **Etapa** y **Próximo recordatorio** en la lista;
- en cada ticket, la línea de tiempo C1→C5 con fecha y avisos enviados;
- filtro "**Para Ceci**": revisar, cliente/asesor sin identificar, escalados, rebotes.

### 8. Prueba con lo real antes de prender (1 día + revisión de Ceci)
- **Replay** de los correos reales del proceso largo desde septiembre, en sandbox. Sale un informe por ticket: qué etapas detectó, qué avisos habría mandado (texto exacto y a quién) y qué recordatorios.
- Ceci lo revisa. Lo que marque como error se convierte en test antes de seguir.
- **Encendido gradual:** primero solo avisos al asesor y a Ceci, después al cliente y por último la escalación a Penny.

---

## Tiempos
≈ **10 días hábiles** de desarrollo (pasos 1–8) + la revisión de Ceci.
Se entrega en una rama, con tests. No se mergea ni se prende nada sin tu OK.

## Lo que necesito de vos 📥
1. Nombre y parámetros de la plantilla WATI "actualización de trámite" → frena el paso 5.
2. Que apruebes o corrijas los textos del paso 5.
3. Confirmar el correo de Penny para la escalación, y si va alguien más en copia además de Ceci.
4. PLU3: ¿largo o corto?
5. (Si lo tenés) una captura de un correo C3 "autorizado".
