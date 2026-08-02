# Diseño correctivo — recomendaciones

## 1. Principios

1. Ninguna llamada externa ocurre dentro de una transacción de escritura.
2. Un lote visible cambia una sola vez, mediante publicación atómica por categoría.
3. El dominio recibe snapshots y configuración explícitos; no consulta `current_app`.
4. La API serializa modelos internos en una frontera única.
5. El worker posee una lease verificable; no basta con recordar un `worker_id` en memoria.
6. Toda regla crítica tiene una prueba tabular con salida exacta.

## 2. Flujo por categoría

```text
snapshot local de señales
→ plan de consultas
→ llamadas externas sin transacción de escritura
→ hidratación completa
→ exclusiones
→ scoring y elegibilidad
→ selección
→ verificación de lease
→ publicación atómica
```

### 2.1 Resultado interno

Cada intento produce uno de estos resultados antes de escribir el lote:

```python
CategoryAttemptResult(
    category_id: int,
    outcome: Literal["publishable", "aborted"],
    candidates: list[Candidate],
    summary: BatchSummary | None,
    error: PublicStageError | None,
)
```

Reglas:

- `publishable` significa que terminaron todas las operaciones previstas de la categoría.
- Puede contener cero candidatos por `insufficient_signals` o un lote menor por `insufficient_candidates`.
- `aborted` nunca contiene un lote publicable.
- Cuota o error posterior a una búsqueda exitosa sigue siendo `aborted`.

### 2.2 Publicación

La publicación usa una nueva conexión o una transacción limpia:

```text
BEGIN IMMEDIATE
verificar que la lease pertenece al worker
persistir/actualizar candidatos seleccionados
persistir discovery_batch
expirar candidatos activos anteriores no seleccionados
COMMIT
```

Ante cualquier error: `ROLLBACK`. Las llamadas al gateway ya deben haber finalizado.

Para un resultado `aborted` solo se actualiza el refresh run mediante otra transacción corta. No se llama a `save_discovery_candidate`, `save_discovery_batch` ni `expire_previous_candidates`.

## 3. Snapshot e identificadores

- Los repositorios devuelven IDs locales enteros para comparaciones internas.
- Los IDs de YouTube se conservan para deduplicación externa y desempates.
- Las exclusiones por video son específicas de categoría salvo bloqueo global.
- Canales `is_subscribed` o `is_locally_followed` se excluyen globalmente de descubrimiento.
- El snapshot se congela al iniciar el intento; propuestas `pending` creadas durante el refresh no participan.

## 4. Scoring determinista

El score es la suma de componentes limitada a `0..100`. Un peso de señal se normaliza así:

```python
normalized_weight = clamp(weight, 0.0, 1.0)
```

`1.0` es neutral y entrega la contribución base completa. Valores mayores a `1.0` conservan prioridad para ordenar consultas y evidencias, pero no pueden exceder el máximo del componente. Esta decisión evita que un peso alto por sí solo atraviese todos los límites del score.

### 4.1 Componentes

| Componente | Rango | Regla determinista inicial |
|---|---:|---|
| Coincidencia temática | 0..35 | keyword positiva en título: `35*w`; solo descripción: `28*w`; tema aprobado en título: `30*w`; solo descripción: `24*w`; tomar máximo |
| Similitud con semillas | 0..20 | Jaccard de tokens normalizados: `>=0.50 → 20`, `>=0.30 → 12`, `>=0.15 → 6`, resto `0` |
| Señales locales recientes | 0..15 | máximo relacionado: apertura `4`, visto `8`, `more_like_this` `15` |
| Actualidad | 0..10 | `<=7 días → 10`, `<=30 → 7`, `<=90 → 4`, `<=180 → 2`, resto `0` |
| Feedback positivo relacionado | 0..10 | `more_like_this` del mismo canal y categoría dentro de ventana: `10`; sin feedback explícito: `0` |
| Novedad y completitud | 0..10 | video no visto antes: `5`; metadatos hidratados completos: `5` |
| Feedback negativo | 0..40 | `less_like_this` del mismo video: `40`; mismo canal/categoría: `20`; tomar máximo |

