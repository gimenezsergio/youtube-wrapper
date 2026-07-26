# Tareas de implementación — YouTube Curator

## Reglas de ejecución

- Ejecutar en orden.
- Cada tarea debe dejar pruebas verdes.
- No implementar una fase posterior para resolver una fase anterior.
- No conectar servicios externos en pruebas automatizadas.
- Marcar cada casilla solo después de cumplir su verificación.

## Fase 0 — Base del proyecto

- [ ] 0.1 Crear estructura Flask con fábrica de aplicación.
- [ ] 0.2 Configurar entornos `development`, `test` y `production`.
- [ ] 0.3 Configurar lint y formato para Python, JavaScript, CSS y YAML.
- [ ] 0.4 Crear esquema de migraciones y primera migración.
- [ ] 0.5 Habilitar SQLite WAL y claves foráneas.
- [ ] 0.6 Crear frontend base HTML/CSS/JS mobile first.
- [ ] 0.7 Añadir endpoint `/health`.
- [ ] 0.8 Añadir test runner y datos de fábrica.
- [ ] 0.9 Crear proceso worker independiente y comando de ejecución.

**Puerta de verificación**

- La aplicación inicia con un comando documentado.
- Una base vacía se crea mediante migraciones.
- `/health` responde sin consultar servicios externos.
- La suite mínima pasa.

## Fase 1 — Seguridad y OAuth

- [ ] 1.1 Implementar configuración obligatoria de secretos.
- [ ] 1.2 Implementar inicio y callback OAuth con validación de `state`.
- [ ] 1.3 Solicitar exclusivamente `youtube.readonly`.
- [ ] 1.4 Restringir acceso a `OWNER_GOOGLE_EMAIL`.
- [ ] 1.5 Implementar sesión segura y cierre de sesión.
- [ ] 1.6 Implementar CSRF para mutaciones.
- [ ] 1.7 Crear pantalla de conexión y errores de autorización.
- [ ] 1.8 Añadir pruebas de autorización y propietario incorrecto.
- [ ] 1.9 Cifrar tokens persistidos mediante clave externa al repositorio.

**Puerta de verificación**

- Ninguna ruta protegida es accesible anónimamente.
- Un usuario distinto del propietario es rechazado.
- Los logs no contienen tokens.

## Fase 2 — Categorías

- [ ] 2.1 Implementar repositorio y servicio de categorías.
- [ ] 2.2 Implementar CRUD conforme a `openapi.yaml`.
- [ ] 2.3 Implementar palabras clave positivas y negativas.
- [ ] 2.4 Implementar reordenamiento.
- [ ] 2.5 Crear interfaz de gestión responsive.
- [ ] 2.6 Representar la categoría seleccionada en la URL.
- [ ] 2.7 Añadir pruebas de unicidad, eliminación y orden.

**Puerta de verificación**

- Se pueden crear, editar, ordenar y borrar categorías desde celular y escritorio.
- Borrar una categoría no elimina otros datos.

## Fase 3 — Importación de suscripciones

- [ ] 3.1 Definir interfaz `YouTubeGateway`.
- [ ] 3.2 Crear fake determinista para pruebas.
- [ ] 3.3 Implementar cliente real con paginación y lotes.
- [ ] 3.4 Implementar `sync_subscriptions`.
- [ ] 3.5 Guardar playlist de publicaciones por canal.
- [ ] 3.6 Marcar desuscripciones sin borrar datos.
- [ ] 3.7 Crear pantalla de canales, búsqueda y estado sin clasificar.
- [ ] 3.8 Añadir pruebas de paginación, reimportación e idempotencia.

**Puerta de verificación**

- Dos importaciones iguales producen el mismo estado.
- Categorías locales sobreviven a una reimportación.

## Fase 4 — Clasificación manual

- [ ] 4.1 Implementar relación muchos-a-muchos.
- [ ] 4.2 Implementar asignación y remoción individual.
- [ ] 4.3 Implementar operaciones en lote.
- [ ] 4.4 Registrar decisiones explícitas `include` y `exclude`.
- [ ] 4.5 Crear UI con selección múltiple.
- [ ] 4.6 Añadir pruebas de idempotencia y precedencia manual.

**Puerta de verificación**

- Un canal puede pertenecer a varias categorías.
- Una exclusión manual no es revertida por automatización simulada.

## Fase 5 — Videos de suscripciones y seguimientos locales

- [ ] 5.1 Implementar consulta incremental de playlists de publicaciones.
- [ ] 5.2 Implementar hidratación de detalles en lotes.
- [ ] 5.3 Implementar `upsert` de videos.
- [ ] 5.4 Clasificar tipo de contenido con estado `unknown` seguro.
- [ ] 5.5 Crear endpoint de feed paginado.
- [ ] 5.6 Crear vista Feed ordenada por fecha.
- [ ] 5.7 Crear vista Por canal sin N+1.
- [ ] 5.8 Añadir estados de carga, error y vacío.
- [ ] 5.9 Probar 20.000 videos sintéticos y medir consulta.
- [ ] 5.10 Verificar que canales seguidos localmente participan en actualizaciones futuras.

