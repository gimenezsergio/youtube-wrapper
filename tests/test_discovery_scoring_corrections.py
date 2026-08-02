from datetime import datetime, timedelta, timezone

from app.db import get_db_connection
from app.domain.discovery.models import Band
from app.domain.discovery.scoring import score_and_classify_candidate
from app.domain.discovery.signals import CategorySignals
from app.repositories.discovery_repository import DiscoveryRepository


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
    local_signals=None,
    more_like_this_channel_ids=None,
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
        local_signals=local_signals or [],
        more_like_this_channel_ids=more_like_this_channel_ids or set(),
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


def test_corr_score_02_weak_keyword_and_missing_metadata():
    """CORR-SCORE-02 — Metadatos ausentes o incompletos y keyword débil."""
    now = datetime.now(timezone.utc)
    pub_date = (now - timedelta(days=2)).isoformat()[:19] + "Z"

    # A) Keyword débil (0.1) -> score 23.5 (no elegible bajo 55.0)
    sig_weak = make_signals(positive_keywords=[("fotografia", 0.1)])
    v_weak = {
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
    assert score_and_classify_candidate(v_weak, sig_weak, now=now, min_score_related=55.0) is None
    c_raw = score_and_classify_candidate(v_weak, sig_weak, now=now, min_score_related=0.0)
    assert c_raw is not None
    assert c_raw.score == 23.5

    # B) Duración ausente o <= 180 -> exclusión
    sig_ok = make_signals(positive_keywords=[("fotografia", 1.0)])
    v_no_dur = {**v_weak, "duration_seconds": None}
    assert score_and_classify_candidate(v_no_dur, sig_ok, now=now, min_score_related=0.0) is None

    v_short = {**v_weak, "duration_seconds": 180}
    assert score_and_classify_candidate(v_short, sig_ok, now=now, min_score_related=0.0) is None

    # C) Publicación ausente -> actualidad 0 (no aporta 10)
    v_no_pub = {**v_weak, "published_at": None}
    c_no_pub = score_and_classify_candidate(v_no_pub, sig_ok, now=now, min_score_related=0.0)
    assert c_no_pub is not None
    assert c_no_pub.score == 45.0  # 35 kw + 0 freshness + 10 completeness

    # D) Descripción o miniatura ausente -> no aporta completitud (+5)
    v_no_desc = {**v_weak, "description": ""}
    c_no_desc = score_and_classify_candidate(v_no_desc, sig_ok, now=now, min_score_related=0.0)
    assert c_no_desc is not None
    assert c_no_desc.score == 50.0  # 35 kw + 10 freshness + 5 (solo no visto)

    v_no_thumb = {**v_weak, "thumbnail_url": ""}
    c_no_thumb = score_and_classify_candidate(v_no_thumb, sig_ok, now=now, min_score_related=0.0)
    assert c_no_thumb is not None
    assert c_no_thumb.score == 50.0


def test_corr_score_03_exact_table():
    """CORR-SCORE-03 — Tabla exacta de mínimos de elegibilidad."""
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
    signals_kw = make_signals(positive_keywords=[("fotografia", 1.0)])

    # 1. score 55, mínimo 55 -> elegible
    c1 = score_and_classify_candidate(video_55, signals_kw, now=now, min_score_related=55.0)
    assert c1 is not None
    assert c1.score == 55.0

    # 2. score 55, mínimo 56 -> no elegible
    c2 = score_and_classify_candidate(video_55, signals_kw, now=now, min_score_related=56.0)
    assert c2 is None

    # Video con score 80 (kw 35 + seed 20 + freshness 10 + feedback 10 + completeness 5 [sin desc] = 80)
    signals_80 = make_signals(
        positive_keywords=[("fotografia", 1.0)],
        seed_channel_titles=["Canal A"],
        more_like_this_channel_ids={10}
    )
    video_80 = {**video_55, "channel_id": 10, "description": ""}
    c_80_raw = score_and_classify_candidate(video_80, signals_80, now=now, min_score_related=0.0)
    assert c_80_raw is not None
    assert c_80_raw.score == 80.0

    # 3. score 80, mínimo 99 -> no elegible
    c3 = score_and_classify_candidate(video_80, signals_80, now=now, min_score_related=99.0)
    assert c3 is None

    # Video con score 100
    signals_99 = make_signals(
        positive_keywords=[("fotografia", 1.0)],
        seed_channel_titles=["Canal A"],
        more_like_this_channel_ids={10},
        local_signals=[{"channel_id": 10, "signal_type": "more_like_this"}]
    )
    video_99 = {**video_55, "channel_id": 10}
    c_99_raw = score_and_classify_candidate(video_99, signals_99, now=now, min_score_related=0.0)
    assert c_99_raw is not None
    assert c_99_raw.score == 100.0

    # 4. score 100, mínimo 99 -> elegible
    c4 = score_and_classify_candidate(video_99, signals_99, now=now, min_score_related=99.0)
    assert c4 is not None
    assert c4.score == 100.0


def test_corr_score_04_topics_and_bands():
    """CORR-SCORE-04 — Clasificación de bandas."""
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

    # Solo tema aprobado -> exploratory (score 50: 30 topic + 10 freshness + 10 completeness)
    signals_topic = make_signals(approved_exploration_topics=[("direccion de arte", 1.0)])
    v1 = {**base_video, "title": "Direccion de arte en cine"}
    c1 = score_and_classify_candidate(v1, signals_topic, now=now, min_score_exploratory=35.0)
    assert c1 is not None
    assert c1.band == Band.EXPLORATORY
    assert c1.score == 50.0

    # Keyword + tema aprobado -> adjacent (score 55: 35 kw + 10 freshness + 10 completeness)
    signals_both = make_signals(
        positive_keywords=[("fotografia", 1.0)],
        approved_exploration_topics=[("direccion de arte", 1.0)]
    )
    v2 = {**base_video, "title": "Fotografia y direccion de arte"}
    c2 = score_and_classify_candidate(v2, signals_both, now=now, min_score_adjacent=45.0)
    assert c2 is not None
    assert c2.band == Band.ADJACENT
    assert c2.score == 55.0

    # Ninguna evidencia -> None
    signals_none = make_signals(positive_keywords=[("musica", 1.0)])
    v3 = {**base_video, "title": "Cocina italiana"}
    c3 = score_and_classify_candidate(v3, signals_none, now=now)
    assert c3 is None


def test_corr_score_05_repository_signals_and_intensity(app):
    """CORR-SCORE-05 — Señales temporales desde el repositorio y jerarquía sin interacción."""
    db_path = app.config["DATABASE_PATH"]
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()[:19] + "Z"
    old_iso = (now_dt - timedelta(days=120)).isoformat()[:19] + "Z"

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO credentials (id, access_token, refresh_token, expires_at, updated_at) "
                "VALUES (1, 'acc', 'ref', '2030-01-01T00:00:00Z', 'now')"
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
                "INSERT INTO channels (id, youtube_channel_id, title, is_blocked, created_at, updated_at) VALUES "
                "(10, 'ch_opened', 'Canal Opened', 0, 'now', 'now'), "
                "(11, 'ch_watched', 'Canal Watched', 0, 'now', 'now'), "
                "(12, 'ch_more', 'Canal More', 0, 'now', 'now'), "
                "(13, 'ch_expired', 'Canal Expired', 0, 'now', 'now')"
            )
            conn.execute(
                "INSERT INTO channel_categories (channel_id, category_id, source, created_at) VALUES "
                "(10, 1, 'accepted_discovery', 'now'), (11, 1, 'accepted_discovery', 'now'), "
                "(12, 1, 'accepted_discovery', 'now'), (13, 1, 'accepted_discovery', 'now')"
            )
            conn.execute(
                "INSERT INTO videos (id, youtube_video_id, channel_id, title, duration_seconds, "
                "content_type, published_at, created_at, updated_at) VALUES "
                "(100, 'v_opened', 10, 'Fotografia Video Opened', 600, 'video', ?, 'now', 'now'), "
                "(101, 'v_watched', 11, 'Fotografia Video Watched', 600, 'video', ?, 'now', 'now'), "
                "(102, 'v_more', 12, 'Fotografia Video More', 600, 'video', ?, 'now', 'now'), "
                "(103, 'v_expired', 13, 'Fotografia Video Expired', 600, 'video', ?, 'now', 'now')",
                (now_iso, now_iso, now_iso, old_iso)
            )
            # Opened state
            conn.execute(
                "INSERT INTO video_user_state (video_id, opened_at, updated_at) VALUES (100, ?, ?)",
                (now_iso, now_iso)
            )
            # Watched state
            conn.execute(
                "INSERT INTO video_user_state (video_id, watched, updated_at) VALUES (101, 1, ?)",
                (now_iso,)
            )
            # More_like_this feedback
            conn.execute(
                "INSERT INTO discovery_feedback (category_id, video_id, channel_id, action, created_at) VALUES "
                "(1, 102, 12, 'more_like_this', ?)",
                (now_iso,)
            )
            # Expired signal (120 days ago, signal_window_days is 90)
            conn.execute(
                "INSERT INTO video_user_state (video_id, opened_at, updated_at) VALUES (103, ?, ?)",
                (old_iso, old_iso)
            )
            conn.commit()

            signals = DiscoveryRepository.get_category_signals(conn, category_id=1, signal_window_days=90)
        finally:
            conn.close()

    base_vid = {
        "description": "desc",
        "thumbnail_url": "thumb",
        "published_at": now_iso,
        "duration_seconds": 600,
        "content_type": "video"
    }

    v_none = {
        **base_vid,
        "youtube_video_id": "v_none",
        "channel_id": 999,
        "channel_title": "Canal Sin Interaccion",
        "title": "Fotografia Sin Interaccion"
    }
    v_opened = {
        **base_vid,
        "youtube_video_id": "v_opened",
        "channel_id": 10,
        "channel_title": "Canal Opened",
        "title": "Fotografia Video Opened"
    }
    v_watched = {
        **base_vid,
        "youtube_video_id": "v_watched",
        "channel_id": 11,
        "channel_title": "Canal Watched",
        "title": "Fotografia Video Watched"
    }
    v_more = {
        **base_vid,
        "youtube_video_id": "v_more",
        "channel_id": 12,
        "channel_title": "Canal More",
        "title": "Fotografia Video More"
    }
    v_expired = {
        **base_vid,
        "youtube_video_id": "v_expired",
        "channel_id": 13,
        "channel_title": "Canal Expired",
        "title": "Fotografia Video Expired"
    }

    c_none = score_and_classify_candidate(v_none, signals, now=now_dt, min_score_related=0.0)
    c_opened = score_and_classify_candidate(v_opened, signals, now=now_dt, min_score_related=0.0)
    c_watched = score_and_classify_candidate(v_watched, signals, now=now_dt, min_score_related=0.0)
    c_more = score_and_classify_candidate(v_more, signals, now=now_dt, min_score_related=0.0)
    c_expired = score_and_classify_candidate(v_expired, signals, now=now_dt, min_score_related=0.0)

    assert c_none is not None
    assert c_opened is not None
    assert c_watched is not None
    assert c_more is not None
    assert c_expired is not None

    # Base score sin interacción: 35 kw + 10 freshness + 10 completeness = 55.0
    assert c_none.score == 55.0
    # Opened (+4 local signal) -> 59.0
    assert c_opened.score == 59.0
    # Watched (+8 local signal) -> 63.0
    assert c_watched.score == 63.0
    # More_like_this (+15 local signal + 10 positive feedback) -> 80.0
    assert c_more.score == 80.0

    assert c_none.score < c_opened.score < c_watched.score < c_more.score
    assert c_expired.score == c_none.score, "Señal fuera de ventana debe equivaler a sin interacción"


