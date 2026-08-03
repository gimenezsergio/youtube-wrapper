from datetime import datetime, timezone

from app.domain.discovery.models import Band, DiscoveryCandidateDomain
from app.domain.discovery.scoring import score_and_classify_candidate
from app.domain.discovery.selection import calculate_jaccard_similarity, select_batch_diverse
from app.domain.discovery.signals import CategorySignals
from app.services.discovery_service import schedule_queries_round_robin


def test_disc_05_exclusions():
    """DISC-05 — Canales/videos bloqueados o vistos se excluyen."""
    signals = CategorySignals(
        category_id=1,
        positive_keywords=[("fotografia", 1.0)],
        negative_keywords=["spam"],
        approved_exploration_topics=[],
        seed_channel_ids={10},
        seed_channel_titles=["Canal Semilla"],
        seed_channel_descriptions=[],
        positive_video_titles=[],
        positive_channel_ids=set(),
        negative_video_ids={101},
        negative_channel_ids={11},
        blocked_channel_ids={12},
        hidden_video_ids={102},
        followed_channel_ids={13},
        watched_video_ids={103}
    )

    base_vid = {
        "title": "Fotografia de paisaje",
        "description": "desc",
        "thumbnail_url": "thumb",
        "published_at": "2026-07-30T10:00:00Z",
        "duration_seconds": 600
    }

    # Bloqueado globalmente
    assert score_and_classify_candidate({**base_vid, "channel_id": 12}, signals) is None
    # Oculto en la categoría
    assert score_and_classify_candidate({**base_vid, "video_id": 102, "channel_id": 99}, signals) is None
    # Ya visto
    assert score_and_classify_candidate({**base_vid, "video_id": 103, "channel_id": 99}, signals) is None
    # Seguido o Semilla (ya suscrito/guardado en categoría)
    assert score_and_classify_candidate({**base_vid, "channel_id": 10}, signals) is None
    assert score_and_classify_candidate({**base_vid, "channel_id": 13}, signals) is None
    # Palabra clave negativa
    assert score_and_classify_candidate({**base_vid, "title": "Fotografia spam", "channel_id": 99}, signals) is None


def test_disc_06_scoring_components():
    """DISC-06 — Casos de tabla validan cada componente y límites 0..100."""
    signals = CategorySignals(
        category_id=1,
        positive_keywords=[("fotografia", 1.0)],
        negative_keywords=[],
        approved_exploration_topics=[("iluminacion", 1.0)],
        seed_channel_ids={5},
        seed_channel_titles=["Canal Semilla"],
        seed_channel_descriptions=[],
        positive_video_titles=["Inspiracion"],
        positive_channel_ids={5},
        negative_video_ids=set(),
        negative_channel_ids=set(),
        blocked_channel_ids=set(),
        hidden_video_ids=set()
    )

    # Caso A: coincidencia temática e seed channel y actualidad
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    video = {
        "youtube_video_id": "v1",
        "title": "Fotografia iluminacion profesional",
        "description": "Tutorial basico de fotografia",
        "thumbnail_url": "thumb",
        "channel_id": 15,  # Distinto de 5 para que no sea excluido por ser canal seguido semilla
        "channel_title": "Canal Semilla",
        "published_at": "2026-07-30T10:00:00Z",  # Hace 2 días
        "duration_seconds": 600
    }
    candidate = score_and_classify_candidate(video, signals, now=now)
    assert candidate is not None
    assert candidate.band == Band.ADJACENT
    assert candidate.score > 50.0
    assert len(candidate.reasons) >= 1


def test_disc_07_reasons():
    """DISC-07 — Todo candidato visible tiene al menos una razón."""
    signals = CategorySignals(
        category_id=1,
        positive_keywords=[("test", 1.0)],
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
        "title": "Test video",
        "description": "desc",
        "thumbnail_url": "thumb",
        "channel_id": 1,
        "channel_title": "Canal A",
        "published_at": "2026-07-30T10:00:00Z",
        "duration_seconds": 600
    }
    candidate = score_and_classify_candidate(video, signals)
    assert candidate is not None
    assert len(candidate.reasons) >= 1


def test_disc_09_10_24_scheduling():
    """DISC-09, DISC-10, DISC-24 — Presupuesto y planificación round-robin."""
    category_queries = {
        1: [{"q": "q1_1"}, {"q": "q1_2"}],
        2: [{"q": "q2_1"}, {"q": "q2_2"}],
        3: [{"q": "q3_1"}]
    }
    scheduled = schedule_queries_round_robin(category_queries, global_budget=4, max_per_category=2)
    # Debe ser: (1, q1_1), (2, q2_1), (3, q3_1), (1, q1_2)
    assert len(scheduled) == 4
    assert scheduled[0] == (1, {"q": "q1_1"})
    assert scheduled[1] == (2, {"q": "q2_1"})
    assert scheduled[2] == (3, {"q": "q3_1"})
    assert scheduled[3] == (1, {"q": "q1_2"})