No se puntúan candidatos con duración desconocida ni menor o igual a 180 segundos. Bloqueo, ocultación, canal seguido, visto ya consumido cuando corresponda y palabra negativa son exclusiones previas, no penalizaciones.

### 4.2 Banda

La banda se determina antes de aplicar el mínimo:

- `adjacent`: existe al menos una keyword positiva coincidente y un tema aprobado coincidente.
- `related`: existe keyword positiva directa o similitud suficiente con una semilla/señal local de la categoría.
- `exploratory`: existe tema aprobado coincidente y no se cumplen las condiciones anteriores.
- sin evidencia: no hay candidato.

Después se aplica el mínimo configurado de la banda. Debajo del mínimo se retorna `None` o un resultado interno no elegible que nunca llega al selector.

### 4.3 Casos dorados

Con defaults `55/45/35`, fecha dentro de siete días y metadatos completos:

| Evidencia | Score esperado | Resultado |
|---|---:|---|
| keyword en título, peso 1, sin otras señales | 55 | `related`, elegible |
| keyword en título, peso 0.1, sin otras señales | 23.5 | no elegible |
| tema aprobado en título, peso 1, sin otras señales | 50 | `exploratory`, elegible |
| keyword + tema aprobado en título, peso 1 | 55 | `adjacent`, elegible |
| keyword peso 1 con mínimo related configurado en 99 | 55 | no elegible |

Los casos dorados congelan la semántica inicial. Cualquier cambio requiere actualizar requisitos, diseño y pruebas en el mismo PR.

## 5. Selección

### 5.1 Entrada

El selector recibe:

```python
SelectionConfig(
    total=8,
    related=5,
    adjacent=2,
    exploratory=1,
    max_per_channel=2,
    duplicate_title_threshold=0.70,
)
```

La suma de cupos no puede superar `total`. Una configuración inválida falla al iniciar la aplicación o devuelve un error explícito antes del refresh.

### 5.2 Algoritmo

1. Deduplicar por `youtube_video_id` conservando el candidato mejor ordenado de cada banda/categoría.
2. Separar pools por banda real.
3. Ordenar cada pool por `(-score, -published_at, youtube_video_id)`; el último desempate usa ID ascendente para una salida inequívoca.
4. Cubrir cupos reales en orden `related`, `adjacent`, `exploratory`, aplicando máximo por canal y similitud de títulos.
5. Calcular faltantes sin alterar las bandas.
6. Aplicar fallback:

   | Cupo faltante | Pool permitido |
   |---|---|
   | `related` | remanente `adjacent` |
   | `adjacent` | remanente `related` |
   | `exploratory` | remanente `adjacent`, luego `related` |

7. Detener al alcanzar `total` o agotar pools permitidos.
8. Ordenar la salida para presentación por cupo de selección y asignar rank 1..N.
9. Contar `selectedByBand` usando `candidate.band`, nunca el cupo que motivó su incorporación.

No existe ningún camino desde un remanente `exploratory` hacia un cupo `related` o `adjacent`.

## 6. Feedback

### 6.1 Comandos HTTP

El cliente envía exclusivamente:

```json
{
  "categoryId": 4,
  "action": "more_like_this"
}
```

Acciones válidas:

- `more_like_this`
- `less_like_this`
- `hide_video`
- `block_channel`
- `accept_channel`

El servidor consulta el video y deriva `channel_id`. Luego valida candidato y categoría antes de mutar.

### 6.2 Interfaz

| Control | Acción |
|---|---|
| Me interesa | `more_like_this` |
| No me interesa | `less_like_this` |
| Ocultar video | `hide_video` |
| Bloquear canal | `block_channel` |
| Seguir canal | `accept_channel` |

La función compartida retorna datos solo con `2xx`; en otro caso lanza un error público. Los listeners modifican DOM únicamente después de la resolución exitosa.

Para mensajes variables se usa `textContent` o creación de nodos. Si una plantilla HTML es inevitable, cada valor variable pasa por `escapeHtml`.

## 7. Contrato de RefreshRun

La representación HTTP usa `camelCase`, aunque internamente SQLite conserve nombres `snake_case`.