def test_corr_score_06_exact_weights_and_limits():
    """CORR-SCORE-06 — Límites exactos de pesos (-1, 0, 1, 5, 100) y score entre 0 y 100."""
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

    # Weight -1 -> kw score 0.0 -> no positive match -> None
    sig_neg1 = make_signals(positive_keywords=[("fotografia", -1.0)])
    c_neg1 = score_and_classify_candidate(base_video, sig_neg1, now=now, min_score_related=0.0)
    assert c_neg1 is None

    # Weight 0 -> kw score 0.0 -> None
    sig_0 = make_signals(positive_keywords=[("fotografia", 0.0)])
    c_0 = score_and_classify_candidate(base_video, sig_0, now=now, min_score_related=0.0)
    assert c_0 is None

    # Weights 1, 5, 100 -> kw score 35.0 (clamped a 1.0 max) -> score exactamente idéntico
    sig_1 = make_signals(positive_keywords=[("fotografia", 1.0)])
    sig_5 = make_signals(positive_keywords=[("fotografia", 5.0)])
    sig_100 = make_signals(positive_keywords=[("fotografia", 100.0)])

    c_1 = score_and_classify_candidate(base_video, sig_1, now=now, min_score_related=0.0)
    c_5 = score_and_classify_candidate(base_video, sig_5, now=now, min_score_related=0.0)
    c_100 = score_and_classify_candidate(base_video, sig_100, now=now, min_score_related=0.0)

    assert c_1 is not None
    assert c_5 is not None
    assert c_100 is not None

    assert c_1.score == 55.0
    assert c_5.score == 55.0
    assert c_100.score == 55.0
    assert c_1.score == c_5.score == c_100.score

    # Penalización por less_like_this
    sig_pen = make_signals(
        positive_keywords=[("fotografia", 1.0)],
        negative_video_ids={1}
    )
    v_pen = {**base_video, "video_id": 1}
    c_pen = score_and_classify_candidate(v_pen, sig_pen, now=now, min_score_related=0.0)
    assert c_pen is not None
    assert c_pen.score == 15.0  # 55 - 40 penalty
    assert 0.0 <= c_pen.score <= 100.0
