from app.auth.encryption import encrypt_token
from app.db import get_db_connection
from app.integrations.youtube.gateway import YouTubeQuotaError
from app.services.discovery_service import DiscoveryService
from tests.fakes.youtube_gateway import FakeYouTubeGateway


class QuotaFailureGateway(FakeYouTubeGateway):
    def __init__(self):
        super().__init__()
        self.search_call_count = 0

    def search_videos(
        self, access_token, q, published_after=None, limit=25, region_code=None, relevance_language=None
    ):
        self.search_call_count += 1
        if self.search_call_count == 1:
            # First search query returns a valid candidate
            return [
                {
                    "youtube_video_id": "vid_new_1",
                    "title": "Fotografía de retrato",
                    "description": "Retrato",
                    "published_at": "2026-07-30T10:00:00Z",
                    "thumbnail_url": "thumb_1",
                    "channel_title": "Canal Foto 1",
                    "youtube_channel_id": "UC_FOTO_1"
                }
            ]
        else:
            # Second search query raises YouTubeQuotaError
            raise YouTubeQuotaError("Quota exceeded on second query")


def test_corr_pub_02_quota_after_success_retains_previous_batch(app):
    """CORR-PUB-02 — Si ocurre una falla de cuota, el lote anterior sigue active."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            # Credenciales
            conn.execute(
                "INSERT INTO credentials (id, access_token, refresh_token, expires_at, updated_at) "
                "VALUES (1, ?, ?, '2030-01-01T00:00:00Z', 'now')",
                (encrypt_token("access"), encrypt_token("refresh"))
            )
            # Categoria
            conn.execute(
                "INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) "
                "VALUES (1, 'Fotografia', 'fotografia', 1, 'now', 'now')"
            )
            # Keywords: two keywords to trigger two search queries
            conn.execute(
                "INSERT INTO category_keywords (category_id, term, polarity, weight) "
                "VALUES (1, 'fotografia', 'positive', 1.0)"
            )
            conn.execute(
                "INSERT INTO category_keywords (category_id, term, polarity, weight) "
                "VALUES (1, 'retrato', 'positive', 0.9)"
            )

            # Canal y video preexistente del lote anterior (refresh_run 1)
            conn.execute(
                "INSERT INTO refresh_runs (id, status, requested_stages_json, current_stage, "
                "requested_at, counters_json, errors_json) "
                "VALUES (1, 'succeeded', '[\"discovery\"]', 'discovery', 'now', '{}', '[]')"
            )
            conn.execute(
                "INSERT INTO channels (id, youtube_channel_id, title, created_at, updated_at) "
                "VALUES (10, 'UC_OLD', 'Canal Viejo', 'now', 'now')"
            )
            conn.execute(
                "INSERT INTO videos (id, youtube_video_id, channel_id, title, published_at, "
                "duration_seconds, created_at, updated_at) "
                "VALUES (20, 'vid_old', 10, 'Video Viejo', '2026-07-20T10:00:00Z', 500, 'now', 'now')"
            )

            # Candidato activo preexistente
            conn.execute("""
                INSERT INTO discovery_candidates (
                    video_id, category_id, score, band, reasons_json, status,
                    last_refresh_run_id, selection_rank, first_seen_at, last_seen_at
                )
                VALUES (20, 1, 60.0, 'related', '["Old reason"]', 'active', 1, 1, 'now', 'now')
            """)

            # Batch preexistente
            conn.execute("""
                INSERT INTO discovery_batches (
                    refresh_run_id, category_id, target_total, selected_total,
                    target_by_band_json, selected_by_band_json, shortfall_reason, generated_at
                )
                VALUES (
                    1, 1, 8, 1, '{"related": 5, "adjacent": 2, "exploratory": 1}',
                    '{"related": 1, "adjacent": 0, "exploratory": 0}', NULL, 'now'
                )
            """)

            # Crear refresh run 2
            conn.execute(
                "INSERT INTO refresh_runs (id, status, requested_stages_json, current_stage, "
                "requested_at, counters_json, errors_json) "
                "VALUES (2, 'running', '[\"discovery\"]', 'discovery', 'now', '{}', '[]')"
            )
            conn.commit()
        finally:
            conn.close()

    fake_gateway = QuotaFailureGateway()
    fake_gateway.videos_details = [
        {
            "youtube_video_id": "vid_new_1",
            "duration_seconds": 600,
            "content_type": "video"
        }
    ]
    fake_gateway.channels_details = [
        {
            "youtube_channel_id": "UC_FOTO_1",
            "title": "Canal Foto 1",
            "description": "desc",
            "uploads_playlist_id": "playlist_1"
        }
    ]

    with app.app_context():
        conn = get_db_connection(db_path)
        service = DiscoveryService(gateway=fake_gateway)
        stats = service.run_discovery(conn, run_id=2)
        conn.close()

    # Verify database state
    conn = get_db_connection(db_path)
    try:
        # Check old candidate status is still active (not expired)
        old_cand = conn.execute(
            "SELECT status FROM discovery_candidates WHERE video_id = 20 AND category_id = 1"
        ).fetchone()
        assert old_cand["status"] == "active", "Old candidate must remain active"

        # Check that no new candidate is active
        new_cands = conn.execute(
            "SELECT status FROM discovery_candidates WHERE last_refresh_run_id = 2"
        ).fetchall()
        assert len(new_cands) == 0, "No new candidates should be published for run 2"

        # Check stats returned
        assert stats["categories"][1]["failed"] is True, "Category 1 should be marked as failed"
        assert stats["categories"][1]["shortfall"] == "quota_exhausted", "Reason should be quota_exhausted"
    finally:
        conn.close()
