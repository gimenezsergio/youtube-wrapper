# Casos de aceptación correctivos

## 1. Reglas generales

- Ninguna prueba llama a YouTube real.
- Integración usa SQLite temporal físico cuando se prueban locks, WAL, lease o migraciones.
- Cada prueba incluye su ID en el nombre o docstring.
- La fase inicial agrega regresiones sin modificar producción.
- Una regresión inicial es válida solo si falla en una aserción del comportamiento auditado, no por fixture, import, sintaxis o dependencia faltante.
- Las tablas declaran resultados exactos; no se aceptan aserciones como `len(result) > 0` cuando la cantidad está especificada.

### 1.1 Trazabilidad

| Requisito | Casos obligatorios |
|---|---|
| CORR-RF-01 | CORR-PUB-07..08, CORR-REF-03 |
| CORR-RF-02 | CORR-PUB-01..05, CORR-PUB-09 |
| CORR-RF-03 | CORR-PUB-06 |
| CORR-RF-04 | CORR-SCORE-01..04, CORR-SCORE-06, CORR-CONF-02 |
| CORR-RF-05 | CORR-SEL-01..06 |
| CORR-RF-06 | CORR-SEL-07..09 |
| CORR-RF-07 | CORR-SCORE-05, CORR-API-04 |
| CORR-RF-08 | CORR-UI-01..02, CORR-API-02..04 |
| CORR-RF-09 | CORR-UI-03..05 |
| CORR-RF-10 | CORR-API-01..06 |
| CORR-RF-11 | CORR-API-07..08, CORR-UI-04 |
| CORR-RF-12 | CORR-REF-04..08 |
| CORR-RF-13 | CORR-REF-01..02 |
| CORR-RF-14 | CORR-CONF-01..03 |
| CORR-RF-15 | CORR-MIG-01..03 |
| CORR-RF-16 | CORR-SEC-01, CORR-UI-05 |
| CORR-RF-17 | CORR-QUAL-01..02 |

## 2. Scoring

### CORR-SCORE-01 — Peso neutral

**Dado** un video de 600 segundos, publicado hace 2 días, con descripción y miniatura, cuyo título contiene una keyword positiva de peso `1.0`.

**Cuando** se puntúa sin otras señales.

**Entonces** obtiene score `55.0`, banda `related` y es elegible con el mínimo predeterminado.

### CORR-SCORE-02 — Keyword débil

Misma entrada que `CORR-SCORE-01`, con peso `0.1`.

**Resultado exacto**: score `23.5` y no elegible.

### CORR-SCORE-03 — Mínimo configurable

| Score del candidato | Mínimo `related` | Elegible |
|---:|---:|---|
| 55 | 55 | sí |
| 55 | 56 | no |
| 80 | 99 | no |
| 99 | 99 | sí |

La prueba debe atravesar la misma configuración utilizada por `DiscoveryService`, no llamar solamente una constante aislada.

### CORR-SCORE-04 — Temas y banda

| Evidencia en título | Score | Banda |
|---|---:|---|
| tema aprobado peso 1 | 50 | `exploratory` |
| keyword peso 1 + tema aprobado peso 1 | 55 | `adjacent` |
| ninguna evidencia | sin candidato | ninguna |

### CORR-SCORE-05 — Ventana e intensidad

Con igual similitud temática:

```text
sin interacción < apertura < visto < more_like_this
```

Las cuatro puntuaciones deben ser distintas y respetar el orden. Una interacción fuera de la ventana produce la misma puntuación que “sin interacción”.

### CORR-SCORE-06 — Límites

Una tabla con pesos `-1`, `0`, `1`, `5` y `100`, más penalizaciones, siempre produce `0 <= score <= 100`. Un peso mayor a 1 no excede el máximo de su componente.

## 3. Selección

Los fixtures de selección usan canales y títulos distintos salvo que el caso indique lo contrario.

### CORR-SEL-01 — Mezcla completa

**Entrada**: 7 related, 4 adjacent y 3 exploratory, todos elegibles.

**Salida exacta**: 8 candidatos; `selectedByBand={related:5, adjacent:2, exploratory:1}`; ranks `1..8`.

### CORR-SEL-02 — Solo exploratorios

**Entrada**: 8 exploratory elegibles.

**Salida exacta**: 1 exploratory, ningún related ni adjacent, `shortfallReason=insufficient_candidates`.

### CORR-SEL-03 — Faltante related

**Entrada**: 3 related, 5 adjacent, 2 exploratory.

**Salida**: related reales `3`, adjacent reales hasta completar los cupos permitidos y exploratory real `1`; ningún segundo exploratory puede cubrir los dos related faltantes. El total esperado es `8` si diversidad lo permite: `3 related + 4 adjacent + 1 exploratory`.

### CORR-SEL-04 — Faltante adjacent

**Entrada**: 8 related, 0 adjacent, 2 exploratory.

**Salida exacta**: `7 related + 1 exploratory`; total 8. El segundo exploratory no cubre adjacent.

### CORR-SEL-05 — Faltante exploratory

**Entrada**: 7 related, 3 adjacent, 0 exploratory.

