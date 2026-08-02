import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest


def test_sqlite_foreign_keys_enabled(db):
    """Verifica que las claves foráneas estén habilitadas en las conexiones."""
    cursor = db.execute("PRAGMA foreign_keys")
    result = cursor.fetchone()
    assert result[0] == 1  # 1 significa habilitado

def test_database_tables_exist(db):
    """Verifica que todas las tablas especificadas en el diseño hayan sido creadas."""
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row["name"] for row in cursor.fetchall()]

    expected_tables = [
        "channels",
        "categories",
        "category_keywords",
        "channel_categories",
        "classification_suggestions",
        "classification_decisions",
        "videos",
        "discovery_candidates",
        "video_user_state",
        "discovery_feedback",
        "refresh_runs",
        "migrations_run"
    ]

    for table in expected_tables:
        assert table in tables, f"La tabla {table} no existe en la base de datos."

def test_foreign_key_constraint_violations(db):
    """Verifica que la restricción de claves foráneas prevenga inconsistencias."""
    now = datetime.now(timezone.utc).isoformat()

    # Intentar insertar un video para un canal_id inexistente (id=999)
    # Debe fallar debido a la clave foránea en videos.channel_id -> channels.id
    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        db.execute("""
            INSERT INTO videos (
                youtube_video_id, channel_id, title, description, published_at, content_type, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ("mock-video-id", 999, "Video sin canal", "Desc", now, "video", now, now))

    assert "FOREIGN KEY constraint failed" in str(excinfo.value)


def test_database_tables_exist_phase1(db):
    """Verifica la existencia de las nuevas tablas de la Fase 1."""
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row["name"] for row in cursor.fetchall()]

    new_tables = ["category_exploration_topics", "discovery_batches"]
    for table in new_tables:
        assert table in tables, f"La tabla {table} no existe en la base de datos."


def test_exploration_topics_constraints(db):
    """Verifica las restricciones de la tabla category_exploration_topics."""
    now = datetime.now(timezone.utc).isoformat()
    # Insertar una categoría de prueba
    db.execute("""
        INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at)
        VALUES (10, 'Test Cat', 'test-cat', 1, ?, ?)
    """, (now, now))
    db.commit()

    # Insertar un tema de exploración
    db.execute("""
        INSERT INTO category_exploration_topics (
            category_id, term, normalized_term, source, status, created_at, updated_at
        ) VALUES (10, 'Python programming', 'python programming', 'manual', 'approved', ?, ?)
    """, (now, now))
    db.commit()

    # Probar restricción UNIQUE (category_id, normalized_term)
    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        db.execute("""
            INSERT INTO category_exploration_topics (
                category_id, term, normalized_term, source, status, created_at, updated_at
            ) VALUES (10, 'Python Programming Different Case', 'python programming', 'manual', 'approved', ?, ?)
        """, (now, now))
    assert "UNIQUE constraint failed" in str(excinfo.value)

    # Probar restricción CHECK para source ('manual' o 'automatic')
    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        db.execute("""
            INSERT INTO category_exploration_topics (
                category_id, term, normalized_term, source, status, created_at, updated_at
            ) VALUES (10, 'Invalid Source', 'invalid source', 'invalid_source', 'approved', ?, ?)
        """, (now, now))
    assert "CHECK constraint failed" in str(excinfo.value)

    # Probar restricción CHECK para status ('pending', 'approved', 'rejected')
    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        db.execute("""
            INSERT INTO category_exploration_topics (
                category_id, term, normalized_term, source, status, created_at, updated_at
            ) VALUES (10, 'Invalid Status', 'invalid status', 'manual', 'invalid_status', ?, ?)
        """, (now, now))
    assert "CHECK constraint failed" in str(excinfo.value)


def test_migration_0003_upgrade(tmp_path):
    """Prueba la migración 0003 sobre un esquema de base de datos anterior (0001 + 0002)."""
    db_file = tmp_path / "test_migration.db"
    db_path = str(db_file)

    # 1. Crear el esquema antiguo (0001 + 0002)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Crear la tabla de control de migraciones e insertar 0001 y 0002
    conn.execute("CREATE TABLE migrations_run (filename TEXT PRIMARY KEY, run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

    migrations_dir = Path(__file__).resolve().parent.parent / "app" / "migrations"

    with open(migrations_dir / "0001_initial_schema.sql", "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    with open(migrations_dir / "0002_credentials.sql", "r", encoding="utf-8") as f:
        conn.executescript(f.read())

    conn.execute("INSERT INTO migrations_run (filename) VALUES ('0001_initial_schema.sql')")
    conn.execute("INSERT INTO migrations_run (filename) VALUES ('0002_credentials.sql')")
    conn.commit()

    # 2. Insertar datos de prueba heredados en discovery_candidates
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at)
        VALUES (1, 'Cat A', 'cat-a', 1, ?, ?)
    """, (now, now))
    conn.execute("""
        INSERT INTO channels (
            id, youtube_channel_id, title, is_subscribed, is_locally_followed, is_blocked, created_at, updated_at
        ) VALUES (1, 'UC_A', 'Canal A', 1, 0, 0, ?, ?)
    """, (now, now))
    conn.execute("""
        INSERT INTO videos (
            id, youtube_video_id, channel_id, title, published_at, content_type, created_at, updated_at
        ) VALUES (1, 'vid_1', 1, 'Video 1', ?, 'video', ?, ?)
    """, (now, now, now))
    conn.execute("""
        INSERT INTO discovery_candidates (video_id, category_id, score, reasons_json, status, first_seen_at, last_seen_at)
        VALUES (1, 1, 85.5, '["test_reason"]', 'active', ?, ?)
    """, (now, now))
    conn.commit()
    conn.close()

    # 3. Ejecutar run_migrations para aplicar la migración 0003
    from app.migrator import run_migrations
    run_migrations(db_path)

    # 4. Verificar integridad de datos migrados
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Comprobar que existe la tabla category_exploration_topics
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='category_exploration_topics'")
    assert cursor.fetchone() is not None

    # Comprobar que los datos heredados siguen existiendo con la banda 'related' y valores por defecto
    cursor = conn.execute("SELECT * FROM discovery_candidates WHERE video_id = 1 AND category_id = 1")
    row = cursor.fetchone()
    assert row is not None
    assert row["score"] == 85.5
    assert json.loads(row["reasons_json"]) == ["test_reason"]
    assert row["status"] == "active"
    assert row["band"] == "related"
    assert row["last_refresh_run_id"] is None
    assert row["selection_rank"] is None

    # Ejecutar Pragma foreign_key_check para comprobar que no hay errores de claves foráneas
    fk_check = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert len(fk_check) == 0, f"Violación de clave foránea encontrada: {fk_check}"

    conn.close()

