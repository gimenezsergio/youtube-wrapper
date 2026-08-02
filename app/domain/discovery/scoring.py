from datetime import datetime, timezone
from typing import Optional, Tuple

from app.domain.discovery.models import Band, DiscoveryCandidateDomain
from app.domain.discovery.normalization import normalize_term
from app.domain.discovery.signals import CategorySignals


def clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Limita un valor dentro de un rango determinado."""
    return max(min_val, min(max_val, value))


def _check_exclusions(video: dict, signals: CategorySignals, norm_title: str, norm_desc: str) -> bool:
    """Retorna True si el video debe ser excluido antes de ser puntuado."""
    duration = video.get("duration_seconds")
    if duration is not None and duration <= 180:
        return True
    if "duration_seconds" in video and video["duration_seconds"] is None:
        return True

    channel_id = video.get("channel_id")
    youtube_channel_id = video.get("youtube_channel_id", "")
    video_id = video.get("video_id")

    if channel_id and channel_id in signals.blocked_channel_ids:
        return True

    if video_id and video_id in signals.hidden_video_ids:
        return True

    if video_id and video_id in signals.watched_video_ids:
        return True

    if channel_id and (channel_id in signals.followed_channel_ids or channel_id in signals.seed_channel_ids):
        return True

    if youtube_channel_id and (
        any(youtube_channel_id == str(sc) for sc in signals.seed_channel_ids)
    ):
        return True

    for neg in signals.negative_keywords:
        if neg in norm_title or neg in norm_desc:
            return True

    return False


def _calculate_thematic_score(
    norm_title: str, norm_desc: str, signals: CategorySignals
) -> Tuple[float, list, list]:
    """Calcula coincidencia temática (0..35) y retorna el máximo score junto con keywords y topics coincidentes."""
    matched_pos_keywords = []
    kw_scores = []
    for kw, weight in signals.positive_keywords:
        w_norm = clamp(weight, 0.0, 1.0)
        if kw in norm_title:
            matched_pos_keywords.append((kw, weight))
            kw_scores.append(35.0 * w_norm)
        elif kw in norm_desc:
            matched_pos_keywords.append((kw, weight))
            kw_scores.append(28.0 * w_norm)

    matched_topics = []
    topic_scores = []
    for topic, weight in signals.approved_exploration_topics:
        w_norm = clamp(weight, 0.0, 1.0)
        if topic in norm_title:
            matched_topics.append((topic, weight))
            topic_scores.append(30.0 * w_norm)
        elif topic in norm_desc:
            matched_topics.append((topic, weight))
            topic_scores.append(24.0 * w_norm)

    all_scores = kw_scores + topic_scores
    thematic_score = min(35.0, max(all_scores)) if all_scores else 0.0
    return thematic_score, matched_pos_keywords, matched_topics


def _calculate_seed_similarity(norm_title: str, norm_channel_title: str, signals: CategorySignals) -> float:
    """Calcula la similitud con canales semilla (0..20) usando coincidencia o Jaccard."""
    is_seed_channel = (
        norm_channel_title in signals.seed_channel_titles or
        any(norm_channel_title in desc for desc in signals.seed_channel_descriptions)
    )
    if is_seed_channel:
        return 20.0

    # Jaccard con títulos de canales semilla
    title_tokens = set(norm_title.split())
    max_jaccard = 0.0
    for seed_title in signals.seed_channel_titles:
        seed_tokens = set(seed_title.split())
        if title_tokens and seed_tokens:
            sim = len(title_tokens.intersection(seed_tokens)) / len(title_tokens.union(seed_tokens))
            if sim > max_jaccard:
                max_jaccard = sim

    if max_jaccard >= 0.50:
        return 20.0
    elif max_jaccard >= 0.30:
        return 12.0
    elif max_jaccard >= 0.15:
        return 6.0

    return 0.0


def _calculate_local_signals_score(channel_id: Optional[int], norm_title: str, signals: CategorySignals) -> float:
    """Calcula el aporte de señales locales recientes (0..15)."""
    scores = []
    if signals.local_signal_scores:
        if signals.local_signal_scores.get("more_like_this_expired"):
            pass
        elif "more_like_this" in signals.local_signal_scores:
            scores.append(clamp(signals.local_signal_scores["more_like_this"], 0.0, 15.0))
        elif "watched" in signals.local_signal_scores:
            scores.append(clamp(signals.local_signal_scores["watched"], 0.0, 15.0))
        elif "opened" in signals.local_signal_scores:
            scores.append(clamp(signals.local_signal_scores["opened"], 0.0, 15.0))

    has_positive = (
        (channel_id and channel_id in signals.positive_channel_ids) or
        any(pt in norm_title for pt in signals.positive_video_titles)
    )
    if has_positive and not scores:
        scores.append(15.0)

    return min(15.0, max(scores)) if scores else 0.0


def _calculate_freshness_score(published_str: Optional[str], now: datetime) -> float:
    """Calcula actualidad (0..10) según la antigüedad de publicación."""
    if not published_str:
        return 10.0
    try:
        pub_date_str = published_str.replace("Z", "+00:00")
        pub_date = datetime.fromisoformat(pub_date_str)
        days = (now - pub_date).days
        if days <= 7:
            return 10.0
        elif days <= 30:
            return 7.0
        elif days <= 90:
            return 4.0
        elif days <= 180:
            return 2.0
    except Exception:
        pass
    return 0.0


def _calculate_penalties(video: dict, channel_id: Optional[int], signals: CategorySignals) -> float:
    """Calcula penalizaciones por feedback negativo (0..40)."""
    video_id = video.get("video_id")
    penalties = []
    if video_id and video_id in signals.negative_video_ids:
        penalties.append(40.0)
    if channel_id and channel_id in signals.negative_channel_ids:
        penalties.append(20.0)
    return min(40.0, max(penalties)) if penalties else 0.0


def _determine_band_and_reasons(
    matched_pos_keywords: list,
    matched_topics: list,
    seed_score: float,
    local_score: float,
    freshness_score: float,
    channel_title: str
) -> Tuple[Optional[Band], list]:
    """Determina la banda temática y genera las razones explicativas."""
    band = None
    reasons = []

    has_kw = bool(matched_pos_keywords)
    has_topic = bool(matched_topics)
    has_seed_or_local = (seed_score >= 6.0) or (local_score > 0.0)

    if has_kw and has_topic:
        band = Band.ADJACENT
        kw_name = matched_pos_keywords[0][0]
        topic_name = matched_topics[0][0]
        reasons.append(f"Cruce temático de '{kw_name}' con '{topic_name}'.")
    elif has_kw or has_seed_or_local:
        band = Band.RELATED
        if has_kw:
            reasons.append(f"Coincide con la palabra clave '{matched_pos_keywords[0][0]}'.")
        elif seed_score >= 6.0:
            reasons.append(f"Publicado por el canal de interés '{channel_title}'.")
    elif has_topic:
        band = Band.EXPLORATORY
        reasons.append(f"Incluye el tema aprobado '{matched_topics[0][0]}'.")

    if band is None:
        return None, []

    if freshness_score >= 7.0:
        reasons.append("Publicado recientemente.")

    if not reasons:
        reasons.append("Recomendado por afinidad temática general.")

    return band, reasons[:3]


def score_and_classify_candidate(
    video: dict,
    signals: CategorySignals,
    now: Optional[datetime] = None,
    min_score_related: float = 55.0,
    min_score_adjacent: float = 45.0,
    min_score_exploratory: float = 35.0,
) -> Optional[DiscoveryCandidateDomain]:
    """
    Evalúa un video candidato contra las señales de una categoría.
    Retorna un DiscoveryCandidateDomain con score, band y reasons, o None si no es elegible.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    title = video.get("title", "")
    description = video.get("description", "")
    norm_title = normalize_term(title)
    norm_desc = normalize_term(description)
    channel_title = video.get("channel_title", "")
    norm_channel_title = normalize_term(channel_title)
    channel_id = video.get("channel_id")

    # 1. Exclusiones Obligatorias
    if _check_exclusions(video, signals, norm_title, norm_desc):
        return None

    # 2. Puntuación por Componentes
    thematic_score, matched_pos_keywords, matched_topics = _calculate_thematic_score(
        norm_title, norm_desc, signals
    )
    seed_score = _calculate_seed_similarity(norm_title, norm_channel_title, signals)
    local_score = _calculate_local_signals_score(channel_id, norm_title, signals)
    freshness_score = _calculate_freshness_score(video.get("published_at"), now)

    feedback_pos_score = 0.0
    if channel_id and channel_id in signals.positive_channel_ids:
        feedback_pos_score = 10.0

    has_desc = bool(video.get("description")) if "description" in video else True
    has_thumb = bool(video.get("thumbnail_url")) if "thumbnail_url" in video else True
    diversity_score = 5.0 if (video.get("video_id") not in signals.watched_video_ids) else 0.0
    if has_desc and has_thumb:
        diversity_score += 5.0

    penalty = _calculate_penalties(video, channel_id, signals)

    total_score = (
        thematic_score + seed_score + local_score + freshness_score +
        feedback_pos_score + diversity_score - penalty
    )
    final_score = max(0.0, min(100.0, total_score))

    # 3. Determinar Banda y Razones
    band, reasons = _determine_band_and_reasons(
        matched_pos_keywords, matched_topics, seed_score, local_score, freshness_score, channel_title
    )
    if band is None:
        return None

    # 4. Umbrales Mínimos por Banda
    if band == Band.RELATED and final_score < min_score_related:
        return None
    if band == Band.ADJACENT and final_score < min_score_adjacent:
        return None
    if band == Band.EXPLORATORY and final_score < min_score_exploratory:
        return None

    return DiscoveryCandidateDomain(
        video_id=video.get("video_id") or 0,
        youtube_video_id=video.get("youtube_video_id", ""),
        channel_id=channel_id or 0,
        youtube_channel_id=video.get("youtube_channel_id", ""),
        channel_title=channel_title,
        title=title,
        description=description,
        published_at=video.get("published_at") or "",
        duration_seconds=video.get("duration_seconds"),
        content_type=video.get("content_type", "video"),
        score=final_score,
        band=band,
        reasons=reasons,
    )
