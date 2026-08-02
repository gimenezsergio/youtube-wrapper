import random

import pytest

from app.domain.discovery.models import Band, DiscoveryCandidateDomain
from app.domain.discovery.scoring import score_and_classify_candidate
from app.domain.discovery.selection import SelectionConfig, select_batch_diverse
from app.domain.discovery.signals import CategorySignals


def make_cand(
    video_id: int,
    band: Band,
    score: float = 60.0,
    yt_vid: str = None,
    yt_cid: str = None,
    title: str = None,
    published_at: str = "2026-07-30T10:00:00Z"
) -> DiscoveryCandidateDomain:
    return DiscoveryCandidateDomain(
        video_id=video_id,
        youtube_video_id=yt_vid or f"vid_{video_id}",
        channel_id=video_id,
        youtube_channel_id=yt_cid or f"chan_{video_id}",
        channel_title=f"Canal {video_id}",
        title=title or f"Video titulo {video_id}",
        description="desc",
        published_at=published_at,
        duration_seconds=600,
        content_type="video",
        score=score,
        band=band,
        reasons=["Razon"]
    )


def test_corr_sel_01_full_mix():
    """CORR-SEL-01 — Entrada: 7 related, 4 adjacent, 3 exploratory -> 8 seleccionados (5/2/1)."""
    candidates = []
    for i in range(1, 8):
        candidates.append(make_cand(i, Band.RELATED, score=80.0 - i))
    for i in range(8, 12):
        candidates.append(make_cand(i, Band.ADJACENT, score=70.0 - i))
    for i in range(12, 15):
        candidates.append(make_cand(i, Band.EXPLORATORY, score=60.0 - i))

    selected, counts, shortfall = select_batch_diverse(
        candidates, target_total=8, target_related=5, target_adjacent=2, target_exploratory=1
    )

    assert len(selected) == 8
    assert counts["selectedByBand"] == {"related": 5, "adjacent": 2, "exploratory": 1}
    assert shortfall is None
    for idx, c in enumerate(selected, start=1):
        assert c.selection_rank == idx


def test_corr_sel_02_only_exploratory():
    """CORR-SEL-02 — Con 8 exploratory elegibles, se selecciona máximo 1 (cupo exploratorio)."""
    candidates = [make_cand(i, Band.EXPLORATORY, score=50.0) for i in range(1, 9)]

    selected, counts, shortfall = select_batch_diverse(
        candidates, target_total=8, target_related=5, target_adjacent=2, target_exploratory=1
    )

    assert len(selected) == 1
    assert selected[0].band == Band.EXPLORATORY
    assert counts["selectedByBand"] == {"related": 0, "adjacent": 0, "exploratory": 1}
    assert shortfall == "insufficient_candidates"


def test_corr_sel_03_missing_related_exact_ranks():
    """CORR-SEL-03 — Faltante related (3 related, 5 adjacent, 2 exploratory) -> orden por cupo de selección."""
    candidates = []
    # 3 related (IDs 1, 2, 3)
    for i in range(1, 4):
        candidates.append(make_cand(i, Band.RELATED, score=80.0 - i, yt_vid=f"vid_rel_{i}"))
    # 5 adjacent (IDs 4..8)
    for i in range(4, 9):
        candidates.append(make_cand(i, Band.ADJACENT, score=70.0 - i, yt_vid=f"vid_adj_{i}"))
    # 2 exploratory (IDs 9, 10)
    for i in range(9, 11):
        candidates.append(make_cand(i, Band.EXPLORATORY, score=60.0 - i, yt_vid=f"vid_exp_{i}"))

    selected, counts, shortfall = select_batch_diverse(
        candidates, target_total=8, target_related=5, target_adjacent=2, target_exploratory=1
    )

    assert len(selected) == 8
    # 3 related reales + 4 adjacent reales + 1 exploratory real
    assert counts["selectedByBand"] == {"related": 3, "adjacent": 4, "exploratory": 1}
    assert shortfall is None

    selected_vids = [c.youtube_video_id for c in selected]
    expected_vids = [
        "vid_rel_1", "vid_rel_2", "vid_rel_3", "vid_adj_6",
        "vid_adj_7", "vid_adj_4", "vid_adj_5", "vid_exp_9"
    ]
    assert selected_vids == expected_vids
    for idx, c in enumerate(selected, start=1):
        assert c.selection_rank == idx


