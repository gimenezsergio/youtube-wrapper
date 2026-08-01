# Estrategia y casos de prueba — YouTube Curator

## 1. Capas

- **Unitarias**: dominio, normalización, puntuación y filtros.
- **Integración**: servicios + SQLite real temporal.
- **Contrato**: respuestas Flask contra `openapi.yaml`.
- **Adaptadores**: YouTube y clasificador con HTTP simulado.
- **E2E**: navegador, frontend y backend.
- **No funcionales**: rendimiento, accesibilidad y seguridad básica.

Las pruebas nunca deben consumir cuota real de YouTube.

## 2. Matriz de trazabilidad

| Requisito | Casos principales |
|---|---|
| RF-01 | AUTH-01..05 |
| RF-02 | SUB-01..06 |
| RF-03 | CAT-01..06 |
| RF-04 | CLASS-M-01..05 |
| RF-05 | CLASS-A-01..11 |
| RF-06 | VID-01..07 |
| RF-07 | REF-01..09 |
| RF-08 | VIEW-01..05 |
| RF-09 | FILTER-01..07 |
| RF-10 | WATCH-01..05 |
| RF-11 | DISC-01..26 |
| RF-12 | FEED-01..10 |
| RF-13 | PWA-01..05 |
| RF-14 | OPS-01..05 |

## 3. Autenticación

### AUTH-01 — Ruta protegida

**Dado** un visitante sin sesión  
**Cuando** solicita `/api/v1/categories`  
**Entonces** recibe `401`.

### AUTH-02 — Propietario válido

Simular callback válido del correo configurado y verificar sesión rotada.

### AUTH-03 — Usuario no permitido

Simular callback válido de otro correo y verificar `403` sin persistir tokens.

### AUTH-04 — State inválido

Debe rechazar callback y no crear sesión.

### AUTH-05 — CSRF

Una mutación autenticada sin token CSRF debe fallar.

## 4. Suscripciones

### SUB-01 — Paginación completa

Tres páginas simuladas deben producir la unión exacta sin omisiones.

### SUB-02 — Idempotencia

Ejecutar dos veces la misma importación y comparar estado completo.

### SUB-03 — Metadatos actualizados

Cambiar título remoto y verificar actualización sin perder categorías.

### SUB-04 — Desuscripción

Eliminar un canal de la respuesta remota y verificar `is_subscribed=false`.

### SUB-05 — Fallo en página intermedia

Verificar que no se consolida una importación incompleta como exitosa.

### SUB-06 — Lotes

Más identificadores que el máximo del gateway deben dividirse correctamente.

## 5. Categorías

### CAT-01 — Crear

Nombre válido crea categoría con posición.

### CAT-02 — Nombre duplicado

`Fotografía` y `fotografía` deben entrar en conflicto.

### CAT-03 — Renombrar

Conserva relaciones con canales y palabras clave.

### CAT-04 — Eliminar

Elimina relaciones, no canales ni videos.

### CAT-05 — Reordenar

Una permutación válida persiste; IDs repetidos o faltantes fallan.

### CAT-06 — Palabras clave

Admite positivas y negativas; normaliza espacios y rechaza vacías.

## 6. Clasificación

### CLASS-M-01 — Varias categorías

Asignar un canal a dos categorías y recuperar ambas.

### CLASS-M-02 — Operación en lote

Asignar varios canales a varias categorías de forma atómica.

### CLASS-M-03 — Idempotencia

Repetir una asignación no crea filas duplicadas.

### CLASS-M-04 — Exclusión

Una exclusión manual impide sugerencia futura equivalente.

### CLASS-M-05 — Remoción selectiva

Quitar una categoría conserva las restantes.

### CLASS-A-01 — Sugerencia múltiple

Un canal mixto puede generar más de una sugerencia.

### CLASS-A-02 — Confianza válida

Valores fuera de 0..1 son rechazados o normalizados según contrato interno.

### CLASS-A-03 — Explicación

Toda sugerencia persistida contiene explicación no vacía.

### CLASS-A-04 — Aceptar

Crea asignación y decisión `include`.

### CLASS-A-05 — Rechazar

Crea decisión `exclude` y no asigna.

### CLASS-A-06 — Corregir

Acepta una categoría diferente y conserva auditoría de la original.

### CLASS-A-07 — Fallback

Fallo del adaptador semántico ejecuta clasificador por palabras clave.

### CLASS-A-08 — Respuesta malformada

No persiste datos parciales y registra error seguro.

### CLASS-A-09 — Autoaplicación

Una confianza igual o superior al umbral crea asignación `automatic` y continúa visible para revisión.

### CLASS-A-10 — Banda de sugerencia

Una confianza entre ambos umbrales crea sugerencia sin asignación.

### CLASS-A-11 — Debajo del umbral

No crea relación ni sugerencia persistente.

## 7. Videos y vistas

### VID-01 — Upsert

