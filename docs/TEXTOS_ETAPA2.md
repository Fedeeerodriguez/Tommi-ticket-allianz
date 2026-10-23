# Textos de los avisos — Etapa 2 (proceso corto y trámites)

Estado: **para aprobar** (Fede / Ceci). Los textos salen de `app/acciones/mensajes_etapa.py`: lo que se lee acá es exactamente lo que se manda.

Las reglas son las mismas de la Etapa 1 (`docs/TEXTOS_ETAPA1.md`):
- textos fijos, sin IA;
- tuteo mexicano;
- Ceci recibe lo mismo que el asesor, más lo que no se pudo avisar (⚠️);
- cada aviso sale una sola vez.

---

## Proceso corto (Elite · Patrimonial · OptiMaxx Plus)

Ejemplo: ticket 2567479 · Guillermo Prueba Castro · Elite (SVIP) · póliza SVIP-21799.

### 1. Allianz confirma los datos (C2) → la guía queda para que Ceci la apruebe
Al cliente y al asesor **no les sale nada** hasta que Ceci aprueba.

| Para | Texto |
|---|---|
| Ceci (Telegram) | Guía de aportación · Ticket 2567479 · Guillermo Prueba Castro · Elite<br><br>*(la guía, abajo)*<br><br>[✅ Aprobar] [🗑 Descartar] |
| Ceci (WhatsApp, solo si no está Telegram) | Ticket 2567479 · Guillermo Prueba Castro · Elite: Allianz confirmó los datos (póliza SVIP-21799). La guía de aportación está lista para que la apruebes. |

**Guía de aportación:** una por producto, cada una con su plantilla de WhatsApp. Son los pasos que Ceci le manda hoy al cliente (22/10). La cuenta para depositar viene en el correo "Felicidades" de Allianz; **lo que Ceci confirma es el número de solicitud**, que es la referencia del pago. El número ya viene precargado del correo de Allianz.

**Patrimonial** (`tommy_guia_patrimonial`):
> Hola Ana 👋 Allianz ya registró tu solicitud de Patrimonial. Para activarla falta tu aportación:
>
> 1. En el correo de Allianz “Felicidades” (Emisión de póliza) está la cuenta bancaria para la aportación.
> 2. Haz el pago por la cantidad exacta registrada en tu solicitud. En concepto y referencia pon SOLO tu número de solicitud: 25290001. Si no lo incluyes, Allianz no podrá reconocer tu pago.
> 3. Envía el comprobante y tu estado de cuenta bancario a cliente.inversion@allianz.com.mx con copia a soporte@babilonia.ai. En el asunto pon: Aplicación de fondos / OPPT-48211 / Ana Prueba Ruiz
>
> Tu aportación se refleja en el portal 48 horas hábiles después de que Allianz confirme el pago.

**Elite** (`tommy_guia_elite`): igual, pero el comprobante va **como respuesta al mismo ticket de soporte**:
> 3. Envía el comprobante y tu estado de cuenta bancario respondiendo al correo del ticket de soporte 2567479 de Allianz (no abras uno nuevo), con copia a soporte@babilonia.ai. En el asunto pon: Aplicación de fondos / SVIP-21799 / Guillermo Prueba Castro

**OptiMaxx Plus** (`tommy_guia_aportacion`, provisoria hasta tener sus pasos): Ceci completa monto y datos para depositar.

- Sin número de solicitud (o, en OptiMaxx Plus, sin monto y datos) **no se puede aprobar**.
- Dónde lo confirma o corrige Ceci:
  - **en Telegram**: si está bien, aprieta Aprobar; para corregirlo, responde `Solicitud: 25290001` y le llega la versión nueva.
  - **en el panel**, en el campo. Ahí ve cómo le llega al cliente antes de aprobar.
- Tampoco se puede aprobar si el cliente y el asesor no están identificados. En ese caso, primero se asignan en el panel.

### 2. Ceci aprueba → sale la guía

| Para | Texto |
|---|---|
| Cliente | *(la guía tal cual la aprobó Ceci)* |
| Asesor | Le mandamos al cliente la guía de aportación (aprobada por Ceci). Número de solicitud: 25287681. |

### 3. Recordatorio de pago
**Patrimonial y Elite no tienen recordatorio de pago**: el cliente manda el comprobante por su cuenta. Solo OptiMaxx Plus lo tiene (variable `RECORDATORIO_PAGO_PRODUCTOS`, hoy `PLU3`): a los 3 días hábiles de aprobar la guía, y si al día hábil siguiente sigue sin llegar, se escala.

| Cuándo | Para | Texto |
|---|---|---|
| Recordatorio | Cliente | Te recuerdo que falta tu aportación para activar tu OptiMaxx Plus. Cuando deposites, mándame por aquí el comprobante y tu estado de cuenta. |
| Recordatorio | Asesor | El cliente todavía no manda el comprobante de pago de la guía de aportación. Ya le recordamos al cliente. |
| Escalado | Asesor | Sigue sin llegar el comprobante de pago de la guía de aportación. Contacta al cliente. |
| Escalado | Ceci | Sigue sin llegar el comprobante de pago de la guía de aportación. |

### 4. Pago enviado a Allianz
Cuándo se da por enviado:
- **Elite:** cuando el comprobante llega como respuesta al ticket.
- **Patrimonial:** cuando se aprieta **Pago enviado** en el panel, porque ese comprobante va en un correo aparte a cliente.inversion@ (con copia a soporte@).

| Para | Texto |
|---|---|
| Asesor | Ticket 2567479 · Guillermo Prueba Castro: Allianz ya tiene el comprobante de pago, esperamos la emisión. |
| Cliente | Hola Guillermo, Allianz ya tiene tu comprobante de pago. Te aviso cuando tu póliza quede emitida. |

