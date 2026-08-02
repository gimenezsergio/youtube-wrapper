import pytest
from datetime import datetime, timezone
from app.domain.discovery.models import Band
from app.domain.discovery.signals import CategorySignals
from app.domain.discovery.scoring import score_and_classify_candidate
from app.services.discovery_service import DiscoveryService
from tests.fakes.youtube_gateway import FakeYouTubeGateway
from app.db import get_db_connection
from app.auth.encryption import encrypt_token

def test_corr_score_03_min_threshold_validation():
    """CORR-SCORE-03 — Mínimo configurable excluye candidatos con puntuación inferior."""
    # 1. Direct domain function test
    signals = CategorySignals(
        category_id=1,
        positive_keywords=[("fotografia", 1.0)],
        negative_keywords=[],
        approved_exploration_topics=[],
        seed_channel_ids=set(),
        seed_channel_titles=[],
        seed_channel_descriptions=[],
        positive_video_titles=[],
        positive_channel_ids=set(),
        negative_video_ids=set(),
        negative_channel_ids=set(),
        blocked_channel_ids=set(),
        hidden_video_ids=set()
    )
    video = {
        "youtube_video_id": "v1",
        "title": "Fotografia de paisajes",
        "description": "Paisajes hermosos",
        "thumbnail_url": "http://example.com/thumb.jpg",
        "channel_title": "Canal A",
        "youtube_channel_id": "c1",
        "published_at": datetime.now(timezone.utc).isoformat()[:19] + "Z",
        "duration_seconds": 600,
        "content_type": "video"
    }

    # Under standard default related threshold (55.0) it matches exactly 55.0
    cand = score_and_classify_candidate(video, signals, min_score_related=55.0)
    assert cand is not None, "Should be eligible under related threshold <= 55"
    assert cand.score == 55.0

    # With higher threshold (56.0), it should be excluded
    cand_fail = score_and_classify_candidate(video, signals, min_score_related=56.0)
    assert cand_fail is None, "Should be excluded under related threshold 56"


def test_corr_score_03_min_threshold_via_service(app):
    """CORR-SCORE-03 — El mínimo configurable se propaga y aplica en DiscoveryService."""
    # Configure the app with custom thresholds that should filter out standard scores
    app.config["DISCOVERY_MIN_SCORE_RELATED"] = 99.0
    app.config["DISCOVERY_MIN_SCORE_ADJACENT"] = 99.0
    app.config["DISCOVERY_MIN_SCORE_EXPLORATORY"] = 99.0

    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            conn.execute("INSERT INTO credentials (id, access_token, refresh_token, expires_at, updated_at) VALUES (1, ?, ?, '2030-01-01T00:00:00Z', 'now')", (encrypt_token("access"), encrypt_token("refresh")))
            conn.execute("INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) VALUES (1, 'Fotografia', 'fotografia', 1, 'now', 'now')")
            conn.execute("INSERT INTO category_keywords (category_id, term, polarity, weight) VALUES (1, 'fotografia', 'positive', 1.0)")
            conn.execute("INSERT INTO refresh_runs (id, status, requested_stages_json, current_stage, requested_at, counters_json, errors_json) VALUES (1, 'running', '[\"discovery\"]', 'discovery', 'now', '{}', '[]')")
            conn.commit()
        finally:
            conn.close()

    fake_gateway = FakeYouTubeGateway()
    fake_gateway.search_results = [
        {
            "youtube_video_id": "vid_photo_1",
            "title": "Fotografía básica",
            "description": "Curso básico",
            "published_at": "2026-07-30T10:00:00Z",
            "thumbnail_url": "thumb_1",
            "channel_title": "Canal Foto 1",
            "youtube_channel_id": "UC_FOTO_1"
        }
    ]
    fake_gateway.videos_details = [
        {
            "youtube_video_id": "vid_photo_1",
            "duration_seconds": 600,
            "content_type": "video"
        }
    ]
    fake_gateway.channels_details = [
        {
            "youtube_channel_id": "UC_FOTO_1",
            "title": "Canal Foto 1",
            "description": "Canal de fotos",
            "thumbnail_url": "thumb_1",
            "uploads_playlist_id": "playlist_1"
        }
    ]

    with app.app_context():
        conn = get_db_connection(db_path)
        service = DiscoveryService(gateway=fake_gateway)
        stats = service.run_discovery(conn, run_id=1)
        conn.close()

    # The candidate has a standard score of 55.0, so under 99.0 threshold it should NOT be selected
    # This verifies the thresholds configured in Flask are actually used by the service and domain.
    assert stats["categories"][1]["selected"] == 0, "No candidates should be selected with a threshold of 99.0"
