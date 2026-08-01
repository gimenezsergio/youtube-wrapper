# Requisitos — YouTube Curator

## 1. Propósito

YouTube Curator es una aplicación web personal que reemplaza la portada de YouTube como punto de entrada. Permite importar suscripciones, organizar canales en categorías propias, consultar videos recientes, filtrar el contenido y descubrir videos o canales relacionados mediante reglas controladas por el usuario.

La aplicación selecciona y organiza contenido. La reproducción ocurre en YouTube.

## 2. Glosario

- **Canal suscripto**: canal al que el usuario está suscripto en YouTube.
- **Canal seguido localmente**: canal aceptado desde descubrimiento, sin crear una suscripción en YouTube.
- **Origen seguido**: video de un canal suscripto o seguido localmente; se muestra bajo la etiqueta de interfaz “Mis canales”.
- **Descubrimiento**: video o canal encontrado por búsquedas configuradas, sin suscripción previa.
- **Banda de descubrimiento**: grado de proximidad temática de una recomendación: `related`, `adjacent` o `exploratory`.
- **Tema adyacente**: tema relacionado con una categoría que amplía su alcance sin reemplazar sus palabras clave principales. Puede ser manual o propuesto automáticamente, pero debe estar aprobado para generar búsquedas.
- **Lote de descubrimiento**: conjunto finito de recomendaciones seleccionadas para una categoría durante una actualización manual.
- **Categoría**: agrupación creada manualmente por el usuario.
- **Clasificación**: asignación de uno o varios canales a categorías.
- **Sugerencia de clasificación**: asignación automática pendiente de revisión.
- **Visto**: video abierto desde la aplicación o marcado manualmente.
- **Actualización**: operación iniciada explícitamente para traer suscripciones, videos y descubrimientos nuevos.

## 3. Actores y restricciones

### 3.1 Actor

Existe un único usuario propietario.

### 3.2 Restricciones

- La aplicación debe estar protegida contra acceso de terceros.
- Debe solicitar únicamente permisos de lectura de YouTube.
- El navegador no debe acceder directamente a SQLite.
- Los secretos OAuth y tokens deben permanecer en el servidor.
- La aplicación no debe afirmar que conoce el historial completo de YouTube.
- No debe reproducir videos dentro de la aplicación durante el MVP.
- Ninguna sincronización externa debe ejecutarse automáticamente.

## 4. Alcance funcional

### RF-01 — Autenticación

El sistema debe permitir iniciar sesión mediante Google OAuth 2.0 y restringir la aplicación al propietario configurado.

**Criterios de aceptación**

1. Dado un visitante no autenticado, cuando accede a una ruta protegida, entonces es dirigido al inicio de sesión.
2. Dado el propietario autenticado, cuando Google devuelve autorización válida, entonces se crea una sesión segura.
3. Dado un correo diferente del propietario, cuando completa OAuth, entonces se rechaza el acceso.
4. Debe solicitar `openid` y `email` para verificar identidad, y `youtube.readonly` como único alcance de YouTube.
5. Cerrar sesión debe invalidar la sesión local sin borrar datos.

### RF-02 — Importación de suscripciones

El sistema debe importar todas las suscripciones del usuario autenticado, recorriendo todas las páginas disponibles.

**Criterios de aceptación**

1. La importación debe crear canales inexistentes y actualizar metadatos de canales existentes.
2. Debe conservar categorías y decisiones locales al actualizar un canal.
3. Un canal que ya no figure entre las suscripciones debe marcarse como no suscripto, no eliminarse.
4. El resultado debe informar canales creados, actualizados y desuscriptos.
5. Un fallo parcial no debe dejar una transacción inconsistente.

### RF-03 — Gestión de categorías

El usuario debe poder crear, renombrar, ordenar y eliminar categorías.

**Criterios de aceptación**

1. El nombre es obligatorio y único sin distinguir mayúsculas.
2. Una categoría puede tener descripción y palabras clave.
3. Un canal puede pertenecer a cero, una o varias categorías.
4. Eliminar una categoría no debe eliminar canales ni videos.
5. El usuario debe poder reordenar categorías y conservar el orden.

