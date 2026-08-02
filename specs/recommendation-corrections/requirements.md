# Requisitos correctivos — recomendaciones

## 1. Objetivo

Estabilizar el incremento de recomendaciones integrado en `main` sin ampliar el producto. Las correcciones deben conservar el feed existente, los datos reales y las partes del motor que ya funcionan.

## 2. Definiciones

- **Intento de categoría**: procesamiento completo de una categoría dentro de un refresh, desde la planificación de consultas hasta la publicación atómica.
- **Intento válido**: todas las operaciones externas previstas para la categoría terminaron sin error y existe un resultado local evaluable, aunque el lote resultante sea menor al objetivo.
- **Intento abortado**: ocurrió cuota, autorización, timeout, error externo, respuesta inválida, fallo de hidratación o pérdida de lease.
- **Publicación**: activación del nuevo lote y expiración del lote activo anterior en una única transacción.
- **Peso neutral**: valor `1.0`; no reduce por sí solo la contribución base de una señal.
- **Error público**: objeto sanitizado con código estable y mensaje apto para la interfaz; nunca contiene traceback ni cuerpo externo completo.

## 3. Publicación segura

### CORR-RF-01 — Aislamiento por categoría

Cada categoría debe procesarse y publicarse de forma independiente.

**Criterios de aceptación**

1. Las llamadas externas no deben ejecutarse dentro de una transacción de escritura SQLite.
2. La publicación de una categoría debe usar una transacción corta y atómica.
3. Un fallo de una categoría no debe revertir ni publicar datos de otra.
4. Una excepción no controlada debe ejecutar rollback de los cambios de negocio de la unidad afectada.
5. El estado y heartbeat del refresh deben persistirse mediante transacciones separadas de las escrituras de negocio.

### CORR-RF-02 — Degradación sin reemplazo

Un intento abortado no puede modificar el lote activo anterior de su categoría.

**Criterios de aceptación**

1. `quota_exhausted`, timeout, autorización, error externo, respuesta inválida y fallo de hidratación abortan la publicación de la categoría.
2. La regla aplica aunque alguna búsqueda anterior del mismo intento haya devuelto candidatos.
3. Los candidatos del intento abortado no quedan `active`.
4. El lote anterior y su resumen siguen siendo los visibles.
5. El refresh registra `stage`, `categoryId`, código público y mensaje accionable.
6. El reintento posterior puede publicar normalmente sin duplicar candidatos ni batches.

### CORR-RF-03 — Lote parcial válido

La falta de inventario local no equivale a un error externo.

**Criterios de aceptación**

1. Si todas las operaciones previstas terminaron correctamente pero hay menos candidatos elegibles, puede publicarse un lote menor.
2. El resumen debe indicar `insufficient_candidates` o `insufficient_signals` según corresponda.
3. Nunca se relajan mínimos, bloqueos, duración, términos negativos ni diversidad para completar ocho lugares.

## 4. Scoring y selección

### CORR-RF-04 — Umbrales configurables efectivos

Los mínimos por banda deben provenir de configuración y aplicarse una sola vez en una frontera explícita de elegibilidad.

**Criterios de aceptación**

1. No existen literales duplicados `55/45/35` fuera de los defaults de configuración o fixtures declarativos.
2. Un candidato por debajo del mínimo de su banda no llega al selector.
3. Cambiar un mínimo cambia el resultado sin modificar código.
4. El selector recibe únicamente candidatos elegibles o recibe los umbrales de forma explícita; no puede inventar defaults propios.
5. Peso `1.0` conserva la contribución base definida en `design.md`.
6. El score final se limita a `0..100`.

### CORR-RF-05 — Mezcla y fallback sin deriva

La mezcla y el fallback deben respetar la cercanía temática.

**Criterios de aceptación**

1. Con inventario suficiente, el resultado exacto es el configurado; por defecto, 5 `related`, 2 `adjacent` y 1 `exploratory`.
2. Un faltante `related` solo puede cubrirse con un `adjacent` elegible.
3. Un faltante `adjacent` solo puede cubrirse con un `related` elegible.
4. Un faltante `exploratory` puede cubrirse primero con `adjacent` y luego con `related`.
5. Nunca se usa un `exploratory` adicional para cubrir `related` o `adjacent`.
6. La banda persistida sigue siendo la banda real del candidato.
7. Si no existe fallback válido, el lote es menor al objetivo.
8. El resumen cuenta las bandas reales seleccionadas, no los cupos lógicos rellenados.

### CORR-RF-06 — Diversidad configurable y determinista

**Criterios de aceptación**

1. El máximo de videos por canal proviene de configuración; por defecto es 2.
2. No se selecciona dos veces el mismo `youtube_video_id`.
3. Los títulos prácticamente duplicados no desplazan candidatos diversos elegibles.
4. El orden es determinista por score descendente, publicación descendente e ID de YouTube como desempate.
5. `selection_rank` es consecutivo desde 1 y estable para la misma entrada.

### CORR-RF-07 — Señales temporales diferenciadas

**Criterios de aceptación**

1. Apertura, visto y feedback explícito respetan categoría y ventana temporal.
2. Una apertura es más débil que `watched`.
3. `more_like_this` es más fuerte que apertura o visto aislados.
4. Un `watched=true` fuera de la ventana no cuenta para sugerir seguimiento.
5. Dos señales sobre el mismo video cuentan como un solo video distinto para el umbral de canal.
6. El bloqueo es global; el resto del feedback es de categoría salvo requisito explícito contrario.