**Puerta de verificación**

- No hay duplicados después de refrescos repetidos.
- Ambas vistas devuelven los mismos videos bajo filtros equivalentes.
- El primer lote cumple el presupuesto de rendimiento.

## Fase 6 — Filtros y estado visto

- [ ] 6.1 Implementar filtros combinables en repositorio.
- [ ] 6.2 Implementar filtro por canal.
- [ ] 6.3 Implementar filtro visto/no visto.
- [ ] 6.4 Implementar filtro de procedencia.
- [ ] 6.5 Sincronizar filtros con query string.
- [ ] 6.6 Implementar endpoint de apertura.
- [ ] 6.7 Registrar apertura antes de devolver URL de YouTube.
- [ ] 6.8 Implementar marcado manual visto/no visto.
- [ ] 6.9 Añadir pruebas de intersección y navegación.

**Puerta de verificación**

- Recargar o compartir una URL conserva filtros.
- Abrir un video lo marca y genera una URL válida de YouTube.

## Fase 7 — Actualización manual

- [ ] 7.1 Implementar entidad y repositorio `refresh_runs`.
- [ ] 7.2 Implementar orquestador por etapas.
- [ ] 7.3 Implementar reclamo atómico, heartbeat, lease y recuperación.
- [ ] 7.4 Crear endpoint de inicio y consulta de progreso.
- [ ] 7.5 Crear botón, progreso y resumen.
- [ ] 7.6 Implementar estados `running`, `succeeded`, `partial`, `failed`.
- [ ] 7.7 Añadir pruebas de fallo parcial y reintento.
- [ ] 7.8 Crear unidades systemd separadas para aplicación y worker.

**Puerta de verificación**

- No existen llamadas externas hasta que el usuario pulsa actualizar.
- Un fallo de descubrimiento conserva suscripciones y videos importados.

## Fase 8 — Clasificación automática

- [ ] 8.1 Definir protocolo `ChannelClassifier`.
- [ ] 8.2 Implementar clasificador por palabras clave.
- [ ] 8.3 Implementar adaptador semántico configurable.
- [ ] 8.4 Validar y normalizar salida del clasificador.
- [ ] 8.5 Guardar sugerencias, confianza, explicación y versión.
- [ ] 8.6 Respetar decisiones manuales.
- [ ] 8.7 Crear bandeja de revisión.
- [ ] 8.8 Implementar aceptar, rechazar y corregir en lote.
- [ ] 8.9 Añadir pruebas de fallback y respuestas inválidas.
- [ ] 8.10 Implementar y probar umbrales de sugerencia y autoaplicación.

**Puerta de verificación**

- El sistema funciona con el adaptador semántico desactivado.
- Ninguna sugerencia pisa una decisión manual.

## Fase 9 — Descubrimiento

- [ ] 9.1 Implementar generador de consultas por categoría, incluyendo señales de videos vistos recientemente con ventana configurable.
- [ ] 9.2 Implementar relación `discovery_candidates` muchos-a-muchos entre videos y categorías.
- [ ] 9.3 Implementar búsqueda limitada mediante `YouTubeGateway`.
- [ ] 9.4 Implementar deduplicación y exclusiones.
- [ ] 9.5 Implementar función pura de puntuación.
- [ ] 9.6 Guardar razones explicables.
- [ ] 9.7 Crear sección separada de descubrimiento.
- [ ] 9.8 Implementar feedback.
- [ ] 9.9 Implementar bloqueo y reversión desde configuración.
- [ ] 9.10 Implementar aceptación como seguimiento local.
- [ ] 9.11 Al aceptar, asignar el canal a la categoría con fuente `accepted_discovery` y promover sus videos conocidos a `followed`.
- [ ] 9.12 Añadir pruebas de puntuación, exclusión y cuota.
- [ ] 9.13 Aplicar presupuestos global y por categoría para `search.list`.

**Puerta de verificación**

- Un canal bloqueado no reaparece.
- Cada candidato visible tiene razones.
- Ninguna búsqueda ocurre fuera de una actualización solicitada.
- Un canal aceptado aporta videos nuevos en la actualización siguiente.

## Fase 10 — PWA, accesibilidad y operación

- [ ] 10.1 Añadir manifest e iconos.
- [ ] 10.2 Añadir service worker limitado a shell y assets.
- [ ] 10.3 Añadir estados offline sin datos engañosos.
- [ ] 10.4 Ejecutar auditoría de teclado, foco, etiquetas y contraste.
- [ ] 10.5 Implementar exportación JSON.
- [ ] 10.6 Documentar Nginx, HTTPS y servicio systemd.
- [ ] 10.7 Documentar backup y restauración de SQLite.
- [ ] 10.8 Añadir logging estructurado sin secretos.
- [ ] 10.9 Ejecutar pruebas E2E en resoluciones móvil y escritorio.

**Puerta final**

- Todos los requisitos RF tienen al menos una prueba.
- La instalación limpia está documentada.
- El flujo completo funciona desde computadora y celular.
- No quedan secretos en el repositorio.
