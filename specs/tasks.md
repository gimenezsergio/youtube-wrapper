# Plan de implementación — Descubrimiento y recomendaciones

## 1. Estado y alcance

Este es el plan vigente para implementar el incremento de descubrimiento definido en:

1. `requirements.md`;
2. `openapi.yaml`;
3. `design.md`;
4. `tests.md`;
5. `current-state.md`.

El agente implementador debe trabajar sobre el código existente, preservar el feed actual y completar las fases en orden. Este plan no autoriza reinterpretar el producto ni reemplazar el stack acordado.

### Incluye

- actualización manual persistente necesaria para ejecutar descubrimiento;
- temas adyacentes y sus estados de revisión;
- búsqueda pública de candidatos en YouTube;
- bandas, puntuación, diversidad y lote 5/2/1;
- consulta de descubrimientos;
- feedback, ocultaciones, bloqueos y seguimiento local;
- interfaz completa de descubrimiento;
- pruebas y documentación del incremento.

### No incluye

- clasificación automática completa de canales de RF-05;
- rediseño general de la aplicación;
- despliegue productivo, systemd o auditoría PWA completa;
- integración con historial, “Ver más tarde” o portada de YouTube;
- dependencia obligatoria de un LLM o servicio semántico.

## 2. Decisiones congeladas

| Decisión | Valor inicial |
|---|---|
| Tamaño objetivo por categoría | 8 videos |
| Mezcla | 5 `related`, 2 `adjacent`, 1 `exploratory` |
| Máximo del mismo canal | 2 videos por lote y categoría |
| Búsquedas por actualización | 10 |
| Búsquedas por categoría | 2 |
| Resultados solicitados por búsqueda | 25 |
| Ventana de señales locales | 90 días |
| Antigüedad máxima inicial de búsqueda | 180 días |
| Umbral de sugerencia de canal | señales positivas sobre 2 videos distintos |
| Puntaje mínimo `related` | 55 |
| Puntaje mínimo `adjacent` | 45 |
| Puntaje mínimo `exploratory` | 35, conservando un ancla temática |
| Región e idioma iniciales | `AR` y `es` |
| Feed normal | `origin=followed` |

Todos los valores son configuración. Cambiarlos durante la implementación requiere actualizar pruebas y justificarlo; la mezcla 5/2/1 no debe alterarse sin revisar los requisitos.

## 3. Reglas de ejecución

1. Leer `current-state.md` y verificar nuevamente la línea base antes de editar código.
2. Instalar `requirements.txt` en un entorno virtual aislado.
3. Ejecutar `pytest` y `ruff check .`; registrar fallos preexistentes por separado.
4. No consumir cuota real de YouTube en pruebas.
5. Implementar primero funciones puras y repositorios, luego servicios, API y finalmente interfaz.
6. Cada fase debe dejar verdes sus pruebas y las pruebas anteriores.
7. No retirar `/channels/sync` ni conectar el botón al worker nuevo hasta la Fase 9.
8. No ejecutar propuestas `pending` en la misma actualización que las genera.
9. Un fallo de una categoría no debe destruir su lote anterior ni los videos seguidos ya importados.
10. No marcar una tarea como terminada con código simulado, `TODO`, contadores falsos o respuestas estáticas.
11. Toda mutación debe respetar CSRF y realizarse dentro de una transacción coherente.
12. Si el código obliga a desviarse de `openapi.yaml`, detenerse y corregir el contrato o solicitar decisión; no crear endpoints alternativos silenciosamente.

## 4. Estructura objetivo orientativa

El agente puede ajustar nombres menores, pero debe mantener la separación de responsabilidades:

```text
app/
  api/
    discoveries.py
    refresh_runs.py
    settings.py
  domain/
    discovery/
      models.py
      normalization.py
      query_builder.py
      scoring.py
      selection.py
      signals.py
  repositories/
    discovery_repository.py
    exploration_topic_repository.py
    refresh_run_repository.py
  services/
    discovery_service.py
    discovery_feedback_service.py
    exploration_topic_service.py
    refresh_orchestrator.py
  integrations/youtube/
    gateway.py
tests/
  fakes/
    youtube_gateway.py
  test_discovery_domain.py
  test_discovery_service.py
  test_discoveries_api.py
  test_exploration_topics.py
  test_discovery_feedback.py
  test_refresh_runs.py
  test_worker.py
```

