# Textos de cobranza

Estado: **para aprobar** (Ceci / Yans). Generado desde `app/acciones/cobranza_resumen.py`: lo que se lee acá es exactamente lo que sale.

Acordado con Yans y Ceci (17/11/2026):
- **Todos los días hábiles a las 10:00 (México)**, con lo acumulado desde el último resumen (el lunes incluye el fin de semana):
  - a **Yans**, un correo con un **Excel adjunto**: todas las pólizas con cargo rechazado, por asesor y de más a menos días de atraso, y al final una lista aparte **"Sin asesor"**;
  - a **Ceci**, un WhatsApp con las pólizas sin asesor (no están en Notion o no tienen asesor), para que las asigne.
- **Martes y jueves a las 10:00**, a **cada asesor**: un correo con el detalle de sus clientes (el mismo Excel, solo con los suyos) y un WhatsApp con la cantidad.
- Al cliente no se le escribe: lo contacta cobranza por su WATI. Pasa a automático cuando la tasa de acierto sea buena.
- Las pólizas que Yans marca en la tabla de Cobranzas de Notion como **"Pago hecho: aplicado"** dejan de salir.

**Días de atraso:** desde la fecha del intento de cobro del **primer** correo de cobranza de esa póliza (si Allianz reintenta, sigue contando desde el primero). Es más exacto que la base de Notion, que se actualiza a mano cada 1 o 2 semanas.

## Excel (columnas)

Asesor · Cliente · Teléfono del cliente · Plan · Póliza · N° de aportación · Monto · Días de atraso · Fecha del primer cargo rechazado · Motivo del banco · Próximo intento · Avisos. En la lista "Sin asesor" se agrega la columna "Por qué no tiene asesor".

## Plantillas de WhatsApp para crear en WATI

Las dos: categoría **Utility**, idioma **Spanish (MEX)**, variables por nombre.

### `tommy_cobranza_asesor` (al asesor, martes y jueves)

```
Hola {{nombre}} 👋 Tienes {{cantidad}} con cargo rechazado por Allianz. Te mandé el detalle a tu correo: contacta a cada uno para que tenga el monto disponible o se ponga al corriente.

Recuerda que luego de 60 días de atraso se puede cancelar el plan en cualquier momento.

— Tommy · Babilonia
```

Ejemplos para Meta: `nombre` = Luisa · `cantidad` = 3 clientes

### `tommy_cobranza` (a Ceci, pólizas sin asesor)

```
🔔 *Cobranza Allianz*
{{cantidad}} un cargo rechazado:
{{clientes}}

{{indicacion}}
Recuerda que luego de 60 días de atraso se puede cancelar el plan en cualquier momento.

— Tommy · Babilonia
```

Ejemplos para Meta:
- `cantidad`: 2 pólizas sin asesor tuvieron
- `clientes`: Luisa Prueba Soto (OptiMaxx Plus PLU3-437821): 23 días de atraso, $2,000.00, fondos insuficientes; Pedro Dos (OptiMaxx Plus PLU3-500001): 9 días de atraso, $1,500.00, fondos insuficientes
- `indicacion`: No encontré a quién avisarle: asígnalas en Notion o avísale tú al asesor.

Van las 6 con más atraso; si hay más: "y N más en el correo de cobranza".

## Correo de Yans (ejemplo)

```
Asunto: [Tommi] Cobranza 18/11: 4 pólizas con cargo rechazado

Cargos rechazados desde el último resumen: 4 pólizas de 2 asesores.
No incluye 1 con el pago ya aplicado en Notion.

El detalle (cliente, teléfono, póliza, aportación, monto, días de atraso) va en el Excel adjunto, de más a menos atraso.

Asesor Uno: 2
Asesor Dos: 1

Sin asesor: 1 (se las mandé a Ceci para que las asigne).

Recuerda que luego de 60 días de atraso se puede cancelar el plan en cualquier momento.
— Tommi
```

## Correo a cada asesor (ejemplo)

```
Asunto: [Tommi] Cobranza 18/11: 2 clientes tuyos con cargo rechazado

Hola Luisa,

Allianz rechazó el cargo de 2 clientes tuyos desde el último resumen. Contacta a cada uno para que tenga el monto disponible o se ponga al corriente.

  • Luisa Prueba Soto (OptiMaxx Plus PLU3-437821): 23 días de atraso, $2,000.00, aportación 1, fondos insuficientes, próximo intento 04 de noviembre de 2026, 2 avisos
  • Pedro Dos (OptiMaxx Plus PLU3-500001): 9 días de atraso, $1,500.00, aportación 1, fondos insuficientes

Va el mismo detalle en el Excel adjunto (con el teléfono de cada cliente).

Recuerda que luego de 60 días de atraso se puede cancelar el plan en cualquier momento.
— Tommi · Babilonia
```
