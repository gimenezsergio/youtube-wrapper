from typing import Any, Dict, List, Tuple

from app.domain.discovery.models import Band
from app.domain.discovery.signals import CategorySignals


def clean_term_for_search(term: str) -> str:
    """Remueve caracteres problemáticos de búsqueda de YouTube, manteniendo letras y números."""
    import re
    return re.sub(r'[^a-zA-Z0-9ñÑáéíóúÁÉÍÓÚüÜ ]', '', term).strip()

def build_queries_for_category(signals: CategorySignals, max_queries: int = 2) -> List[Dict[str, Any]]:
    """
    Genera hasta `max_queries` consultas para una categoría.
    - Consulta 1 (related): Palabras clave positivas + exclusión de negativas.
    - Consulta 2 (adjacent/exploratory): Ancla de palabras clave + temas de exploración aprobados.
    """
    queries = []
    negative_part = ""

    # Construir exclusiones negativas (ej: "-noterm1 -noterm2")
    if signals.negative_keywords:
        neg_terms = []
        for nk in signals.negative_keywords:
            cleaned = clean_term_for_search(nk)
            if cleaned:
                neg_terms.append(f"-{cleaned}")
        negative_part = " " + " ".join(neg_terms)

    # 1. Consulta 'related' (Búsqueda principal)
    # Combinar palabras clave positivas ordenadas por peso desc
    pos_keywords = sorted(signals.positive_keywords, key=lambda x: x[1], reverse=True)
    if pos_keywords:
        terms_to_include = []
        # Agregamos las palabras clave principales que quepan en 100 caracteres (dejando espacio para las negativas)
        current_len = len(negative_part)
        for term, weight in pos_keywords:
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

    # Si aún no tenemos consulta, intentar con títulos de canales semilla o videos vistos
    if not queries and (signals.seed_channel_titles or signals.positive_video_titles):
        seeds = signals.seed_channel_titles + signals.positive_video_titles
        # Tomar el más importante
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

    # 2. Consulta 'adjacent' (Si hay temas de exploración aprobados y tenemos espacio para más consultas)
    if len(queries) < max_queries and signals.approved_exploration_topics and pos_keywords:
        # Tomar la palabra clave con más peso como ancla
        anchor = clean_term_for_search(pos_keywords[0][0])

        # Tomar temas aprobados
        topics = sorted(signals.approved_exploration_topics, key=lambda x: x[1], reverse=True)
        for topic_term, topic_weight in topics:
            cleaned_topic = clean_term_for_search(topic_term)
            if anchor and cleaned_topic:
                q_str = f"{anchor} {cleaned_topic}" + negative_part
                queries.append({
                    "q": q_str.strip()[:100],
                    "band": Band.ADJACENT,
                    "source": f"adjacent_topic:{topic_term}",
                    "explanation": f"Cruce temático de '{anchor}' con '{topic_term}'"
                })
                if len(queries) >= max_queries:
                    break

    return queries

def schedule_queries_round_robin(
    category_queries: Dict[int, List[Dict[str, Any]]],
    global_budget: int = 10,
    max_per_category: int = 2
) -> List[Tuple[int, Dict[str, Any]]]:
    """
    Planifica consultas en round-robin.
    Retorna una lista de tuplas (category_id, query_dict).
    """
    scheduled = []
    # Copia de las consultas por categoría
    queries_pool = {cat_id: list(q_list[:max_per_category]) for cat_id, q_list in category_queries.items()}

    # Lista de categorías ordenadas para round-robin
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
