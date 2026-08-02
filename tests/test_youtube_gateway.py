from unittest.mock import MagicMock, patch

import pytest

from app.integrations.youtube.gateway import (
    YouTubeAuthorizationError,
    YouTubeGateway,
    YouTubeQuotaError,
)


@patch("app.integrations.youtube.gateway.requests.request")
def test_youtube_gateway_search_success(mock_request, app):
    """Prueba una búsqueda exitosa normalizada de YouTubeGateway."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "items": [
            {
                "id": {"videoId": "vid_1"},
                "snippet": {
                    "title": "Video 1 Title",
                    "description": "Video 1 Desc",
                    "publishedAt": "2026-07-30T10:00:00Z",
                    "channelTitle": "Canal 1",
                    "channelId": "UC_1",
                    "thumbnails": {
                        "high": {"url": "thumb_url"}
                    }
                }
            }
        ]
    }
    mock_request.return_value = mock_response

    with app.app_context():
        gateway = YouTubeGateway()
        res = gateway.search_videos("token", "linux tutorial", limit=5)

        assert len(res) == 1
        assert res[0]["youtube_video_id"] == "vid_1"
        assert res[0]["title"] == "Video 1 Title"
        assert res[0]["channel_title"] == "Canal 1"

        # Verificar parámetros de llamada
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        assert kwargs["params"]["q"] == "linux tutorial"
        assert kwargs["params"]["maxResults"] == 5

@patch("app.integrations.youtube.gateway.requests.request")
def test_youtube_gateway_transient_error_retry(mock_request, app):
    """Prueba que el gateway reintenta ante errores transitorios y luego falla."""
    # 2 fallos 503 seguidos de un éxito 200
    mock_fail = MagicMock()
    mock_fail.status_code = 503

    mock_success = MagicMock()
    mock_success.status_code = 200
    mock_success.json.return_value = {"items": []}

    mock_request.side_effect = [mock_fail, mock_fail, mock_success]

    with app.app_context():
        # Parchear time.sleep para que la prueba corra instantáneamente
        with patch("app.integrations.youtube.gateway.time.sleep") as mock_sleep:
            gateway = YouTubeGateway()
            res = gateway.search_videos("token", "test")
            assert len(res) == 0
            assert mock_request.call_count == 3
            assert mock_sleep.call_count == 2

@patch("app.integrations.youtube.gateway.requests.request")
def test_youtube_gateway_quota_error(mock_request, app):
    """Prueba que los errores de cuota lancen YouTubeQuotaError de inmediato."""
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = '{"error": {"message": "The request cannot be completed because you have exceeded your quota."}}'
    mock_request.return_value = mock_response

    with app.app_context():
        gateway = YouTubeGateway()
        with pytest.raises(YouTubeQuotaError):
            gateway.search_videos("token", "test")
        # No debe haber reintentos para cuota
        mock_request.assert_called_once()

@patch("app.integrations.youtube.gateway.requests.request")
def test_youtube_gateway_auth_error(mock_request, app):
    """Prueba que los errores 401 lancen YouTubeAuthorizationError."""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_request.return_value = mock_response

    with app.app_context():
        gateway = YouTubeGateway()
        with pytest.raises(YouTubeAuthorizationError):
            gateway.search_videos("token", "test")
        mock_request.assert_called_once()
