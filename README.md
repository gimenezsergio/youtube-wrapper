# YouTube Curator

YouTube Curator es una aplicación web personal diseñada para organizar y descubrir contenido de YouTube sin depender del algoritmo oficial.

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
   Ajusta los valores del archivo `.env` según sea necesario.

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
