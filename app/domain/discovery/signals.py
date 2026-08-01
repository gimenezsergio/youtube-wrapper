from typing import Set, Dict, List, Tuple
from app.domain.discovery.normalization import normalize_term

class CategorySignals:
    def __init__(
        self,
        category_id: int,
        positive_keywords: List[Tuple[str, float]], # (term, weight)
        negative_keywords: List[str],              # terms
        approved_exploration_topics: List[Tuple[str, float]], # (term, weight)
        seed_channel_ids: Set[int],
        seed_channel_titles: List[str],            # titles
        seed_channel_descriptions: List[str],      # descriptions
        positive_video_titles: List[str],          # video titles that were opened/watched/more_like_this
        positive_channel_ids: Set[int],            # channels of positive videos
        negative_video_ids: Set[int],              # less_like_this video ids
        negative_channel_ids: Set[int],            # less_like_this channel ids / block_channel ids
        blocked_channel_ids: Set[int],             # globally blocked channel ids
        hidden_video_ids: Set[int]                 # hidden video ids
    ):
        self.category_id = category_id
        # Normalize keywords/topics
        self.positive_keywords = [(normalize_term(k), w) for k, w in positive_keywords if normalize_term(k)]
        self.negative_keywords = [normalize_term(k) for k in negative_keywords if normalize_term(k)]
        self.approved_exploration_topics = [(normalize_term(t), w) for t, w in approved_exploration_topics if normalize_term(t)]
        
        self.seed_channel_ids = seed_channel_ids
        self.seed_channel_titles = [normalize_term(t) for t in seed_channel_titles if normalize_term(t)]
        self.seed_channel_descriptions = [normalize_term(d) for d in seed_channel_descriptions if normalize_term(d)]
        
        self.positive_video_titles = [normalize_term(t) for t in positive_video_titles if normalize_term(t)]
        self.positive_channel_ids = positive_channel_ids
        
        self.negative_video_ids = negative_video_ids
        self.negative_channel_ids = negative_channel_ids
        self.blocked_channel_ids = blocked_channel_ids
        self.hidden_video_ids = hidden_video_ids
