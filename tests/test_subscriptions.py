from datetime import datetime, timedelta, timezone

import pytest

from app.auth.encryption import encrypt_token
from app.db import get_db_connection
from app.services.subscription_service import SubscriptionService


from tests.fakes.youtube_gateway import FakeYouTubeGateway

@pytest.fixture
def setup_mock_credentials(app):
    """Inserta credenciales mock en la base de datos de pruebas."""
    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(hours=1)).isoformat()

        enc_access = encrypt_token("mock-access-token")
        enc_refresh = encrypt_token("mock-refresh-token")

        conn.execute("""
            INSERT INTO credentials (access_token, refresh_token, expires_at, updated_at)
            VALUES (?, ?, ?, ?)
        """, (enc_access, enc_refresh, expires_at, now.isoformat()))
        conn.commit()
        conn.close()

def test_sync_01_first_import(setup_mock_credentials, app):
    """Sincroniza por primera vez importando todos los canales."""
    fake_gateway = FakeYouTubeGateway()
    service = SubscriptionService(gateway=fake_gateway)

    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])

        result = service.sync_subscriptions(conn)
        assert result["created"] == 3
        assert result["updated"] == 0
        assert result["unsubscribed"] == 0

        # Verificar canales en base de datos
        cursor = conn.execute("SELECT youtube_channel_id, title, is_subscribed, uploads_playlist_id FROM channels")
        rows = cursor.fetchall()
        assert len(rows) == 3

        channel_ids = [r["youtube_channel_id"] for r in rows]
        assert "UC_A" in channel_ids
        assert "UC_B" in channel_ids
        assert "UC_C" in channel_ids

        # Detalle de uploads playlist
        chan_a = next(r for r in rows if r["youtube_channel_id"] == "UC_A")
        assert chan_a["uploads_playlist_id"] == "UU_A"
        assert chan_a["is_subscribed"] == 1

        conn.close()

def test_sync_02_idempotency(setup_mock_credentials, app):
    """Sincronizar dos veces seguidas no duplica registros y solo actualiza."""
    fake_gateway = FakeYouTubeGateway()
    service = SubscriptionService(gateway=fake_gateway)

    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])

        # Primera sincronización
        service.sync_subscriptions(conn)

        # Segunda sincronización idéntica
        result = service.sync_subscriptions(conn)
        assert result["created"] == 0
        assert result["updated"] == 3
        assert result["unsubscribed"] == 0

        cursor = conn.execute("SELECT COUNT(*) as count FROM channels")
        assert cursor.fetchone()["count"] == 3

        conn.close()

def test_sync_03_unsubscriptions_handling(setup_mock_credentials, app):
    """Los canales que ya no están en las suscripciones remotas se marcan como desuscritos (is_subscribed = 0)."""
    fake_gateway = FakeYouTubeGateway()
    service = SubscriptionService(gateway=fake_gateway)

    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])

        # 1. Primera importación: UC_A, UC_B, UC_C
        service.sync_subscriptions(conn)

        # 2. Modificar respuestas del fake gateway para simular desuscripción de UC_B y UC_C
        # y una nueva suscripción de UC_D
        fake_gateway.subscriptions_responses = [
            [
                {"youtube_channel_id": "UC_A", "title": "Canal A"},
                {"youtube_channel_id": "UC_D", "title": "Canal D"}
            ]
        ]

        # 3. Sincronizar de nuevo
        result = service.sync_subscriptions(conn)
        assert result["created"] == 1  # UC_D
        assert result["updated"] == 1  # UC_A
        assert result["unsubscribed"] == 2  # UC_B y UC_C desuscritos

        # 4. Verificar estados en la DB
        rows = conn.execute("SELECT youtube_channel_id, is_subscribed FROM channels").fetchall()
        assert len(rows) == 4

        chan_a = next(r for r in rows if r["youtube_channel_id"] == "UC_A")
        assert chan_a["is_subscribed"] == 1

        chan_b = next(r for r in rows if r["youtube_channel_id"] == "UC_B")
        assert chan_b["is_subscribed"] == 0  # Desuscrito

        chan_c = next(r for r in rows if r["youtube_channel_id"] == "UC_C")
        assert chan_c["is_subscribed"] == 0  # Desuscrito

        chan_d = next(r for r in rows if r["youtube_channel_id"] == "UC_D")
        assert chan_d["is_subscribed"] == 1  # Nuevo suscrito

        conn.close()

def test_sync_04_preserve_local_categories(setup_mock_credentials, app):
    """Categorías locales y relaciones sobreviven a una reimportación completa."""
    fake_gateway = FakeYouTubeGateway()
    service = SubscriptionService(gateway=fake_gateway)

    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])

        # 1. Crear categoría
        conn.execute("""
            INSERT INTO categories (name, normalized_name, position, created_at, updated_at)
            VALUES ('Tech', 'tech', 1, 'now', 'now')
        """)
        cat_id = conn.execute("SELECT id FROM categories LIMIT 1").fetchone()["id"]
        conn.commit()

        # 2. Sincronizar
        service.sync_subscriptions(conn)
        chan_id = conn.execute("SELECT id FROM channels WHERE youtube_channel_id = 'UC_A'").fetchone()["id"]

        # Asignar canal A a la categoría 'Tech'
        conn.execute("""
            INSERT INTO channel_categories (channel_id, category_id, source, created_at)
            VALUES (?, ?, 'manual', 'now')
        """, (chan_id, cat_id))
        conn.commit()

        # 3. Volver a sincronizar
        service.sync_subscriptions(conn)

        # 4. Verificar que la categoría local de UC_A se mantiene intacta
        cursor = conn.execute("""
            SELECT COUNT(*) as count
            FROM channel_categories
            WHERE channel_id = ? AND category_id = ?
        """, (chan_id, cat_id))
        assert cursor.fetchone()["count"] == 1

        conn.close()
