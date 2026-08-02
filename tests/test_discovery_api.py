import json

import pytest

from app.db import get_db_connection
from app.domain.discovery.models import Band, DiscoveryCandidateDomain
from app.repositories.discovery_repository import DiscoveryRepository


@pytest.fixture
def auth_client(client):
    """Cliente de pruebas con sesión de propietario iniciada."""
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["email"] = "test_owner@gmail.com"
        sess["csrf_token"] = "mock-csrf-token"
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "mock-csrf-token"
    return client

def test_discovery_api_endpoints(auth_client, app):
    """Prueba todos los endpoints REST del motor de descubrimiento y feedback."""
    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])

        # Insertar datos de prueba
        db.execute("""
            INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at)
            VALUES (1, 'Cat A', 'cat-a', 1, 'now', 'now')
        """)
        db.execute("""
            INSERT INTO refresh_runs (id, status, requested_stages_json, current_stage, requested_at, counters_json, errors_json)
            VALUES (1, 'running', '["discovery"]', 'discovery', 'now', '{}', '{}')
        """)
        db.commit()

        # 1. Crear canal y video candidatos
        channel_data = {"youtube_channel_id": "UC_API_1", "title": "Canal API 1"}
        video_data = {"youtube_video_id": "vid_api_1", "title": "Video API 1", "published_at": "2026-07-30T10:00:00Z"}
        cid, vid = DiscoveryRepository.upsert_channel_and_video(db, channel_data, video_data)

        candidate = DiscoveryCandidateDomain(
            video_id=vid,
            youtube_video_id="vid_api_1",
            channel_id=cid,
            youtube_channel_id="UC_API_1",
            channel_title="Canal API 1",
            title="Video API 1",
            description="",
            published_at="2026-07-30T10:00:00Z",
            duration_seconds=300,
            content_type="video",
            score=75.0,
            band=Band.RELATED,
            reasons=["Razón API"],
            selection_rank=1,
            category_id=1
        )
        DiscoveryRepository.save_discovery_candidate(db, candidate, refresh_run_id=1)

        # Insertar batch summary para FK/datos
        counts = {
            "targetByBand": {"related": 5, "adjacent": 2, "exploratory": 1},
            "selectedByBand": {"related": 1, "adjacent": 0, "exploratory": 0}
        }
        DiscoveryRepository.save_discovery_batch(db, run_id=1, category_id=1, counts_dict=counts)
        db.commit()
        db.close()

    # A. GET /api/v1/discoveries
    resp = auth_client.get("/api/v1/discoveries?categoryId=1")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert len(data["items"]) == 1
    assert data["items"][0]["video"]["youtubeVideoId"] == "vid_api_1"
    assert len(data["batches"]) == 1
    assert data["batches"][0]["categoryId"] == 1

    # B. POST /api/v1/discoveries/{videoId}/feedback (hide_video)
    resp = auth_client.post(f"/api/v1/discoveries/{vid}/feedback", json={
        "categoryId": 1,
        "action": "hide_video",
        "channelId": cid
    })
    assert resp.status_code == 200
    assert json.loads(resp.data)["applied"] is True

    # C. GET /api/v1/discoveries (debe estar vacío ahora porque se ocultó)
    resp = auth_client.get("/api/v1/discoveries?categoryId=1")
    assert resp.status_code == 200
    assert len(json.loads(resp.data)["items"]) == 0

    # D. GET /api/v1/settings/discovery-exclusions
    resp = auth_client.get("/api/v1/settings/discovery-exclusions")
    assert resp.status_code == 200
    excl = json.loads(resp.data)
    assert len(excl["hiddenVideos"]) == 1
    assert excl["hiddenVideos"][0]["video"]["youtubeVideoId"] == "vid_api_1"

    # E. DELETE /api/v1/discoveries/{videoId}/hidden (restaurar)
    resp = auth_client.delete(f"/api/v1/discoveries/{vid}/hidden?categoryId=1")
    assert resp.status_code == 204

    # F. GET /api/v1/discoveries (vuelve a aparecer)
    resp = auth_client.get("/api/v1/discoveries?categoryId=1")
    assert resp.status_code == 200
    assert len(json.loads(resp.data)["items"]) == 1

    # G. PUT /api/v1/channels/{channelId}/block
    resp = auth_client.put(f"/api/v1/channels/{cid}/block", json={"blocked": True})
    assert resp.status_code == 200
    assert json.loads(resp.data)["blocked"] is True

    # H. GET /api/v1/discoveries (vacío por canal bloqueado)
    resp = auth_client.get("/api/v1/discoveries?categoryId=1")
    assert len(json.loads(resp.data)["items"]) == 0

    # I. PUT /api/v1/channels/{channelId}/block (unblock)
    resp = auth_client.put(f"/api/v1/channels/{cid}/block", json={"blocked": False})
    assert resp.status_code == 200
    assert json.loads(resp.data)["blocked"] is False

    # J. GET /api/v1/channels/{channelId}/suggest-follow
    resp = auth_client.get(f"/api/v1/channels/{cid}/suggest-follow?categoryId=1")
    assert resp.status_code == 200
    assert json.loads(resp.data)["suggestFollow"] is False # Solo 0 interacciones positivas
