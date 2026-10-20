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

**Guía de aportación:** sale por la plantilla de WhatsApp `tommy_guia_aportacion`. Nombre, producto y póliza los pone el sistema; **Ceci completa el monto y los datos para depositar**. No es texto libre: WhatsApp no deja cambiar el texto de una plantilla.
> Hola Guillermo 👋 Allianz ya confirmó tu solicitud de Elite (póliza SVIP-21799). Para activarla falta tu aportación inicial:
>
> • Monto: *(lo completa Ceci)*
> • Datos para depositar: *(lo completa Ceci)*
> • Referencia: póliza SVIP-21799
>
> Cuando deposites, mándame por aquí el comprobante y tu estado de cuenta, y yo lo envío a Allianz.

- Sin monto y datos para depositar, **no se puede aprobar**.
- Dónde los completa Ceci:
  - **en Telegram**, respondiendo al mensaje con `Monto: $50,000 MXN` y `Datos: CLABE … a nombre de …` (en dos líneas o en una). Le llega la versión nueva con botones nuevos.
  - **en el panel**, en los dos campos. Ahí ve cómo le llega al cliente antes de aprobar.
- Tampoco se puede aprobar si el cliente y el asesor no están identificados. En ese caso, primero se asignan en el panel.

### 2. Ceci aprueba → sale la guía

| Para | Texto |
|---|---|
| Cliente | *(la guía tal cual la aprobó Ceci)* |
| Asesor | Ticket 2567479 · Guillermo Prueba Castro: le mandamos al cliente la guía de aportación (aprobada por Ceci). Monto: $50,000 MXN · Datos para depositar: CLABE … |

Arranca el **recordatorio de pago**.

### 3. Recordatorio de pago
Se manda a los 3 días hábiles desde la aprobación. Si al día hábil siguiente sigue sin llegar el pago, se escala.

| Cuándo | Para | Texto |
|---|---|---|
| Recordatorio | Cliente | Hola Guillermo, te recuerdo que falta tu aportación para activar tu Elite. Cuando deposites, mándame por aquí el comprobante y tu estado de cuenta. |
| Recordatorio | Asesor | Ticket 2567479 · Guillermo Prueba Castro: el cliente todavía no manda el comprobante de pago de la guía de aportación. Ya le recordamos al cliente. |
| Escalado | Asesor | Ticket 2567479 · Guillermo Prueba Castro: sigue sin llegar el comprobante de pago de la guía de aportación. Contacta al cliente. |
| Escalado | Ceci | Ticket 2567479 · Guillermo Prueba Castro: sigue sin llegar el comprobante de pago de la guía de aportación. |

### 4. Pago enviado a Allianz
Cuándo se da por enviado:
- **Elite:** cuando respondemos en el hilo.
- **Patrimonial:** cuando se aprieta **Pago enviado** en el panel, porque ese pago va en un correo nuevo a "cliente inversión".

| Para | Texto |
|---|---|
| Asesor | Ticket 2567479 · Guillermo Prueba Castro: se envió a Allianz el comprobante de pago, esperamos la emisión. |
| Cliente | Hola Guillermo, ya enviamos tu comprobante de pago a Allianz. Te aviso cuando tu póliza quede emitida. |

Corta el recordatorio de pago y arranca el de "esperando a Allianz", el mismo de la Etapa 1.

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

Los textos del proceso largo (Etapa 1) **no cambian**.