def test_corr_sel_04_missing_adjacent_exact_ranks():
    """CORR-SEL-04 — Faltante adjacent (8 related, 0 adjacent, 2 exploratory) -> 7 rel + 1 exp = 8."""
    candidates = []
    for i in range(1, 9):
        candidates.append(make_cand(i, Band.RELATED, score=80.0 - i, yt_vid=f"vid_rel_{i}"))
    for i in range(9, 11):
        candidates.append(make_cand(i, Band.EXPLORATORY, score=60.0 - i, yt_vid=f"vid_exp_{i}"))

    selected, counts, shortfall = select_batch_diverse(
        candidates, target_total=8, target_related=5, target_adjacent=2, target_exploratory=1
    )

    assert len(selected) == 8
    assert counts["selectedByBand"] == {"related": 7, "adjacent": 0, "exploratory": 1}
    assert shortfall is None

    selected_vids = [c.youtube_video_id for c in selected]
    expected_vids = [
        "vid_rel_1", "vid_rel_2", "vid_rel_3", "vid_rel_4",
        "vid_rel_5", "vid_rel_6", "vid_rel_7", "vid_exp_9"
    ]
    assert selected_vids == expected_vids
    for idx, c in enumerate(selected, start=1):
        assert c.selection_rank == idx


def test_corr_sel_05_missing_exploratory_exact_ranks():
    """CORR-SEL-05 — Faltante exploratory (7 related, 3 adjacent, 0 exploratory) -> 5 rel + 3 adj = 8."""
    candidates = []
    for i in range(1, 8):
        candidates.append(make_cand(i, Band.RELATED, score=80.0 - i, yt_vid=f"vid_rel_{i}"))
    for i in range(8, 11):
        candidates.append(make_cand(i, Band.ADJACENT, score=70.0 - i, yt_vid=f"vid_adj_{i}"))

    selected, counts, shortfall = select_batch_diverse(
        candidates, target_total=8, target_related=5, target_adjacent=2, target_exploratory=1
    )

    assert len(selected) == 8
    assert counts["selectedByBand"] == {"related": 5, "adjacent": 3, "exploratory": 0}
    assert shortfall is None

    selected_vids = [c.youtube_video_id for c in selected]
    expected_vids = [
        "vid_rel_1", "vid_rel_2", "vid_rel_3", "vid_rel_4",
        "vid_rel_5", "vid_adj_8", "vid_adj_9", "vid_adj_10"
    ]
    assert selected_vids == expected_vids
    for idx, c in enumerate(selected, start=1):
        assert c.selection_rank == idx


