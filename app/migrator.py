from pathlib import Path

from app.db import get_db_connection

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

def run_migrations(db_path=None):
    """Ejecuta todas las migraciones SQL pendientes en la base de datos."""
    conn = get_db_connection(db_path)
    try:
        # Asegurar la existencia de la tabla de control de migraciones
        conn.execute("""
            CREATE TABLE IF NOT EXISTS migrations_run (
                filename TEXT PRIMARY KEY,
                run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # Listar y ordenar los archivos de migración (.sql)
        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

        for file_path in migration_files:
            filename = file_path.name

            # Verificar si ya fue ejecutado
            cursor = conn.execute("SELECT 1 FROM migrations_run WHERE filename = ?", (filename,))
            if cursor.fetchone():
                continue

            print(f"Ejecutando migración: {filename}...")

            # Leer el archivo SQL completo
            with open(file_path, "r", encoding="utf-8") as f:
                sql_script = f.read()

            # Ejecutar el script completo en una transacción
            # SQLite executescript hace commit implícito y permite múltiples statements
            conn.executescript(sql_script)

            # Registrar el éxito de la migración
            conn.execute("INSERT INTO migrations_run (filename) VALUES (?)", (filename,))
            conn.commit()

            print(f"Migración {filename} ejecutada con éxito.")

    except Exception as e:
        conn.rollback()
        print(f"Error ejecutando migración {filename if 'filename' in locals() else ''}: {e}")
        raise e
    finally:
        conn.close()

if __name__ == "__main__":
    # Cargar configuración por defecto
    from app.config import get_config
    config = get_config()
    print(f"Iniciando migraciones en base de datos: {config.DATABASE_PATH}")
    run_migrations(config.DATABASE_PATH)
