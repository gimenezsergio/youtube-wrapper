from datetime import datetime, timezone
from typing import Optional

from app.domain.discovery.models import Band, DiscoveryCandidateDomain
from app.domain.discovery.normalization import normalize_term
from app.domain.discovery.signals import CategorySignals


def score_and_classify_candidate(
    video: dict,  # Contiene youtube_video_id, title, description, published_at, duration_seconds, content_type, channel_title, youtube_channel_id, channel_id (opcional)
    signals: CategorySignals,
    now: Optional[datetime] = None,
    min_score_related: float = 0.0,
    min_score_adjacent: float = 0.0,
    min_score_exploratory: float = 0.0
) -> Optional[DiscoveryCandidateDomain]:
    """
    Evalúa un video candidato contra los señales de una categoría.
    Retorna un DiscoveryCandidateDomain con score, band y reasons, o None si no es elegible.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    title = video.get("title", "")
    description = video.get("description", "")
    normalized_title = normalize_term(title)
    normalized_desc = normalize_term(description)

    channel_id = video.get("channel_id")
    youtube_channel_id = video.get("youtube_channel_id", "")
    channel_title = video.get("channel_title", "")
    normalized_channel_title = normalize_term(channel_title)

    # 0. Exclusiones Obligatorias
    # A) Exclusión por canal bloqueado, video oculto o video ya visto
    if (channel_id and channel_id in signals.blocked_channel_ids) or \
       (video.get("video_id") and video.get("video_id") in signals.hidden_video_ids) or \
       (video.get("video_id") and video.get("video_id") in signals.watched_video_ids):
        return None
    # B) Exclusión por canal seguido localmente o suscripto (no se recomienda contenido ya seguido)
    if channel_id and (channel_id in signals.followed_channel_ids or channel_id in signals.seed_channel_ids):
        return None

    # C) Palabras clave negativas
    for neg in signals.negative_keywords:
        if neg in normalized_title or neg in normalized_desc:
            return None

    # D) Duración menor o igual a 180 segundos (Shorts)
    duration = video.get("duration_seconds")
    if duration is not None and duration <= 180:
        return None

    # Detectar coincidencias para scoring y clasificación
    matched_pos_keywords = []
    for kw, weight in signals.positive_keywords:
        if kw in normalized_title or kw in normalized_desc:
            matched_pos_keywords.append((kw, weight))

    matched_topics = []
    for topic, weight in signals.approved_exploration_topics:
        if topic in normalized_title or topic in normalized_desc:
            matched_topics.append((topic, weight))

    is_seed_channel = (
        normalized_channel_title in signals.seed_channel_titles or
        any(normalized_channel_title in desc for desc in signals.seed_channel_descriptions)
    )

    has_positive_local_signal = (
        channel_id in signals.positive_channel_ids or
        any(pt in normalized_title for pt in signals.positive_video_titles)
    )

    # 1. Puntuación (Scoring) 0..100
    score = 0.0

    # A) Coincidencia temática (0..35)
    thematic_score = 0.0
    kw_scores = [w * 35.0 for kw, w in matched_pos_keywords]
    topic_scores = [w * 30.0 for topic, w in matched_topics]
    all_thematic = kw_scores + topic_scores
    if all_thematic:
        thematic_score = max(all_thematic)
    score += min(thematic_score, 35.0)

    # B) Similitud con canales semilla (0..20)
    seed_score = 0.0
    if is_seed_channel:
        seed_score = 20.0
    score += seed_score

    # C) Similitud con señales locales recientes (0..15)
    local_score = 0.0
    if has_positive_local_signal:
        local_score = 15.0
    score += local_score

    # D) Actualidad (0..10)
    freshness_score = 0.0
    published_str = video.get("published_at")
    if published_str:
        try:
            pub_date_str = published_str.replace("Z", "+00:00")
            pub_date = datetime.fromisoformat(pub_date_str)
            days = (now - pub_date).days
            if days <= 7:
                freshness_score = 10.0
            elif days <= 30:
                freshness_score = 7.0
            elif days <= 90:
                freshness_score = 4.0
            elif days <= 180:
                freshness_score = 2.0
        except Exception:
            pass
    score += freshness_score

    # E) Feedback positivo relacionado (0..10)
    feedback_pos_score = 0.0
    if channel_id and channel_id in signals.positive_channel_ids:
        feedback_pos_score = 10.0
    score += feedback_pos_score

    # F) Adecuación de diversidad/novedad para la banda (0..10)
    diversity_score = 5.0
    if video.get("description") and video.get("thumbnail_url"):
        diversity_score += 5.0
    score += diversity_score

    # G) Feedback negativo relacionado (restar 0..40)
    negative_feedback_penalty = 0.0
    if (video.get("video_id") and video.get("video_id") in signals.negative_video_ids) or \
       (channel_id and channel_id in signals.negative_channel_ids):
        negative_feedback_penalty = 40.0
    score -= negative_feedback_penalty

    # Limitar puntuación final a 0..100
    score = max(0.0, min(100.0, score))

    # 2. Determinar Banda de Descubrimiento (Elegibilidad)
    band = None
    reasons = []

    if matched_pos_keywords and matched_topics:
        band = Band.ADJACENT
        kw_name = matched_pos_keywords[0][0]
        topic_name = matched_topics[0][0]
        reasons.append(f"Cruce temático de '{kw_name}' con '{topic_name}'.")
    elif matched_pos_keywords or is_seed_channel:
        band = Band.RELATED
        if matched_pos_keywords:
            reasons.append(f"Coincide con la palabra clave '{matched_pos_keywords[0][0]}'.")
        if is_seed_channel:
            reasons.append(f"Publicado por el canal de interés '{channel_title}'.")
    elif matched_topics:
        band = Band.EXPLORATORY
        reasons.append(f"Incluye el tema aprobado '{matched_topics[0][0]}'.")

    # Si no entra en ninguna banda, el video no es elegible
    if band is None:
        return None

    # Verificar umbrales mínimos por banda
    if band == Band.RELATED and score < min_score_related:
        return None
    if band == Band.ADJACENT and score < min_score_adjacent:
        return None
    if band == Band.EXPLORATORY and score < min_score_exploratory:
        return None

    if freshness_score >= 7.0:
        reasons.append("Publicado recientemente.")

    # Asegurar entre 1 y 3 razones
    if not reasons:
        reasons.append("Recomendado por afinidad temática general.")
    reasons = reasons[:3]

    return DiscoveryCandidateDomain(
        video_id=video.get("video_id") or 0,
        youtube_video_id=video.get("youtube_video_id", ""),
        channel_id=channel_id or 0,
        youtube_channel_id=youtube_channel_id,
        channel_title=channel_title,
        title=title,
        description=description,
        published_at=published_str or "",
        duration_seconds=duration,
        content_type=video.get("content_type", "video"),
        score=score,
        band=band,
        reasons=reasons
    )
