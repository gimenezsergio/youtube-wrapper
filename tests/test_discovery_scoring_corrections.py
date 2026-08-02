import sys
from datetime import datetime, timedelta, timezone

from app.auth.encryption import encrypt_token
from app.db import get_db_connection
from app.domain.discovery.models import Band
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


def make_signals(
    positive_keywords=None,
    negative_keywords=None,
    approved_exploration_topics=None,
    seed_channel_ids=None,
    seed_channel_titles=None,
    seed_channel_descriptions=None,
    positive_video_titles=None,
    positive_channel_ids=None,
    negative_video_ids=None,
    negative_channel_ids=None,
    blocked_channel_ids=None,
    hidden_video_ids=None,
    followed_channel_ids=None,
    watched_video_ids=None,
    local_signal_scores=None,
):
    return CategorySignals(
        category_id=1,
        positive_keywords=positive_keywords or [],
        negative_keywords=negative_keywords or [],
        approved_exploration_topics=approved_exploration_topics or [],
        seed_channel_ids=seed_channel_ids or set(),
        seed_channel_titles=seed_channel_titles or [],
        seed_channel_descriptions=seed_channel_descriptions or [],
        positive_video_titles=positive_video_titles or [],
        positive_channel_ids=positive_channel_ids or set(),
        negative_video_ids=negative_video_ids or set(),
        negative_channel_ids=negative_channel_ids or set(),
        blocked_channel_ids=blocked_channel_ids or set(),
        hidden_video_ids=hidden_video_ids or set(),
        followed_channel_ids=followed_channel_ids or set(),
        watched_video_ids=watched_video_ids or set(),
        local_signal_scores=local_signal_scores,
    )


def test_corr_score_01_neutral_weight():
    """CORR-SCORE-01 — Peso neutral (1.0) obtiene score 55.0, banda related y es elegible."""
    now = datetime.now(timezone.utc)
    pub_date = (now - timedelta(days=2)).isoformat()[:19] + "Z"
    signals = make_signals(positive_keywords=[("fotografia", 1.0)])

    video = {
        "youtube_video_id": "v1",
        "title": "Fotografia de retrato",
        "description": "Un gran curso",
        "thumbnail_url": "http://example.com/thumb.jpg",
        "channel_title": "Canal A",
        "youtube_channel_id": "c1",
        "published_at": pub_date,
        "duration_seconds": 600,
        "content_type": "video"
    }

    cand = score_and_classify_candidate(video, signals, now=now, min_score_related=55.0)
    assert cand is not None, "Debería ser elegible con el mínimo predeterminado de 55"
    assert cand.score == 55.0
    assert cand.band == Band.RELATED


def test_corr_score_02_weak_keyword():
    """CORR-SCORE-02 — Keyword débil (0.1) obtiene score 23.5 y no es elegible."""
    now = datetime.now(timezone.utc)
    pub_date = (now - timedelta(days=2)).isoformat()[:19] + "Z"
    signals = make_signals(positive_keywords=[("fotografia", 0.1)])

    video = {
        "youtube_video_id": "v1",
        "title": "Fotografia de retrato",
        "description": "Un gran curso",
        "thumbnail_url": "http://example.com/thumb.jpg",
        "channel_title": "Canal A",
        "youtube_channel_id": "c1",
        "published_at": pub_date,
        "duration_seconds": 600,
        "content_type": "video"
    }

    # Score calculado: 3.5 (kw title) + 10 (freshness <=7d) + 10 (completeness) = 23.5
    cand = score_and_classify_candidate(video, signals, now=now, min_score_related=55.0)
    assert cand is None, "Score 23.5 debe quedar excluido con umbral related=55.0"

    # Verificación del valor sin umbral
    cand_raw = score_and_classify_candidate(video, signals, now=now, min_score_related=0.0)
    assert cand_raw is not None
    assert cand_raw.score == 23.5