**Salida exacta**: `5 related + 3 adjacent`; total 8.

### CORR-SEL-06 — Debajo del mínimo

Un related con score `54.999`, un adjacent con `44.999` y un exploratory con `34.999` no aparecen en la selección.

### CORR-SEL-07 — Máximo por canal configurable

| `max_per_channel` | Candidatos mejores del mismo canal | Cantidad seleccionada de ese canal |
|---:|---:|---:|
| 1 | 4 | 1 |
| 2 | 4 | 2 |
| 3 | 4 | 3 |

### CORR-SEL-08 — Determinismo

Permutar la entrada diez veces produce exactamente los mismos IDs y ranks. Empates de score y fecha se resuelven por ID de YouTube ascendente.

### CORR-SEL-09 — Duplicados

Dos objetos con el mismo `youtube_video_id` producen una sola selección. Dos títulos con similitud superior al umbral no desplazan a un título diverso elegible.

## 4. Publicación y degradación

Cada caso comienza con un batch anterior visible y al menos un candidato `active` asociado al refresh anterior.

### CORR-PUB-01 — Cuota antes de resultados

La primera búsqueda lanza `YouTubeQuotaError`.

**Entonces**:

- el batch anterior sigue siendo el último visible;
- sus candidatos siguen `active`;
- no existe batch de la categoría para el refresh fallido;
- el refresh contiene código `YOUTUBE_QUOTA_EXHAUSTED`.

### CORR-PUB-02 — Cuota después de un resultado

La primera búsqueda devuelve un candidato hidratable; la segunda lanza `YouTubeQuotaError`.

**Resultado exacto**:

```text
old-v: active, refresh anterior
new-v: no active
batch visible: refresh anterior
```

### CORR-PUB-03 — Timeout

Un timeout después de cualquier cantidad de resultados conserva el lote anterior y registra `YOUTUBE_TIMEOUT` sin traceback público.

### CORR-PUB-04 — Hidratación de videos incompleta

Si el gateway no devuelve detalles para todos los videos requeridos por la política del intento, no publica la categoría. Debe distinguir ausencia individual descartable de fallo total del endpoint según el resultado tipado del gateway.

### CORR-PUB-05 — Hidratación de canales fallida

Una excepción al hidratar canales aborta la categoría sin expirar el lote anterior.

### CORR-PUB-06 — Lote parcial válido

Todas las llamadas terminan correctamente y solo existen 6 candidatos elegibles.

**Salida**: nuevo batch con 6, anterior expirado, `shortfallReason=insufficient_candidates`.

### CORR-PUB-07 — Categorías aisladas

Categoría A produce 8 válidos; categoría B agota cuota después de una búsqueda.

**Salida**:

- A publica su nuevo lote;
- B conserva el anterior;
- el refresh termina `partial`;
- no existe una transacción que publique o revierta ambas conjuntamente.

### CORR-PUB-08 — Excepción durante publicación

Inyectar un fallo después de guardar candidatos nuevos pero antes de expirar anteriores.

**Salida**: rollback total; no quedan candidatos ni batch nuevos y los anteriores siguen activos.

### CORR-PUB-09 — Reintento

Después de `CORR-PUB-02`, un nuevo refresh exitoso publica una sola copia del candidato, un solo batch por categoría/refresh y expira el lote anterior una vez.

## 5. API y contrato

Todas las respuestas de error se validan contra `components.schemas.Error`.

### CORR-API-01 — Query inválida

| Solicitud | Estado |
|---|---:|
| `/discoveries?cursor=abc` | 400 |
| `/discoveries?band=nonsense` | 400 |
| `/discoveries?limit=0` | 400 |
| `/discoveries?limit=101` | 400 |

### CORR-API-02 — Feedback inválido

| Caso | Estado |
|---|---:|
| acción `invented` | 422 |
| falta `categoryId` | 422 |
| `categoryId` no entero | 422 |
| propiedad `channelId` enviada | 422 |

Ningún caso genera `IntegrityError`.

### CORR-API-03 — Recursos inexistentes

| Operación | Estado |
|---|---:|
| feedback sobre video inexistente | 404 |
| feedback en categoría inexistente | 404 |
| bloquear canal inexistente | 404 |
| restaurar ocultación inexistente | 404 |
| modificar tema inexistente | 404 |

### CORR-API-04 — Integridad del canal

Crear video V del canal A y canal B. El cliente no puede usar feedback de V para bloquear, aceptar o afectar B. El servidor deriva A desde V.

### CORR-API-05 — Temas

Pesos `-0.1` y `10.1`, estado desconocido y transición no permitida devuelven `422`; no hay cambios persistidos.

### CORR-API-06 — Limit de refresh runs

Con 15 ejecuciones:

| `limit` | `len(items)` |
|---:|---:|
| 1 | 1 |
| 10 | 10 |
| 15 | 15 |

### CORR-API-07 — Contrato RefreshRun

Validar automáticamente una respuesta `succeeded`, una `partial` y una `failed` contra OpenAPI. `errors` es lista tipada, `counters` usa camelCase y ningún campo JSON interno se devuelve como string.