Arranca el recordatorio de "esperando a Allianz", el mismo de la Etapa 1 (y en OptiMaxx Plus corta el de pago).

### 5. Póliza emitida → cierra
Es el mismo texto de la Etapa 1.

| Para | Texto |
|---|---|
| Asesor | Ticket 2567479 · Guillermo Prueba Castro: póliza SVIP-21799 emitida. |
| Cliente | Hola Guillermo, ¡tu póliza SVIP-21799 ya está emitida! Te va a llegar el acceso al portal de Allianz. |

---

## Trámites (los abrimos nosotros)

Siempre llevan **n° de ticket + cliente + asunto** (pedido de Ceci). El asunto es el título con que abrimos el hilo, sin el "[EXT]".

Ejemplo: ticket 2587626 · Ana Ruiz Pérez · "Aplicación de mensualidad".

| Etapa | Para | Texto |
|---|---|---|
| Allianz recibió el trámite (C1) | Asesor | Ticket 2587626 · Ana Ruiz Pérez · Aplicación de mensualidad: Allianz recibió el trámite. |
| | Cliente | Hola Ana, Allianz ya recibió tu trámite «Aplicación de mensualidad» (ticket 2587626). Te aviso cada avance. |
| Allianz pide algo (C2) | Asesor | Ticket 2587626 · Ana Ruiz Pérez · Aplicación de mensualidad: Allianz pide → *(lo que piden)*. Plazo: 72 h hábiles. |
| | Cliente | Hola Ana, para avanzar con tu trámite «Aplicación de mensualidad», Allianz necesita: *(lo que piden)*. Tienes hasta el 22/10/2026. Mándamelo por aquí y yo lo envío. |
| Le respondimos a Allianz | Asesor | Ticket 2587626 · Ana Ruiz Pérez · Aplicación de mensualidad: le respondimos a Allianz, esperamos respuesta. |
| | Cliente | Hola Ana, ya le mandamos a Allianz lo de tu trámite «Aplicación de mensualidad». Te aviso cuando respondan. |
| Atendido (C3) → cierra | Asesor | Ticket 2587626 · Ana Ruiz Pérez · Aplicación de mensualidad: Allianz lo atendió. Ticket cerrado. |
| | Cliente | Hola Ana, ¡listo! Allianz atendió tu trámite «Aplicación de mensualidad». |
| Cerrado por inactividad (C3.1) | Asesor | Ticket 2587626 · Ana Ruiz Pérez · Aplicación de mensualidad: Allianz cerró el ticket por inactividad. Contacta al cliente para retomarlo. |
| | Cliente | Hola Ana, Allianz cerró tu trámite «Aplicación de mensualidad» por falta de respuesta. Tu asesor te va a contactar para retomarlo. |
| Rechazado | Asesor | Ticket 2587626 · Ana Ruiz Pérez · Aplicación de mensualidad: Allianz rechazó el trámite. Contacta al cliente. |

Al cliente no le sale nada cuando el trámite es rechazado, igual que en la Etapa 1.

**Lo que piden** se copia del correo de Allianz, sin saludo ni firma y recortado a 300 caracteres. En el trámite de la captura queda así: "Revisamos su pago y observamos que no incluye la fecha de pago. Por favor, envíenos el estado de cuenta". Allianz le habla de usted; el resto del mensaje tutea.

**Si el asunto no trae la póliza**, no hay cómo saber de qué cliente es. El aviso va solo a Ceci, que lo asigna en el panel:
> Ticket 2587626 · cliente sin identificar · Aplicaciónes de mensualidad: Allianz recibió el trámite.
> ⚠️ No pude identificar al cliente/asesor (…): no se le avisó al asesor.

Para que se identifique solo, conviene poner la **póliza en el asunto** de los trámites que abrimos.

### Recordatorios y escalación del trámite
Son los mismos de la Etapa 1, con el asunto:

| Cuándo | Para | Texto |
|---|---|---|
| Recordatorio del pedido | Asesor | Ticket 2587626 · Ana Ruiz Pérez · Aplicación de mensualidad: sigue pendiente lo que pidió Allianz → *(lo que piden)*. |
| Allianz no responde | Ceci | Ticket 2587626 · Ana Ruiz Pérez · Aplicación de mensualidad: Allianz no responde desde que mandamos nuestra respuesta (20/10). Si sigue sin responder, se escala con copia a la ejecutiva. |

**Correo de escalación** (en el hilo, con copia a la ejecutiva; Ceci lo aprueba antes de que salga):
> Buen día,
>
> Damos seguimiento al trámite «Aplicación de mensualidad» de Ana Ruiz Pérez (ticket 2587626). El 20/10 enviamos la información solicitada y a la fecha no hemos recibido respuesta.
>
> ¿Nos apoyan con el estatus, por favor?
>
> Quedamos atentos.
> Babilonia

### Correo para abrir un trámite desde el panel (Etapa 3)
Sale desde hola@ al correo de Allianz de ese trámite. El texto es fijo; la nota de Ceci y los adjuntos son opcionales.

**Asunto:** `Cambio de conducto de cobro - Póliza PLU3-408444 - Ana Prueba Lopez`
> Buen día,
>
> Solicitamos su apoyo con el trámite de cambio de conducto de cobro para la póliza PLU3-408444, contratante Ana Prueba Lopez.
>
> *(nota de Ceci, si escribió una)*
>
> Adjuntamos: formato.pdf.
>
> Quedamos atentos.
> Babilonia

Al abrir **no** se avisa al cliente ni al asesor: les llega el aviso del acuse de Allianz (el de arriba, con el n° de ticket).

Los textos del proceso largo (Etapa 1) **no cambian**.
