# Plan de desarrollo — Mapa de procesos Allianz

Base: mapa conceptual de Fede + llamada del 09/10/2026 con Ceci y José (detalle en Obsidian, nota Tomi-Allianz → "Mapa de procesos Allianz").
Prioridad que marcó José: **el sistema de seguimiento** (etapas, avisos, recordatorios). Todo lo demás viene después.
Regla general: cada fase sale primero en **sandbox** (DRY_RUN + aprobación en el panel). Una etapa recién pasa a envío automático cuando Ceci aprueba 20 envíos seguidos sin editar.

Marca 📥 = depende de material que Fede está ordenando (lo que mandó Ceci por WhatsApp).

---

## Fase 0 — Estabilizar y armar el corpus (≈3 días)
Antes de construir encima, dejar limpio lo que hay.
- Bug del guardarraíl: "Hemos" (y palabras con mayúscula al inicio de oración) tomadas como nombre → lista de palabras comunes excluidas + test con el caso real.
- Reactivaciones "omitidas" que se repiten una por día por ticket → registrar una sola vez por ticket/motivo.
- **Corpus de etapas:** exportar de `tickets_allianz.correos` los correos reales y etiquetarlos a mano con su etapa (C1…C5, bloque, producto). 📥 Sumar las capturas de los correos 1–5 de una emisión.
- **Contactos en config** (tabla `tickets_allianz.contactos`, no hardcodeado): Penny, Beto, "cliente inversión", integraciones, José Mier, ejecutivos. 📥
- Hecho cuando: tests verdes, corpus con ≥5 correos reales por etapa.

## Fase 1 — Detector de etapas (≈1 semana)
Hoy el ticket tiene `subtipo` (asignación, respuesta, cierre…) pero no sabe **en qué etapa del proceso** está.
- Campos nuevos en `tickets`: `bloque` (`bloque1` / `bloque2` / `tramite`), `producto` (Auto, SV, SGMM, OP3D, HOFP, SVIP, OPPT) y `etapa` (`C1`…`C5`, `C3_autorizado`, `C3_req_adicional`, `C3_1_inactividad`). Migración SQL con respaldo.
- Producto/bloque: por prefijo de póliza y asunto (reglas, sin IA).
- Etapa: **reglas primero** (frases fijas de Allianz: "emisión", "confirmación de datos", "autorizado", "atendida, en proceso de cobro"…), IA solo si ninguna regla matchea, temperatura 0 y respuesta de una lista cerrada. Si la IA duda → `etapa = revisar` y va al panel, nunca se adivina.
- Requerimiento adicional = lo escribe una **persona** de Allianz en el hilo (no "Sistema"); extraer QUÉ pide y el plazo.
- La etapa solo avanza (C3 no vuelve a C1), salvo rechazo de documento que reabre el requerimiento.
- Tests: un test por correo del corpus.
- Hecho cuando: ≥95 % del corpus bien clasificado y 0 errores en cierres (C5).

## Fase 2 — Matriz de avisos (≈1 semana)
Reemplaza la lógica suelta de `motor.py`/`resumen.py` por **una tabla** (código + test) etapa → acción:

| Etapa | Avisar a | Recordatorio | Responder a Allianz | Cierra |
|---|---|---|---|---|
| B1 C1 emisión + ticket | Ceci, cliente, asesor | no | no | no |
| B1 C2 confirmación de datos | nadie (solo estado) | no | no | no |
| B1 C3 autorizado | los 3 | no | no | no |
| B1 C3 req. adicional | los 3 (qué piden) | sí | sí, con el doc | no |
| B1 C4 envío de documentos | los 3 | no | no | no |
| B1 C5 atendida | los 3 | no | no | **sí** |
| B2 C1 emisión | nadie (registrar) | no | no | no |
| B2 C2 confirmación + ticket | Ceci por Telegram → cliente y asesor | no | no | no |
| B2 C3 pago | — (fase 5) | sí | sí | al confirmar emisión |

- **Un aviso por (ticket, etapa)**: clave única en la base → mata los "4+ avisos por un correo".
- Contenido fijo: asesor = n° ticket + cliente + qué pide; cliente = ticket + qué se le pide en lenguaje simple; Ceci recibe todo.
- Canal: plantilla WATI de "actualización de trámite" que ya usan (ticket, tipo de trámite, cliente, teléfono). 📥 Nombre exacto de la plantilla y sus parámetros.
- Respuestas a Allianz cortas ("Wendy, gracias por tu apoyo") → regla dura en el redactor + guardarraíl de largo máximo.
- Hecho cuando: replay de los correos de los últimos 30 días en sandbox no genera ni un aviso duplicado ni uno en etapa "no avisar".