### CORR-API-08 — Etapas

`subscriptions`, `followed_videos` y `discovery` son aceptadas. `channels`, `classification` y cualquier otra etapa devuelven `422`.

## 6. Frontend

Las pruebas pueden usar el entorno JavaScript existente o un harness Node con DOM/fetch simulado. No se acepta una búsqueda textual como única evidencia cuando el comportamiento puede ejecutarse.

### CORR-UI-01 — Me interesa

Click en “Me interesa” envía `{categoryId, action:"more_like_this"}` y no cambia `is_locally_followed`.

### CORR-UI-02 — Seguir canal

Click explícito en “Seguir canal” envía `accept_channel` y solo después de `2xx` retira o actualiza las tarjetas correspondientes.

### CORR-UI-03 — Error de feedback

Simular `500`:

- la tarjeta permanece;
- no se muestra éxito;
- aparece mensaje sanitizado;
- el usuario puede reintentar.

Repetir con `400`, timeout y rechazo de red.

### CORR-UI-04 — Polling fallido

Una respuesta `RefreshRun` con:

```json
{"status":"failed","errors":[{"stage":"discovery","code":"YOUTUBE_TIMEOUT","message":"Mensaje público"}]}
```

se renderiza sin excepción JavaScript, detiene polling y muestra el mensaje.

### CORR-UI-05 — XSS

Un mensaje remoto con `<img src=x onerror=...>` se muestra como texto. No se crea el elemento `img` ni se ejecuta código.

### CORR-UI-06 — Origen predeterminado

Sin parámetro de URL, la primera consulta de feed usa `origin=followed`. `origin=all` solo aparece después de selección explícita.

## 7. Worker, lease y transacciones

### CORR-REF-01 — Endpoint solo encola

Interceptar gateway y creación de threads. `POST /refresh-runs` devuelve `202`, crea `pending`, no llama gateway y no crea thread.

### CORR-REF-02 — Proceso independiente

Crear trabajo, ejecutar el entry point real del worker en subprocess con gateway fake y comprobar finalización sin request context.

### CORR-REF-03 — Rollback de etapa

Un handler inserta una fila y luego lanza `StageError`. Al finalizar:

- la fila no existe;
- el refresh es `failed` o `partial` según etapas anteriores;
- el error público no contiene `Traceback`.

### CORR-REF-04 — Dos workers

Dos conexiones y dos procesos/barreras intentan reclamar el mismo trabajo. Exactamente uno obtiene propiedad; el otro recibe `None`.

### CORR-REF-05 — Renovación

Una etapa dura más que una lease inicial y renueva heartbeat. Un segundo worker no puede recuperarla mientras las renovaciones estén vigentes.

### CORR-REF-06 — Pérdida de lease

Forzar cambio de propietario antes de publicar. El worker original recibe `LeaseLostError`, hace rollback y no finaliza ni publica.

### CORR-REF-07 — Recuperación

Un worker muerto deja expirar la lease. Otro la reclama y completa una única publicación idempotente.

### CORR-REF-08 — Estado informado

Una etapa no implementada o fallida produce mensaje de proceso “failed”; nunca “completado con éxito”.

## 8. Configuración

### CORR-CONF-01 — Defaults

Comparar defaults de `Config` y `.env.example`:

```text
max_searches_per_refresh=10
max_searches_per_category=2
batch_size=8
mix=5/2/1
max_per_channel=2
results_per_search=25
region=AR
language=es
```

### CORR-CONF-02 — Propagación

Configurar valores no predeterminados y verificar argumentos del gateway y selector mediante spies. Cada valor debe observarse en el consumidor correspondiente.

### CORR-CONF-03 — Configuración inválida

Mezcla cuya suma supera batch, límites no positivos o umbrales fuera de `0..100` deben impedir el inicio con mensaje claro.

## 9. Migración

### CORR-MIG-01 — Base anterior

Construir una base hasta la versión anterior con dos categorías y candidatos activos. Ejecutar migraciones actuales y verificar identidad, conteos, estados, reasons y ranks deterministas.

### CORR-MIG-02 — Fallo intermedio

Inyectar fallo después de copiar datos y antes del swap. Reabrir la base y comprobar que el esquema anterior sigue operativo y la migración no figura como ejecutada.

### CORR-MIG-03 — Idempotencia

Ejecutar el migrador dos veces produce el mismo esquema y datos.

## 10. Seguridad y calidad

### CORR-SEC-01 — Error externo sanitizado

Gateway lanza una excepción que contiene token, URL y cuerpo remoto. La respuesta y `errors_json` no contienen esos valores; el log correlacionado tampoco contiene el token.

### CORR-QUAL-01 — Puerta completa

Los siguientes comandos terminan con código 0:

```bash
pytest -q
ruff check .
git diff --check
python -m compileall -q app worker.py
node --check app/static/js/app.js
npx @redocly/cli lint specs/openapi.yaml
```

### CORR-QUAL-02 — Trazabilidad

La entrega incluye una tabla con cada ID `CORR-*`, nombre de prueba, archivo de producción y commit. Ningún requisito obligatorio queda únicamente como afirmación manual.