### RF-04 — Clasificación manual

El usuario debe poder asignar y quitar categorías a uno o varios canales.

**Criterios de aceptación**

1. La asignación múltiple debe aceptar varios canales y varias categorías.
2. Repetir una asignación existente debe ser idempotente.
3. Quitar una categoría no debe afectar otras asignaciones del canal.
4. La interfaz debe mostrar canales sin clasificar.

### RF-05 — Clasificación automática revisable

El sistema debe analizar cada canal y producir sugerencias para las categorías creadas por el usuario.

**Criterios de aceptación**

1. La clasificación debe considerar nombre, descripción y títulos/descripciones de videos recientes.
2. Una sugerencia debe incluir categoría, confianza entre 0 y 1 y explicación breve.
3. El sistema puede sugerir varias categorías para un canal.
4. La política predeterminada debe ser: confianza `>= 0,85`, asignación automática y revisión posterior; confianza entre `0,55` y `0,84`, sugerencia pendiente; confianza `< 0,55`, sin sugerencia.
5. Los umbrales deben ser configurables sin modificar código.
6. Toda asignación automática debe permanecer identificada como tal y aparecer en la bandeja de revisión.
7. El usuario debe poder aceptar, rechazar o corregir sugerencias y asignaciones automáticas individualmente o en lote.
8. Una decisión manual debe prevalecer sobre futuras ejecuciones automáticas.
9. Si el clasificador falla, la clasificación manual debe seguir funcionando.

### RF-06 — Obtención de videos

El sistema debe consultar videos recientes de los canales suscriptos y de los canales seguidos localmente durante una actualización manual.

**Criterios de aceptación**

1. Debe evitar búsquedas costosas por canal cuando pueda usar la playlist de publicaciones del canal.
2. Debe insertar videos nuevos y actualizar metadatos de los conocidos.
3. Debe registrar título, descripción, fecha, miniaturas, duración, canal y tipo de contenido disponible.
4. Los videos deben conservarse aunque posteriormente dejen de aparecer en la respuesta remota.
5. Debe evitar duplicados por identificador de YouTube.

### RF-07 — Actualización manual

El sistema debe ofrecer un botón para actualizar el contenido y no debe actualizarlo en segundo plano.

**Criterios de aceptación**

1. Una actualización completa debe incluir suscripciones, canales, videos de canales suscriptos o seguidos localmente, clasificación y descubrimiento.
2. Solo puede existir una actualización activa.
3. Debe mostrarse progreso por etapa y un resumen final.
4. Debe registrarse inicio, finalización, estado, contadores y errores.
5. Un fallo en descubrimiento no debe descartar los videos de suscripciones ya importados.
6. La interfaz debe mostrar la fecha de la última actualización exitosa.
7. Una actualización aceptada debe persistirse antes de ejecutarse y poder recuperarse después de reiniciar el proceso web.
8. El sistema no debe iniciar actualizaciones programadas ni implícitas.

### RF-08 — Navegación por categoría

El usuario debe poder seleccionar una categoría y alternar entre dos vistas.

**Criterios de aceptación**

1. La vista **Feed** mezcla videos de todos los canales de la categoría.
2. La vista **Por canal** agrupa los videos por canal.
3. Ambas vistas deben ordenar los videos desde el más reciente.
4. Cambiar de vista debe conservar los filtros activos.
5. El diseño debe funcionar en computadora y celular.

### RF-09 — Filtros

El usuario debe poder combinar los siguientes filtros:

- categoría;
- uno o varios canales;
- visto, no visto o todos;
- mis canales (`followed`), descubrimiento o todos.

**Criterios de aceptación**

1. Los filtros deben combinarse mediante intersección.
2. La URL debe representar categoría, vista y filtros para soportar recarga y navegación.
3. Debe existir una acción para limpiar filtros secundarios.
4. Un resultado vacío debe explicar qué filtros están activos.

### RF-10 — Apertura y estado visto

El sistema debe abrir videos en YouTube y registrar su apertura.

**Criterios de aceptación**