Mismo ID actualiza metadatos sin duplicar.

### VID-02 — Incremental

Una playlist con videos conocidos detiene consultas según checkpoint.

### VID-03 — Duración

Convierte duración ISO 8601 a segundos.

### VID-04 — Video eliminado

Una ausencia remota no borra el registro local.

### VID-05 — Orden

Videos con fechas distintas aparecen descendentes.

### VID-06 — Empate

Fechas iguales mantienen paginación estable mediante ID.

### VID-07 — Lotes

Los detalles se solicitan respetando máximo del gateway.

### VIEW-01 — Feed combinado

Incluye canales pertenecientes a la categoría y excluye los demás.

### VIEW-02 — Por canal

Agrupa correctamente sin perder videos.

### VIEW-03 — Equivalencia

Ambas vistas contienen el mismo conjunto bajo filtros equivalentes.

### VIEW-04 — Cambio de vista

Conserva query string de filtros.

### VIEW-05 — Responsive

Flujo principal usable en 360×800 y 1440×900.

## 8. Filtros y visto

### FILTER-01 — Categoría

Solo devuelve videos de canales asignados o descubrimientos de esa categoría.

### FILTER-02 — Canales

Uno y varios IDs funcionan.

### FILTER-03 — Vistos

Estados `all`, `true` y `false`.

### FILTER-04 — Procedencia

Estados `all`, `followed` y `discovery`.

### FILTER-05 — Intersección

Combinar categoría + canal + no visto + seguido devuelve solo coincidencias completas.

### FILTER-06 — Parámetro inválido

Devuelve `400` con error estructurado.

### FILTER-07 — Resultado vacío

La respuesta contiene cero elementos y conserva filtros aplicados.

### WATCH-01 — Apertura

Marca `opened_at` y `watched=true`.

### WATCH-02 — URL

Devuelve URL canónica HTTPS de YouTube para el ID.

### WATCH-03 — Reapertura

No duplica estado y actualiza fecha según política.

### WATCH-04 — Marcar no visto

Deja `watched=false` sin borrar auditoría de apertura.

### WATCH-05 — Fallo de persistencia

No devuelve una apertura exitosa si no pudo registrar el evento.

## 9. Actualización

### REF-01 — Inicio manual

No existe ejecución hasta invocar explícitamente `POST`.

### REF-02 — Exclusión mutua

Segundo inicio durante ejecución devuelve `409`.

### REF-03 — Progreso

Cada etapa actualiza estado observable.

### REF-04 — Éxito

Finaliza con contadores coherentes.

### REF-05 — Fallo temprano

Error de autorización produce `failed`.

### REF-06 — Fallo parcial

Error en descubrimiento después de videos produce `partial`.

### REF-07 — Reintento

Una nueva ejecución parte del estado confirmado sin duplicados.

### REF-08 — Persistencia

Reiniciar Flask después de crear una ejecución no elimina el trabajo pendiente.

### REF-09 — Lease vencida

El worker recupera una ejecución abandonada sin que dos workers la procesen simultáneamente.

## 10. Descubrimiento y feedback

### DISC-01 — Consultas

Construye una consulta directa y una expandida combinando palabras clave, señales de canales semilla y temas aprobados.

### DISC-02 — Sin palabras clave

Usa señales de canales o registra que no existen señales suficientes.

### DISC-03 — Duplicado de suscripción

Video ya importado como `followed` no se crea como descubrimiento.

### DISC-04 — Duplicado candidato

Un resultado repetido se consolida.

### DISC-05 — Bloqueo

Canales bloqueados reciben exclusión absoluta.

### DISC-06 — Puntuación

Casos de tabla validan cada componente, penalizaciones, determinismo y límites 0..100.

### DISC-07 — Razones

Todo candidato visible tiene al menos una razón.

### DISC-08 — Separación

La respuesta permite distinguir inequívocamente `origin=discovery`.

### DISC-09 — Presupuesto global

El generador deja de buscar al alcanzar el máximo de la actualización.

### DISC-10 — Presupuesto por categoría

Una categoría no consume el presupuesto reservado para todas las demás.

### DISC-11 — Varias categorías

El mismo video conserva puntuación, razones y estado independientes en dos categorías sin duplicarse en `videos`.

### DISC-12 — Precedencia de origen

Al aceptar su canal, el video se devuelve como `followed` sin duplicar tarjeta y conserva sus contextos de descubrimiento para auditoría.

### DISC-13 — Señal de visualización

Un video visto recientemente dentro de una categoría aporta términos y similitud a esa categoría, sin afectar categorías no relacionadas.

### DISC-14 — Tema manual aprobado

Crear manualmente un tema adyacente lo guarda como `approved` y permite utilizarlo en la siguiente actualización.

### DISC-15 — Propuesta pendiente

Un tema automático `pending` aparece para revisión, pero no forma parte de consultas, bandas ni puntuaciones.

