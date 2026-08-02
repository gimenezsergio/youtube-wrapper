-- Segunda migración: Tabla para almacenar credenciales del propietario cifradas

CREATE TABLE IF NOT EXISTS credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at TEXT NOT NULL, -- ISO 8601 UTC
    updated_at TEXT NOT NULL
);