## 5. Feedback e interfaz

### CORR-RF-08 — Acciones semánticamente separadas

**Criterios de aceptación**

1. “Me interesa” envía `more_like_this`.
2. “No me interesa” envía `less_like_this`.
3. “Seguir canal” es una acción visible distinta y envía `accept_channel`.
4. Alcanzar el umbral de sugerencia nunca ejecuta `accept_channel` automáticamente.
5. La interfaz no envía `channelId` para feedback de video; el backend lo deriva del registro persistido.

### CORR-RF-09 — Mutaciones frontend confirmadas

**Criterios de aceptación**

1. Toda mutación comprueba `response.ok`.
2. Ante `4xx`, `5xx`, timeout o error de red, la tarjeta y el estado visual permanecen sin confirmar.
3. Solo una respuesta exitosa produce notificación de éxito y cambio visual.
4. El usuario recibe un mensaje público accionable y puede reintentar.
5. Ningún mensaje variable se inserta sin escape mediante `innerHTML`.

## 6. Contrato HTTP

### CORR-RF-10 — Validación estricta

**Criterios de aceptación**

1. Cursor malformado, banda desconocida, `limit` fuera de rango y query inválida devuelven `400`.
2. Cuerpos con acción, estado, etapa o peso fuera del esquema devuelven `422`.
3. Video, canal, categoría, tema o candidato inexistente devuelven `404`.
4. Una acción de feedback no puede llegar a una restricción SQLite como mecanismo primario de validación.
5. El backend valida que video y candidato pertenezcan al contexto indicado.
6. Todos los errores siguen el esquema `Error` de OpenAPI.
7. `GET /refresh-runs` respeta `limit`.

### CORR-RF-11 — RefreshRun coherente

**Criterios de aceptación**

1. `errors` es una lista de `{stage, categoryId?, code, message}`.
2. `message` es público y sanitizado.
3. `counters` usa la estructura definida en OpenAPI y nombres JSON `camelCase`.
4. Backend, frontend y pruebas de contrato consumen exactamente la misma forma.
5. Las etapas aceptadas por API, OpenAPI, worker y orquestador son idénticas.
6. En este incremento solo son válidas `subscriptions`, `followed_videos` y `discovery`; `channels` y `classification` permanecen fuera hasta tener handlers reales.

## 7. Worker y concurrencia

### CORR-RF-12 — Propiedad exclusiva del trabajo

**Criterios de aceptación**

1. El claim es atómico entre conexiones independientes.
2. Solo el propietario vigente puede actualizar progreso, publicar o finalizar.
3. El worker renueva la lease durante etapas largas antes de alcanzar la mitad del tiempo de expiración.
4. Si pierde la lease, deja de escribir y no publica resultados.
5. Un worker recuperador puede continuar de forma idempotente.
6. El mensaje final del proceso refleja el estado persistido real.

### CORR-RF-13 — Flask no ejecuta red del refresh

**Criterios de aceptación**

1. `POST /refresh-runs` solo valida y crea un trabajo `pending`.
2. No inicia threads ni llama gateways externos.
3. Reiniciar Flask no elimina el trabajo.
4. El entry point real del worker funciona sin request context.

## 8. Configuración y migración

### CORR-RF-14 — Una única fuente de configuración

**Criterios de aceptación**

1. Tamaño, mezcla, máximo por canal, búsquedas, resultados, región, idioma, ventanas, umbrales y sugerencia de canal se leen desde configuración.
2. `app/config.py`, `.env.example`, servicio, selector y pruebas comparten defaults.
3. Los presupuestos predeterminados son 10 globales y 2 por categoría.
4. Configuración declarada pero no utilizada se conecta o se elimina del incremento.

### CORR-RF-15 — Migración recuperable

**Criterios de aceptación**

1. Una base anterior con datos conserva conteos e identidades después de migrar.
2. Los candidatos legados reciben rank determinista cuando están activos.
3. Un fallo intermedio no deja tablas renombradas, faltantes o parcialmente copiadas.
4. La solución no reescribe una migración ya registrada de forma incompatible; se agrega una migración correctiva si corresponde.
5. La estrategia de backup y restauración queda documentada.

## 9. Seguridad y calidad

### CORR-RF-16 — Errores seguros

**Criterios de aceptación**

1. La API no devuelve tracebacks, tokens, secretos ni cuerpos completos externos.
2. Los logs técnicos pueden incluir stack interno, pero deben sanitizar credenciales y respuestas sensibles.
3. Los errores persistidos contienen código y mensaje público; el detalle técnico queda en logs correlacionados por `refresh_run_id`.

### CORR-RF-17 — Puerta de calidad

**Criterios de aceptación**

1. Cada defecto auditado tiene al menos una regresión automatizada.
2. Las pruebas nuevas fallan antes del cambio de producción por el motivo esperado.
3. `pytest -q`, `ruff check .`, compilación, sintaxis JavaScript, `git diff --check` y validación OpenAPI terminan correctamente.
4. No se permiten exclusiones globales, pruebas debilitadas ni `# noqa` para ocultar defectos del incremento.
5. La matriz final relaciona requisito, prueba, archivo y commit.
