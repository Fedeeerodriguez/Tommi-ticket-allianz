# Plan de acción — Sistema de tickets Allianz (reglas reales de negocio)

Basado en las respuestas del equipo de Babilonia y en el análisis del sandbox sobre correos
reales. El foco de arranque son **los tickets** (`Allianz.Mexico@`); las notificaciones
(DAF/emisión/cobranza) se ingieren para conocimiento pero **no accionan** todavía.

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
| `notif_daf/emision/cobranza` | remitentes de notificaciones | (fase 2) solo registrar |

## Fases de implementación

### Fase A — Clasificador real (reemplazar supuestos)
- Normalizar todo el texto entrante a **NFC** (Allianz manda en Unicode descompuesto).
- Priorizar el **dominio Allianz** antes de las reglas genéricas de ruido.
- Reconocer los subtipos de la tabla; extraer **nº ticket**, **actor** (nombre/correo), **plazos**.
- Mapear subtipos → taxonomía interna (`TipoCorreo`), agregando los que falten.

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
- Cliente → **correo**, solo cuando requiere acción/documento; procesos con confirmación desde el
  correo del cliente (cancelación, suspensión de aportaciones, período de descanso).

### Fase E — Guardarraíl de acciones críticas (Ceci primero)
- Extender el guardarraíl `delicado/autorizado` con la lista crítica: **nunca se ejecutan solas**;
  van a **Ceci** para aprobación manual antes de ejecutar.

### Fase F — Enriquecimiento desde Notion (base emisiones)
- Mapear campos de la base **emisiones** (póliza, cliente, correo del cliente, asesor) vía Notion
  MCP; cruzar por póliza / nº de solicitud para rutear al destinatario correcto.

### Fase G — Notificaciones (fase 2)
- Ingerir DAF/emisión/cobranza como conocimiento (registrar + vincular por póliza/solicitud), sin
  accionar todavía.

## Sandbox (herramienta de apoyo — ya construida)
- `app/sandbox.py` + `python -m app.run_sandbox [query] [límite]`: lee correos reales por Gmail API
  (**solo lectura**, no envía ni escribe) y muestra, por correo, el subtipo, nº de ticket, actor,
  plazos, datos de hilo y banderas (crítico / Message-ID roto). Vuelca el detalle a
  `data/sandbox_analisis.json`. Se usa para **validar cada fase contra datos reales** antes de
  activarla.

## Orden sugerido
A → B → C → D → E (transversal, se aplica desde el inicio) → F → G. Cada fase se valida con el
sandbox antes de tocar el modo real (`DRY_RUN=false`).