### DISC-16 — Tema rechazado

Un tema `rejected` no participa en descubrimiento y no vuelve a proponerse automáticamente con el mismo término normalizado.

### DISC-17 — Aprobación y reversión

Cambiar un tema de `pending` a `approved` habilita su uso; cambiarlo luego a `rejected` lo excluye de actualizaciones posteriores sin borrar auditoría.

### DISC-18 — Clasificación de bandas

Una tabla de candidatos produce `related`, `adjacent` y `exploratory` de acuerdo con las señales y mínimos configurados. La banda se calcula por relación video-categoría.

### DISC-19 — Mezcla completa

Con candidatos suficientes, el lote de una categoría contiene exactamente 8 elementos: 5 `related`, 2 `adjacent` y 1 `exploratory`.

### DISC-20 — Fallback entre bandas

Casos de tabla validan la matriz completa: `related` solo se cubre con `adjacent`; `adjacent` solo con `related`; `exploratory` con `adjacent` y luego `related`. Nunca se incluyen exploratorios adicionales para cubrir las bandas más cercanas ni candidatos por debajo del mínimo.

### DISC-21 — Lote parcial seguro

Con solo 6 candidatos válidos, devuelve 6 y explica el faltante; no relaja bloqueos, términos negativos ni relevancia mínima.

### DISC-22 — Diversidad de canal

Aunque un canal tenga las puntuaciones más altas, no selecciona más de 2 videos suyos en el lote de la misma categoría.

### DISC-23 — Duplicados temáticos

Videos con títulos casi idénticos reciben penalización de diversidad y no desplazan innecesariamente a candidatos de otros temas o canales.

### DISC-24 — Reparto justo de búsquedas

Con presupuesto limitado, el orden de llamadas concede una primera búsqueda a cada categoría elegible antes de conceder la segunda a cualquiera.

### DISC-25 — Consulta del lote

`GET /discoveries` devuelve solo candidatos `active` del último lote aplicable, conserva `selectionRank`, permite filtrar por categoría y banda, incluye el resumen y faltante por categoría y no devuelve ocultos, aceptados ni expirados.

### DISC-26 — Lote finito en interfaz

La vista muestra el lote persistido y desplazarse hasta el final no crea búsquedas ni otro lote. Solo una actualización manual puede generar recomendaciones nuevas.

### FEED-01 — Más similar

Incrementa señal futura en la categoría correcta.

### FEED-02 — Menos similar

Reduce señal futura sin bloquear globalmente el canal.

### FEED-03 — Ocultar video

Desaparece de resultados normales y puede restaurarse.

### FEED-04 — Bloquear canal

Oculta todos sus candidatos y evita reingreso.

### FEED-05 — Aceptar canal

Activa seguimiento local sin invocar una suscripción de YouTube.

Asigna el canal a la categoría con fuente `accepted_discovery`, promueve sus videos conocidos a `followed` y la actualización posterior consulta su playlist de publicaciones.

### FEED-06 — Revertir bloqueo

Permite al canal ser candidato en actualizaciones futuras.

### FEED-07 — Categorías aisladas

Feedback en Fotografía no altera indebidamente IA.

### FEED-08 — Intensidad de señales

Una acción explícita “Me interesa” pesa más que una apertura o marcado como visto aislado para futuras puntuaciones de la categoría.

### FEED-09 — Umbral de sugerencia de canal

Dos señales positivas sobre videos distintos del mismo canal y categoría habilitan la sugerencia de seguimiento; una sola señal no la habilita con la configuración predeterminada.

### FEED-10 — Sin seguimiento implícito

Al alcanzar el umbral solo aparece una sugerencia. `is_locally_followed` y la relación `accepted_discovery` no cambian hasta confirmar explícitamente.

## 11. PWA y operación

### PWA-01

Manifest válido e instalable.

### PWA-02

Service worker cachea assets versionados.

### PWA-03

API usa network-first y comunica desconexión.

### PWA-04

No permite actualización o feedback offline.

### PWA-05

Todos los controles principales funcionan con teclado y tacto.

### OPS-01

Exportación JSON contiene categorías, relaciones, palabras, estados y bloqueos.

### OPS-02

Exportación nunca contiene tokens ni secretos.

### OPS-03

Logs no contienen access token, refresh token o secreto OAuth.

### OPS-04

Backup y restore reproducen conteos e integridad referencial.

### OPS-05

Consulta de feed con 20.000 videos cumple presupuesto en hardware objetivo.

## 12. Datos de prueba mínimos

- 12 categorías.
- 500 canales.
- 20.000 videos de suscripciones y seguimientos locales.
- 2.000 candidatos de descubrimiento.
- Canales en cero, una y varias categorías.
- Títulos multilingües y caracteres Unicode.
- Fechas iguales, metadatos faltantes y videos eliminados.
- Respuestas externas paginadas, limitadas y con errores transitorios.
