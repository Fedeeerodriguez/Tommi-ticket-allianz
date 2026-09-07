# Tommi · Tickets Allianz

Repositorio **aislado** (no toca el backend principal de Tommy) para la nueva fase:
un **agente de tickets con Allianz** que ingesta correos, los clasifica, cruza con Notion,
lleva seguimiento y ejecuta acciones — con memoria y bitácora.

> Canal del sistema: **`hola@babilonia.ai`** — **único correo, lee y envía** (decisión de José/Fede).
> Stack: Python (FastAPI) + n8n + Supabase + WATI + Notion.

---

## 1. El problema

- Con Allianz **todo es por correo** (no hay API usable).
- Se abren **~100 tickets/mes** y muchos se pierden: Allianz no avisa, hay ruido en el buzón,
  el cliente no da seguimiento y a veces el asesor tampoco.
- Hoy es manual (Ceci) y no escala (80 asesores hoy → 200-300 la próxima generación).

**Objetivo:** que cada correo entrante se convierta en un evento estructurado, quede registrado,
y dispare la acción correcta automáticamente — con atención y seguimiento de excelencia.

---

## 2. Qué tiene que saber hacer Tommy (pedido de José)

1. **Levantar tickets** con Allianz cuando lo pida un **cliente o asesor**.
2. **Dar seguimiento** a los tickets abiertos (procesar respuestas de Allianz).
3. **Avisar actualizaciones en lenguaje coloquial** a asesores y clientes.
4. Disparar **aviso de WATI** cuando el ticket requiera **intervención humana**.
5. Cuando tenga info suficiente, **contestar a Allianz a nombre del prospecto — bajo su autorización**.
6. **Excepciones (tickets delicados)** → escala a **Ceci** (lista a definir con ella).
7. **Consultar a los ejecutivos de Allianz** por dudas de producto/proceso → **nutrir la base de conocimiento**.
8. **Detectar inactividad** (asesor/cliente/Allianz) y **reactivar** el ticket avisando al responsable.

---

## 3. Arquitectura del flujo (pipeline)

```
Buzón ÚNICO: hola@babilonia.ai  (lee entrantes y envía salientes)
   │  cada correo = 1 evento
   ▼
(1) INTAKE ─────────► normaliza {from,to,cc,subject,body,adjuntos,headers,date}
(2) DEDUP ──────────► idempotencia por message_id
(3) CLASIFICA L1 ───► reglas baratas (Allianz? CC de cliente? publicidad? 2FA? reenvío asesor?)
(4) CLASIFICA L2 ───► clasificador con IA (solo lo ambiguo) → { tipo, confianza }
(5) EXTRAE ─────────► nº ticket · nº póliza · cliente · producto · estado
(6) ENRIQUECE ──────► cruce con Notion (asesor / DAF / cliente)
(7) PERSISTE ───────► DB: correos + tickets + bitácora de eventos
(8) MOTOR ACCIONES ─► decide qué hacer (avisar, abrir/actualizar, recordatorio, escalar)
(9) EJECUTA ────────► WATI (plantilla) · correo saliente · update Notion
(10) AUDITA ────────► todo logueado → Tommy "se acuerda"
```

Regla de oro: **clasificar barato (reglas) antes que caro (LLM).**

---

## 4. Módulos

| Módulo | Qué hace | Cubre |
|--------|----------|-------|
| **M1 · Intake & clasificación** | Lee el buzón, ordena y clasifica cada correo por tipo | 2, 3 |
| **M2 · Gestión de tickets** | Levanta tickets (outbound) y actualiza estado + bitácora (inbound) | 1, 2 |
| **M3 · Autorización** | Captura y registra el "sí, autorizo" antes de actuar en nombre del prospecto | 5 |
| **M4 · Avisos (WATI + coloquial)** | Notifica en tono coloquial; plantilla cuando hace falta intervención; ventana 24 h | 3, 4 |
| **M5 · Excepciones / handoff Ceci** | Clasifica sensibilidad; los delicados NO se automatizan | 6 |
| **M6 · KB / consultas a ejecutivos** | Duda de producto → correo al ejecutivo → respuesta a la KB → Tommy responde | 7 |
| **M7 · Reactivación por inactividad** | Reloj por ticket; nudge al responsable si nadie actualizó | 8 |
| **M8 · Bitácora & memoria** | Historial fechado en Notion + todo en Supabase | transversal |