La lógica de puntuación y selección no debe quedar en rutas Flask, repositorios SQL ni JavaScript.

---

## Fase 0 — Línea base reproducible

### Objetivo

Comenzar desde un estado verificable y proteger la base existente antes de migrar.

### Tareas

- [ ] **0.1** Crear y activar un entorno virtual; instalar `requirements.txt`.
- [ ] **0.2** Ejecutar `pytest -q` y guardar el resultado de la línea base en la descripción del cambio.
- [ ] **0.3** Ejecutar `ruff check .` y separar fallos preexistentes de regresiones.
- [ ] **0.4** Identificar la base configurada para desarrollo. Si contiene datos, crear una copia consistente antes de probar migraciones.
- [ ] **0.5** Crear un fake de YouTube reutilizable en `tests/fakes/` que conserve las operaciones existentes y pueda registrar llamadas futuras a búsqueda.
- [ ] **0.6** Confirmar que las especificaciones actualizadas y `current-state.md` forman parte del working tree que se implementará.

### Puerta de verificación

- Existe un resultado reproducible de pruebas y lint.
- Ningún dato real fue modificado.
- El fake compartido puede reemplazar gradualmente los fakes duplicados sin cambiar comportamiento.

---

## Fase 1 — Migración y configuración

### Objetivo

Persistir el modelo actualizado sin perder datos y exponer todos los valores configurables.

### Tareas

- [ ] **1.1** Crear `app/migrations/0003_discovery_engine.sql`.
- [ ] **1.2** Crear `category_exploration_topics` con unicidad por `(category_id, normalized_term)` y estados restringidos.
- [ ] **1.3** Crear `discovery_batches` conforme a `design.md`.
- [ ] **1.4** Migrar `discovery_candidates` para añadir `band`, `last_refresh_run_id` y `selection_rank`, conservando filas existentes.
- [ ] **1.5** Para candidatos heredados, asignar `band='related'`, conservar `score`, `reasons_json`, estado y fechas, y generar un orden determinista por categoría.
- [ ] **1.6** Crear los índices definidos en `design.md` y verificar claves foráneas con `PRAGMA foreign_key_check`.
- [ ] **1.7** Actualizar `app/config.py` con las decisiones congeladas de la sección 2.
- [ ] **1.8** Mantener los límites configurables mediante variables de entorno y documentarlos en el ejemplo de configuración disponible.
- [ ] **1.9** Añadir prueba de migración desde una base creada con `0001` y `0002`, incluyendo datos heredados de descubrimiento.
- [ ] **1.10** Actualizar `tests/test_db.py` para validar tablas, restricciones, índices y cascadas nuevas.

### Pruebas mínimas

- Migración limpia desde base vacía.
- Migración sobre esquema anterior con filas preservadas.
- Reejecución idempotente del migrador.
- Rechazo de banda, estado o tema inválidos.

### Puerta de verificación

- Los conteos antes y después de la migración coinciden para datos existentes.
- `foreign_key_check` no informa errores.
- La suite previa continúa verde.

---

## Fase 2 — Dominio puro de descubrimiento

### Objetivo

Implementar reglas deterministas y probables sin base de datos, HTTP ni Flask.

### Tareas

- [ ] **2.1** Definir modelos y enums internos para señales, consulta generada, candidato, componentes de score, banda, selección y resumen de lote.
- [ ] **2.2** Implementar normalización de términos, espacios, mayúsculas, puntuación y diacríticos usando biblioteca estándar.
- [ ] **2.3** Implementar extracción de señales trazables desde palabras clave, canales semilla, videos recientes y feedback local.
- [ ] **2.4** Implementar generador de consulta directa y expandida; aplicar términos negativos y limitar longitud de `q`.
- [ ] **2.5** Implementar el planificador round-robin que respeta 10 búsquedas globales y 2 por categoría.
- [ ] **2.6** Implementar elegibilidad y clasificación en bandas. `adjacent` requiere ancla principal más tema aprobado; `exploratory` conserva al menos un ancla temática.
- [ ] **2.7** Implementar la función pura de puntuación 0..100 con desglose por componente.
- [ ] **2.8** Generar entre 1 y 3 razones desde componentes reales; prohibir explicaciones genéricas sin evidencia.
- [ ] **2.9** Implementar selección 5/2/1 con los mínimos 55/45/35 y la matriz de fallback.
- [ ] **2.10** Limitar a 2 videos por canal y penalizar títulos casi duplicados mediante similitud de tokens determinista.
- [ ] **2.11** Ordenar empates de forma estable por score, fecha de publicación e ID de YouTube.
- [ ] **2.12** Crear pruebas tabulares para `DISC-01`, `DISC-02`, `DISC-05..07`, `DISC-09..10` y `DISC-18..24`.

