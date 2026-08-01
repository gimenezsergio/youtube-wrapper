# Estado actual y análisis de brechas — Descubrimiento

## 1. Propósito

Este documento registra el punto de partida real del repositorio antes de implementar el sistema de descubrimiento definido en `requirements.md`, `design.md`, `openapi.yaml` y `tests.md`.

No reemplaza los requisitos ni propone otro diseño. Su función es impedir que el agente implementador confunda estructuras preparatorias con funcionalidad terminada.

## 2. Referencia del relevamiento

- Repositorio: `gimenezsergio/youtube-wrapper`.
- Rama relevada: `main`.
- Commit base: `07b56b7`.
- Stack observado: Flask, SQLite, HTML/CSS/JavaScript vanilla.
- El directorio no contiene instrucciones `AGENTS.md` adicionales.
- Las especificaciones de descubrimiento se modificaron localmente después del commit base y deben formar parte del mismo cambio o de un commit anterior a la implementación.

## 3. Funcionalidad existente que debe preservarse

### 3.1 Aplicación y seguridad

- Fábrica Flask en `app/__init__.py`.
- Autenticación Google OAuth y restricción por propietario.
- Persistencia cifrada de credenciales.
- Protección CSRF en mutaciones.
- SQLite con claves foráneas y WAL fuera de `:memory:`.
- Migraciones SQL registradas mediante `migrations_run`.

### 3.2 Categorías y canales

- CRUD y reordenamiento de categorías.
- Palabras clave positivas y negativas con peso.
- Importación de suscripciones de YouTube.
- Obtención de metadatos de canales y playlist de publicaciones.
- Clasificación manual muchos-a-muchos de canales.
- Registro de decisiones manuales `include` y `exclude`.
- Bloqueo y desbloqueo básico de canales mediante la API de canales.

### 3.3 Videos y estado local

- Sincronización incremental de videos de canales suscriptos o seguidos localmente.
- Hidratación de duración y tipo de contenido.
- Feed paginado y vista agrupada por canal.
- Filtros por categoría, canal, visto y origen.
- Búsqueda local por título, descripción o canal.
- Registro de apertura y marcado manual visto/no visto.
- Exclusión actual de videos de duración menor o igual a 180 segundos.

## 4. Estructuras preparatorias existentes

La migración inicial ya crea:

- `discovery_candidates`;
- `discovery_feedback`;
- `refresh_runs`;
- `classification_suggestions`.

Estas tablas no implican que las funciones estén implementadas. Su esquema tampoco alcanza el contrato actualizado:

- `discovery_candidates` no contiene `band`, `last_refresh_run_id` ni `selection_rank`;
- no existe `category_exploration_topics`;
- no existe `discovery_batches`;
- no existen repositorios o servicios específicos de descubrimiento.

`app/api/videos.py` consulta `discovery_candidates` y calcula el origen, pero actualmente:

- no hay un proceso que genere candidatos reales;
- no filtra por lote vigente o estado `active` en todos los caminos;
- no conoce bandas ni posición estable;
- devuelve `reasons_json` sin una normalización contractual completa;
- el origen predeterminado del endpoint sigue siendo `all`, mientras que la especificación actualizada exige `followed` para el feed normal.

## 5. Funcionalidad parcial que debe reemplazarse

### 5.1 Actualización manual

El botón “Actualizar” llama directamente a `POST /api/v1/channels/sync`. Esa ruta ejecuta suscripciones y videos dentro de la petición HTTP.

El archivo `worker.py` contiene reclamo, heartbeat y lease básicos, pero `process_job` solo:

- recorre nombres de etapas;
- espera dos segundos;
- asigna contadores simulados;
- no invoca los servicios reales.

No existen endpoints Flask para crear, listar o consultar `refresh_runs` conforme a `openapi.yaml`.

### 5.2 Interfaz de descubrimiento

La ruta `/discoveries` existe en el shell SPA, pero `renderDiscoveriesView()` muestra únicamente un aviso de futura implementación.

No existen:

- consulta del lote actual;
- etiquetas `Relacionado`, `Tema cercano` y `Para explorar`;
- razones de recomendación;
- acciones de feedback;
- sugerencia o aceptación de seguimiento local;
- gestión de temas adyacentes;
- restauración de videos ocultos desde ajustes.

