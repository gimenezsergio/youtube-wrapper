from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.domain.discovery.models import Band, DiscoveryCandidateDomain
from app.domain.discovery.normalization import normalize_term


class SelectionConfig:
    """Configuración inmutable y validada para la selección de descubrimientos."""

    def __init__(
        self,
        total: int = 8,
        related: int = 5,
        adjacent: int = 2,
        exploratory: int = 1,
        max_per_channel: int = 2,
        duplicate_title_threshold: float = 0.70,
    ):
        if total <= 0:
            raise ValueError("total must be positive")
        if related < 0 or adjacent < 0 or exploratory < 0:
            raise ValueError("targets cannot be negative")
        if related + adjacent + exploratory > total:
            raise ValueError("sum of targets cannot exceed total")
        if max_per_channel <= 0:
            raise ValueError("max_per_channel must be positive")
        if not (0.0 <= duplicate_title_threshold <= 1.0):
            raise ValueError("duplicate_title_threshold must be between 0.0 and 1.0")

        self.total = total
        self.related = related
        self.adjacent = adjacent
        self.exploratory = exploratory
        self.max_per_channel = max_per_channel
        self.duplicate_title_threshold = duplicate_title_threshold


def _stem_word(word: str) -> str:
    if len(word) > 3 and word.endswith("es"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


STOP_WORDS = {
    "de", "del", "la", "las", "el", "los", "en", "y", "a", "o", "con", "un", "una", "unos", "unas", "por", "para"
}


def calculate_jaccard_similarity(text1: str, text2: str) -> float:
    """Calcula la similitud de Jaccard de conjuntos de tokens entre dos textos normalizados."""
    norm1 = normalize_term(text1)
    norm2 = normalize_term(text2)
    tokens1 = {_stem_word(w) for w in norm1.split() if w not in STOP_WORDS}
    tokens2 = {_stem_word(w) for w in norm2.split() if w not in STOP_WORDS}
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)


def _get_sort_key(c: DiscoveryCandidateDomain) -> Tuple[float, float, str]:
    """Genera la clave de ordenamiento determinista: (-score, -published_at_ts, youtube_video_id_asc)."""
    ts = 0.0
    if c.published_at:
        try:
            pub_str = c.published_at.replace("Z", "+00:00")
            ts = datetime.fromisoformat(pub_str).timestamp()
        except Exception:
            pass
    return (-c.score, -ts, c.youtube_video_id)


def _can_add_candidate(
    candidate: DiscoveryCandidateDomain,
    selected: List[DiscoveryCandidateDomain],
    max_per_channel: int,
    duplicate_title_threshold: float,
) -> bool:
    """Verifica si un candidato respeta el límite por canal y la diversidad de títulos."""
    channel_key = candidate.youtube_channel_id or candidate.channel_id
    channel_count = sum(
        1 for s in selected if (s.youtube_channel_id or s.channel_id) == channel_key
    )
    if channel_count >= max_per_channel:
        return False

    for s in selected:
        if calculate_jaccard_similarity(candidate.title, s.title) >= duplicate_title_threshold:
            return False

    return True


def _prepare_pools(
    candidates: List[DiscoveryCandidateDomain],
    min_related: float,
    min_adjacent: float,
    min_exploratory: float,
) -> Tuple[List[DiscoveryCandidateDomain], List[DiscoveryCandidateDomain], List[DiscoveryCandidateDomain]]:
    """Filtra y prepara las tres listas de candidatos por banda real ordenadas determinísticamente."""
    unique_by_id: Dict[str, DiscoveryCandidateDomain] = {}
    for c in candidates:
        if c.band == Band.RELATED and c.score < min_related:
            continue
        if c.band == Band.ADJACENT and c.score < min_adjacent:
            continue
        if c.band == Band.EXPLORATORY and c.score < min_exploratory:
            continue

        vid = c.youtube_video_id
        if vid not in unique_by_id or _get_sort_key(c) < _get_sort_key(unique_by_id[vid]):
            unique_by_id[vid] = c

    pool_rel = sorted(
        [c for c in unique_by_id.values() if c.band == Band.RELATED], key=_get_sort_key
    )
    pool_adj = sorted(
        [c for c in unique_by_id.values() if c.band == Band.ADJACENT], key=_get_sort_key
    )
    pool_exp = sorted(
        [c for c in unique_by_id.values() if c.band == Band.EXPLORATORY], key=_get_sort_key
    )
    return pool_rel, pool_adj, pool_exp


