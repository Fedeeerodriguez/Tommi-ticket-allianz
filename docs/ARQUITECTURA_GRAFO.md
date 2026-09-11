# Arquitectura: grafo LangGraph + agentes LangChain

El procesamiento de cada correo se modela como un **grafo de estados de LangGraph**. Los
pasos determinísticos (reglas, extracción, DB, Notion, SMTP) son **nodos-herramienta**; los
pasos que razonan con LLM son **agentes LangChain**. Un correo entra por `START` y va
llenando el estado (`EstadoCorreo`) a medida que recorre los nodos.

## Por qué un grafo (y no el pipeline lineal)

- El flujo tiene **ramas reales**: correo ambiguo → L2; duplicado o no-ticket → corta;
  delicado → estado Ceci. Un grafo expresa esas bifurcaciones sin `if` anidados.
- **Estado explícito y observable**: cada nodo devuelve un dict parcial que LangGraph fusiona;
  `ruta` acumula la traza de nodos (debug/telemetría gratis).
- **Extensible**: sumar reintentos, ramas humanas (aprobación de Ceci) o checkpoints de
  LangGraph es agregar nodos/edges, no reescribir la función.

## El grafo

```
START
  → clasificar_l1            (reglas baratas)
      ├─ confianza baja  → clasificar_l2   (AGENTE LangChain, salida estructurada)
      └─ confianza ok    ──────────────────┐
                                            ▼
  → extraer                  (entidades: nº ticket, póliza, cliente)
  → persistir                (guarda correo, idempotente por message_id)
      ├─ duplicado / no-ticket → END
      └─ ticket nuevo → enriquecer         (Notion: asesor/DAF/cliente + marca delicado)
                      → upsert_ticket       (busca/crea/actualiza + bitácora)
                      → registrar_notion    (objetivo 3: UPSERT base Tickets Allianz)
                      → decidir             (motor de acciones → cola 'sugerida')
                      → despachar           (objetivo 2: envío SMTP; respeta DRY_RUN)
                      → END
```

Código: `app/grafo/estado.py` (estado), `app/grafo/nodos.py` (nodos), `app/grafo/grafo.py`
(ensamblado + ramas). `repo` y `emisor` se inyectan al construir (`construir_grafo(repo, emisor)`),
así los nodos quedan puros y el grafo es reutilizable/testeable.

## Agentes LangChain

| Agente | Archivo | Qué hace |
|---|---|---|
| Clasificador L2 | `app/agentes/clasificador_l2.py` | `ChatOpenAI.with_structured_output(SalidaClasificacion)` — clasifica el correo ambiguo con esquema forzado (sin parseo manual de JSON). |
| Redactor | `app/agentes/redactor.py` | `ChatPromptTemplate | ChatOpenAI` — redacta el mensaje coloquial de WhatsApp (cliente/asesor). |

Ambos son **defensivos**: sin `OPENAI_API_KEY`, sin LangChain instalado o ante cualquier
error, devuelven `None` y el sistema cae a **reglas (L1) / plantillas fijas**. El LLM nunca
puede romper el pipeline.

## Cómo correrlo

```bash
python -m app.run_grafo               # muestras (o IMAP si hay credenciales)
python -m app.run_grafo --despachar   # además ejecuta el envío (SMTP), respetando DRY_RUN
```

`run_pipeline.py` (lineal, hand-rolled) queda como referencia/legacy; el camino oficial es
el grafo.

## Modelo

OpenAI `gpt-4.1-mini` (reusa `OPENAI_API_KEY`/`OPENAI_CHAT_MODEL` del backend principal),
vía `langchain-openai`. Cambiar de proveedor = cambiar la construcción del `ChatModel` en
`app/agentes/*`, sin tocar el grafo.