## 6. Brechas de backend

1. Migración compatible con bases existentes para el nuevo modelo de descubrimiento.
2. Configuración de mezcla, presupuestos, límites, ventanas y mínimos.
3. Modelo de dominio puro para señales, consultas, bandas, puntuación, diversidad y fallback.
4. Persistencia de temas adyacentes, candidatos, lotes y feedback.
5. Adaptador `YouTubeGateway.search_videos` y errores externos tipados.
6. Generador determinista de propuestas de temas adyacentes.
7. Motor de descubrimiento completo e idempotente.
8. Orquestador real de actualizaciones y worker recuperable.
9. Endpoints de temas adyacentes, descubrimientos, feedback y restauración.
10. Transacción de aceptación de canal y precedencia de origen.

## 7. Brechas de frontend

1. Sustituir el placeholder de `/discoveries` por el lote persistido.
2. Filtros por categoría y banda representados en la URL.
3. Tarjetas con banda, razones y estados accesibles.
4. Acciones “Me interesa”, “No me interesa”, ocultar, bloquear y seguir canal.
5. Resumen de lote incompleto y errores accionables.
6. Gestión de temas adyacentes pendientes, aprobados y rechazados.
7. Actualización manual mediante `refresh_runs`, progreso por polling y resultado final.
8. Restauración de ocultaciones y bloqueos desde ajustes.

## 8. Brechas de pruebas

La suite contiene pruebas de autenticación, base de datos, categorías, suscripciones, canales, clasificación manual, videos, filtros y rendimiento del feed.

No existen pruebas automatizadas para:

- `REF-01..09` aplicadas al worker real;
- `DISC-01..26`;
- `FEED-01..10`;
- endpoints nuevos de `openapi.yaml`;
- la vista real de descubrimiento.

La suite no pudo ejecutarse durante este relevamiento porque el entorno disponible no tenía instalado el módulo `pytest`. El primer paso del agente implementador debe instalar `requirements.txt` en un entorno aislado y registrar el resultado de la línea base antes de modificar código.

## 9. Riesgos técnicos que condicionan el orden

### 9.1 Migración SQLite

La base puede contener datos reales. La migración no debe borrar ni recrear la base completa. Si se reconstruye `discovery_candidates` para agregar restricciones y claves foráneas, debe copiar filas existentes, asignar valores de compatibilidad y verificar conteos antes de eliminar la tabla anterior.

### 9.2 Cambio de actualización

No debe retirarse `/channels/sync` ni cambiarse el botón actual hasta que `refresh_runs`, el worker real y su polling estén probados. El reemplazo se realiza al final de la integración.

### 9.3 Cuota externa

Ninguna prueba debe llamar YouTube. La planificación usa fakes deterministas y presupuestos de 10 búsquedas por actualización y 2 por categoría.

### 9.4 Idempotencia y reintentos

Una lease vencida puede repetir una etapa. La escritura del lote, el vencimiento de candidatos previos y la aceptación de canales deben ser idempotentes. Un reintento no puede duplicar videos, feedback ni relaciones canal-categoría.

### 9.5 Dependencia semántica

El núcleo debe funcionar sin LLM, embeddings ni proveedor externo adicional. La coincidencia de términos es obligatoria; cualquier mejora semántica queda detrás de una interfaz opcional.

## 10. Fuera del alcance de esta planificación

Esta planificación no completa por sí sola:

- clasificación automática de canales de RF-05;
- auditoría completa de PWA, despliegue o systemd;
- cambios generales de diseño no relacionados con descubrimiento;
- suscripciones reales, historial, “Ver más tarde” o recomendaciones propietarias de YouTube.

La integración debe mantener un punto de extensión para ejecutar `classification` en el orquestador cuando esa función se planifique, sin convertirla en requisito previo del descubrimiento basado en categorías manuales.

## 11. Resultado esperado del incremento

Al finalizar `tasks.md`, el propietario podrá actualizar manualmente, obtener un lote finito y explicable por categoría, controlar sus señales, aprobar temas adyacentes, seguir canales localmente y conservar el feed cronológico separado. Las pruebas de descubrimiento y feedback deberán pasar sin consumir cuota real.