---

## 5. Taxonomía de correos *(borrador — a validar con muestras reales + Ceci)*

| Cód | Tipo | Detección |
|-----|------|-----------|
| A | Respuesta de Allianz a un ticket existente | dominio Allianz + nº ticket |
| B | Acuse de ticket nuevo | dominio Allianz + "folio/ticket creado" |
| C | Allianz pide algo al cliente | dominio Allianz + solicitud |
| D | Reenvío de asesor pidiendo abrir trámite | remitente = asesor (Notion) |
| E | CC de cliente (copió a Babilonia) | Babilonia en CC + destino Allianz |
| F | Consulta de producto de asesor | asesor + pregunta de producto |
| G | Sistema (2FA, códigos, WATI, n8n) | remitentes/patrones de sistema |
| H | Publicidad / newsletter / spam | header List-Unsubscribe |
| I | No clasificable | ninguna regla con confianza → Ceci |

---

## 6. Roadmap por fases (seguro: observar → sugerir → actuar)

| Fase | Entregable | ¿Envía a cliente/Allianz? |
|------|-----------|---------------------------|
| **0 · Setup** | Repo · acceso al buzón · muestras reales · Notion (Directorio + Tickets) · scope con Ceci | No |
| **1 · Intake** | Ingesta + clasificación + extracción + cruce Notion (**dry-run**) | No |
| **2 · Registro** | Persistencia Supabase + **bitácora fechada en Notion** | No |
| **3 · Seguimiento (inbound)** | Avisos coloquiales + detección de inactividad, **en sugerencia → aprobación humana** | No (revisado) |
| **4 · Agente (outbound)** | Levantar/contestar tickets **bajo autorización** + **handoff a Ceci** + aviso WATI | Sí, gradual |
| **5 · KB loop** | Consultas a ejecutivos + nutrición de la base + consolidación (batch) | Sí |
| **Continuo** | Revisión **semanal** de calidad (Fede + Jime) | — |

**Meta inmediata:** prototipo (Fases 0-1 + arranque de 2).
**Regla dura:** nada se manda a un cliente ni a Allianz hasta la Fase 4, siempre con autorización + excepciones a Ceci.

---

## 7. Guardarraíles (no negociables)

- **Autorización explícita** del prospecto antes de actuar en su nombre.
- **Handoff obligatorio a Ceci** en tickets delicados.
- **Dry-run / aprobación humana** en fases tempranas; envío gradual por tipos de bajo riesgo.
- **Cuidar el número de WhatsApp** (riesgo Meta): nada que parezca venta directa; solo plantillas aprobadas.
- **Ventana de 24 h** de WhatsApp.
- **Aislado del backend principal** de Tommy.

---

## 8. Qué necesito para arrancar

**🔴 Bloqueante (Fase 0-1):**
1. **Acceso a `hola@babilonia.ai`** (canal único, lee y envía): ¿es Gmail/Workspace u otro? ¿cómo damos acceso — OAuth / reenvío / IMAP con app password?
2. **15-30 correos reales** de muestra (uno por tipo).
3. **Formato del nº de ticket** de Allianz (ejemplos de asunto y cuerpo).

**🟡 Fases 2-5:** Directorio + Tickets Allianz (Notion), plantillas WATI, credenciales Supabase/WATI/Notion, el Zapier viejo, la charla con **Ceci** (delicados + trámites SÍ/NO), y cómo capturamos la **autorización**.

---

## 9. Estructura del repo *(a medida que se construye)*

```
app/          # servicio Python (intake, clasificador, extracción, enriquecimiento, acciones, db)
n8n/          # workflows exportados (.json)
docs/         # plan, decisiones, muestras anonimizadas
.env.example  # variables necesarias (sin secretos reales)
```