### Puerta de verificación

- Una misma entrada produce exactamente la misma salida.
- La lógica se prueba sin SQLite ni red.
- No puede seleccionarse un candidato bloqueado, oculto, seguido o debajo del mínimo.
- Con pool suficiente, el resultado exacto es 5/2/1 y máximo 2 videos por canal.

---

## Fase 3 — Repositorios de descubrimiento

### Objetivo

Encapsular SQL y transacciones antes de exponer casos de uso.

### Tareas

- [ ] **3.1** Implementar `ExplorationTopicRepository`: listar, crear manual aprobado, insertar propuesta pendiente, cambiar estado y evitar duplicados normalizados.
- [ ] **3.2** Implementar `DiscoveryRepository`: buscar exclusiones, upsert de canales/videos candidatos, upsert de contextos y lectura del lote actual.
- [ ] **3.3** Implementar persistencia de `discovery_batches` y resúmenes por categoría.
- [ ] **3.4** Implementar expiración de candidatos anteriores solo después de persistir exitosamente el lote nuevo de esa categoría.
- [ ] **3.5** Implementar lectura y escritura de feedback con alcance de categoría; el bloqueo de canal permanece global.
- [ ] **3.6** Parsear y serializar `reasons_json` como lista, nunca como JSON doblemente codificado.
- [ ] **3.7** Implementar consulta de señales locales dentro de 90 días, diferenciando apertura/visto de feedback explícito.
- [ ] **3.8** Implementar conteo de videos positivos distintos por canal y categoría para la sugerencia de seguimiento.
- [ ] **3.9** Añadir pruebas de repositorio con SQLite temporal para `DISC-03..05`, `DISC-11..12`, `DISC-14..17` y `FEED-07..09`.

### Puerta de verificación

- Un mismo video existe una sola vez en `videos` y puede tener contextos independientes en varias categorías.
- Un fallo antes del commit conserva el lote anterior.
- Los estados `hidden` y `accepted` no vuelven a `active` por un upsert posterior.

---

## Fase 4 — Adaptador de búsqueda de YouTube

### Objetivo

Obtener candidatos públicos de manera controlada y simulable.

### Tareas

- [ ] **4.1** Extender `YouTubeGateway` con `search_videos`.
- [ ] **4.2** Enviar `part=snippet`, `type=video`, `maxResults=25`, `publishedAfter`, `relevanceLanguage=es`, `regionCode=AR` y `q`.
- [ ] **4.3** Usar una sola página por consulta en el MVP; cualquier página adicional consume otra unidad del presupuesto.
- [ ] **4.4** Normalizar resultados a IDs, título, descripción, fecha, miniatura, canal y procedencia de consulta.
- [ ] **4.5** Reutilizar `fetch_videos_details` y `fetch_channels_details` en lotes para duración, tipo y playlist del canal.
- [ ] **4.6** Incorporar canales candidatos sin marcarlos como suscriptos ni seguidos localmente.
- [ ] **4.7** Definir errores tipados: autorización, cuota, transitorio, respuesta inválida y no encontrado.
- [ ] **4.8** Aplicar reintento limitado solo a fallos transitorios; nunca reintentar automáticamente cuota o autorización.
- [ ] **4.9** Actualizar el fake compartido para devolver resultados por consulta y registrar parámetros/orden de llamadas.
- [ ] **4.10** Probar parámetros, normalización, lotes, error de cuota y ausencia total de llamadas reales.

### Puerta de verificación

- Los tests demuestran que no se supera el presupuesto.
- No se usa `relatedToVideoId`, historial ni portada.
- Un error externo queda tipado sin exponer tokens o payloads sensibles.

---

## Fase 5 — Actualización persistente y worker real

### Objetivo

Ejecutar descubrimiento únicamente a partir de una actualización manual recuperable.

### Tareas

