# Plan de acción — Sistema de tickets Allianz (reglas reales de negocio)

Basado en las respuestas del equipo de Babilonia y en el análisis del sandbox sobre correos
reales. El foco es **solo los tickets** (`Allianz.Mexico@`). Las notificaciones
(DAF/emisión/cobranza) **YA están cubiertas** por el WATI actual del equipo → quedan fuera de
alcance (ver Fase G).

## Actualizaciones tras la llamada (2026-09-15)

**Se afinó:**
- **"Sistema escribió un mensaje" no es solo apertura:** puede ser **asignación** de ticket
  (avisar el nº al cliente), **recordatorio** (por cerrar por inactividad) o **cierre**. "Sistema"
  = Allianz avisando; hay que mirar el cuerpo para saber cuál es.
- **Actor (regla fina):** en "<actor> escribió un mensaje", si es **NOMBRE** → agente/ejecutivo de
  **Allianz**; si es **CORREO** → externo a Allianz (**cliente / asesor de Babilonia / nosotros**).
- **Ruteo:** avisos por **WATI** — a **asesores** siempre (plantilla de avances); al **cliente**
  solo cuando se le pide una acción/documento (los automáticos lo saturaban).
- **Confirmación desde el correo del cliente (obligatoria, lista final):** cancelación de póliza,
  suspensión de aportaciones, período de descanso. (Aumento/disminución NO es obligatorio.)
  Para esos, avisamos al cliente por WATI, pero la confirmación la manda **él** desde su correo.
- **Acción crítica → Ceci revisa el BORRADOR** que el bot va a enviar y da el **visto bueno antes**
  de ejecutar (hay casos donde el cliente puede **perder dinero**). No es solo "escalar".
- **SLA:** default **72 h hábiles**; el plazo real viene en la última respuesta de Allianz
  (ejecutivo o sistema). Hay un plazo aparte para el **cliente** (envío de documentos).

**Se agregó (nuevo):**
- **Bot asertivo / malas prácticas de Allianz:** Allianz "no lee y contesta otra cosa". El bot
  debe ser **crítico y direccional**: detectar respuestas fuera de tema y **volver a exigir** lo
  pedido, en vez de tragarse cualquier respuesta.
- **Destino en Allianz = un DIRECTORIO por tipo de trámite** (cliente.optimax, endosos, etc.), NO
  un único correo. Ceci va a compartir la **página de Allianz que explica trámite-por-trámite quién
  lo hace y a qué correo** → base del ruteo y del `ALLIANZ_DEST` (que pasa a ser un mapa).
- **Notion para visualización + checkbox de aprobación (visto bueno de Ceci).** Fede: frontend/
  sandbox primero, bajar a Notion después; bases nuevas en Supabase (RAG vectorial).

**Se sacó del alcance:**
- **Notificaciones (DAF / emisión / cobranza):** ya están mapeadas y con WATI por el equipo →
  el sistema nuevo NO las procesa. Fase G queda como opcional/futuro.

**Riesgos abiertos:**
- **Cobertura de casilla:** algunos correos de Allianz llegan **directo a `integraciones@`** sin
  pasar por `hola@`. Si el sistema lee solo `hola@`, puede **perder tickets**. Definir: leer ambas
  casillas o arreglar el ruteo. (Parkeado con el tema del reenvío roto.)

## Reglas de negocio confirmadas

- **Identificador:** el `Ticket-XXXX` (literal) sigue cada trámite. El remitente cambia según el
  trámite. El "nº de solicitud" es distinto: es el **nº de emisión** (se genera al emitir póliza).
- **Ciclo de vida:** mandás correo → se abre → mensaje automático asigna nº de ticket → el
  ejecutivo responde (pide algo o da el paso a seguir) → hay que responder **en el mismo hilo** →
  si no se responde en **2–15 días hábiles** el ticket **se cierra** y hay que empezar de nuevo.
- **Cierre:** Allianz manda "solicitud cerrada/atendida/finalizada". Antes de cerrar por falta de
  respuesta, manda un **recordatorio**.
- **Seguimiento por correo:** se responde **en el mismo hilo** (fuera de hilo se abre un ticket
  nuevo). El plazo para responder viene en la última respuesta de Allianz; si no viene, **72 h
  hábiles**. El correo también trae el plazo que tiene el **cliente** para responder.
- **Ruteo de avisos:** a asesores por **WATI** (plantilla de avances). Al **cliente** solo cuando
  se le pide una acción o un documento — sobre todo en procesos que requieren confirmación **desde
  el correo del cliente**: cancelación de póliza, suspensión de aportaciones, período de descanso.
- **Datos:** asesor/cliente/póliza están en Notion (base **emisiones**) → mapear por MCP.
- **⚠️ Acciones críticas:** cualquier cosa con impacto negativo crítico para el cliente
  (cancelación de póliza, suspensión de aportaciones, período de descanso, rescate/retiro total,
  fallecimiento) → **primero a Ceci** para revisión y aprobación manual antes de ejecutar.

## Subtipos reales (validados en el sandbox)

