# Plan de ejecución correctiva — baby steps

## 1. Regla de operación

Este plan está diseñado para agentes con capacidad limitada de razonamiento simultáneo. Cada fase debe ejecutarse en una conversación o encargo separado.

Al terminar una fase, el agente:

1. ejecuta su puerta específica;
2. muestra la salida exacta;
3. crea el commit indicado;
4. hace push a la misma rama de corrección;
5. se detiene y espera revisión.

No se autoriza continuar automáticamente a la fase siguiente.

## 2. Preparación

- [ ] Actualizar `main` y crear `agent/correcciones-finales-recomendaciones`.
- [ ] Confirmar que contiene el merge `99023ae` o su descendiente.
- [ ] Registrar `git status --short --branch` y `git log -1 --oneline`.
- [ ] Instalar `requirements.txt` en venv aislado.
- [ ] Ejecutar y registrar línea base: pytest, Ruff, compileall, JavaScript, diff-check y Redocly.
- [ ] Si `main` cambió mientras se preparaba este paquete, actualizar `current-state.md` solo con evidencia nueva antes de codificar.

## Fase 0 — Regresiones rojas, sin producción

### Alcance

Agregar pruebas que reproduzcan los defectos confirmados. No modificar `app/`, `worker.py`, migraciones, frontend ni OpenAPI.

### Casos obligatorios

- [ ] `CORR-PUB-02`: cuota después de una búsqueda exitosa conserva lote.
- [ ] `CORR-SEL-02`: ocho exploratorios producen uno.
- [ ] `CORR-SCORE-03`: mínimo 99 excluye score 80 atravesando configuración real.
- [ ] `CORR-API-01`: cursor y banda inválidos.
- [ ] `CORR-API-02`: feedback inválido controlado.
- [ ] `CORR-API-03`: canal inexistente devuelve 404.
- [ ] `CORR-UI-01`: “Me interesa” envía `more_like_this`.
- [ ] `CORR-UI-03`: error no retira tarjeta.
- [ ] `CORR-REF-03`: error de etapa hace rollback.
- [ ] `CORR-REF-04`: dos workers no reclaman lo mismo.

### Puerta

- Cada prueba falla por su aserción esperada.
- Las pruebas anteriores del proyecto siguen pasando cuando se excluyen las regresiones nuevas.
- No hay cambios de producción en el diff.

### Commit

```text
test: reproducir defectos pendientes de recomendaciones
```

**DETENERSE PARA REVISIÓN.**

## Fase 1 — Scoring y selección

### Archivos autorizados

- dominio de scoring, señales, selección y modelos;
- configuración tipada necesaria;
- pruebas `CORR-SCORE-*` y `CORR-SEL-*`.

No modificar servicios, API, frontend, worker ni migraciones.

### Baby steps

1. Aplicar umbrales configurables en una sola frontera.
2. Hacer verde `CORR-SCORE-03`.
3. Implementar casos dorados `CORR-SCORE-01..04`.
4. Diferenciar señales temporales `CORR-SCORE-05`.
5. Limitar componentes `CORR-SCORE-06`.
6. Eliminar fallback exploratorio hacia bandas cercanas.
7. Hacer verde `CORR-SEL-02`.
8. Implementar la matriz completa `CORR-SEL-01..06`.
9. Conectar máximo por canal y determinismo `CORR-SEL-07..09`.

### Puerta

```bash
pytest -q tests/test_discovery_scoring_corrections.py tests/test_discovery_selection_corrections.py
ruff check app/domain tests/test_discovery_scoring_corrections.py tests/test_discovery_selection_corrections.py
```

Los nombres se adaptan si se eligieron otros archivos, conservando todos los IDs.

### Commit

```text
fix: respetar scoring y fallback configurables
```

**DETENERSE PARA REVISIÓN.**

## Fase 2 — Publicación y transacciones

### Archivos autorizados

- `DiscoveryService` y modelos de resultado;
- repositorios de candidatos/batches;
- transacciones del orquestador estrictamente necesarias;
- gateway fake y pruebas `CORR-PUB-*`.

No modificar frontend ni migraciones.

### Baby steps

1. Introducir `CategoryAttemptResult` o equivalente.
2. Separar obtención externa de publicación SQLite.
3. Abortar publicación ante cuota antes de resultados.
4. Hacer verde `CORR-PUB-01`.
5. Abortar aunque existan resultados previos.
6. Hacer verde `CORR-PUB-02`.
7. Cubrir timeout e hidratación `CORR-PUB-03..05`.
8. Publicar lote parcial válido `CORR-PUB-06`.
9. Aislar categorías `CORR-PUB-07`.
10. Probar rollback e idempotencia `CORR-PUB-08..09`.

### Puerta

```bash
pytest -q tests/test_discovery_publication_corrections.py
ruff check app/services app/repositories tests/test_discovery_publication_corrections.py
```

### Commit

```text
fix: publicar lotes de descubrimiento de forma segura
```

**DETENERSE PARA REVISIÓN.**

## Fase 3 — API y contrato OpenAPI

### Archivos autorizados

- rutas y serializadores relacionados;
- esquemas/validadores de entrada;
- `specs/openapi.yaml` conforme a este paquete;
- pruebas `CORR-API-*`.

No modificar frontend todavía.

### Baby steps

