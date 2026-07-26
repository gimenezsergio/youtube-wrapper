# YouTube Curator — paquete SDD

Aplicación web personal para organizar y descubrir contenido de YouTube sin depender de su portada algorítmica.

## Documentos

- `requirements.md`: alcance, requisitos funcionales y criterios de aceptación.
- `design.md`: arquitectura, modelo de datos, flujos y decisiones técnicas.
- `tasks.md`: plan de implementación incremental y verificable.
- `tests.md`: estrategia, casos de prueba y trazabilidad.
- `openapi.yaml`: contrato HTTP de la API Flask.

## Alcance de esta especificación

Incluye:

1. Autenticación con Google y acceso de solo lectura a YouTube.
2. Importación de suscripciones.
3. Categorías manuales con relación muchos-a-muchos.
4. Clasificación automática revisable.
5. Videos recientes con actualización manual.
6. Vistas por feed y por canal.
7. Filtros por categoría, canal, estado visto y procedencia.
8. Descubrimiento separado mediante canales semilla y palabras clave.
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
4. Ejecutar `tasks.md` en orden, sin saltar las puertas de verificación.
5. Validar cada incremento con `tests.md`.

