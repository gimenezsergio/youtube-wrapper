from typing import Any, List, Optional, Set, Tuple

from app.domain.discovery.models import LocalSignal
from app.domain.discovery.normalization import normalize_term


class CategorySignals:
    def __init__(
        self,
        category_id: int,
        positive_keywords: List[Tuple[str, float]],
        negative_keywords: List[str],
        approved_exploration_topics: List[Tuple[str, float]],
        seed_channel_ids: Set[int],
        seed_channel_titles: List[str],
        seed_channel_descriptions: List[str],
        positive_video_titles: List[str],
        positive_channel_ids: Set[int],
        negative_video_ids: Set[int],
        negative_channel_ids: Set[int],
        blocked_channel_ids: Set[int],
        hidden_video_ids: Set[int],
        followed_channel_ids: Optional[Set[int]] = None,
        watched_video_ids: Optional[Set[int]] = None,
        local_signals: Optional[List[Any]] = None,
        more_like_this_channel_ids: Optional[Set[int]] = None,
    ):
        self.category_id = category_id

        # Normalizar palabras clave y temas
        self.positive_keywords = [
            (normalize_term(k), float(w)) for k, w in positive_keywords if normalize_term(k)
        ]
        self.negative_keywords = [
            normalize_term(k) for k in negative_keywords if normalize_term(k)
        ]
        self.approved_exploration_topics = [
            (normalize_term(t), float(w))
            for t, w in approved_exploration_topics
            if normalize_term(t)
        ]

        self.seed_channel_ids = seed_channel_ids or set()
        self.seed_channel_titles = [
            normalize_term(t) for t in seed_channel_titles if normalize_term(t)
        ]
        self.seed_channel_descriptions = [
            normalize_term(d) for d in seed_channel_descriptions if normalize_term(d)
        ]

        self.positive_video_titles = [
            normalize_term(t) for t in positive_video_titles if normalize_term(t)
        ]
        self.positive_channel_ids = positive_channel_ids or set()

        self.negative_video_ids = negative_video_ids or set()
        self.negative_channel_ids = negative_channel_ids or set()
        self.blocked_channel_ids = blocked_channel_ids or set()
        self.hidden_video_ids = hidden_video_ids or set()
        self.followed_channel_ids = followed_channel_ids or set()
        self.watched_video_ids = watched_video_ids or set()

        self.local_signals: List[LocalSignal] = []
        if local_signals:
            for s in local_signals:
                if isinstance(s, LocalSignal):
                    self.local_signals.append(s)
                elif isinstance(s, dict):
                    self.local_signals.append(LocalSignal(**s))

        self.more_like_this_channel_ids = more_like_this_channel_ids or set()
