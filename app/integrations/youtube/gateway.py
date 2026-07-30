import requests
from flask import current_app


class YouTubeGateway:
    def __init__(self, client_id=None, client_secret=None):
        self.client_id = client_id
        self.client_secret = client_secret

    def _get_client_credentials(self):
        cid = self.client_id or current_app.config.get("GOOGLE_CLIENT_ID")
        csec = self.client_secret or current_app.config.get("GOOGLE_CLIENT_SECRET")
        return cid, csec

    def refresh_access_token(self, refresh_token: str) -> dict:
        """
        Solicita un nuevo access_token usando el refresh_token.
        Retorna diccionario con access_token y expires_in.
        """
        client_id, client_secret = self._get_client_credentials()
        url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }

        current_app.logger.info("Solicitando refresco de access_token a Google...")
        response = requests.post(url, data=data, timeout=10)
        if response.status_code != 200:
            raise Exception(f"Fallo al refrescar token: {response.text}")

        return response.json()

    def fetch_subscriptions(self, access_token: str) -> list[dict]:
        """
        Obtiene la lista completa de suscripciones del canal autenticado (paginando).
        Retorna una lista de diccionarios con youtube_channel_id y title.
        """
        url = "https://www.googleapis.com/youtube/v3/subscriptions"
        params = {
            "part": "snippet",
            "mine": "true",
            "maxResults": 50
        }
        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        subscriptions = []
        next_page_token = None
        pages_count = 0

        while True:
            if next_page_token:
                params["pageToken"] = next_page_token

            current_app.logger.info(f"Youtube API Call: subscriptions.list (Pág {pages_count + 1})")
            response = requests.get(url, params=params, headers=headers, timeout=10)
            pages_count += 1

            # Si expira el token, levantamos excepción para que la capa superior lo refresque y reintente
            if response.status_code == 401:
                raise PermissionError("Access token expirado.")
            elif response.status_code != 200:
                raise Exception(f"Error consultando suscripciones: {response.text}")

            data = response.json()
            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                resource_id = snippet.get("resourceId", {})
                channel_id = resource_id.get("channelId")
                title = snippet.get("title", "")

                if channel_id:
                    subscriptions.append({
                        "youtube_channel_id": channel_id,
                        "title": title
                    })

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break

        current_app.logger.info(
            f"Suscripciones importadas: {len(subscriptions)} "
            f"(Consumo cuota: {pages_count} unidades)"
        )
        return subscriptions

    def fetch_channels_details(self, access_token: str, channel_ids: list[str]) -> list[dict]:
        """
        Obtiene los detalles de una lista de canales de YouTube en lotes de máximo 50.
        Retorna lista de diccionarios con youtube_channel_id, title, description, thumbnail_url y uploads_playlist_id.
        """
        if not channel_ids:
            return []

        url = "https://www.googleapis.com/youtube/v3/channels"
        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        channels_details = []
        # Dividir los IDs en lotes de 50 (límite de la API de YouTube)
        batch_size = 50
        batches = [channel_ids[i:i + batch_size] for i in range(0, len(channel_ids), batch_size)]

        for batch in batches:
            params = {
                "part": "snippet,contentDetails",
                "id": ",".join(batch),
                "maxResults": 50
            }

            current_app.logger.info(f"Youtube API Call: channels.list (Lote de {len(batch)} IDs)")
            response = requests.get(url, params=params, headers=headers, timeout=10)

            if response.status_code == 401:
                raise PermissionError("Access token expirado.")
            elif response.status_code != 200:
                raise Exception(f"Error consultando detalles de canales: {response.text}")

            data = response.json()
            for item in data.get("items", []):
                channel_id = item.get("id")
                snippet = item.get("snippet", {})
                content_details = item.get("contentDetails", {})

                title = snippet.get("title", "")
                description = snippet.get("description", "")

                # Obtener thumbnail
                thumbnails = snippet.get("thumbnails", {})
                # Intentamos default, medium, high
                thumbnail_url = (
                    thumbnails.get("default", {}).get("url") or
                    thumbnails.get("medium", {}).get("url") or
                    thumbnails.get("high", {}).get("url")
                )

                # Obtener playlist de uploads
                related_playlists = content_details.get("relatedPlaylists", {})
                uploads_playlist_id = related_playlists.get("uploads")

                channels_details.append({
                    "youtube_channel_id": channel_id,
                    "title": title,
                    "description": description,
                    "thumbnail_url": thumbnail_url,
                    "uploads_playlist_id": uploads_playlist_id
                })

        current_app.logger.info(
            f"Detalles hidratados para {len(channels_details)} canales. "
            f"(Consumo cuota: {len(batches)} unidades)"
        )
        return channels_details
