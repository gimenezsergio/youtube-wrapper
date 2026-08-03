from enum import Enum
from typing import Any, Dict, List, Literal, Optional


class Band(Enum):
    RELATED = "related"
    ADJACENT = "adjacent"
    EXPLORATORY = "exploratory"

    @property
    def label(self) -> str:
        if self == Band.RELATED:
            return "Relacionado"
        elif self == Band.ADJACENT:
            return "Tema cercano"
        elif self == Band.EXPLORATORY:
            return "Para explorar"
        return "Desconocido"


class SignalType(Enum):
    OPENED = "opened"
    WATCHED = "watched"
    MORE_LIKE_THIS = "more_like_this"
    LESS_LIKE_THIS = "less_like_this"


class LocalSignal:
    def __init__(
        self,
        video_id: Optional[int] = None,
        youtube_video_id: Optional[str] = None,
        channel_id: Optional[int] = None,
        youtube_channel_id: Optional[str] = None,
        title: Optional[str] = None,
        signal_type: SignalType = SignalType.OPENED,
        created_at: Optional[str] = None,
        days_ago: int = 0,
        weight: float = 1.0,
    ):
        self.video_id = video_id
        self.youtube_video_id = youtube_video_id
        self.channel_id = channel_id
        self.youtube_channel_id = youtube_channel_id
        self.title = title
        self.signal_type = (
            signal_type if isinstance(signal_type, SignalType) else SignalType(signal_type)
        )
        self.created_at = created_at
        self.days_ago = days_ago
        self.weight = weight


class DiscoveryCandidateDomain:
    def __init__(
        self,
        video_id: int,
        youtube_video_id: str,
        channel_id: int,
        youtube_channel_id: str,
        channel_title: str,
        title: str,
        description: str,
        published_at: str,
        duration_seconds: Optional[int],
        content_type: str,
        score: float = 0.0,
        band: Band = Band.RELATED,
        reasons: Optional[List[str]] = None,
        selection_rank: Optional[int] = None,
        category_id: int = 0,
    ):
        self.video_id = video_id
        self.youtube_video_id = youtube_video_id
        self.channel_id = channel_id
        self.youtube_channel_id = youtube_channel_id
        self.channel_title = channel_title
        self.title = title
        self.description = description
        self.published_at = published_at
        self.duration_seconds = duration_seconds
        self.content_type = content_type
        self.score = score
        self.band = band
        self.reasons = reasons or []
        self.selection_rank = selection_rank
        self.category_id = category_id


class PublicStageError:
    def __init__(
        self,
        stage: str,
        code: str,
        message: str,
        category_id: Optional[int] = None,
    ):
        self.stage = stage
        self.code = code
        self.message = message
        self.category_id = category_id

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
        }
        if self.category_id is not None:
            d["categoryId"] = self.category_id
        return d


class CategoryAttemptResult:
    def __init__(
        self,
        category_id: int,
        outcome: Literal["publishable", "aborted"],
        candidates: Optional[List[DiscoveryCandidateDomain]] = None,
        summary: Optional[Dict[str, Any]] = None,
        error: Optional[PublicStageError] = None,
        selected_items_data: Optional[List[Any]] = None,
    ):
        self.category_id = category_id
        self.outcome = outcome
        self.candidates = candidates or []
        self.summary = summary
        self.error = error
        self.selected_items_data = selected_items_data or []