1. Centralizar error `code/message/details`.
2. Validar cursor, band y limit.
3. Hacer verde `CORR-API-01`.
4. Validar feedback antes del repositorio y derivar canal.
5. Hacer verdes `CORR-API-02..04`.
6. Validar temas `CORR-API-05`.
7. Respetar limit de refresh `CORR-API-06`.
8. Congelar `RefreshRun` y validar respuestas `CORR-API-07`.
9. Unificar etapas `CORR-API-08`.

### Puerta

```bash
pytest -q tests/test_discovery_api_validation.py tests/test_openapi_contract.py
npx @redocly/cli lint specs/openapi.yaml
ruff check app/api tests/test_discovery_api_validation.py tests/test_openapi_contract.py
```

### Commit

```text
fix: validar API y alinear contrato de refresh
```

**DETENERSE PARA REVISIÓN.**

## Fase 4 — Frontend y seguridad de renderizado

### Archivos autorizados

- JavaScript/CSS/HTML de descubrimientos y polling;
- harness frontend;
- pruebas `CORR-UI-*`.

No modificar reglas de backend salvo adaptación contractual mínima justificada.

### Baby steps

1. Separar `more_like_this` y `accept_channel`.
2. Agregar control explícito “Seguir canal”.
3. Hacer verdes `CORR-UI-01..02`.
4. Comprobar `response.ok` y preservar UI ante error.
5. Hacer verde `CORR-UI-03`.
6. Consumir lista tipada de errores `CORR-UI-04`.
7. Eliminar interpolación insegura `CORR-UI-05`.
8. Verificar origen predeterminado `CORR-UI-06`.

### Puerta

```bash
node --check app/static/js/app.js
pytest -q tests/test_discovery_frontend_contract.py
ruff check tests/test_discovery_frontend_contract.py
```

### Commit

```text
fix: separar feedback y confirmar mutaciones frontend
```

**DETENERSE PARA REVISIÓN.**

## Fase 5 — Worker, lease y errores seguros

### Archivos autorizados

- worker y orquestador;
- repositorio de refresh;
- logging/errores tipados;
- pruebas `CORR-REF-*` y `CORR-SEC-01`.

### Baby steps

1. Mantener endpoint como enqueue puro `CORR-REF-01`.
2. Probar entry point real `CORR-REF-02`.
3. Separar rollback y actualización de progreso `CORR-REF-03`.
4. Comprobar `rowcount` y claim exclusivo `CORR-REF-04`.
5. Implementar renovación periódica `CORR-REF-05`.
6. Verificar propiedad antes de escribir `CORR-REF-06`.
7. Recuperar lease idempotentemente `CORR-REF-07`.
8. Informar estado real `CORR-REF-08`.
9. Sanitizar error público `CORR-SEC-01`.

### Puerta

```bash
pytest -q tests/test_refresh_transactions.py tests/test_refresh_worker_concurrency.py tests/test_security_errors.py
ruff check worker.py app/services/refresh_orchestrator.py app/repositories/refresh_run_repository.py tests/test_refresh_transactions.py tests/test_refresh_worker_concurrency.py tests/test_security_errors.py
```

### Commit

```text
fix: asegurar lease transacciones y errores del worker
```

**DETENERSE PARA REVISIÓN.**

## Fase 6 — Configuración y migración

### Archivos autorizados

- configuración y `.env.example`;
- inyección de configuración en consumidores;
- migrador y nueva migración correctiva;
- documentación de backup;
- pruebas `CORR-CONF-*` y `CORR-MIG-*`.

### Baby steps

1. Corregir defaults 10/2 y completar `.env.example`.
2. Hacer verde `CORR-CONF-01`.
3. Inyectar todos los valores `CORR-CONF-02`.
4. Validar combinaciones `CORR-CONF-03`.
5. Crear fixture de base anterior `CORR-MIG-01`.
6. Implementar migración correctiva sin reescribir una ya aplicada.
7. Probar rollback `CORR-MIG-02`.
8. Probar idempotencia `CORR-MIG-03`.
9. Documentar backup/restauración.

### Puerta

```bash
pytest -q tests/test_discovery_config.py tests/test_discovery_migration_corrections.py
ruff check app/config.py app/migrator.py tests/test_discovery_config.py tests/test_discovery_migration_corrections.py
```

### Commit

```text
fix: conectar configuración y asegurar migración
```

**DETENERSE PARA REVISIÓN.**

## Fase 7 — Consolidación

### Tareas

- [ ] Ejecutar todos los casos `CORR-*`.
- [ ] Ejecutar suite preexistente completa.
- [ ] Corregir Ruff sin exclusiones evasivas.
- [ ] Validar OpenAPI y contrato automático.
- [ ] Compilar Python y validar JavaScript.
- [ ] Ejecutar `git diff --check`.
- [ ] Revisar que no existan `TODO`, código simulado o etapas aceptadas sin handler.
- [ ] Crear matriz requisito → prueba → producción → commit.
- [ ] Actualizar `current-state.md` con resultado final sin borrar evidencia histórica.

### Puerta final

```bash
pytest -q
ruff check .
git diff --check
python -m compileall -q app worker.py
node --check app/static/js/app.js
npx @redocly/cli lint specs/openapi.yaml
```

Todos deben terminar con código 0. Advertencias de Redocly preexistentes deben clasificarse; ninguna advertencia nueva relacionada con el incremento puede quedar sin resolver.

### Commit

```text
test: consolidar correcciones de recomendaciones
```

Después de este commit se abre o actualiza el PR y se solicita auditoría independiente. No se hace merge automático.