1. Al pulsar un video, debe registrarse la apertura antes de abrir YouTube.
2. YouTube debe abrirse en una pestaña nueva.
3. El usuario debe poder marcar un video como visto o no visto manualmente.
4. La interfaz debe diferenciar visualmente ambos estados.
5. La apertura no debe interpretarse como porcentaje reproducido ni finalización.

### RF-11 — Descubrimiento por categoría

El sistema debe generar recomendaciones propias y explicables combinando palabras clave, canales semilla, temas adyacentes aprobados y señales locales del usuario. No debe presentarlas como recomendaciones propietarias ni como la portada personal de YouTube.

**Criterios de aceptación**

1. Solo debe ejecutarse al solicitar una actualización.
2. Debe utilizar palabras clave configurables por categoría.
3. Debe utilizar metadatos de los canales confirmados como señales temáticas.
4. Debe admitir temas adyacentes manuales y propuestas automáticas con estados `pending`, `approved` y `rejected`.
5. Solo pueden formar parte de consultas externas señales trazables de la categoría: palabras clave, temas adyacentes aprobados, términos de canales semilla confirmados y señales locales dentro de su ventana. Una propuesta pendiente o rechazada no debe influir en consultas, candidatos ni puntuaciones.
6. Cada candidato debe pertenecer, en el contexto de una categoría, a una banda: `related`, `adjacent` o `exploratory`.
7. La mezcla predeterminada por categoría debe ser un lote finito de 8 recomendaciones: 5 `related`, 2 `adjacent` y 1 `exploratory`.
8. Si una banda no tiene suficientes candidatos válidos, el sistema debe aplicar la matriz de fallback definida en el diseño; nunca debe usar candidatos exploratorios adicionales para cubrir faltantes de las bandas más cercanas y debe devolver menos de 8 antes que incluir un candidato por debajo del mínimo de relevancia temática.
9. Debe excluir videos de canales suscriptos o seguidos localmente del conjunto de descubrimiento y evitar duplicados por video.
10. Debe excluir canales bloqueados, videos ocultos y candidatos incompatibles con palabras clave negativas.
11. Cada candidato debe guardar puntuación, banda, posición en el lote y entre 1 y 3 razones comprensibles.
12. La selección final debe favorecer diversidad y limitar de forma predeterminada a 2 los videos del mismo canal por categoría y actualización.
13. Los descubrimientos deben aparecer en una sección separada del feed cronológico; no debe existir carga infinita automática.
14. Debe existir un presupuesto configurable de búsquedas por actualización y por categoría, con valores iniciales conservadores de 10 y 2 respectivamente.
15. El presupuesto debe repartirse de forma justa: todas las categorías elegibles reciben una primera oportunidad antes de que una categoría consuma una segunda búsqueda.
16. Si se agota el presupuesto o la cuota externa, debe conservar resultados previos y mostrar un estado accionable.
17. Un mismo video puede ser candidato en varias categorías con banda, puntuación, razones y estado independientes.
18. Debe considerar como señal los videos abiertos o marcados como vistos dentro de la categoría, con una ventana temporal configurable.
19. La apertura o el estado visto son señales positivas débiles; el feedback explícito debe tener mayor peso.
20. La popularidad global o el número de visualizaciones no deben ser señales obligatorias ni dominantes en el MVP.
21. El sistema debe poder funcionar con coincidencia de términos sin depender de un modelo semántico externo.

### RF-12 — Feedback de descubrimiento

El usuario debe poder controlar los candidatos.

**Criterios de aceptación**

1. Acciones mínimas: aceptar canal, ocultar video, bloquear canal, más contenido similar y menos contenido similar.
2. Aceptar un canal debe incorporarlo como canal seguido localmente, asignarlo a la categoría desde la que fue aceptado y no suscribirlo automáticamente en YouTube.
3. Bloquear un canal debe retirar todos sus candidatos activos.
4. Las acciones deben afectar futuras puntuaciones.
5. Debe poder revertirse una ocultación o bloqueo desde configuración.
6. Sus videos conocidos deben pasar al origen `followed` y sus videos nuevos deben obtenerse en futuras actualizaciones.
7. En la interfaz, `more_like_this` y `less_like_this` deben presentarse como “Me interesa” y “No me interesa”.
8. Salvo el bloqueo de canal, el feedback debe afectar primero a la categoría desde la cual se emitió y no contaminar indebidamente otras categorías.
9. La aplicación puede sugerir seguir un canal cuando existan señales positivas sobre al menos 2 videos distintos de ese canal dentro de la misma categoría y ventana temporal configurable.
10. Una sugerencia de canal nunca debe activar seguimiento local sin confirmación explícita.
11. El usuario debe poder abrir o aceptar un canal desde cualquier recomendación sin esperar a que se alcance el umbral de sugerencia.

