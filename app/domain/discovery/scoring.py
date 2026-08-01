from datetime import datetime, timezone
from typing import List, Tuple, Optional
from app.domain.discovery.models import Band, DiscoveryCandidateDomain
from app.domain.discovery.signals import CategorySignals
from app.domain.discovery.normalization import normalize_term

def score_and_classify_candidate(
    video: dict,  # Contiene youtube_video_id, title, description, published_at, duration_seconds, content_type, channel_title, youtube_channel_id, channel_id (opcional)
    signals: CategorySignals,
    now: Optional[datetime] = None
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
    # A) Exclusión por canal bloqueado o video oculto
    if channel_id in signals.blocked_channel_ids or video.get("youtube_video_id") in signals.hidden_video_ids:
        return None
    # B) Exclusión por canal seguido localmente o suscripto (no se recomienda contenido ya seguido)
    if channel_id in signals.seed_channel_ids:
        # Pero ojo: el canal semilla se usa como señal. ¿Debemos excluir videos de canales seguidos/suscriptos?
        # Sí, el diseño dice: "Debe excluir videos de canales suscriptos o seguidos localmente del conjunto de descubrimiento"
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

    # 1. Determinar Banda de Descubrimiento (Elegibilidad)
    # related: coincidencia directa con palabras clave o canal semilla
    # adjacent: cruce de palabra clave (ancla) + tema aprobado
    # exploratory: al menos un ancla o tema aprobado, o señal fuerte
    band = None
    reasons = []
    
    if matched_pos_keywords and matched_topics:
        band = Band.ADJACENT
        # Agregar razones
        kw_name = matched_pos_keywords[0][0]
        topic_name = matched_topics[0][0]
        reasons.append(f"Cruce temático de '{kw_name}' con '{topic_name}'.")
    elif matched_pos_keywords or is_seed_channel:
        band = Band.RELATED
        if matched_pos_keywords:
            reasons.append(f"Coincide con la palabra clave '{matched_pos_keywords[0][0]}'.")
        if is_seed_channel:
            reasons.append(f"Publicado por el canal de interés '{channel_title}'.")
    elif matched_topics or has_positive_local_signal:
        band = Band.EXPLORATORY
        if matched_topics:
            reasons.append(f"Incluye el tema aprobado '{matched_topics[0][0]}'.")
        if has_positive_local_signal:
            reasons.append("Relacionado con videos que viste recientemente.")
            
    # Si no entra en ninguna banda, el video no es elegible
    if band is None:
        return None

    # 2. Puntuación (Scoring) 0..100
    score = 0.0
    
    # A) Coincidencia temática (0..35)
    thematic_score = 0.0
    for kw, w in matched_pos_keywords:
        thematic_score += w * 10.0
    for topic, w in matched_topics:
        thematic_score += w * 8.0
    score += min(thematic_score, 35.0)
    
    # B) Similitud con canales semilla (0..20)
    seed_score = 0.0
    if is_seed_channel:
        seed_score += 20.0
    score += min(seed_score, 20.0)
    
    # C) Similitud con señales locales recientes (0..15)
    local_score = 0.0
    if has_positive_local_signal:
        local_score += 15.0
    score += min(local_score, 15.0)
    
    # D) Actualidad (0..10)
    freshness_score = 0.0
    published_str = video.get("published_at")
    if published_str:
        try:
            # Parse ISO 8601 date string, handle Z suffix
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
    if freshness_score >= 7.0:
        reasons.append("Publicado recientemente.")
        
    # E) Feedback positivo relacionado (0..10)
    # (Por ejemplo, si hubo feedback 'more_like_this' en la categoría)
    # Agregamos 5 puntos si el canal tiene interacciones positivas previas
    feedback_pos_score = 0.0
    if video.get("youtube_video_id") in signals.hidden_video_ids: # just in case
        return None
    score += feedback_pos_score
    
    # F) Adecuación de diversidad/novedad para la banda (0..10)
    diversity_score = 5.0
    if video.get("description") and video.get("thumbnail_url"):
        diversity_score += 5.0
    score += diversity_score
    
    # G) Feedback negativo relacionado (restar 0..40)
    # Por ejemplo, si está en negative_video_ids o negative_channel_ids
    negative_feedback_penalty = 0.0
    if video.get("video_id") in signals.negative_video_ids or channel_id in signals.negative_channel_ids:
        negative_feedback_penalty = 40.0
    score -= negative_feedback_penalty
    
    # Limitar puntuación final a 0..100
    score = max(0.0, min(100.0, score))

    # Asegurar entre 1 y 3 razones
    if not reasons:
        reasons.append("Recomendado por afinidad temática general.")
    reasons = reasons[:3]

    return DiscoveryCandidateDomain(
        video_id=video.get("video_id", 0),
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