- [ ] **5.1** Implementar `RefreshRunRepository` con creación, listado, consulta, exclusión mutua, reclamo atómico, heartbeat, lease y finalización.
- [ ] **5.2** Implementar `POST /refresh-runs`, `GET /refresh-runs` y `GET /refresh-runs/{id}` conforme a OpenAPI.
- [ ] **5.3** Crear `RefreshOrchestrator` con registro explícito de handlers de etapa.
- [ ] **5.4** Conectar `subscriptions` a `SubscriptionService` y `followed_videos` a `VideoService`.
- [ ] **5.5** Reservar el punto de extensión `classification` sin simular resultados. El flujo de este incremento solicita `subscriptions`, `followed_videos` y `discovery`; si un cliente solicita `classification` explícitamente antes de implementarla, registrar un error de etapa y finalizar `partial` en lugar de informar éxito falso.
- [ ] **5.6** Reemplazar el contenido simulado de `worker.py` por el orquestador real.
- [ ] **5.7** Actualizar heartbeat durante operaciones largas y verificar propiedad por `worker_id` antes de confirmar etapa o finalización.
- [ ] **5.8** Registrar contadores y errores estructurados por etapa y categoría.
- [ ] **5.9** Marcar `partial` si suscripciones/videos se confirmaron y descubrimiento falla; marcar `failed` si no se preservó ninguna etapa útil.
- [ ] **5.10** Detectar y recuperar lease vencida sin dos procesamientos simultáneos.
- [ ] **5.11** Mantener temporalmente `/channels/sync` y el botón actual sin cambios hasta la Fase 9.
- [ ] **5.12** Implementar `REF-01..09` con worker y servicios falsos deterministas.

### Puerta de verificación

- Crear un refresh no realiza llamadas externas dentro de la petición Flask.
- Dos workers no reclaman el mismo trabajo.
- Reiniciar Flask no elimina el trabajo pendiente.
- El worker ya no contiene esperas ni contadores simulados de negocio.

---

## Fase 6 — Temas adyacentes y propuestas revisables

### Objetivo

Permitir variedad controlada sin introducir temas silenciosamente.

### Tareas

- [ ] **6.1** Implementar `ExplorationTopicService`.
- [ ] **6.2** Crear temas manuales como `source=manual`, `status=approved`.
- [ ] **6.3** Implementar generador determinista de propuestas a partir de términos distintivos de canales semilla y títulos recientes, excluyendo stopwords, palabras negativas y términos ya registrados.
- [ ] **6.4** Guardar propuestas automáticas como `pending` con `rationale` trazable.
- [ ] **6.5** Ejecutar propuestas durante el refresh, pero congelar el conjunto de temas aprobados al inicio para impedir su uso en esa misma ejecución.
- [ ] **6.6** Implementar endpoints GET/POST/PATCH de temas adyacentes conforme a OpenAPI.
- [ ] **6.7** Validar pertenencia de `topicId` a `categoryId`, unicidad normalizada, pesos y transiciones.
- [ ] **6.8** Implementar `DISC-14..17` como pruebas de servicio y contrato.

### Puerta de verificación

- Un tema pendiente o rechazado no aparece en ninguna consulta generada.
- Una aprobación comienza a influir recién en el refresh siguiente.
- El generador funciona sin servicio semántico externo.

---

## Fase 7 — Motor de descubrimiento

### Objetivo

Generar y persistir un lote real, diverso y explicable por categoría.

### Tareas

- [ ] **7.1** Implementar `DiscoveryService` como caso de uso independiente de Flask.
- [ ] **7.2** Determinar categorías elegibles y tomar un snapshot de palabras clave, temas aprobados, canales semilla, señales y exclusiones.
- [ ] **7.3** Registrar propuestas pendientes sin incorporarlas al snapshot actual.
- [ ] **7.4** Generar consultas directas y expandidas; programarlas en round-robin.
- [ ] **7.5** Buscar e hidratar candidatos respetando presupuesto, ventana de 180 días y exclusión de videos menores o iguales a 180 segundos.
- [ ] **7.6** Excluir canales suscriptos/seguidos, bloqueados, videos ocultos, palabras negativas y duplicados.
- [ ] **7.7** Calcular componentes, score, banda y razones por relación video-categoría.
- [ ] **7.8** Seleccionar el lote con mezcla 5/2/1, mínimos, diversidad, máximo por canal y fallback.
- [ ] **7.9** Persistir candidatos y `discovery_batches` por categoría en transacciones independientes.
- [ ] **7.10** Expirar el lote anterior de una categoría solo después del éxito de su lote nuevo.
- [ ] **7.11** Si no hay señales o temas aprobados suficientes, persistir resumen parcial con `shortfall_reason` sin fabricar candidatos.
- [ ] **7.12** Si hay cuota, presupuesto o error externo, conservar el lote anterior y registrar estado accionable.
- [ ] **7.13** Integrar el servicio como handler `discovery` del orquestador.
- [ ] **7.14** Implementar pruebas `DISC-01..24`, incluyendo dos categorías y reintento de la misma etapa.

