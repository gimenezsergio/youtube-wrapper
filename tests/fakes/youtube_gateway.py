class FakeYouTubeGateway:
    def __init__(self):
        # Para suscripciones
        self.subscriptions_responses = [
            [
                {"youtube_channel_id": "UC_A", "title": "Canal A"},
                {"youtube_channel_id": "UC_B", "title": "Canal B"}
            ],
            [
                {"youtube_channel_id": "UC_C", "title": "Canal C"}
            ]
        ]
        self.channels_details = {
            "UC_A": {
                "youtube_channel_id": "UC_A",
                "title": "Canal A Completo",
                "description": "Descripcion A",
                "thumbnail_url": "thumb_a.jpg",
                "uploads_playlist_id": "UU_A"
            },
            "UC_B": {
                "youtube_channel_id": "UC_B",
                "title": "Canal B Completo",
                "description": "Descripcion B",
                "thumbnail_url": "thumb_b.jpg",
                "uploads_playlist_id": "UU_B"
            },
            "UC_C": {
                "youtube_channel_id": "UC_C",
                "title": "Canal C Completo",
                "description": "Descripcion C",
                "thumbnail_url": "thumb_c.jpg",
                "uploads_playlist_id": "UU_C"
            },
            "UC_D": {
                "youtube_channel_id": "UC_D",
                "title": "Canal D Completo",
                "description": "Descripcion D",
                "thumbnail_url": "thumb_d.jpg",
                "uploads_playlist_id": "UU_D"
            }
        }
        self.refresh_calls = 0

        # Para videos
        self.playlist_items = {
            "UU_A": {
                "items": [
                    {
                        "youtube_video_id": "vid_1",
                        "title": "Video 1",
                        "description": "Desc 1",
                        "published_at": "2026-07-30T10:00:00Z",
                        "thumbnail_url": "t1"
                    },
                    {
                        "youtube_video_id": "vid_2",
                        "title": "Video 2",
                        "description": "Desc 2",
                        "published_at": "2026-07-30T09:00:00Z",
                        "thumbnail_url": "t2"
                    }
                ],
                "nextPageToken": None
            },
            "UU_B": {
                "items": [
                    {
                        "youtube_video_id": "vid_3",
                        "title": "Video 3",
                        "description": "Desc 3",
                        "published_at": "2026-07-30T08:00:00Z",
                        "thumbnail_url": "t3"
                    }
                ],
                "nextPageToken": None
            }
        }
        self.video_details = [
            {"youtube_video_id": "vid_1", "duration_seconds": 600, "content_type": "video"},
            {"youtube_video_id": "vid_2", "duration_seconds": 240, "content_type": "video"},
            {"youtube_video_id": "vid_3", "duration_seconds": 1800, "content_type": "live"}
        ]

        # Para búsquedas (descubrimiento)
        self.search_calls = [] # Registrar parámetros de llamadas a búsqueda
        self.search_responses = {} # Mapeo de consulta (q) a resultados de búsqueda

    def refresh_access_token(self, refresh_token):
        self.refresh_calls += 1
        return {"access_token": "new-access-token", "expires_in": 3600}

    def fetch_subscriptions(self, access_token):
        result = []
        for page in self.subscriptions_responses:
            result.extend(page)
        return result

    def fetch_channels_details(self, access_token, channel_ids):
        return [self.channels_details[cid] for cid in channel_ids if cid in self.channels_details]

    def fetch_playlist_items(self, access_token, playlist_id, limit=50, page_token=None):
        return self.playlist_items.get(playlist_id, {"items": [], "nextPageToken": None})

    def fetch_videos_details(self, access_token, video_ids):
        return [d for d in self.video_details if d["youtube_video_id"] in video_ids]

    def search_videos(self, access_token, q, published_after=None, limit=25, region_code='AR', relevance_language='es'):
        self.search_calls.append({
            "q": q,
            "published_after": published_after,
            "limit": limit,
            "region_code": region_code,
            "relevance_language": relevance_language
        })
        # Buscar en respuestas simuladas, por defecto retorna vacío si no hay mock
        return self.search_responses.get(q, [])
