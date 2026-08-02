import re
from typing import Dict, List, Optional, Set, Tuple

from app.domain.discovery.models import Band, DiscoveryCandidateDomain


def calculate_jaccard_similarity(title_a: str, title_b: str) -> float:
    """
    Calcula la similitud de Jaccard basada en raíces de palabras normalizadas
    para ignorar plurales/singulares y palabras de parada cortas.
    """
    from app.domain.discovery.normalization import normalize_term

    def get_stems(t: str) -> Set[str]:
        normalized = normalize_term(t)
        words = re.findall(r'\w+', normalized)
        stems = set()
        for w in words:
            if len(w) > 3:
                stems.add(w[:5])
        return stems

    stems_a = get_stems(title_a)
    stems_b = get_stems(title_b)

    if not stems_a or not stems_b:
        return 0.0

    intersection = stems_a.intersection(stems_b)
    union = stems_a.union(stems_b)
    return len(intersection) / len(union)

def sort_candidates_stable(candidates: List[DiscoveryCandidateDomain]) -> List[DiscoveryCandidateDomain]:
    """
    Ordena candidatos de forma estable:
    1. Score descendente.
    2. Fecha de publicación descendente (más recientes primero).
    3. YouTube Video ID descendente como desempate final.
    """
    # En Python, el ordenamiento es estable. Hacemos llaves múltiples:
    # Para ordenar desc, ordenamos por (-score, -published_at, -id)
    # published_at es un string ISO, por lo que podemos usar comparación lexicográfica inversa
    return sorted(
        candidates,
        key=lambda c: (c.score, c.published_at or "", c.youtube_video_id or ""),
        reverse=True
    )

def select_batch_diverse(
    candidates: List[DiscoveryCandidateDomain],
    target_total: int = 8,
    target_related: int = 5,
    target_adjacent: int = 2,
    target_exploratory: int = 1,
    max_videos_per_channel: int = 2,
    min_score_related: float = 55.0,
    min_score_adjacent: float = 45.0,
    min_score_exploratory: float = 35.0
) -> Tuple[List[DiscoveryCandidateDomain], dict, Optional[str]]:
    """
    Realiza la selección determinista y diversa del lote respetando la mezcla 5/2/1.
    Aplica límites de diversidad:
    - Máximo videos por canal (configurable).
    - Evita títulos duplicados (Jaccard > 0.7).
    Aplica la matriz de fallback en caso de escasez:
    - Faltante de related -> cubierto por adjacent. NUNCA por exploratory.
    - Faltante de adjacent -> cubierto por related. NUNCA por exploratory.
    - Faltante de exploratory -> cubierto por adjacent, luego related.
    """
    # 1. Separar por bandas y filtrar por puntajes mínimos configurados
    pool_related = [c for c in candidates if c.band == Band.RELATED and c.score >= min_score_related]
    pool_adjacent = [c for c in candidates if c.band == Band.ADJACENT and c.score >= min_score_adjacent]
    pool_exploratory = [c for c in candidates if c.band == Band.EXPLORATORY and c.score >= min_score_exploratory]

    # Ordenar cada pool de forma estable
    pool_related = sort_candidates_stable(pool_related)
    pool_adjacent = sort_candidates_stable(pool_adjacent)
    pool_exploratory = sort_candidates_stable(pool_exploratory)

    selected: List[DiscoveryCandidateDomain] = []
    channel_counts: Dict[str, int] = {}
    selected_titles: List[str] = []

    def is_eligible(c: DiscoveryCandidateDomain) -> bool:
        # Límite por canal
        if channel_counts.get(c.youtube_channel_id, 0) >= max_videos_per_channel:
            return False
        # Similitud de títulos
        for title in selected_titles:
            if calculate_jaccard_similarity(c.title, title) > 0.7:
                return False
        return True

    def add_to_selected(c: DiscoveryCandidateDomain):
        selected.append(c)
        channel_counts[c.youtube_channel_id] = channel_counts.get(c.youtube_channel_id, 0) + 1
        selected_titles.append(c.title)

    # 2. Selección inicial por banda
    # Related
    related_selected = 0
    remaining_related = []
    for c in pool_related:
        if related_selected < target_related and is_eligible(c):
            add_to_selected(c)
            related_selected += 1
        else:
            remaining_related.append(c)

    # Adjacent
    adjacent_selected = 0
    remaining_adjacent = []
    for c in pool_adjacent:
        if adjacent_selected < target_adjacent and is_eligible(c):
            add_to_selected(c)
            adjacent_selected += 1
        else:
            remaining_adjacent.append(c)

    # Exploratory
    exploratory_selected = 0
    remaining_exploratory = []
    for c in pool_exploratory:
        if exploratory_selected < target_exploratory and is_eligible(c):
            add_to_selected(c)
            exploratory_selected += 1
        else:
            remaining_exploratory.append(c)

    # 3. Aplicar matriz de Fallback
    # A) Si falta related: intentar rellenar con adjacent restantes (NUNCA con exploratory)
    if related_selected < target_related:
        needed = target_related - related_selected
        fallback_added = 0
        still_remaining_adjacent = []
        for c in remaining_adjacent:
            if fallback_added < needed and is_eligible(c):
                add_to_selected(c)
                fallback_added += 1
            else:
                still_remaining_adjacent.append(c)
        remaining_adjacent = still_remaining_adjacent
        related_selected += fallback_added

    # B) Si falta adjacent: intentar rellenar con related restantes (NUNCA con exploratory)
    if adjacent_selected < target_adjacent:
        needed = target_adjacent - adjacent_selected
        fallback_added = 0
        still_remaining_related = []
        for c in remaining_related:
            if fallback_added < needed and is_eligible(c):
                add_to_selected(c)
                fallback_added += 1
            else:
                still_remaining_related.append(c)
        remaining_related = still_remaining_related
        adjacent_selected += fallback_added

    # C) Si falta exploratory: intentar rellenar con adjacent restantes, luego con related restantes
    if exploratory_selected < target_exploratory:
        needed = target_exploratory - exploratory_selected
        fallback_added = 0

        # Primero de adjacent restante
        still_remaining_adjacent = []
        for c in remaining_adjacent:
            if fallback_added < needed and is_eligible(c):
                add_to_selected(c)
                fallback_added += 1
            else:
                still_remaining_adjacent.append(c)
        remaining_adjacent = still_remaining_adjacent
        exploratory_selected += fallback_added

        # Luego de related restante
        if fallback_added < needed:
            still_remaining_related = []
            for c in remaining_related:
                if fallback_added < needed and is_eligible(c):
                    add_to_selected(c)
                    fallback_added += 1
                else:
                    still_remaining_related.append(c)
            remaining_related = still_remaining_related
            exploratory_selected += fallback_added

    # Asignar selection_rank (1-based index)
    for index, c in enumerate(selected):
        c.selection_rank = index + 1

    # Construir resumen de contadores por banda
    counts_dict = {
        "targetByBand": {
            "related": target_related,
            "adjacent": target_adjacent,
            "exploratory": target_exploratory
        },
        "selectedByBand": {
            "related": len([c for c in selected if c.band == Band.RELATED]),
            "adjacent": len([c for c in selected if c.band == Band.ADJACENT]),
            "exploratory": len([c for c in selected if c.band == Band.EXPLORATORY])
        }
    }

    # Determinar shortfall_reason si no se completó el lote
    shortfall_reason = None
    if len(selected) < target_total:
        shortfall_reason = "insufficient_candidates"

    return selected, counts_dict, shortfall_reason