### RF-13 — PWA y responsive

La aplicación debe poder instalarse como PWA y adaptarse a computadora y celular.

**Criterios de aceptación**

1. Debe incluir manifest, iconos y service worker.
2. El shell visual puede almacenarse en caché.
3. Las respuestas de contenido no deben presentarse como actuales si provienen de caché.
4. Los controles táctiles deben tener tamaño adecuado.
5. Las funciones críticas deben ser utilizables sin hover.

### RF-14 — Configuración y diagnóstico

El sistema debe mostrar configuración e información operativa mínima.

**Criterios de aceptación**

1. Debe mostrar identidad conectada, última actualización y consumo/errores conocidos de API.
2. Debe permitir reautorizar Google.
3. Debe permitir exportar categorías, asignaciones, palabras clave, temas adyacentes, estados, feedback y bloqueos en JSON.
4. Los logs no deben contener tokens, secretos ni respuestas completas sensibles.

## 5. Requisitos no funcionales

### RNF-01 — Seguridad

- Cookies de sesión `HttpOnly`, `Secure` y `SameSite=Lax`.
- Protección CSRF en mutaciones.
- Validación estricta de parámetros.
- Content Security Policy compatible con las miniaturas requeridas.
- Secretos mediante variables de entorno.

### RNF-02 — Rendimiento

- La primera página del feed debe responder en menos de 500 ms con 500 canales y 20.000 videos en el servidor objetivo, excluyendo llamadas externas.
- La interfaz debe paginar o usar carga incremental.
- Deben existir índices para fecha, canal, origen y estado visto.

### RNF-03 — Confiabilidad

- Las migraciones deben versionar el esquema.
- Cada etapa de actualización debe ser reiniciable e idempotente.
- Las actualizaciones deben ser reclamadas por un único worker mediante una operación atómica.
- Una ejecución abandonada debe poder detectarse mediante heartbeat/lease y recuperarse de forma segura.
- SQLite debe operar en modo WAL.
- Debe existir respaldo documentado de la base y variables necesarias.

### RNF-04 — Mantenibilidad

- Separar rutas HTTP, servicios, repositorios y adaptadores externos.
- La lógica de clasificación y puntuación no debe residir en las vistas Flask.
- Las llamadas a YouTube y al clasificador deben poder simularse en pruebas.

### RNF-05 — Accesibilidad

- Navegación por teclado.
- Foco visible.
- Etiquetas accesibles.
- Contraste WCAG AA en elementos esenciales.
- Estados no comunicados exclusivamente mediante color.

## 6. Fuera de alcance

- Extensión de navegador.
- Historial completo de YouTube. La API oficial no se tratará como fuente de ese dato.
- Sincronización automática periódica.
- Reproducción embebida.
- Comentarios, publicación o modificación del canal.
- Suscribirse o desuscribirse en YouTube desde la aplicación.
- Recomendaciones propietarias de YouTube.
- Importación del feed de inicio, del historial de reproducción o de la lista “Ver más tarde” de YouTube.
- Uso del antiguo mecanismo `relatedToVideoId`, retirado de la YouTube Data API.
- Sistema multiusuario.
- Aplicaciones móviles nativas.

## 7. Definición de éxito del MVP

El MVP se considera validado cuando el propietario puede:

1. conectarse e importar sus suscripciones;
2. crear categorías y revisar clasificaciones automáticas;
3. actualizar manualmente videos;
4. navegar una categoría en ambas vistas;
5. filtrar por canal, visto y procedencia;
6. abrir un video y verlo registrado;
7. obtener descubrimientos explicados y separados;
8. usar el flujo completo desde computadora y celular.