```json
{
  "id": 12,
  "status": "partial",
  "currentStage": null,
  "stages": ["subscriptions", "followed_videos", "discovery"],
  "requestedAt": "2026-08-02T12:00:00Z",
  "startedAt": "2026-08-02T12:00:01Z",
  "finishedAt": "2026-08-02T12:00:08Z",
  "counters": {
    "subscriptions": {"created": 1, "updated": 4},
    "followedVideos": {"created": 8, "processedChannels": 5},
    "discovery": {
      "searchesExecuted": 4,
      "quotaExhausted": false,
      "categories": {
        "4": {"selected": 6, "shortfall": "insufficient_candidates"}
      }
    }
  },
  "errors": [
    {
      "stage": "discovery",
      "categoryId": 7,
      "code": "YOUTUBE_TIMEOUT",
      "message": "YouTube no respondió a tiempo; se conservó el lote anterior."
    }
  ],
  "heartbeatAt": "2026-08-02T12:00:07Z",
  "leaseExpiresAt": null
}
```

El serializador transforma explícitamente las claves internas. El frontend no interpreta JSON serializado como texto ni estructuras alternativas.

## 8. Transacciones del orquestador

Cada handler de etapa devuelve un resultado o lanza un error tipado. El orquestador aplica:

```python
try:
    result = handler.run(...)
except StageError as exc:
    business_db.rollback()
    progress_repo.append_public_error(...)
else:
    business_db.commit_if_required()
    progress_repo.store_counters(...)
```

No se concatena `traceback.format_exc()` en `errors_json`. El traceback se registra en logging técnico con `refresh_run_id`.

## 9. Lease y heartbeat

- Claim mediante `BEGIN IMMEDIATE` y `UPDATE ... WHERE` condicionado.
- La operación devuelve trabajo solo si `rowcount == 1`.
- El handler recibe un `LeaseGuard` con `assert_owned()` y `heartbeat()`.
- Para llamadas paginadas, se renueva entre páginas/lotes.
- Para una operación única potencialmente larga, un hilo de heartbeat dedicado puede usarse solo dentro del proceso worker, nunca en Flask, con conexión SQLite propia y ciclo menor a `lease_duration / 2`.
- Antes de publicar o finalizar se ejecuta `assert_owned()`.
- Una pérdida de lease provoca rollback y `LeaseLostError`; el worker anterior no marca el refresh como finalizado.

## 10. Configuración

El servicio recibe una estructura inmutable:

```python
DiscoveryConfig(
    batch_size,
    mix_related,
    mix_adjacent,
    mix_exploratory,
    max_videos_per_channel,
    max_searches_per_refresh,
    max_searches_per_category,
    results_per_search,
    signal_window_days,
    max_search_age_days,
    suggest_channel_threshold_videos,
    min_score_related,
    min_score_adjacent,
    min_score_exploratory,
    region_code,
    relevance_language,
)
```

La capa Flask construye esta configuración; dominio, repositorios y worker no leen variables globales dispersas.

## 11. Migración correctiva

No se edita retrospectivamente una migración que pueda figurar en `migrations_run`.

La nueva migración debe:

1. crear tablas temporales nuevas;
2. copiar datos con rank determinista por categoría usando `ROW_NUMBER()` cuando SQLite lo permita;
3. verificar conteos mediante SQL antes del swap;
4. realizar el swap dentro de una transacción controlada sin `executescript` destructivo;
5. registrar la migración solo después del éxito;
6. restaurar la base original ante cualquier fallo.

Si el runner actual no puede garantizar atomicidad para un script múltiple, la migración correctiva se implementa como función Python versionada que ejecuta sentencias individuales.

## 12. Organización de pruebas

Archivos recomendados:

```text
tests/test_discovery_scoring_corrections.py
tests/test_discovery_selection_corrections.py
tests/test_discovery_publication_corrections.py
tests/test_discovery_api_validation.py
tests/test_discovery_frontend_contract.py
tests/test_refresh_transactions.py
tests/test_refresh_worker_concurrency.py
tests/test_discovery_migration_corrections.py
```

Los nombres pueden adaptarse al proyecto, pero cada caso de `tests.md` debe ser localizable mediante su ID.
