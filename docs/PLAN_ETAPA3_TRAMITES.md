# Plan Etapa 3 — Trámites que hacemos nosotros (Fase 7)

Estado: **A hecha (23/10)**; B y C esperan material. Va sobre la rama `feat/etapas-allianz` (pantalla: `tomi-babilonia` → `feat/panel-etapas-allianz`).

## A — cómo quedó (23/10)
- **Panel → "Abrir un trámite con Allianz"**:
  - Ceci elige el trámite (del catálogo u "Otro…") y la póliza, y suma una nota y adjuntos (hasta 5, 8 MB en total).
  - **Ver cómo sale** muestra el cliente y el asesor identificados, el destino, el asunto y el cuerpo.
  - **Abrir trámite** lo crea.
- **Identificación:** la póliza se busca exacta en Notion Emisiones. Si no aparece o es ambigua, **no se abre**: no se adivina a quién avisar después.
- **El correo** (`app/acciones/abrir_tramite.py`):
  - texto fijo, sin IA; sale desde hola@ en el próximo ciclo del worker (respeta `DRY_RUN`);
  - asunto `<Trámite> - Póliza <X> - <Cliente>`, con guion ASCII para que Allianz no lo deforme;
  - destino: `ALLIANZ_DIRECTORIO[clave]`, o si no está, `ALLIANZ_DEST`. Sin destino queda **bloqueado** y aparece en "Para Ceci".
  - **No se retiene para aprobar:** lo armó y lo revisó Ceci misma. Por eso tampoco se frena si el tema es "crítico".
- **Vuelta de Allianz:** el acuse `[EXT] <nuestro asunto>` se engancha solo a ese ticket (`enlazar`, en `n_upsert_ticket`). La coincidencia tolera acentos y títulos recortados. Desde ahí sigue el seguimiento de trámites de la Etapa 2.
- **Al abrir no se avisa al cliente ni al asesor:** el aviso sale con el acuse, que ya trae el n° de ticket. Así no les llegan dos mensajes en minutos.
- **Ventaja:** como sale de hola@, la respuesta de Allianz vuelve a hola@. Los trámites que abrimos desde el panel ya no dependen del reenvío desde `integraciones@`.
- **También en esta entrega:**
  - **Enviar / Descartar** desde el panel los correos retenidos para Ceci. Antes no había cómo aprobar la escalación a Allianz con copia a Penny.
  - **El borrador editado en el panel ahora es el que se envía.** Antes salía el original.
- **Duplicados:** un trámite igual (mismo asunto) que sigue abierto → 409, no se abre otro.
- **Tests:** `tests/test_abrir_tramite.py` (20). Total: 259.
- **Variable nueva opcional:** `ALLIANZ_DIRECTORIO` (JSON clave→correo, por ejemplo `{"cambio_conducto_cobro": "…@allianz.com.mx"}`). Ya pasa por el compose.

---
**Propuesta original (22/10):**

## Qué ya está (Etapa 2)
- **Seguimiento del trámite** una vez abierto (hilo `[EXT] <nuestro asunto>`):
  - C1 acuse, C2 requerimiento con recordatorio, nuestra respuesta con escalación, C3/C3.1 cierre;
  - avisos con n° de ticket + cliente + asunto.
- **Catálogo** (`app/tramites/catalogo.py`): qué trámite hace el cliente solo en el portal (Tommy le da los pasos) y cuál hacemos nosotros por correo (hoy solo el cambio de conducto de cobro → acción `gestionar_tramite`).

## Lo que falta: abrir el trámite nosotros
Hoy el trámite se abre a mano desde `integraciones@`. Faltan tres piezas, de menor a mayor dependencia de material:

### A. Abrir el trámite desde el panel (no depende de material)
- Ceci elige cliente (de Notion), póliza y tipo de trámite, y agrega una nota opcional.
- El sistema arma el correo a Allianz:
  - destino = directorio por trámite (`ALLIANZ_DIRECTORIO`), y si no está, `ALLIANZ_DEST`;
  - asunto fijo `<Trámite> · Póliza <X> · <Cliente>`, para que el acuse de Allianz se enganche solo al cliente (hoy, sin póliza en el asunto, el aviso cae a Ceci).
- Crea el ticket como `proceso=tramite`, con cliente y asesor ya identificados.
- El correo queda **para aprobar** en el panel, como los demás envíos a Allianz. Respeta `DRY_RUN`.
- Le avisa al cliente y al asesor: "abrimos tu trámite".

### B. Cliente atrasado: transferencia + estado de cuenta (el caso más común)
- El cliente le manda los dos archivos a Tommy → se arma el trámite de A con los adjuntos.
- **Depende de F5:** que WATI nos deje descargar el archivo. Primero va una prueba técnica de 1 día. Si WATI no lo permite, la alternativa es un link de Drive.
- Mientras tanto, Ceci sube los adjuntos a mano en la pantalla de A.

### C. Autollenado del PDF de solicitud
- Trámites: aumento o disminución de aportación y cambio de conducto de cobro.
- Con los datos de Notion se llena el PDF y el cliente solo firma.
- Sale por Tommy como documento, o adjunto en el correo de A.
- **Depende de 📥:** los PDFs en blanco. Si traen campos rellenables, es rápido; si son escaneados, hay que ubicar cada texto por coordenadas, por cada formulario.

## Orden propuesto
1. **A** (≈4 días): API + pantalla + tests. Se prueba con el informe de la semana de prueba.
2. **Prueba técnica de F5** (1 día), en paralelo, para destrabar B.
3. **B** (≈3 días), si la prueba sale.
4. **C** (≈1 día por formulario rellenable), cuando lleguen los PDFs.

## Lo que necesito 📥
1. **PDFs en blanco** de los formularios: aumento y disminución de aportación, cambio de conducto de cobro → frena C.
2. **Directorio Allianz por trámite:** a qué correo va cada uno (la página de Allianz que iba a pasar Ceci). Sin esto, todo va a `ALLIANZ_DEST`.
3. **Lista de trámites por portal vs por correo**, para completar el catálogo. Hoy por correo solo figura el conducto de cobro.
4. Confirmar el **formato del asunto** con Ceci.
