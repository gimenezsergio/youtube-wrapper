# Estado auditado — commit `99023ae`

## 1. Propósito

Este documento registra la evidencia que origina la especificación correctiva. Describe el estado observado; no define por sí mismo el comportamiento deseado.

## 2. Validaciones generales

| Validación | Resultado auditado |
|---|---|
| `pytest -q` | 60 pruebas aprobadas |
| `ruff check .` | 65 errores |
| Compilación Python | correcta |
| Sintaxis JavaScript | correcta |
| `git diff --check` | correcto |
| Redocly | OpenAPI válido, 12 advertencias |

La cantidad de pruebas no aumentó respecto de la implementación anterior. No existe la matriz ejecutable completa requerida por `DISC`, `FEED` y `REF`.

## 3. Correcciones confirmadas

El incremento integrado corrigió parcialmente:

- el endpoint de refresh ya no inicia un thread dentro de Flask;
- el worker crea un contexto de aplicación y puede reclamar un trabajo como proceso separado;
- la búsqueda hidrata detalles de videos y canales antes de seleccionar;
- los videos con duración desconocida o menor o igual a 180 segundos no se seleccionan;
- las exclusiones convierten IDs de YouTube a IDs locales y consideran canales seguidos globalmente;
- `normalize_term` está disponible en el endpoint de temas;
- el filtro de descubrimientos usa `navigateToRoute`;
- parte de las respuestas de descubrimiento utiliza nombres compatibles con OpenAPI.

Estas correcciones deben preservarse.

## 4. Defectos reproducidos

### AUD-01 — Cuota después de un éxito reemplaza el lote anterior

Secuencia reproducida:

1. existe un lote anterior activo;
2. la primera búsqueda devuelve un candidato;
3. la segunda búsqueda lanza `YouTubeQuotaError`;
4. la ejecución publica el candidato parcial;
5. el lote anterior pasa a `expired`.

Resultado observado:

```text
new-v: active, last_refresh_run_id=2
old-v: expired, last_refresh_run_id=1
shortfall: quota_exhausted
```

### AUD-02 — Deriva del fallback

Con ocho candidatos válidos, todos `exploratory`, el selector devuelve ocho elementos. La especificación general permite como máximo el cupo exploratorio configurado y prohíbe usar exploratorios adicionales para cubrir `related` o `adjacent`.

### AUD-03 — Umbrales configurables ignorados

La función de scoring recibe mínimos por banda pero no los aplica. La selección usa nuevamente literales `55/45/35`. Un mínimo configurado distinto no modifica la decisión final.

### AUD-04 — Feedback de interfaz incorrecto

“Me interesa” envía `accept_channel`, sigue el canal y retira la tarjeta. No existe una acción visible que envíe `more_like_this`. `sendFeedback` no comprueba `response.ok`.

### AUD-05 — Validación HTTP insuficiente

Resultados reproducidos:

| Solicitud | Resultado actual | Resultado requerido |
|---|---|---|
| `/discoveries?cursor=abc` | `200` | `400` |
| `/discoveries?band=nonsense` | `200` | `400` |
| feedback con acción desconocida | excepción SQLite / `500` | `422` |
| bloquear canal inexistente | `TypeError` / `500` | `404` |

El feedback también acepta un `channelId` provisto por el cliente aunque el canal puede derivarse del video persistido.

### AUD-06 — Commit posterior a una excepción

El orquestador captura una excepción de etapa, almacena un traceback y luego ejecuta `commit()` sin rollback previo. Puede confirmar escrituras parciales de una etapa fallida.

### AUD-07 — Contrato de refresh inconsistente

El backend serializa `errors` como una lista, mientras el frontend lo recorre como mapa y llama `split()` sobre cada valor. El esquema de `counters` declara enteros, pero la respuesta real contiene objetos anidados por etapa.

### AUD-08 — Lease sin renovación durante trabajo largo

El heartbeat se actualiza antes y después de cada etapa, no durante llamadas externas largas. Un segundo worker puede recuperar la lease mientras el primero continúa procesando y escribiendo.

### AUD-09 — Configuración declarada pero desconectada

La implementación conserva literales para tamaño, mezcla, máximo por canal, resultados por búsqueda, región, idioma, umbrales y sugerencia de seguimiento. `.env.example` contradice los valores conservadores 10/2.

### AUD-10 — Migración no atómica

La migración existente usa `executescript`, que realiza commits implícitos durante una reconstrucción destructiva, y copia candidatos anteriores con `selection_rank=NULL`.

### AUD-11 — Seguridad de errores

Se persisten tracebacks completos y el frontend inserta mensajes variables mediante `innerHTML`. Esto expone información interna y permite contenido no escapado.

### AUD-12 — Etapas incoherentes

La API acepta `channels` y `classification`; el orquestador no implementa `channels` y conserva `classification` como punto de extensión no implementado. Un worker puede imprimir éxito aunque el refresh termine en `failed`.

## 5. Conclusión del relevamiento

El motor no debe considerarse estable hasta que cada defecto tenga una regresión automatizada y se superen las puertas definidas en `tasks.md`. Una suite verde de 60 pruebas no constituye evidencia suficiente.