def _fill_quota(
    pool: List[DiscoveryCandidateDomain],
    target_count: int,
    target_list: List[DiscoveryCandidateDomain],
    all_selected: List[DiscoveryCandidateDomain],
    config: SelectionConfig,
) -> List[DiscoveryCandidateDomain]:
    """Llena un cupo primario retornando los elementos no utilizados."""
    remanentes = []
    for c in pool:
        if len(target_list) < target_count and len(all_selected) < config.total:
            if _can_add_candidate(c, all_selected, config.max_per_channel, config.duplicate_title_threshold):
                target_list.append(c)
                all_selected.append(c)
            else:
                remanentes.append(c)
        else:
            remanentes.append(c)
    return remanentes


def _apply_fallback_step(
    rem_source: List[DiscoveryCandidateDomain],
    needed_count: int,
    target_list: List[DiscoveryCandidateDomain],
    all_selected: List[DiscoveryCandidateDomain],
    config: SelectionConfig,
) -> Tuple[List[DiscoveryCandidateDomain], int]:
    """Aplica un paso de la matriz de fallback."""
    still_remanente = []
    for c in rem_source:
        if needed_count > 0 and len(all_selected) < config.total:
            if _can_add_candidate(c, all_selected, config.max_per_channel, config.duplicate_title_threshold):
                target_list.append(c)
                all_selected.append(c)
                needed_count -= 1
            else:
                still_remanente.append(c)
        else:
            still_remanente.append(c)
    return still_remanente, needed_count


def select_batch_diverse(
    candidates: List[DiscoveryCandidateDomain],
    target_total: int = 8,
    target_related: int = 5,
    target_adjacent: int = 2,
    target_exploratory: int = 1,
    max_videos_per_channel: int = 2,
    duplicate_title_threshold: float = 0.70,
    min_score_related: float = 0.0,
    min_score_adjacent: float = 0.0,
    min_score_exploratory: float = 0.0,
) -> Tuple[List[DiscoveryCandidateDomain], Dict[str, Any], Optional[str]]:
    """
    Selecciona un lote diverso y determinista de candidatos aplicando la matriz de fallback estricta.
    """
    rel, adj, exp = target_related, target_adjacent, target_exploratory
    if rel + adj + exp > target_total:
        rel = min(rel, target_total)
        adj = min(adj, max(0, target_total - rel))
        exp = min(exp, max(0, target_total - rel - adj))

    config = SelectionConfig(
        total=target_total,
        related=rel,
        adjacent=adj,
        exploratory=exp,
        max_per_channel=max_videos_per_channel,
        duplicate_title_threshold=duplicate_title_threshold,
    )

    pool_rel, pool_adj, pool_exp = _prepare_pools(
        candidates, min_score_related, min_score_adjacent, min_score_exploratory
    )

    selected_rel: List[DiscoveryCandidateDomain] = []
    selected_adj: List[DiscoveryCandidateDomain] = []
    selected_exp: List[DiscoveryCandidateDomain] = []
    all_selected: List[DiscoveryCandidateDomain] = []

    # 1. Fase Primaria
    rem_rel = _fill_quota(pool_rel, config.related, selected_rel, all_selected, config)
    rem_adj = _fill_quota(pool_adj, config.adjacent, selected_adj, all_selected, config)
    _ = _fill_quota(pool_exp, config.exploratory, selected_exp, all_selected, config)

    # 2. Matriz de Fallback Estricta
    # A) Faltante related -> cubierto únicamente con adjacent remanente
    needed_rel = config.related - len(selected_rel)
    rem_adj, _ = _apply_fallback_step(rem_adj, needed_rel, selected_rel, all_selected, config)

    # B) Faltante adjacent -> cubierto únicamente con related remanente
    needed_adj = config.adjacent - len(selected_adj)
    rem_rel, _ = _apply_fallback_step(rem_rel, needed_adj, selected_adj, all_selected, config)

    # C) Faltante exploratory -> cubierto primero con adjacent remanente, luego related remanente
    needed_exp = config.exploratory - len(selected_exp)
    if needed_exp > 0:
        rem_adj, needed_exp = _apply_fallback_step(rem_adj, needed_exp, selected_exp, all_selected, config)
    if needed_exp > 0:
        rem_rel, needed_exp = _apply_fallback_step(rem_rel, needed_exp, selected_exp, all_selected, config)

    # 3. Asignar Ranks Consecutivos
    for idx, c in enumerate(all_selected, start=1):
        c.selection_rank = idx

    # 4. Contar selectedByBand por la BANDA REAL del candidato
    counts = {
        "targetByBand": {
            "related": config.related,
            "adjacent": config.adjacent,
            "exploratory": config.exploratory,
        },
        "selectedByBand": {
            "related": sum(1 for c in all_selected if c.band == Band.RELATED),
            "adjacent": sum(1 for c in all_selected if c.band == Band.ADJACENT),
            "exploratory": sum(1 for c in all_selected if c.band == Band.EXPLORATORY),
        },
    }

    shortfall = "insufficient_candidates" if len(all_selected) < config.total else None
    return all_selected, counts, shortfall
