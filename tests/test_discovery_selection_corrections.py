import random

from app.domain.discovery.models import Band, DiscoveryCandidateDomain
from app.domain.discovery.selection import select_batch_diverse


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


def test_corr_sel_03_missing_related():
    """CORR-SEL-03 — Faltante related (3 related, 5 adjacent, 2 exploratory) -> 3 rel + 4 adj + 1 exp = 8."""
    candidates = []
    for i in range(1, 4):
        candidates.append(make_cand(i, Band.RELATED, score=80.0 - i))
    for i in range(4, 9):
        candidates.append(make_cand(i, Band.ADJACENT, score=70.0 - i))
    for i in range(9, 11):
        candidates.append(make_cand(i, Band.EXPLORATORY, score=60.0 - i))

    selected, counts, shortfall = select_batch_diverse(
        candidates, target_total=8, target_related=5, target_adjacent=2, target_exploratory=1
    )

    assert len(selected) == 8
    assert counts["selectedByBand"] == {"related": 3, "adjacent": 4, "exploratory": 1}
    assert shortfall is None


def test_corr_sel_04_missing_adjacent():
    """CORR-SEL-04 — Faltante adjacent (8 related, 0 adjacent, 2 exploratory) -> 7 rel + 1 exp = 8."""
    candidates = []
    for i in range(1, 9):
        candidates.append(make_cand(i, Band.RELATED, score=80.0 - i))
    for i in range(9, 11):
        candidates.append(make_cand(i, Band.EXPLORATORY, score=60.0 - i))

    selected, counts, shortfall = select_batch_diverse(
        candidates, target_total=8, target_related=5, target_adjacent=2, target_exploratory=1
    )

    assert len(selected) == 8
    assert counts["selectedByBand"] == {"related": 7, "adjacent": 0, "exploratory": 1}
    assert shortfall is None


def test_corr_sel_05_missing_exploratory():
    """CORR-SEL-05 — Faltante exploratory (7 related, 3 adjacent, 0 exploratory) -> 5 rel + 3 adj = 8."""
    candidates = []
    for i in range(1, 8):
        candidates.append(make_cand(i, Band.RELATED, score=80.0 - i))
    for i in range(8, 11):
        candidates.append(make_cand(i, Band.ADJACENT, score=70.0 - i))

    selected, counts, shortfall = select_batch_diverse(
        candidates, target_total=8, target_related=5, target_adjacent=2, target_exploratory=1
    )

    assert len(selected) == 8
    assert counts["selectedByBand"] == {"related": 5, "adjacent": 3, "exploratory": 0}
    assert shortfall is None


def test_corr_sel_06_below_minimum_excluded():
    """CORR-SEL-06 — Candidatos por debajo del umbral mínimo se excluyen de la selección."""
    # Candidatos con scores por debajo de los mínimos configurados
    c_rel = make_cand(1, Band.RELATED, score=54.999)
    c_adj = make_cand(2, Band.ADJACENT, score=44.999)
    c_exp = make_cand(3, Band.EXPLORATORY, score=34.999)

    selected, _, _ = select_batch_diverse(
        [c_rel, c_adj, c_exp],
        target_total=8,
        min_score_related=55.0,
        min_score_adjacent=45.0,
        min_score_exploratory=35.0
    )

    assert len(selected) == 0, "Candidatos con score por debajo del umbral no deben ser seleccionados"


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


def test_corr_sel_08_determinism():
    """CORR-SEL-08 — Determinismo: 10 permutaciones de entrada producen exactamente los mismos IDs y ranks."""
    # Crear candidatos con empates de score y fecha
    base_cands = [
        make_cand(1, Band.RELATED, score=70.0, yt_vid="vid_C"),
        make_cand(2, Band.RELATED, score=70.0, yt_vid="vid_A"),
        make_cand(3, Band.RELATED, score=70.0, yt_vid="vid_B"),
        make_cand(4, Band.ADJACENT, score=60.0, yt_vid="vid_Z"),
        make_cand(5, Band.ADJACENT, score=60.0, yt_vid="vid_X"),
        make_cand(6, Band.EXPLORATORY, score=50.0, yt_vid="vid_M")
    ]

    reference_selected, _, _ = select_batch_diverse(base_cands, target_total=5)
    ref_ids_and_ranks = [(c.youtube_video_id, c.selection_rank) for c in reference_selected]

    for seed in range(10):
        shuffled = list(base_cands)
        random.seed(seed)
        random.shuffle(shuffled)
        sel, _, _ = select_batch_diverse(shuffled, target_total=5)
        current_ids_and_ranks = [(c.youtube_video_id, c.selection_rank) for c in sel]
        assert current_ids_and_ranks == ref_ids_and_ranks, f"Permutation seed {seed} produced different result"

    # Verificación del desempate por ID ascendente para empates de score y fecha: vid_A < vid_B < vid_C
    rel_selected_ids = [c.youtube_video_id for c in reference_selected if c.band == Band.RELATED]
    assert rel_selected_ids[:3] == ["vid_A", "vid_B", "vid_C"]


def test_corr_sel_09_duplicates_and_title_similarity():
    """CORR-SEL-09 — Duplicados de ID se filtran y títulos similares no desplazan a un candidato diverso."""
    # A) Mismo youtube_video_id no se incluye 2 veces
    c1 = make_cand(1, Band.RELATED, score=80.0, yt_vid="SAME_VID")
    c1_dup = make_cand(1, Band.RELATED, score=75.0, yt_vid="SAME_VID")
    c2 = make_cand(2, Band.RELATED, score=70.0, yt_vid="OTHER_VID")

    sel_dup, _, _ = select_batch_diverse([c1, c1_dup, c2], target_total=5)
    vids = [c.youtube_video_id for c in sel_dup]
    assert vids.count("SAME_VID") == 1

    # B) Títulos similares no desplazan a candidato diverso
    t1 = make_cand(10, Band.RELATED, score=85.0, title="Curso Completo de Fotografia Digital")
    t2 = make_cand(11, Band.RELATED, score=84.0, title="Curso Completo de Fotografia Digital 2026") # Jaccard > 0.70
    t3 = make_cand(12, Band.RELATED, score=80.0, title="Direccion de Arte en el Cine Contemporaneo") # Diverso

    sel_title, _, _ = select_batch_diverse(
        [t1, t2, t3], target_total=2, target_related=2, duplicate_title_threshold=0.70
    )
    title_ids = [c.video_id for c in sel_title]
    assert 10 in title_ids
    assert 12 in title_ids, "Candidato diverso t3 (12) no debió ser desplazado por el duplicado t2 (11)"
    assert 11 not in title_ids