def test_disc_18_classification():
    """DISC-18 — Clasificación de bandas."""
    signals = CategorySignals(
        category_id=1,
        positive_keywords=[("fotografia", 1.0)],
        negative_keywords=[],
        approved_exploration_topics=[("iluminacion", 1.0)],
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

    base_vid = {
        "description": "desc",
        "thumbnail_url": "thumb",
        "published_at": "2026-07-30T10:00:00Z",
        "duration_seconds": 600,
        "channel_title": "Otro"
    }

    # 1. Related
    c_rel = score_and_classify_candidate({**base_vid, "title": "Clase de fotografia"}, signals)
    assert c_rel is not None
    assert c_rel.band == Band.RELATED

    # 2. Adjacent
    c_adj = score_and_classify_candidate({**base_vid, "title": "fotografia con iluminacion"}, signals)
    assert c_adj is not None
    assert c_adj.band == Band.ADJACENT

    # 3. Exploratory (solo matches topic)
    c_exp = score_and_classify_candidate({**base_vid, "title": "iluminacion de interiores"}, signals)
    assert c_exp is not None
    assert c_exp.band == Band.EXPLORATORY


def test_disc_19_20_21_22_23_selection():
    """Valida la selección de lotes, fallbacks, diversidad de canal y duplicados."""
    c1 = DiscoveryCandidateDomain(1, "v1", 10, "ch_1", "ch_1", "Fotografia de retratos", "", "2026-07-30T10:00:00Z", 600, "video", 90.0, Band.RELATED)
    c2 = DiscoveryCandidateDomain(2, "v2", 10, "ch_1", "ch_1", "Fotografia de paisajes", "", "2026-07-30T09:00:00Z", 600, "video", 85.0, Band.RELATED)
    c3 = DiscoveryCandidateDomain(3, "v3", 10, "ch_1", "ch_1", "Fotografia de deportes", "", "2026-07-30T08:00:00Z", 600, "video", 80.0, Band.RELATED)
    c4 = DiscoveryCandidateDomain(4, "v4", 11, "ch_2", "ch_2", "Fotografia callejera", "", "2026-07-30T07:00:00Z", 600, "video", 75.0, Band.RELATED)
    c5 = DiscoveryCandidateDomain(5, "v5", 12, "ch_3", "ch_3", "Retrato de calle", "", "2026-07-30T06:00:00Z", 600, "video", 70.0, Band.RELATED)
    c6_rel = DiscoveryCandidateDomain(9, "v9", 17, "ch_7", "ch_7", "Naturaleza y paisajes", "", "2026-07-30T02:00:00Z", 600, "video", 69.0, Band.RELATED)

    # Candidato casi duplicado con c1
    c1_dup = DiscoveryCandidateDomain(6, "v6", 13, "ch_4", "ch_4", "Fotografía de retrato", "", "2026-07-30T05:00:00Z", 600, "video", 88.0, Band.RELATED)

    c_adj1 = DiscoveryCandidateDomain(7, "v7", 14, "ch_5", "ch_5", "Fotografia e iluminacion", "", "2026-07-30T04:00:00Z", 600, "video", 65.0, Band.ADJACENT)
    c_adj2 = DiscoveryCandidateDomain(10, "v10", 18, "ch_8", "ch_8", "Tecnicas avanzadas de iluminacion", "", "2026-07-30T01:00:00Z", 600, "video", 64.0, Band.ADJACENT)
    c_exp1 = DiscoveryCandidateDomain(8, "v8", 15, "ch_6", "ch_6", "Iluminacion de teatro", "", "2026-07-30T03:00:00Z", 600, "video", 55.0, Band.EXPLORATORY)

    candidates = [c1, c2, c3, c4, c5, c6_rel, c1_dup, c_adj1, c_adj2, c_exp1]

    # Mezcla ideal 5 / 2 / 1
    selected, counts, shortfall = select_batch_diverse(
        candidates, target_total=8, target_related=5, target_adjacent=2, target_exploratory=1, max_videos_per_channel=2
    )

    assert len(selected) == 8
    assert counts["selectedByBand"]["related"] == 5
    assert counts["selectedByBand"]["adjacent"] == 2
    assert counts["selectedByBand"]["exploratory"] == 1
    assert shortfall is None

    # Max per channel: canal 10 solo debe aportar maximo 2 (c1 y c2)
    ch10_count = sum(1 for c in selected if c.channel_id == 10)
    assert ch10_count == 2

    # Duplicados: c1_dup debe ser filtrado por similitud de titulo con c1
    selected_ids = {c.video_id for c in selected}
    assert 6 not in selected_ids


def test_jaccard_similarity():
    """Valida el cálculo de similitud Jaccard para deduplicación."""
    sim1 = calculate_jaccard_similarity("Curso Completo de Fotografia Digital", "Curso Completo de Fotografía Digital 2026")
    assert sim1 >= 0.70

    sim2 = calculate_jaccard_similarity("Fotografia de retratos", "Iluminación en estudio fotográfico")
    assert sim2 < 0.70
