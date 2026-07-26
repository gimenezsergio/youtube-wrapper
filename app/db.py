import sqlite3

from flask import current_app, g


def get_db_connection(db_path=None):
    """Crea y configura una nueva conexión SQLite."""
    if db_path is None:
        db_path = current_app.config["DATABASE_PATH"]

    # Si la base de datos es en memoria, usamos una conexión persistente para testing?
    # No, en pytest es mejor pasar la conexión o configurar una db temporal.
    conn = sqlite3.connect(
        db_path,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
    )

    # Configurar para que devuelva diccionarios en lugar de tuplas
    conn.row_factory = sqlite3.Row

    # Habilitar claves foráneas y WAL
    conn.execute("PRAGMA foreign_keys = ON;")

    # Nota: WAL no se puede habilitar en bases de datos ":memory:"
    if db_path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL;")

    return conn

def get_db():
    """Obtiene la conexión a la base de datos para el contexto actual de Flask."""
    if "db" not in g:
        g.db = get_db_connection()
    return g.db

def close_db(e=None):
    """Cierra la conexión a la base de datos si existe en el contexto."""
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_app(app):
    """Registra las funciones de ciclo de vida de la base de datos en la app Flask."""
    app.teardown_appcontext(close_db)
