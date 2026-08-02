import pytest
from app.domain.discovery.models import Band, DiscoveryCandidateDomain
from app.domain.discovery.selection import select_batch_diverse

def test_corr_sel_02_only_exploratory():
    """CORR-SEL-02 — Con 8 exploratory elegibles, se selecciona máximo el cupo exploratorio (1) y no deriva a related/adjacent."""
    candidates = []
    for i in range(8):
        c = DiscoveryCandidateDomain(
            video_id=i+1,
            youtube_video_id=f"vid_exp_{i}",
            channel_id=1,
            youtube_channel_id=f"chan_{i}",
            channel_title="Canal",
            title=f"Tema de exploracion {i}",
            description="desc",
            published_at="2026-07-30T10:00:00Z",
            duration_seconds=600,
            content_type="video",
            score=50.0,
            band=Band.EXPLORATORY,
            reasons=["Tema de exploracion"]
        )
        candidates.append(c)

    selected, counts, shortfall = select_batch_diverse(
        candidates,
        target_total=8,
        target_related=5,
        target_adjacent=2,
        target_exploratory=1,
        max_videos_per_channel=2
    )

    assert len(selected) == 1, f"Should select exactly 1 exploratory candidate, got {len(selected)}"
    assert selected[0].band == Band.EXPLORATORY
    assert counts["selectedByBand"]["exploratory"] == 1
    assert counts["selectedByBand"]["related"] == 0
    assert counts["selectedByBand"]["adjacent"] == 0
    assert shortfall == "insufficient_candidates"
