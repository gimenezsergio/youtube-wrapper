import sys
from datetime import datetime, timezone

from app.auth.encryption import encrypt_token
from app.db import get_db_connection
from app.domain.discovery.scoring import score_and_classify_candidate
from app.domain.discovery.signals import CategorySignals
from app.services.discovery_service import DiscoveryService
from tests.fakes.youtube_gateway import FakeYouTubeGateway


class SpyYouTubeGateway(FakeYouTubeGateway):
    def __init__(self):
        super().__init__()
        self.search_called = False
        self.video_details_called = False
        self.channel_details_called = False

    def search_videos(
        self, access_token, q, published_after=None, limit=25, region_code="AR", relevance_language="es"
    ):
        self.search_called = True
        return super().search_videos(
            access_token, q, published_after, limit, region_code, relevance_language
        )

    def get_videos_details(self, access_token, video_ids):
        self.video_details_called = True
        return super().get_videos_details(access_token, video_ids)

    def get_channels_details(self, access_token, channel_ids):
        self.channel_details_called = True
        return super().get_channels_details(access_token, channel_ids)


def test_corr_score_03_min_threshold_validation():
    """CORR-SCORE-03 — Mínimo configurable excluye candidatos con puntuación inferior."""
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
            conn.execute(
                "INSERT INTO credentials (id, access_token, refresh_token, expires_at, updated_at) "
                "VALUES (1, ?, ?, '2030-01-01T00:00:00Z', 'now')",
                (encrypt_token("access"), encrypt_token("refresh"))
            )
            conn.execute(
                "INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) "
                "VALUES (1, 'Fotografia', 'fotografia', 1, 'now', 'now')"
            )
            conn.execute(
                "INSERT INTO category_keywords (category_id, term, polarity, weight) "
                "VALUES (1, 'fotografia', 'positive', 1.0)"
            )
            conn.execute(
                "INSERT INTO refresh_runs (id, status, requested_stages_json, current_stage, "
                "requested_at, counters_json, errors_json) "
                "VALUES (1, 'running', '[\"discovery\"]', 'discovery', 'now', '{}', '[]')"
            )
            conn.commit()
        finally:
            conn.close()

    fake_gateway = SpyYouTubeGateway()
    fake_gateway.search_responses["default"] = [
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
    fake_gateway.video_details = [
        {
            "youtube_video_id": "vid_photo_1",
            "duration_seconds": 600,
            "content_type": "video"
        }
    ]
    fake_gateway.channels_details = {
        "UC_FOTO_1": {
            "youtube_channel_id": "UC_FOTO_1",
            "title": "Canal Foto 1",
            "description": "Canal de fotos",
            "thumbnail_url": "thumb_1",
            "uploads_playlist_id": "playlist_1"
        }
    }

    # Setup spy on score_and_classify_candidate
    discovery_service_module = sys.modules["app.services.discovery_service"]
    orig_score_fn = discovery_service_module.score_and_classify_candidate
    called_args = []

    def spy_score_fn(*args, **kwargs):
        called_args.append((args, kwargs))
        return orig_score_fn(*args, **kwargs)

    discovery_service_module.score_and_classify_candidate = spy_score_fn

    try:
        with app.app_context():
            conn = get_db_connection(db_path)
            service = DiscoveryService(gateway=fake_gateway)
            stats = service.run_discovery(conn, run_id=1)
            conn.close()
    finally:
        discovery_service_module.score_and_classify_candidate = orig_score_fn

    # 1. Verify Gateway spies executed
    assert fake_gateway.search_called, "search_videos was not executed"
    assert fake_gateway.video_details_called, "get_videos_details was not executed"
    assert fake_gateway.channel_details_called, "get_channels_details was not executed"

    # 2. Verify score function spy and config propagation
    assert len(called_args) > 0, "score_and_classify_candidate was not called"
    matched_call = None
    for args, kwargs in called_args:
        if kwargs.get("min_score_related") == 99.0:
            matched_call = (args, kwargs)
            break
    assert matched_call is not None, "Threshold of 99.0 was not propagated to scoring function"

    # Verify that without threshold=99.0, candidate score is < 99
    video_eval, signals_eval = matched_call[0][0], matched_call[0][1]
    unthresholded_cand = orig_score_fn(video_eval, signals_eval, min_score_related=0.0)
    assert unthresholded_cand is not None, "Candidate should be valid when unthresholded"
    assert unthresholded_cand.score < 99.0, f"Candidate score {unthresholded_cand.score} should be < 99.0"

    # 3. Verify database: no candidates stored as active
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            saved_candidates = conn.execute(
                "SELECT count(*) FROM discovery_candidates WHERE status = 'active'"
            ).fetchone()[0]
            assert saved_candidates == 0, "Active candidates were persisted despite falling below threshold"
        finally:
            conn.close()

    # 4. Verify stats
    assert stats["categories"][1]["selected"] == 0, "selected count must be 0"
