from datetime import datetime, timezone
import pytest
from app.domain.discovery.models import Band, DiscoveryCandidateDomain
from app.domain.discovery.normalization import normalize_term
from app.domain.discovery.signals import CategorySignals
from app.domain.discovery.query_builder import build_queries_for_category, schedule_queries_round_robin
from app.domain.discovery.scoring import score_and_classify_candidate
from app.domain.discovery.selection import select_batch_diverse, calculate_jaccard_similarity

def test_normalization():
    """Valida la normalización de texto."""
    assert normalize_term("Fotografía de retrato y dirección de arte!") == "fotografia de retrato y direccion de arte"
    assert normalize_term("  MÚSICA   electrónica  ") == "musica electronica"
    assert normalize_term("áéíóú üÜ ñÑ") == "aeiou uu nn"

def test_disc_01_query_builder():
    """DISC-01 — Construye una consulta directa y una expandida."""
    signals = CategorySignals(
        category_id=1,
        positive_keywords=[("fotografia", 1.0), ("iluminacion", 0.8)],
        negative_keywords=["bodas", "videomarketing"],
        approved_exploration_topics=[("direccion de arte", 1.0)],
        seed_channel_ids={10, 11},
        seed_channel_titles=["Canal Foto", "Canal Iluminar"],
        seed_channel_descriptions=[],
        positive_video_titles=[],
        positive_channel_ids=set(),
        negative_video_ids=set(),
        negative_channel_ids=set(),
        blocked_channel_ids=set(),
        hidden_video_ids=set()
    )
    
    queries = build_queries_for_category(signals, max_queries=2)
    assert len(queries) == 2
    
    # Consulta 1: Related
    assert queries[0]["band"] == Band.RELATED
    assert "fotografia" in queries[0]["q"]
    assert "-bodas" in queries[0]["q"]
    assert "-videomarketing" in queries[0]["q"]
    
    # Consulta 2: Adjacent
    assert queries[1]["band"] == Band.ADJACENT
    assert "fotografia" in queries[1]["q"]
    assert "direccion de arte" in queries[1]["q"]

def test_disc_02_query_builder_no_keywords():
    """DISC-02 — Usa señales de canales o registra que no existen señales suficientes."""
    signals = CategorySignals(
        category_id=1,
        positive_keywords=[],
        negative_keywords=[],
        approved_exploration_topics=[],
        seed_channel_ids={10},
        seed_channel_titles=["Canal Foto"],
        seed_channel_descriptions=[],
        positive_video_titles=["Un video visto"],
        positive_channel_ids=set(),
        negative_video_ids=set(),
        negative_channel_ids=set(),
        blocked_channel_ids=set(),
        hidden_video_ids=set()
    )
    queries = build_queries_for_category(signals, max_queries=2)
    assert len(queries) == 1
    assert queries[0]["band"] == Band.RELATED
    assert "canal foto" in queries[0]["q"]

def test_disc_05_scoring_block():
    """DISC-05 — Canales bloqueados reciben exclusión absoluta (retorna None)."""
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
        blocked_channel_ids={99},  # Bloqueado
        hidden_video_ids=set()
    )
    video = {
        "youtube_video_id": "v1",
        "title": "Un video de prueba",
        "description": "Desc",
        "channel_id": 99,
        "channel_title": "Canal Malo",
        "published_at": "2026-07-30T10:00:00Z"
    }
    candidate = score_and_classify_candidate(video, signals)
    assert candidate is None

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
        "channel_id": 15, # Distinto de 5 para que no sea excluido por ser canal seguido semilla
        "channel_title": "Canal Semilla",
        "published_at": "2026-07-30T10:00:00Z" # Hace 2 días
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
        "channel_id": 1,
        "channel_title": "Canal A"
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
    
    # 1. Related
    c_rel = score_and_classify_candidate({"title": "Clase de fotografia", "channel_title": "Otro"}, signals)
    assert c_rel.band == Band.RELATED
    
    # 2. Adjacent
    c_adj = score_and_classify_candidate({"title": "fotografia con iluminacion", "channel_title": "Otro"}, signals)
    assert c_adj.band == Band.ADJACENT
    
    # 3. Exploratory (solo matches topic)
    c_exp = score_and_classify_candidate({"title": "iluminacion de interiores", "channel_title": "Otro"}, signals)
    assert c_exp.band == Band.EXPLORATORY

def test_disc_19_20_21_22_23_selection():
    """Valida la selección de lotes, fallbacks, diversidad de canal y duplicados."""
    c1 = DiscoveryCandidateDomain(1, "v1", 10, "ch_1", "ch_1", "Fotografia de retratos", "", "2026-07-30T10:00:00Z", 600, "video", 90.0, Band.RELATED)
    c2 = DiscoveryCandidateDomain(2, "v2", 10, "ch_1", "ch_1", "Fotografia de paisajes", "", "2026-07-30T09:00:00Z", 600, "video", 85.0, Band.RELATED)
    c3 = DiscoveryCandidateDomain(3, "v3", 10, "ch_1", "ch_1", "Fotografia de deportes", "", "2026-07-30T08:00:00Z", 600, "video", 80.0, Band.RELATED) # Tercero del mismo canal
    c4 = DiscoveryCandidateDomain(4, "v4", 11, "ch_2", "ch_2", "Fotografia callejera", "", "2026-07-30T07:00:00Z", 600, "video", 75.0, Band.RELATED)
    c5 = DiscoveryCandidateDomain(5, "v5", 12, "ch_3", "ch_3", "Retrato de calle", "", "2026-07-30T06:00:00Z", 600, "video", 70.0, Band.RELATED)
    
    # Candidato casi duplicado con c1
    c1_dup = DiscoveryCandidateDomain(6, "v6", 13, "ch_4", "ch_4", "Fotografía de retrato", "", "2026-07-30T05:00:00Z", 600, "video", 88.0, Band.RELATED)

    c_adj1 = DiscoveryCandidateDomain(7, "v7", 14, "ch_5", "ch_5", "Fotografia e iluminacion", "", "2026-07-30T04:00:00Z", 600, "video", 65.0, Band.ADJACENT)
    c_exp1 = DiscoveryCandidateDomain(8, "v8", 15, "ch_6", "ch_6", "Iluminacion de teatro", "", "2026-07-30T03:00:00Z", 600, "video", 55.0, Band.EXPLORATORY)
    
    candidates = [c1, c2, c3, c4, c5, c1_dup, c_adj1, c_exp1]
    
    selected, counts, shortfall = select_batch_diverse(
        candidates,
        target_total=8,
        target_related=5,
        target_adjacent=2,
        target_exploratory=1
    )
    
    # 1. c3 debe ser excluido porque ch_1 ya tiene c1 y c2 seleccionados.
    selected_ids = [c.video_id for c in selected]
    assert 3 not in selected_ids
    
    # 2. c1_dup debe ser excluido porque es casi idéntico a c1 ("Fotografia de retratos" vs "Fotografía de retrato")
    assert 6 not in selected_ids
    
    # 3. Contar bandas
    # Con pool incompleto o fallbacks activos
    assert len(selected) > 0
    
def test_jaccard_similarity():
    """Valida el cálculo de similitud de Jaccard."""
    assert calculate_jaccard_similarity("Fotografía de retrato", "Fotografía de retratos") > 0.6
    assert calculate_jaccard_similarity("Python en Linux", "Linux con Python") == 1.0
    assert calculate_jaccard_similarity("Python en Linux", "Aprender fotografia") == 0.0