## Fase 3 — Motor de recordatorios y escalamiento (≈1 semana)
`tickets/sla.py` ya calcula horas hábiles con feriados MX; falta el motor.
- Tabla `recordatorios` (ticket, a quién, motivo, vence, estado).
- Se activa: (a) Allianz pide algo con plazo, (b) **nosotros** mandamos algo que espera respuesta de Allianz (no un "gracias").
- 72 h hábiles (o el plazo del correo, el menor) → recordar a quien falte. +24 h → escalar: correo con **copia a Penny** + aviso a Ceci.
- Se cancela solo cuando llega la respuesta que se esperaba. Los recordatorios automáticos de Allianz se ignoran.
- El requerimiento adicional usa este mismo esquema.
- Tests con reloj simulado (viernes → lunes, feriados).
- Hecho cuando: ningún recordatorio sale dos veces y todos se cortan al responder.

## Fase 4 — Tablero de Ceci (≈4 días)
En el panel actual (Admin/Super Admin): tickets abiertos por etapa, quién tiene la pelota, próximo recordatorio, escalados, últimos avisos enviados. Filtros por asesor y producto.
Va acá porque con F1–F3 ya hay datos reales para mostrar, y es lo que Ceci va a mirar todos los días en el sandbox.

## Fase 5 — Documentos por WhatsApp → correo (≈1 semana, con prueba técnica)
- **Prueba técnica primero (1 día):** que WATI nos pase el archivo (webhook → descargar media). Si no se puede, alternativa: link de Drive.
- El cliente manda el doc a Tommy → backend busca su ticket con requerimiento pendiente → Tommy escribe un **correo nuevo en el hilo** con el adjunto (no reenvía: el cliente no ve lo que dice Allianz).
- Si el cliente o el asesor ya lo mandaron en el hilo → no duplicar. Si Allianz lo rechaza → vuelve a C3 req. adicional y se pide de nuevo.
- Necesita un tool nuevo en n8n (`documento_ticket_python`).

## Fase 6 — Bloque 2 (Elite / Patrimonial) (≈1,5 semanas)
- **Aprobación por Telegram:** en C2 se genera la guía de aportación → a Ceci con botones [Aprobar] / [Editar] → al aprobar, sale a cliente y asesor. Prueba técnica del bot primero. 📥 Speech de la guía de aportación.
- C3 pago: el cliente manda comprobante + estado de cuenta a Tommy →
  - **Elite:** respuesta en el hilo, cc Ceci + José Mier + integraciones.
  - **Patrimonial:** correo nuevo (ticket nuevo) a "cliente inversión", cc Ceci + Beto + integraciones. 📥 Direcciones.
- Confirmación → aviso de emisión → cierra.

## Fase 7 — Trámites salientes (≈1,5 semanas)
- Tickets que abrimos nosotros: C1 asignación, C2 requerimiento/observación (recordatorio), C3 atendido/cerrado, C3.1 cerrado por inactividad. Mismos avisos (n° ticket + cliente + asunto).
- Caso más común primero: cliente atrasado manda transferencia + estado de cuenta.
- Trámites que hacemos nosotros (aumento/disminución de aportación, cambio de conducto de cobro): **prueba de autollenado del PDF** de solicitud; el cliente solo firma. 📥 Lista de trámites por portal vs por correo + PDFs en blanco.

## Fase 8 — Preguntas a ejecutivos (≈1 semana)
- Asesor pregunta a Tommy algo que no sabe → correo al ejecutivo según el **Directorio de Notion** (Beto Patrimonial, Blanca GMM, Juan PPR, Nelda Auto). 📥 Acceso al Directorio.
- La respuesta vuelve al asesor por WhatsApp y **se guarda** en el conocimiento de Tommy (RAG) para no volver a preguntar. Sin respuesta → recordatorio/escalamiento de la Fase 3.
- Toca los dos repos (tool nuevo en Tomi + correo en Allianz).

## Aparte (no bloquea)
- Falla de reenvío de "Hola Babilonia" → diagnóstico propio, José dijo que va por separado.
- Pedirle al equipo que vuelva a calificar en el panel (0 calificaciones desde el 08/10): sin eso no hay métrica para pasar a automático.

---

## Orden y tiempos
F0 → F1 → F2 → F3 → F4 (seguimiento completo, ~4 semanas) · después F5–F8 según llegue el material (~5–6 semanas).
Las pruebas técnicas de F5 (WATI media), F6 (Telegram) y F7 (PDF) se pueden hacer en paralelo desde ya: son de un día cada una y sacan riesgo.
Tiempos estimados de desarrollo; no incluyen los 2–3 meses de sandbox que pidió Ceci.

## Lo que necesito de Fede 📥
1. Correos de una emisión completa (1–5) de bloque 1 y de bloque 2 → **frena F1**.
2. Direcciones: Penny, Beto, "cliente inversión", integraciones, José Mier, ejecutivos → frena F3 (escalar) y F6.
3. Nombre y parámetros de la plantilla WATI "actualización de trámite" → frena F2.
4. Speech de la guía de aportación → F6.
5. Lista de trámites portal vs correo + PDFs de solicitud → F7.
6. Acceso al Directorio de ejecutivos en Notion → F8.
