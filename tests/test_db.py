import sqlite3
from datetime import datetime, timezone

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

    # Intentar insertar un video para un canal_id inexsitente (id=999)
    # Debe fallar debido a la clave foránea en videos.channel_id -> channels.id
    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        db.execute("""
            INSERT INTO videos (
                youtube_video_id, channel_id, title, description, published_at, content_type, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ("mock-video-id", 999, "Video sin canal", "Desc", now, "video", now, now))

    assert "FOREIGN KEY constraint failed" in str(excinfo.value)