| Subtipo | Origen / patrón | Acción |
|---|---|---|
| `apertura_nuestra` | "Sistema creó una nueva solicitud en su nombre" | avisar al cliente el nº de ticket |
| `asignacion_ticket` | "Sistema escribió un mensaje" (asigna nº) | avisar al cliente el nº de ticket |
| `recordatorio` | "Sistema escribió un mensaje" + texto de cierre próximo | **urgente**: responder en el hilo |
| `respuesta_participante` | "<actor> escribió un mensaje" (nombre=Allianz, correo=no participante) | leer; si piden algo → pedírselo al cliente/asesor |
| `cierre` | "solicitud cerrada/atendida/finalizada" | marcar ticket resuelto |
| `notif_daf/emision/cobranza` | remitentes de notificaciones | **fuera de alcance** (ya cubierto por el WATI del equipo) |

## Fases de implementación

### Fase A — Clasificador real (reemplazar supuestos)
- Normalizar todo el texto entrante a **NFC** (Allianz manda en Unicode descompuesto).
- Priorizar el **dominio Allianz** antes de las reglas genéricas de ruido.
- Reconocer los subtipos de la tabla; extraer **nº ticket**, **actor** (nombre/correo), **plazos**, **detalle del mail**.
- Mapear subtipos → taxonomía interna (`TipoCorreo`), agregando los que falten.

- Obtener los tipos de correo que manda allianz, tener un ejemplo de cada uno y extraer la informacion para ver el orden que ellos utilizan

### Fase B — Ticket con hilo (seguimiento por correo)
- Guardar el **`threadId` de Gmail** + `References` por ticket para **responder en el mismo hilo**
  (funciona aunque el Message-ID venga roto — confirmado en el sandbox).
- `EmisorGmail`: soportar **responder dentro de un hilo** (threadId + In-Reply-To/References,
  manteniendo el asunto `[Allianz México Ticket-XXXX]`).
- Estados alineados a Allianz: abierto / esperando_allianz / esperando_cliente / por_cerrar / cerrado.
- Detección de **cierre** → resuelto; detección de **recordatorio de cierre** → acción urgente.

### Fase C — SLA / plazos hábiles
- Extraer el plazo de la última respuesta de Allianz; si no viene → **72 h hábiles**.
- Extraer el plazo que tiene el **cliente**.
- Cálculo en **días/horas hábiles** (calendario laboral MX).
- Recordatorios **antes** del cierre para no perder el ticket.

### Fase D — Ruteo y notificaciones
- Asesor → **WATI** (plantilla de avances).
- Cliente → **WATI-PLANTILLA**, solo cuando requiere acción/documento; procesos con confirmación desde el
  correo del cliente (cancelación, suspensión de aportaciones, período de descanso).
- **Seguimiento a Allianz** → por **correo, en el hilo del ticket** (esto NO es WATI).
- **Destino en Allianz = directorio por tipo de trámite** (cliente.optimax, endosos, etc.) →
  pendiente la página de Allianz "trámite-por-trámite" que comparte Ceci.
- **Asertividad:** si Allianz responde fuera de tema, el bot re-exige lo pedido (no lo da por bueno).

### Fase E — Guardarraíl de acciones críticas (Ceci primero)
- Extender el guardarraíl `delicado/autorizado` con la lista crítica: **nunca se ejecutan solas**;
  van a **Ceci** para aprobación manual antes de ejecutar.
- **Ceci revisa el BORRADOR** de la respuesta que el bot va a mandar y da el **visto bueno** antes
  de que se ejecute (hay casos donde el cliente puede perder dinero).
- Lista crítica: cancelación de póliza, suspensión de aportaciones, período de descanso, rescate /
  retiro total, siniestro / fallecimiento.
- Los mensajes a **Ceci** van por **WATI**

### Fase F — Enriquecimiento desde Notion (base emisiones)
- Mapear campos de la base **emisiones** (póliza, cliente, correo del cliente, asesor) vía Notion
  MCP; cruzar por póliza / nº de solicitud para rutear al destinatario correcto.
-Crear **Rieles** en python para que encuentre las bases de datos y campos necesarios de forma automatica en notion

### Fase G — Notificaciones (FUERA DE ALCANCE / futuro)
- DAF/emisión/cobranza **ya están cubiertas** por el WATI actual del equipo → el sistema nuevo NO
  las procesa. Solo se retomaría si más adelante se quiere sumar ese conocimiento a la base.

## Sandbox (herramienta de apoyo — ya construida)
- `app/sandbox.py` + `python -m app.run_sandbox [query] [límite]`: lee correos reales por Gmail API
  (**solo lectura**, no envía ni escribe) y muestra, por correo, el subtipo, nº de ticket, actor,
  plazos, datos de hilo y banderas (crítico / Message-ID roto). Vuelca el detalle a
  `data/sandbox_analisis.json`. Se usa para **validar cada fase contra datos reales** antes de
  activarla.

## Orden sugerido
A → B → C → D → E (transversal, se aplica desde el inicio) → F → G. Cada fase se valida con el
sandbox antes de tocar el modo real (`DRY_RUN=false`).
