# 📺 YouTube Curator

**YouTube Curator** es una aplicación web personal diseñada para recuperar el control de tu consumo de video. El algoritmo oficial de YouTube prioriza la retención de los usuarios a toda costa, lo que satura tu pantalla de inicio y reduce tu libertad de elección.

---

## 🎯 El Problema: La Pérdida de Control en YouTube

Cuando utilizas la interfaz oficial de YouTube, te enfrentas a un feed caótico diseñado para retener tu atención de manera constante mediante:
*   **Recomendaciones invasivas e irrelevantes**: El feed se inunda de videos sugeridos sobre temáticas que no guardan relación con tus intereses reales del momento.
*   **Canales desconocidos**: Aparecen constantemente videos y creadores de contenido de canales que no sabes cuáles son, desplazando los videos de las personas a las que decidiste seguir.
*   **Contenido fuera de contexto**: Los videos de diferentes temáticas (ej. programación, filosofía, entretenimiento) se mezclan en una única lista infinita, impidiendo que puedas concentrarte en un área de estudio o entretenimiento específica.
*   **Shorts y videos cortos**: Formatos cortos diseñados para un consumo rápido e impulsivo saturan tu feed, alejándote de videos formativos o de mayor duración (excluyendo aquellos menores a 3 minutos).

---

## 💡 La Solución: Un Entorno Controlado y Guiado por tus Decisiones

**YouTube Curator** soluciona esto aislando tu biblioteca de la plataforma oficial y ofreciéndote un panel de control absoluto sobre tu feed:
1.  **Feeds Puros y Cronológicos**: Accede a listas de videos ordenadas exclusivamente por fecha de publicación de los canales a los que has decidido seguir explícitamente. Sin sugerencias de la plataforma en tu página principal.
2.  **Categorías Temáticas y Palabras Clave**: Agrupa tus canales favoritos en categorías (ej. *Tecnología*, *Filosofía y Letras*, *Salud*) y define palabras clave con polaridad y peso para puntuar los videos automáticamente.
3.  **Descubrimiento bajo Demanda**: En lugar de recibir recomendaciones continuas e infinitas, tú decides cuándo buscar contenido nuevo en la sección de *Descubrimiento*. El sistema genera un lote controlado de exactamente **8 videos candidatos** por categoría, clasificados según su afinidad temática, divididos en tres bandas:
    -   *Relacionados*: Canales de tu biblioteca con videos nuevos que aún no has seguido.
    -   *Temas cercanos (Adyacentes)*: Videos buscados a partir de temas de exploración sugeridos por la propia aplicación o introducidos por ti.
    -   *Para explorar*: Coincidencias generales con tus palabras clave positivas.
4.  **Feedback Reversible y Exclusión Mutua**: Controla activamente el feed. Puedes ocultar videos, bloquear canales permanentemente o indicar si quieres "más como esto" o "menos como esto", todo de manera transparente y reversible desde el menú de Ajustes.

---

## Requisitos de Sistema

- Python 3.10+
- SQLite3

## Configuración Inicial

1. Crear y activar el entorno virtual de Python:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. Instalar las dependencias del proyecto:
   ```bash
   pip install -r requirements.txt
   ```

3. Configurar el entorno creando un archivo `.env`:
   ```bash
   cp .env.example .env
   ```
   Ajusta los valores del archivo `.env` según se detalla en la siguiente sección.

## Configuración de Google OAuth 2.0

Para permitir el inicio de sesión y la lectura de suscripciones/búsquedas, debes obtener credenciales de Google OAuth 2.0 y registrar el usuario propietario.

### 1. Obtener Credenciales de Google Cloud

1. Ve a [Google Cloud Console](https://console.cloud.google.com/).
2. Crea un nuevo proyecto (por ejemplo, `YouTube Curator`).
3. Busca **YouTube Data API v3** en la biblioteca de APIs y actívala para tu proyecto.
4. Configura la **Pantalla de consentimiento de OAuth** (OAuth Consent Screen):
   - Selecciona el tipo de usuario **Externo** (External).
   - Completa la información básica requerida.
   - En **Permisos** (Scopes), agrega únicamente el permiso de solo lectura: `https://www.googleapis.com/auth/youtube.readonly`.
   - **IMPORTANTE**: Agrega tu cuenta de correo de Google en la lista de **Usuarios de prueba** (Test Users) para poder iniciar sesión mientras la aplicación esté en modo de prueba.
5. Crea las credenciales en **Credenciales** -> **Crear credenciales** -> **ID de cliente de OAuth**:
   - Tipo de aplicación: **Aplicación web**.
   - En **Orígenes de JavaScript autorizados**, añade: `http://localhost:5000` (o tu dominio de producción).
   - En **URIs de redireccionamiento autorizados**, añade: `http://localhost:5000/api/v1/auth/callback`.
6. Guarda y copia el **ID de cliente** (Client ID) y el **Secreto de cliente** (Client Secret).

### 2. Configurar Variables de Entorno

Edita el archivo `.env` creado anteriormente y define las siguientes variables con tus datos:

```bash
OWNER_GOOGLE_EMAIL=tu-email-propietario@gmail.com
GOOGLE_CLIENT_ID=tu-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=tu-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:5000/api/v1/auth/callback
```

## Ejecución del Proyecto

### 1. Inicializar Base de Datos (Migraciones)

Las migraciones se ejecutan automáticamente en modo desarrollo o test al iniciar la aplicación Flask. Para ejecutarlas manualmente:
```bash
PYTHONPATH=. python app/migrator.py
```

### 2. Ejecutar el Servidor Web (Flask)

Para iniciar la aplicación web en modo de desarrollo local:
```bash
flask --app app run --debug
```
La aplicación estará disponible en [http://localhost:5000](http://localhost:5000).

### 3. Ejecutar el Worker en Segundo Plano

El worker de procesamiento en segundo plano se ejecuta en un proceso independiente:
```bash
PYTHONPATH=. python worker.py
```

## Pruebas de Software

Ejecuta la suite completa de pruebas unitarias y de integración utilizando `pytest`:
```bash
pytest
```

Para verificar el cumplimiento del formato y estilo de código con `ruff`:
```bash
ruff check .
```
