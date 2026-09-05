import re
from typing import Any, Dict, List, Tuple

from app.domain.discovery.models import Band
from app.domain.discovery.signals import CategorySignals


def clean_term_for_search(term: str) -> str:
    """Remueve caracteres problemáticos de búsqueda de YouTube, manteniendo letras y números."""
    return re.sub(r'[^a-zA-Z0-9ñÑáéíóúÁÉÍÓÚüÜ ]', '', term).strip()


def _build_negative_part(signals: CategorySignals) -> str:
    """Construye las exclusiones negativas (ej: "-noterm1 -noterm2")."""
    if not signals.negative_keywords:
        return ""
    neg_terms = []
    for nk in signals.negative_keywords:
        cleaned = clean_term_for_search(nk)
        if cleaned:
            neg_terms.append(f"-{cleaned}")
    return (" " + " ".join(neg_terms)) if neg_terms else ""


def _build_related_query(signals: CategorySignals, negative_part: str) -> List[Dict[str, Any]]:
    """Construye la consulta 'related' principal basada en palabras clave o semillas."""
    queries = []
    pos_keywords = sorted(signals.positive_keywords, key=lambda x: x[1], reverse=True)
    if pos_keywords:
        terms_to_include = []
        current_len = len(negative_part)
        for term, _weight in pos_keywords:
            cleaned = clean_term_for_search(term)
            if not cleaned:
                continue
            if current_len + len(cleaned) + 1 <= 100:
                terms_to_include.append(cleaned)
                current_len += len(cleaned) + 1
            else:
                break

        if terms_to_include:
            q_str = " ".join(terms_to_include) + negative_part
            queries.append({
                "q": q_str.strip()[:100],
                "band": Band.RELATED,
                "source": "keywords",
                "explanation": f"Basado en palabras clave de la categoría: {', '.join(terms_to_include[:3])}"
            })

    if not queries and (signals.seed_channel_titles or signals.positive_video_titles):
        seeds = signals.seed_channel_titles + signals.positive_video_titles
        for seed in seeds:
            cleaned = clean_term_for_search(seed)
            if cleaned:
                q_str = cleaned + negative_part
                queries.append({
                    "q": q_str.strip()[:100],
                    "band": Band.RELATED,
                    "source": "seeds",
                    "explanation": f"Basado en canal o video de la categoría: {cleaned}"
                })
                break

    return queries


def _build_adjacent_queries(
    signals: CategorySignals, negative_part: str, max_queries: int, current_queries_count: int
) -> List[Dict[str, Any]]:
    """Construye consultas 'adjacent' basadas en cruces temáticos."""
    queries = []
    pos_keywords = sorted(signals.positive_keywords, key=lambda x: x[1], reverse=True)
    if current_queries_count < max_queries and signals.approved_exploration_topics and pos_keywords:
        anchor = clean_term_for_search(pos_keywords[0][0])
        topics = sorted(signals.approved_exploration_topics, key=lambda x: x[1], reverse=True)
        for topic_term, _topic_weight in topics:
            cleaned_topic = clean_term_for_search(topic_term)
            if anchor and cleaned_topic:
                q_str = f"{anchor} {cleaned_topic}" + negative_part
                queries.append({
                    "q": q_str.strip()[:100],
                    "band": Band.ADJACENT,
                    "source": f"adjacent_topic:{topic_term}",
                    "explanation": f"Cruce temático de '{anchor}' con '{topic_term}'"
                })
                if current_queries_count + len(queries) >= max_queries:
                    break
    return queries


def build_queries_for_category(signals: CategorySignals, max_queries: int = 2) -> List[Dict[str, Any]]:
    """Genera hasta `max_queries` consultas para una categoría."""
    negative_part = _build_negative_part(signals)
    queries = _build_related_query(signals, negative_part)
    adjacent = _build_adjacent_queries(signals, negative_part, max_queries, len(queries))
    queries.extend(adjacent)
    return queries


def schedule_queries_round_robin(
    category_queries: Dict[int, List[Dict[str, Any]]],
    global_budget: int = 10,
    max_per_category: int = 2
) -> List[Tuple[int, Dict[str, Any]]]:
    """Planifica consultas en round-robin."""
    scheduled = []
    queries_pool = {cat_id: list(q_list[:max_per_category]) for cat_id, q_list in category_queries.items()}
    cat_ids = sorted(list(queries_pool.keys()))

    any_added = True
    while len(scheduled) < global_budget and any_added:
        any_added = False
        for cat_id in cat_ids:
            if len(scheduled) >= global_budget:
                break
            if queries_pool[cat_id]:
                q = queries_pool[cat_id].pop(0)
                scheduled.append((cat_id, q))
                any_added = True

    return scheduled
