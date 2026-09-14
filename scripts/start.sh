#!/usr/bin/env bash
# Script de inicio rápido para YouTube Curator

# Determinar el directorio del proyecto
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

# Cargar entorno virtual si existe
if [ -d "$PROJECT_DIR/venv" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
fi

# Comprobar si el servidor ya está escuchando en el puerto 5000
if lsof -Pi :5000 -sTCP:LISTEN -t >/dev/null ; then
    echo "El servidor de YouTube Curator ya se encuentra en ejecución."
else
    echo "Iniciando servidor web (Flask)..."
    flask --app app run --port 5000 --debug >/tmp/yt_curator_flask.log 2>&1 &
    FLASK_PID=$!
    
    echo "Iniciando worker en segundo plano..."
    PYTHONPATH=. python worker.py >/tmp/yt_curator_worker.log 2>&1 &
    WORKER_PID=$!
    
    # Esperar 2 segundos a que inicialicen los servicios
    sleep 2
fi

# Abrir el navegador en http://localhost:5000
echo "Abriendo YouTube Curator en el navegador..."
if command -v xdg-open > /dev/null; then
    xdg-open "http://localhost:5000"
elif command -v gio > /dev/null; then
    gio open "http://localhost:5000"
else
    echo "Abre manualmente la URL: http://localhost:5000"
fi