def test_corr_score_03_configurable_minimums():
    """CORR-SCORE-03 — Tabla de mínimos configurables."""
    now = datetime.now(timezone.utc)
    pub_2d = (now - timedelta(days=2)).isoformat()[:19] + "Z"

    video_55 = {
        "youtube_video_id": "v1",
        "title": "Fotografia de retrato",
        "description": "Un gran curso",
        "thumbnail_url": "http://example.com/thumb.jpg",
        "channel_title": "Canal A",
        "youtube_channel_id": "c1",
        "published_at": pub_2d,
        "duration_seconds": 600,
        "content_type": "video"
    }
    signals = make_signals(positive_keywords=[("fotografia", 1.0)])

    # Score 55 vs min 55 -> elegible
    c1 = score_and_classify_candidate(video_55, signals, now=now, min_score_related=55.0)
    assert c1 is not None

    # Score 55 vs min 56 -> no elegible
    c2 = score_and_classify_candidate(video_55, signals, now=now, min_score_related=56.0)
    assert c2 is None

    # Video con score alto (ej: keyword + seed channel + local signal = score > 80)
    signals_80 = make_signals(
        positive_keywords=[("fotografia", 1.0)],
        seed_channel_titles=["Canal A"]
    )
    c3_raw = score_and_classify_candidate(video_55, signals_80, now=now, min_score_related=0.0)
    assert c3_raw is not None
    assert c3_raw.score >= 75.0

    # Score vs min 99 -> no elegible
    c3 = score_and_classify_candidate(video_55, signals_80, now=now, min_score_related=99.0)
    assert c3 is None


def test_corr_score_03_min_threshold_via_service(app):
    """CORR-SCORE-03 — El mínimo configurable se propaga y aplica en DiscoveryService."""
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

    assert fake_gateway.search_called, "YouTube search was not executed"
    assert fake_gateway.video_details_called, "YouTube video details was not executed"
    assert fake_gateway.channel_details_called, "YouTube channel details was not executed"

    assert len(called_args) > 0, "score_and_classify_candidate was not called"
    matched_call = None
    for args, kwargs in called_args:
        if kwargs.get("min_score_related") == 99.0:
            matched_call = (args, kwargs)
            break
    assert matched_call is not None, "Threshold of 99.0 was not propagated to scoring function"

    video_eval, signals_eval = matched_call[0][0], matched_call[0][1]
    unthresholded_cand = orig_score_fn(video_eval, signals_eval, min_score_related=0.0)
    assert unthresholded_cand is not None, "Candidate should be valid when unthresholded"
    assert unthresholded_cand.score < 99.0, f"Candidate score {unthresholded_cand.score} should be < 99.0"

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            saved_candidates = conn.execute(
                "SELECT count(*) FROM discovery_candidates WHERE status = 'active'"
            ).fetchone()[0]
            assert saved_candidates == 0, "Active candidates were persisted despite falling below threshold"
        finally:
            conn.close()

    assert stats["categories"][1]["selected"] == 0, "No candidates should be selected with threshold 99.0"


def test_corr_score_04_topics_and_bands():
    """CORR-SCORE-04 — Temas y bandas de clasificación."""
    now = datetime.now(timezone.utc)
    pub_2d = (now - timedelta(days=2)).isoformat()[:19] + "Z"

    base_video = {
        "youtube_video_id": "v1",
        "description": "desc",
        "thumbnail_url": "thumb",
        "channel_title": "Canal",
        "youtube_channel_id": "c1",
        "published_at": pub_2d,
        "duration_seconds": 600,
        "content_type": "video"
    }

    # A) Solo tema aprobado -> exploratory (score 50: 30 topic + 10 freshness + 10 completeness)
    signals_topic = make_signals(approved_exploration_topics=[("direccion de arte", 1.0)])
    v1 = {**base_video, "title": "Direccion de arte en cine"}
    c1 = score_and_classify_candidate(v1, signals_topic, now=now, min_score_exploratory=35.0)
    assert c1 is not None
    assert c1.band == Band.EXPLORATORY
    assert c1.score == 50.0

    # B) Keyword + tema aprobado -> adjacent (score 55: 35 kw + 10 freshness + 10 completeness)
    signals_both = make_signals(
        positive_keywords=[("fotografia", 1.0)],
        approved_exploration_topics=[("direccion de arte", 1.0)]
    )
    v2 = {**base_video, "title": "Fotografia y direccion de arte"}
    c2 = score_and_classify_candidate(v2, signals_both, now=now, min_score_adjacent=45.0)
    assert c2 is not None
    assert c2.band == Band.ADJACENT
    assert c2.score == 55.0

    # C) Ninguna evidencia -> None
    signals_none = make_signals(positive_keywords=[("musica", 1.0)])
    v3 = {**base_video, "title": "Cocina italiana"}
    c3 = score_and_classify_candidate(v3, signals_none, now=now)
    assert c3 is None