### Puerta de verificación

- Con candidatos suficientes se persisten exactamente 5/2/1.
- Cada tarjeta tiene banda, score, posición y entre 1 y 3 razones.
- Ninguna búsqueda ocurre fuera de un refresh solicitado.
- Un fallo de una categoría no modifica las demás ni elimina su lote previo.

---

## Fase 8 — Lectura, feedback y seguimiento local

### Objetivo

Exponer el lote y permitir que el usuario controle futuras recomendaciones.

### Tareas

- [ ] **8.1** Implementar `GET /discoveries` con filtros `categoryId`, `band`, cursor y límite.
- [ ] **8.2** Devolver solo candidatos `active` del lote vigente, ordenados por categoría y `selection_rank`.
- [ ] **8.3** Incluir `DiscoveryBatchSummary` con objetivos, seleccionados y `shortfallReason`.
- [ ] **8.4** Actualizar serialización y filtros de `/videos`; el default debe ser `origin=followed` y la precedencia `followed` debe evitar duplicados.
- [ ] **8.5** Implementar `DiscoveryFeedbackService` y `POST /discoveries/{videoId}/feedback`.
- [ ] **8.6** `more_like_this` y `less_like_this` crean señales de categoría; la UI no debe duplicar el mismo clic accidentalmente.
- [ ] **8.7** `hide_video` oculta el contexto de esa categoría y puede revertirse mediante `DELETE /discoveries/{videoId}/hidden?categoryId=...`.
- [ ] **8.8** `block_channel` marca el canal globalmente y retira todos sus candidatos activos; la reversión usa `PUT /channels/{id}/block` con `blocked=false`.
- [ ] **8.9** Implementar `GET /settings/discovery-exclusions` para listar restauraciones disponibles.
- [ ] **8.10** `accept_channel` ejecuta en una transacción: seguimiento local, relación `accepted_discovery`, estado candidato aceptado y precedencia de origen.
- [ ] **8.11** Calcular sugerencia de seguimiento con señales positivas sobre 2 videos distintos; nunca seguir implícitamente.
- [ ] **8.12** Implementar pruebas `DISC-25`, `FEED-01..10` y validación de contrato OpenAPI.

### Puerta de verificación

- Ocultar, restaurar, bloquear, desbloquear y aceptar son reversibles o auditables según especificación.
- Feedback de una categoría no modifica indebidamente otra.
- Aceptar un canal no llama la API de suscripciones de YouTube.
- El canal aceptado participa en la siguiente sincronización de videos seguidos.

---

## Fase 9 — Interfaz e integración del flujo completo

### Objetivo

Reemplazar placeholders y conectar la actualización persistente sin romper la aplicación existente.

### Tareas

- [ ] **9.1** Sustituir `renderDiscoveriesView()` por una vista que consuma `GET /discoveries`.
- [ ] **9.2** Implementar selector de categoría y banda sincronizado con `URLSearchParams`.
- [ ] **9.3** Renderizar etiquetas textuales, razones, estado visto, resumen del lote y faltantes accionables.
- [ ] **9.4** Añadir acciones “Me interesa”, “No me interesa”, ocultar, bloquear y seguir canal con confirmaciones proporcionales.
- [ ] **9.5** Mantener el lote finito: llegar al final no dispara búsqueda, actualización ni carga infinita.
- [ ] **9.6** Añadir gestión de temas adyacentes en la edición de categoría, separando pendientes, aprobados y rechazados.
- [ ] **9.7** Añadir en Ajustes la lista de videos ocultos y canales bloqueados con restauración.
- [ ] **9.8** Cambiar el botón “Actualizar” para crear un `refresh_run` y consultar su progreso por polling.
- [ ] **9.9** Mostrar etapas, contadores, resultado `succeeded/partial/failed`, errores accionables y fecha de última actualización.
- [ ] **9.10** Solo después de validar el nuevo flujo, retirar el uso frontend de `/channels/sync`; eliminar la ruta o convertirla en compatibilidad documentada que cree un refresh, sin ejecutar red en Flask.
- [ ] **9.11** Actualizar el feed normal para solicitar `origin=followed` explícitamente.
- [ ] **9.12** Asegurar navegación por teclado, foco visible, etiquetas accesibles y controles táctiles en 360×800 y 1440×900.
- [ ] **9.13** Verificar `DISC-26` y realizar smoke test manual de actualización → descubrimiento → feedback → aceptación.