def test_corr_sel_06_single_eligibility_boundary():
    """CORR-SEL-06 — Comprueba el flujo real: los candidatos por debajo del mínimo no superan el scoring."""
    signals = CategorySignals(
        category_id=1,
        positive_keywords=[("fotografia", 0.1)],  # Keyword débil 0.1 -> score 23.5 < 55.0
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
    v_low = {
        "youtube_video_id": "v_low",
        "title": "Fotografia de paisaje",
        "description": "desc",
        "thumbnail_url": "thumb",
        "channel_title": "Canal A",
        "youtube_channel_id": "c1",
        "published_at": "2026-07-30T10:00:00Z",
        "duration_seconds": 600,
        "content_type": "video"
    }

    cand = score_and_classify_candidate(v_low, signals, min_score_related=55.0)
    assert cand is None, "Candidato por debajo del mínimo debe retornar None en scoring"

    # El selector solo procesa candidatos elegibles no nulos
    eligible_candidates = [c for c in [cand] if c is not None]
    selected, _, _ = select_batch_diverse(eligible_candidates, target_total=8)
    assert len(selected) == 0


def test_corr_sel_07_max_per_channel():
    """CORR-SEL-07 — Máximo por canal configurable (1, 2, 3)."""
    candidates = []
    for i in range(1, 5):
        candidates.append(make_cand(i, Band.RELATED, score=90.0 - i, yt_cid="SAME_CHANNEL"))
    for i in range(5, 10):
        candidates.append(make_cand(i, Band.RELATED, score=70.0 - i, yt_cid=f"OTHER_{i}"))

    for max_ch in [1, 2, 3]:
        selected, _, _ = select_batch_diverse(
            candidates, target_total=8, max_videos_per_channel=max_ch
        )
        same_ch_count = sum(1 for c in selected if c.youtube_channel_id == "SAME_CHANNEL")
        assert same_ch_count == max_ch, f"Expected {max_ch} from SAME_CHANNEL, got {same_ch_count}"


def test_corr_sel_08_determinism_and_tied_duplicates():
    """CORR-SEL-08 — Determinismo total: permutaciones incluyendo duplicados empatados."""
    cand_a_related = make_cand(1, Band.RELATED, score=70.0, yt_vid="vid_DUP", published_at="2026-07-30T10:00:00Z")
    cand_a_adjacent = make_cand(2, Band.ADJACENT, score=70.0, yt_vid="vid_DUP", published_at="2026-07-30T10:00:00Z")

    base_cands = [
        cand_a_adjacent,  # Mismo vid_DUP pero adjacent
        cand_a_related,   # Mismo vid_DUP pero related (debe prevalecer related por jerarquía de banda)
        make_cand(3, Band.RELATED, score=70.0, yt_vid="vid_A", published_at="2026-07-30T10:00:00Z"),
        make_cand(4, Band.RELATED, score=70.0, yt_vid="vid_B", published_at="2026-07-30T10:00:00Z"),
        make_cand(5, Band.ADJACENT, score=60.0, yt_vid="vid_Z", published_at="2026-07-30T10:00:00Z"),
        make_cand(6, Band.ADJACENT, score=60.0, yt_vid="vid_X", published_at="2026-07-30T10:00:00Z"),
        make_cand(7, Band.EXPLORATORY, score=50.0, yt_vid="vid_M", published_at="2026-07-30T10:00:00Z")
    ]

    ref_selected, ref_counts, _ = select_batch_diverse(
        base_cands, target_total=5, target_related=3, target_adjacent=1, target_exploratory=1
    )
    ref_signature = [(c.youtube_video_id, c.band.value, c.selection_rank) for c in ref_selected]

    for seed in range(10):
        shuffled = list(base_cands)
        random.seed(seed)
        random.shuffle(shuffled)
        sel, _, _ = select_batch_diverse(
            shuffled, target_total=5, target_related=3, target_adjacent=1, target_exploratory=1
        )
        current_signature = [(c.youtube_video_id, c.band.value, c.selection_rank) for c in sel]
        assert current_signature == ref_signature, f"Seed {seed} produjo una ordenación distinta"

    # Verificar que para vid_DUP prevaleció la banda RELATED
    dup_cand = next(c for c in ref_selected if c.youtube_video_id == "vid_DUP")
    assert dup_cand.band == Band.RELATED


def test_corr_sel_09_invalid_config_raises_value_error():
    """CORR-SEL-09 — Configuración inválida lanza ValueError explícito."""
    # 1. Suma de cupos supera el total
    with pytest.raises(ValueError, match="sum of targets cannot exceed total"):
        SelectionConfig(total=2, related=5, adjacent=2, exploratory=1)

    with pytest.raises(ValueError, match="sum of targets cannot exceed total"):
        select_batch_diverse([], target_total=2, target_related=5, target_adjacent=2, target_exploratory=1)

    # 2. Total <= 0
    with pytest.raises(ValueError, match="total must be positive"):
        SelectionConfig(total=0, related=0, adjacent=0, exploratory=0)

    # 3. Cupos negativos
    with pytest.raises(ValueError, match="targets cannot be negative"):
        SelectionConfig(total=5, related=-1, adjacent=2, exploratory=1)

    # 4. max_per_channel <= 0
    with pytest.raises(ValueError, match="max_per_channel must be positive"):
        SelectionConfig(total=5, related=3, adjacent=1, exploratory=1, max_per_channel=0)

    # 5. Threshold de duplicados fuera de 0..1
    with pytest.raises(ValueError, match="duplicate_title_threshold must be between 0.0 and 1.0"):
        SelectionConfig(total=5, related=3, adjacent=1, exploratory=1, duplicate_title_threshold=1.5)