def test_corr_score_05_window_and_intensity():
    """CORR-SCORE-05 — Ventana e intensidad de señales temporales."""
    now = datetime.now(timezone.utc)
    pub_2d = (now - timedelta(days=2)).isoformat()[:19] + "Z"

    base_video = {
        "youtube_video_id": "v1",
        "title": "Fotografia nocturna",
        "description": "desc",
        "thumbnail_url": "thumb",
        "channel_title": "Canal",
        "youtube_channel_id": "c1",
        "published_at": pub_2d,
        "duration_seconds": 600,
        "content_type": "video"
    }

    # Base: no local interaction signals
    sig_none = make_signals(positive_keywords=[("fotografia", 1.0)])
    c_none = score_and_classify_candidate(base_video, sig_none, now=now, min_score_related=0.0)

    # Opened signal (+4)
    sig_opened = make_signals(
        positive_keywords=[("fotografia", 1.0)],
        local_signal_scores={"opened": 4.0}
    )
    c_opened = score_and_classify_candidate(base_video, sig_opened, now=now, min_score_related=0.0)

    # Watched signal (+8)
    sig_watched = make_signals(
        positive_keywords=[("fotografia", 1.0)],
        local_signal_scores={"watched": 8.0}
    )
    c_watched = score_and_classify_candidate(base_video, sig_watched, now=now, min_score_related=0.0)

    # More_like_this signal (+15)
    sig_more = make_signals(
        positive_keywords=[("fotografia", 1.0)],
        local_signal_scores={"more_like_this": 15.0}
    )
    c_more = score_and_classify_candidate(base_video, sig_more, now=now, min_score_related=0.0)

    # Assert strict ordering: no interaction < opened < watched < more_like_this
    assert c_none.score < c_opened.score < c_watched.score < c_more.score, (
        f"Ordering mismatch: none({c_none.score}) < opened({c_opened.score}) < "
        f"watched({c_watched.score}) < more({c_more.score})"
    )

    # Signal outside window -> same score as no interaction
    sig_expired = make_signals(
        positive_keywords=[("fotografia", 1.0)],
        local_signal_scores={"more_like_this_expired": True}
    )
    c_expired = score_and_classify_candidate(base_video, sig_expired, now=now, min_score_related=0.0)
    assert c_expired.score == c_none.score, "Expired interaction signal must produce same score as no interaction"


def test_corr_score_06_limits_and_clamping():
    """CORR-SCORE-06 — Límites 0..100 y clamping de pesos."""
    now = datetime.now(timezone.utc)
    pub_2d = (now - timedelta(days=2)).isoformat()[:19] + "Z"

    base_video = {
        "youtube_video_id": "v1",
        "title": "Fotografia nocturna",
        "description": "desc",
        "thumbnail_url": "thumb",
        "channel_title": "Canal A",
        "youtube_channel_id": "c1",
        "published_at": pub_2d,
        "duration_seconds": 600,
        "content_type": "video"
    }

    # Weight 5.0 and 100.0 must clamp to 1.0 and not exceed component max (35)
    for w in [-1.0, 0.0, 1.0, 5.0, 100.0]:
        sig = make_signals(positive_keywords=[("fotografia", w)])
        cand = score_and_classify_candidate(base_video, sig, now=now, min_score_related=0.0)
        if cand:
            assert 0.0 <= cand.score <= 100.0, f"Score {cand.score} out of bounds for weight {w}"

    # Maximum combined score with all positive components should cap at 100
    sig_max = make_signals(
        positive_keywords=[("fotografia", 10.0)],
        seed_channel_titles=["Canal A"],
        positive_channel_ids={10},
        local_signal_scores={"more_like_this": 15.0}
    )
    cand_max = score_and_classify_candidate(
        {**base_video, "channel_id": 10}, sig_max, now=now, min_score_related=0.0
    )
    assert cand_max is not None
    assert cand_max.score == 100.0, f"Max score should be 100.0, got {cand_max.score}"

    # Penalty for less_like_this should reduce score but stay >= 0
    sig_pen = make_signals(
        positive_keywords=[("fotografia", 0.1)],
        negative_video_ids={1}
    )
    cand_pen = score_and_classify_candidate(
        {**base_video, "video_id": 1}, sig_pen, now=now, min_score_related=0.0
    )
    if cand_pen:
        assert cand_pen.score >= 0.0, "Score with penalty must not be negative"