### Puerta de verificación

- `/discoveries` ya no muestra contenido provisional.
- El feed cronológico no mezcla descubrimientos por defecto.
- No hay llamadas externas implícitas al navegar, filtrar o hacer scroll.
- El flujo completo funciona en computadora y celular.

---

## Fase 10 — Consolidación, rendimiento y entrega

### Objetivo

Entregar un incremento verificable, documentado y seguro para revisión.

### Tareas

- [ ] **10.1** Ejecutar la suite completa con `pytest -q`.
- [ ] **10.2** Ejecutar `ruff check .` y corregir solo problemas relacionados o acordados.
- [ ] **10.3** Validar `specs/openapi.yaml` con Redocly u otro validador OpenAPI 3.1.
- [ ] **10.4** Añadir prueba de rendimiento con 20.000 videos y candidatos suficientes; la primera página debe respetar RNF-02.
- [ ] **10.5** Probar migración sobre copia de una base anterior y documentar respaldo/restauración.
- [ ] **10.6** Probar cuota agotada, autorización vencida, timeout, respuesta malformada y recuperación de lease.
- [ ] **10.7** Confirmar que logs y errores no contienen tokens, secretos ni respuestas externas completas.
- [ ] **10.8** Verificar que exportación JSON incluya temas adyacentes, estados, feedback y bloqueos sin credenciales.
- [ ] **10.9** Actualizar `README.md` principal y documentación de configuración/ejecución del worker.
- [ ] **10.10** Revisar el diff final: sin `TODO`, código simulado, dependencias innecesarias ni cambios fuera del alcance.
- [ ] **10.11** Preparar una matriz final de evidencia que vincule cada caso `DISC`, `FEED` y `REF` implementado con su archivo de prueba.

### Puerta final

- OpenAPI válido.
- Suite y lint verdes.
- Migración preserva datos.
- Cero llamadas reales de YouTube en pruebas.
- Descubrimiento solo se genera manualmente.
- Lote, feedback y seguimiento local cumplen requisitos.
- No quedan rutas o pantallas simulando funcionalidad terminada.

## 5. Trazabilidad de fases

| Fase | Requisitos/casos principales |
|---|---|
| 0 | Línea base y RNF-04 |
| 1 | RF-11.4, RF-11.6..17, RNF-03 |
| 2 | DISC-01..02, DISC-05..07, DISC-09..10, DISC-18..24 |
| 3 | DISC-03..05, DISC-11..17, FEED-07..09 |
| 4 | RF-11.1..5, DISC-01, DISC-09..10 |
| 5 | Infraestructura de RF-07 y etapas del alcance; REF-01..09 |
| 6 | RF-11.4..5, DISC-14..17 |
| 7 | RF-11, DISC-01..24 |
| 8 | RF-12, DISC-25, FEED-01..10 |
| 9 | RF-11.13, RF-12.7..11, DISC-26, RF-13.5 |
| 10 | RNF-01..05 y evidencia final |

## 6. Orden de commits sugerido

El agente implementador puede usar un commit por fase o dividir fases grandes, manteniendo este orden lógico:

1. especificaciones y línea base;
2. migración/configuración;
3. dominio puro;
4. repositorios;
5. gateway;
6. refresh/worker;
7. temas adyacentes;
8. motor;
9. API/feedback;
10. frontend;
11. consolidación.

No mezclar migraciones, lógica de dominio y cambios visuales en un único commit si eso impide revisar o revertir el incremento de forma segura.
