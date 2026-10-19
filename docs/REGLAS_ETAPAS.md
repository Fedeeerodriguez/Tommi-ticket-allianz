# Reglas de etapas — qué correo de Allianz es y qué hacer

Código: `app/clasificador/etapas.py` (`detectar_etapa`) · Tests: `tests/test_etapas.py`.
Fuentes:
- las capturas de Ceci (`correos allianz/`: proceso largo, proceso corto y trámites);
- los 482 correos reales de `hola@babilonia.ai`. Los 79 que importan se clasifican todos; ninguno queda en "revisar".

Sin IA: son reglas fijas. Si ninguna aplica, el correo va a **REVISAR** (panel) y no se manda nada.

## Cómo reconocer un correo (de arriba hacia abajo; gana la primera regla que aplica)

| # | Señal | Etapa |
|---|---|---|
| 1 | Remitente fuera de `allianz.com(.mx)` | no aplica |
| 2 | Asunto `Emisión póliza No. Póliza: X No. Solicitud: N` o cuerpo "¡Felicidades, su solicitud se registró correctamente!" (incluye "Solicitud de cotización N") | **emisión registrada** |
| 3 | Asunto `Aviso de emisión de póliza X …` (remite notificaciones.optimaxx / aviso.electronico / comunicados.agentes) | **póliza emitida** |
| 4 | Cuerpo "ticket que ya se encuentra cerrado" (asunto `Solicitud finalizada Ticket N`) | **rebote: ticket cerrado** |
| 5 | Sin n° de ticket (huracanes, MyAllianz, DAF, recordatorio de pago, envío a cobro) | no aplica |
| 6 | `RV:`/`RE:` + ticket, de una ejecutiva (Penny, Blanca) | **copia** (solo "para su conocimiento") o **nota de ejecutiva** (si escribió algo propio) |
| 7 | Asunto `<X> creó una nueva solicitud en su nombre` | **apertura (C1)** |
| 8 | `Sistema escribió…` + "atendida"/"queda cerrado" | **atendida (C5)** |
| 9 | `Sistema escribió…` + "cerrado por inactividad" | **cerrado por inactividad (C3.1)** |
| 10 | `Sistema escribió…` + "Le confirmamos que recibimos su solicitud" | **confirmación de datos (C2)** |
| 11 | `Sistema escribió…` + "respuesta automática… hemos recibido su solicitud" | **apertura de trámite (C1)** |
| 12 | `Sistema escribió…` + recordatorio / por cerrar | recordatorio de Allianz (se ignora) |
| 13 | Persona: "se procede a rechazar el presente ticket" | **rechazado** |
| 14 | Persona: "riesgo… declinado" | **declinado** |
| 15 | Persona: "atendida" (sin "no/aún" antes) o "folio cerrado" | **atendida (C5)** |
| 16 | Persona: "autorizado", "pasa a cobro", "en proceso de cobro" (sin "no/aún" antes) | **autorizado para cobro (C3)** |
| 17 | Lo escribe **nuestro lado** (correo @babilonia.ai, el gmail del asesor, Blanca/Penny en el ticket) y no pide nada; o "anexo/envío lo solicitado" | **documentos enviados (C4)** |
| 18 | Persona pide algo: "favor de enviar/proporcionar", "le solicitamos", "envíenos", "tiene N días", "no incluye / no coincide" | **requerimiento (C3)** |
| 19 | Nada de lo anterior | **REVISAR** |

**Actor** = lo que va antes de "escribió un mensaje" en el asunto:
- `SISTEMA` → automático.
- Un correo → nuestro lado.
- Penny o Blanca → ejecutiva (de nuestro lado).
- Un nombre (incluye `EXTERNO <nombre>`, que son los laboratorios y proveedores de Allianz) → persona de Allianz.

**Proceso**, según el título del hilo ("…escribió un mensaje en **<título>**:") y el producto:
- `[EXT] Emisión póliza …` o producto SVIP/OPPT → **corto**.
- Otro `[EXT] …`, o el acuse automático "hemos recibido" → **trámite** (lo abrimos nosotros con ese asunto).
- El resto → **largo**. El producto sale del prefijo: GMMI/GMLI (gastos médicos), VIPP (vida), OP3D (educación), HOFP (residencial), PLU3.

