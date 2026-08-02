# YouTube Curator — paquete SDD

Aplicación web personal para organizar y descubrir contenido de YouTube sin depender de su portada algorítmica.

## Documentos

- `requirements.md`: alcance, requisitos funcionales y criterios de aceptación.
- `design.md`: arquitectura, modelo de datos, flujos y decisiones técnicas.
- `current-state.md`: relevamiento del código actual, estructuras parciales, brechas y riesgos de integración.
- `tasks.md`: plan vigente y ordenado para implementar descubrimiento y recomendaciones.
- `tests.md`: estrategia, casos de prueba y trazabilidad.
- `openapi.yaml`: contrato HTTP de la API Flask.
- `recommendation-corrections/`: especificación incremental para estabilizar el motor integrado en `99023ae`, con regresiones ejecutables y ejecución en baby steps.

## Alcance de esta especificación

Incluye:

1. Autenticación con Google y acceso de solo lectura a YouTube.
2. Importación de suscripciones.
3. Categorías manuales con relación muchos-a-muchos.
4. Clasificación automática revisable.
5. Videos recientes con actualización manual.
6. Vistas por feed y por canal.
7. Filtros por categoría, canal, estado visto y procedencia.
8. Descubrimiento separado y explicable, con variedad controlada en bandas `related`, `adjacent` y `exploratory`.
9. Interfaz responsive instalable como PWA.

No incluye una extensión de navegador, reproducción embebida ni sincronización garantizada con el historial completo de YouTube.

## Stack acordado

- Frontend: HTML, CSS y JavaScript vanilla.
- Backend: Python 3 + Flask.
- Persistencia: SQLite.
- Integración externa: YouTube Data API v3 mediante OAuth 2.0.
- Despliegue: servidor Debian con HTTPS.

## Orden de lectura para un agente

1. Leer `requirements.md`.
2. Leer `design.md`.
3. Consultar `openapi.yaml`.
4. Leer `tests.md` como criterios verificables de aceptación.
5. Leer `current-state.md` y confirmar que la brecha sigue vigente respecto del código.
6. Ejecutar `tasks.md` en orden, sin saltar dependencias ni puertas de verificación.
7. Si el código cambió después del commit relevado, actualizar primero `current-state.md` y ajustar únicamente las tareas afectadas.
8. Para corregir el incremento de recomendaciones ya integrado, leer además `recommendation-corrections/README.md` y ejecutar sus fases una por vez.

## Precedencia documental

En caso de contradicción, prevalecen en este orden:

1. `requirements.md` para alcance y comportamiento observable.
2. `openapi.yaml` para el contrato HTTP.
3. `design.md` para arquitectura y reglas internas.
4. `tests.md` para ejemplos verificables.
5. `current-state.md` para el punto de partida observado.
6. `tasks.md` para el orden de ejecución; nunca puede contradecir los cuatro documentos normativos anteriores.

Para el alcance correctivo declarado en `recommendation-corrections/README.md`, ese paquete tiene precedencia acotada sobre las secciones generales que precisa. No modifica requisitos ajenos a recomendaciones.