## Qué hacer en cada etapa

| Etapa | Avisar | Recordatorio | Responder a Allianz | Cierra |
|---|---|---|---|---|
| Apertura (largo) | Ceci, asesor, cliente ("en proceso de autorización") | — | no | — |
| Apertura (trámite) | los 3, con n° ticket + cliente + asunto | — | no | — |
| Confirmación de datos (largo / trámite) | nadie, solo estado | — | no | — |
| Confirmación de datos (**corto**) | guía de aportación → **Ceci aprueba por Telegram** → cliente y asesor | — | no | — |
| Requerimiento | los 3, diciendo **qué piden** | sí (plazo del correo o 72 h hábiles) | sí, con el documento, en el hilo | — |
| Autorizado (C3: Allianz autoriza el cobro) | los 3 | corta | no | — |
| Documentos enviados | los 3 | corta el del requerimiento y arranca "esperando a Allianz" | no | — |
| Atendida / folio cerrado (C5: ya se cobró) | los 3 | corta | no | **sí** |
| Rechazado (venció el plazo) | Ceci y asesor: "contacta al cliente" (hay que cotizar de nuevo) | corta | no | **sí** |
| Declinado | Ceci y asesor: "contacta al cliente" | corta | no | **sí** |
| Cerrado por inactividad | los 3 | corta | no | **sí** |
| Recordatorio de Allianz | nadie | — | — | — |
| Copia de ejecutiva | nadie (ya se avisó con el original). Si pide "brindar respuesta" → alerta a Ceci | — | — | — |
| Nota de ejecutiva | Ceci y asesor | — | — | — |
| Rebote: ticket cerrado | **Ceci: nuestra respuesta no entró, hay que abrir ticket nuevo** | — | — | — |
| Emisión registrada | nadie, se registra póliza y solicitud | — | — | — |
| Póliza emitida | los 3 | corta | no | **sí** (fin) |

Rechazado y declinado son **delicados**: al cliente no le sale nada automático.

## Datos que se extraen
N° de ticket, n° de solicitud, póliza (normalizada como `PLU3-429083`, sin importar si llega con `/`, `_` o `-0`), cliente, producto, quién escribió, título del hilo, **qué piden** (el texto sin saludo ni firma) y el **plazo** (`tiene 15 días hábiles` → 15 días hábiles; `cuenta con 10 días` → 10 días corridos).

## Fallas del clasificador viejo (`allianz.py`) que esto corrige
- "su solicitud **fue** atendida", "ATENDIDA" suelto, "folio cerrado" y "ticket queda cerrado" no se reconocían como cierre.
- El rebote "Solicitud finalizada…" se tomaba como **cierre** (en realidad avisa que nuestra respuesta no entró).
- Los reenvíos de Penny y Blanca (`RV:`) se tomaban como un mensaje nuevo, lo que generaba avisos repetidos.
- Las pólizas `SVIP-21799`, `PLU3/429083`, `VIPP-145029-0` y `GMLI_1131_0` no se extraían.
- Los correos de emisión de `notificaciones.optimaxx` se descartaban como "sistema".

## Confirmado con Fede (19/10)
- C1: al cliente se le dice "en proceso de autorización".
- C3 = Allianz autoriza el cobro; C5 = ya se cobró.
- Rechazado / declinado: se avisa al asesor para que contacte al cliente.
- Póliza emitida: se avisa a los 3.

## Por confirmar
1. **PLU3 (OptiMaxx Plus):** ¿proceso largo o corto (como Elite)? Hoy queda como largo.
2. **"Autorizado" (C3 del proceso largo):** no hay captura. La regla busca "autorizado", "pasa a cobro" o "en proceso de cobro". Si llega un correo real, lo sumo como test.
3. **Correo 3 del trámite (atendido / cerrado):** no hay captura. Se asume que es igual al C5 ("atendida", "folio cerrado").
