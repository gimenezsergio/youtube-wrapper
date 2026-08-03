import json
from unittest.mock import patch

from app.auth.encryption import encrypt_token
from app.db import get_db_connection
from app.integrations.youtube.gateway import YouTubeQuotaError
from app.repositories.discovery_repository import DiscoveryRepository
from app.services.discovery_service import DiscoveryService
from app.services.refresh_orchestrator import RefreshOrchestrator
from tests.fakes.youtube_gateway import FakeYouTubeGateway


class QuotaFailureGateway(FakeYouTubeGateway):
    def __init__(self, fail_at_call: int = 2):
        super().__init__()
        self.search_call_count = 0
        self.fail_at_call = fail_at_call

    def search_videos(
        self, access_token, q, published_after=None, limit=25, region_code=None, relevance_language=None
    ):
        self.search_call_count += 1
        if self.search_call_count < self.fail_at_call:
            return [
                {
                    "youtube_video_id": f"vid_new_{self.search_call_count}",
                    "title": f"Fotografía de retrato {self.search_call_count}",
                    "description": "Retrato",
                    "published_at": "2026-07-30T10:00:00Z",
                    "thumbnail_url": "thumb_1",
                    "channel_title": f"Canal Foto {self.search_call_count}",
                    "youtube_channel_id": f"UC_FOTO_{self.search_call_count}"
                }
            ]
        else:
            raise YouTubeQuotaError("Quota exceeded on query")


class TimeoutGateway(FakeYouTubeGateway):
    def search_videos(
        self, access_token, q, published_after=None, limit=25, region_code=None, relevance_language=None
    ):
        raise TimeoutError("YouTube API call timed out: token=SECRET_TOKEN https://private.internal/api")


def setup_base_db(conn):
    """Auxiliar para inicializar credenciales, categoría 1 y datos del lote previo."""
    conn.execute(
        "INSERT INTO credentials (id, access_token, refresh_token, expires_at, updated_at) "
        "VALUES (1, ?, ?, '2030-01-01T00:00:00Z', 'now')",
        (encrypt_token("access"), encrypt_token("refresh"))
    )
    conn.execute(
        "INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) "
        "VALUES (1, 'Fotografia', 'fotografia', 1, 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO category_keywords (category_id, term, polarity, weight) "
        "VALUES (1, 'fotografia', 'positive', 1.0)"
    )
    conn.execute(
        "INSERT INTO category_keywords (category_id, term, polarity, weight) "
        "VALUES (1, 'retrato', 'positive', 0.9)"
    )
    conn.execute(
        "INSERT INTO category_exploration_topics "
        "(category_id, term, normalized_term, weight, status, source, created_at, updated_at) "
        "VALUES (1, 'iluminacion', 'iluminacion', 1.0, 'approved', 'manual', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO refresh_runs "
        "(id, status, requested_stages_json, current_stage, requested_at, counters_json, errors_json) "
        "VALUES (1, 'succeeded', '[\"discovery\"]', 'discovery', 'now', '{}', '[]')"
    )
    conn.execute(
        "INSERT INTO channels (id, youtube_channel_id, title, created_at, updated_at) "
        "VALUES (10, 'UC_OLD', 'Canal Viejo', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO videos "
        "(id, youtube_video_id, channel_id, title, published_at, duration_seconds, created_at, updated_at) "
        "VALUES (20, 'vid_old', 10, 'Video Viejo', '2026-07-20T10:00:00Z', 500, 'now', 'now')"
    )
    conn.execute("""
        INSERT INTO discovery_candidates (
            video_id, category_id, score, band, reasons_json, status,
            last_refresh_run_id, selection_rank, first_seen_at, last_seen_at
        ) VALUES (20, 1, 60.0, 'related', '["Old reason"]', 'active', 1, 1, 'now', 'now')
    """)
    conn.execute("""
        INSERT INTO discovery_batches (
            refresh_run_id, category_id, target_total, selected_total,
            target_by_band_json, selected_by_band_json, shortfall_reason, generated_at
        ) VALUES (
            1, 1, 8, 1, '{"related": 5, "adjacent": 2, "exploratory": 1}',
            '{"related": 1, "adjacent": 0, "exploratory": 0}', NULL, 'now'
        )
    """)
    conn.execute(
        "INSERT INTO refresh_runs "
        "(id, status, worker_id, requested_stages_json, current_stage, requested_at, counters_json, errors_json) "
        "VALUES (2, 'running', 'w-1', '[\"discovery\"]', 'discovery', 'now', '{}', '[]')"
    )
    conn.commit()


def test_corr_pub_01_quota_before_results(app):
    """CORR-PUB-01 — Cuota antes de obtener resultados aborta la categoría sin alterar la BD."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn)
        finally:
            conn.close()

    fake_gateway = QuotaFailureGateway(fail_at_call=1)
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=fake_gateway)
            stats = service.run_discovery(conn, run_id=2)
        finally:
            conn.close()

    conn = get_db_connection(db_path)
    try:
        old_cand = conn.execute(
            "SELECT status FROM discovery_candidates WHERE video_id = 20 AND category_id = 1"
        ).fetchone()
        assert old_cand["status"] == "active", "Candidato anterior debe seguir activo"

        new_cands = conn.execute(
            "SELECT count(*) FROM discovery_candidates WHERE last_refresh_run_id = 2"
        ).fetchone()[0]
        assert new_cands == 0, "No debe haberse guardado ningún candidato nuevo"

        run2_batch = conn.execute(
            "SELECT count(*) FROM discovery_batches WHERE refresh_run_id = 2"
        ).fetchone()[0]
        assert run2_batch == 0, "No debe crearse batch para el intento fallido"

        assert stats["quota_exhausted"] is True
        assert stats["categories"][1]["failed"] is True
        assert any(e["code"] == "YOUTUBE_QUOTA_EXHAUSTED" for e in stats["errors"])
    finally:
        conn.close()


def test_corr_pub_02_quota_after_success_retains_previous_batch(app):
    """CORR-PUB-02 — Si ocurre una falla de cuota tras resultados previos, el lote anterior sigue active."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn)
        finally:
            conn.close()

    fake_gateway = QuotaFailureGateway(fail_at_call=2)
    fake_gateway.videos_details = [
        {"youtube_video_id": "vid_new_1", "duration_seconds": 600, "content_type": "video"}
    ]

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=fake_gateway)
            stats = service.run_discovery(conn, run_id=2)
        finally:
            conn.close()

    conn = get_db_connection(db_path)
    try:
        old_cand = conn.execute(
            "SELECT status FROM discovery_candidates WHERE video_id = 20 AND category_id = 1"
        ).fetchone()
        assert old_cand["status"] == "active", "Old candidate must remain active"

        new_cands = conn.execute(
            "SELECT status FROM discovery_candidates WHERE last_refresh_run_id = 2"
        ).fetchall()
        assert len(new_cands) == 0, "No new candidates should be published for run 2"

        batch_count = conn.execute(
            "SELECT count(*) FROM discovery_batches WHERE refresh_run_id = 2"
        ).fetchone()[0]
        assert batch_count == 0, "No batch must be published for aborted run 2"

        assert stats["categories"][1]["failed"] is True
        assert stats["categories"][1]["shortfall"] == "youtube_quota_exhausted"
    finally:
        conn.close()


def test_corr_pub_03_timeout_conserves_previous_batch(app):
    """CORR-PUB-03 — Timeout aborta la categoría, conserva el lote anterior y no expone datos sensibles."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn)
        finally:
            conn.close()

    fake_gateway = TimeoutGateway()
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=fake_gateway)
            stats = service.run_discovery(conn, run_id=2)
        finally:
            conn.close()

    conn = get_db_connection(db_path)
    try:
        old_cand = conn.execute(
            "SELECT status FROM discovery_candidates WHERE video_id = 20 AND category_id = 1"
        ).fetchone()
        assert old_cand["status"] == "active"

        err = stats["errors"][0]
        assert err["code"] == "YOUTUBE_TIMEOUT"
        assert "SECRET_TOKEN" not in err["message"]
        assert "private.internal" not in err["message"]
        assert "Se conservó el lote anterior" in err["message"]
    finally:
        conn.close()


def test_corr_pub_04_incomplete_video_hydration_aborts_category(app):
    """CORR-PUB-04 — Hidratación de videos marcada como incompleta aborta la categoría."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn)
        finally:
            conn.close()

    fake_gateway = FakeYouTubeGateway()
    fake_gateway.search_responses["default"] = [
        {
            "youtube_video_id": "v_inc_1",
            "title": "Fotografía básica",
            "description": "Curso básico",
            "published_at": "2026-07-30T10:00:00Z",
            "thumbnail_url": "thumb_1",
            "channel_title": "Canal Foto 1",
            "youtube_channel_id": "UC_FOTO_1"
        }
    ]
    fake_gateway.video_details_incomplete = True

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=fake_gateway)
            stats = service.run_discovery(conn, run_id=2)
        finally:
            conn.close()

    conn = get_db_connection(db_path)
    try:
        old_cand = conn.execute(
            "SELECT status FROM discovery_candidates WHERE video_id = 20 AND category_id = 1"
        ).fetchone()
        assert old_cand["status"] == "active"

        new_count = conn.execute(
            "SELECT count(*) FROM discovery_candidates WHERE last_refresh_run_id = 2"
        ).fetchone()[0]
        assert new_count == 0

        assert stats["categories"][1]["failed"] is True
    finally:
        conn.close()


def test_corr_pub_05_channel_hydration_failure_aborts_category(app):
    """CORR-PUB-05 — Fallo al hidratar canales aborta la categoría sin expirar nada."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn)
        finally:
            conn.close()

    fake_gateway = FakeYouTubeGateway()
    fake_gateway.search_responses["default"] = [
        {
            "youtube_video_id": "v_ch_1",
            "title": "Fotografía básica",
            "description": "Curso básico",
            "published_at": "2026-07-30T10:00:00Z",
            "thumbnail_url": "thumb_1",
            "channel_title": "Canal Foto 1",
            "youtube_channel_id": "UC_FOTO_1"
        }
    ]
    fake_gateway.channel_hydration_error = RuntimeError("Channel API failure")

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=fake_gateway)
            stats = service.run_discovery(conn, run_id=2)
        finally:
            conn.close()

    conn = get_db_connection(db_path)
    try:
        old_cand = conn.execute(
            "SELECT status FROM discovery_candidates WHERE video_id = 20 AND category_id = 1"
        ).fetchone()
        assert old_cand["status"] == "active"

        assert stats["categories"][1]["failed"] is True
    finally:
        conn.close()


def test_corr_pub_06_valid_partial_batch(app):
    """CORR-PUB-06 — Publica lote parcial válido de 6 candidatos y expira el anterior con shortfall_reason."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn)
        finally:
            conn.close()

    fake_gateway = FakeYouTubeGateway()
    search_results = []
    for i in range(1, 7):
        search_results.append({
            "youtube_video_id": f"vid_p_{i}",
            "title": f"Fotografía parte {i}",
            "description": "Curso fotografía",
            "published_at": f"2026-07-30T{10+i}:00:00Z",
            "thumbnail_url": f"thumb_{i}",
            "channel_title": f"Canal Foto {i}",
            "youtube_channel_id": f"UC_FOTO_{i}"
        })
    fake_gateway.search_responses["default"] = search_results

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=fake_gateway)
            stats = service.run_discovery(conn, run_id=2)
        finally:
            conn.close()

    conn = get_db_connection(db_path)
    try:
        old_cand = conn.execute(
            "SELECT status FROM discovery_candidates WHERE video_id = 20 AND category_id = 1"
        ).fetchone()
        assert old_cand["status"] == "expired"

        active_cands = conn.execute(
            "SELECT count(*) FROM discovery_candidates "
            "WHERE category_id = 1 AND status = 'active' AND last_refresh_run_id = 2"
        ).fetchone()[0]
        assert active_cands == 6

        batch_row = conn.execute(
            "SELECT selected_total, shortfall_reason FROM discovery_batches "
            "WHERE refresh_run_id = 2 AND category_id = 1"
        ).fetchone()
        assert batch_row["selected_total"] == 6
        assert batch_row["shortfall_reason"] == "insufficient_candidates"

        assert stats["categories"][1]["selected"] == 6
        assert stats["categories"][1]["shortfall"] == "insufficient_candidates"
    finally:
        conn.close()


def test_corr_pub_07_isolated_categories(app):
    """CORR-PUB-07 — Categoría 1 publica exitosamente y Categoría 2 falla por cuota: se aislan perfectamente."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn)
            conn.execute(
                "INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) "
                "VALUES (2, 'Cine', 'cine', 2, 'now', 'now')"
            )
            conn.execute(
                "INSERT INTO category_keywords (category_id, term, polarity, weight) "
                "VALUES (2, 'cine', 'positive', 1.0)"
            )
            conn.execute("""
                INSERT INTO discovery_batches (
                    refresh_run_id, category_id, target_total, selected_total,
                    target_by_band_json, selected_by_band_json, shortfall_reason, generated_at
                ) VALUES (
                    1, 2, 8, 1, '{"related": 5, "adjacent": 2, "exploratory": 1}',
                    '{"related": 1, "adjacent": 0, "exploratory": 0}', NULL, 'now'
                )
            """)
            conn.commit()
        finally:
            conn.close()

    class IsolatedGateway(FakeYouTubeGateway):
        def search_videos(
            self, access_token, q, published_after=None, limit=25, region_code="AR", relevance_language="es"
        ):
            if "cine" in q:
                raise YouTubeQuotaError("Quota exhausted for cine category")
            return [
                {
                    "youtube_video_id": "vid_cat1_1",
                    "title": "Fotografía profesional",
                    "description": "Curso completo",
                    "published_at": "2026-07-30T10:00:00Z",
                    "thumbnail_url": "thumb_1",
                    "channel_title": "Canal Foto 1",
                    "youtube_channel_id": "UC_FOTO_1"
                }
            ]

    gateway = IsolatedGateway()
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            orchestrator = RefreshOrchestrator(gateway=gateway)
            orchestrator.run_refresh(conn, run_id=2, worker_id="w-1")
            conn.commit()
        finally:
            conn.close()

    conn = get_db_connection(db_path)
    try:
        run_row = conn.execute(
            "SELECT status, counters_json, errors_json FROM refresh_runs WHERE id = 2"
        ).fetchone()
        assert run_row["status"] == "partial", "Refresh run status must be partial"

        cat1_batch = conn.execute(
            "SELECT selected_total FROM discovery_batches WHERE refresh_run_id = 2 AND category_id = 1"
        ).fetchone()
        assert cat1_batch is not None

        cat2_batch_run2 = conn.execute(
            "SELECT count(*) FROM discovery_batches WHERE refresh_run_id = 2 AND category_id = 2"
        ).fetchone()[0]
        assert cat2_batch_run2 == 0

        errors = json.loads(run_row["errors_json"])
        assert isinstance(errors, list)
        assert any(e.get("categoryId") == 2 and e.get("code") == "YOUTUBE_QUOTA_EXHAUSTED" for e in errors)
    finally:
        conn.close()


def test_corr_pub_08_publication_exception_rolls_back(app):
    """CORR-PUB-08 — Una excepción durante la escritura en SQLite produce un rollback atómico completo."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn)
        finally:
            conn.close()

    fake_gateway = FakeYouTubeGateway()
    fake_gateway.search_responses["default"] = [
        {
            "youtube_video_id": "vid_err_1",
            "title": "Fotografía básica",
            "description": "Curso básico",
            "published_at": "2026-07-30T10:00:00Z",
            "thumbnail_url": "thumb_1",
            "channel_title": "Canal Foto 1",
            "youtube_channel_id": "UC_FOTO_1"
        }
    ]

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=fake_gateway)

            with patch.object(
                DiscoveryRepository, "save_discovery_candidate", side_effect=RuntimeError("DB write crash")
            ):
                stats = service.run_discovery(conn, run_id=2)
        finally:
            conn.close()

    conn = get_db_connection(db_path)
    try:
        old_cand = conn.execute(
            "SELECT status FROM discovery_candidates WHERE video_id = 20 AND category_id = 1"
        ).fetchone()
        assert old_cand["status"] == "active", "Candidato anterior debe mantenerse activo"

        new_cands = conn.execute(
            "SELECT count(*) FROM discovery_candidates WHERE last_refresh_run_id = 2"
        ).fetchone()[0]
        assert new_cands == 0, "No debe guardarse ningún candidato parcial"

        new_batch = conn.execute(
            "SELECT count(*) FROM discovery_batches WHERE refresh_run_id = 2"
        ).fetchone()[0]
        assert new_batch == 0, "No debe guardarse ningún batch parcial"

        assert stats["categories"][1]["failed"] is True
    finally:
        conn.close()


def test_corr_pub_09_idempotent_retry_after_aborted_attempt(app):
    """CORR-PUB-09 — Después de un intento abortado, un reintento exitoso no duplica entidades y publica limpiamente."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn)
        finally:
            conn.close()

    # 1. Intento abortado (run 2)
    fake_gateway_quota = QuotaFailureGateway(fail_at_call=1)
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=fake_gateway_quota)
            service.run_discovery(conn, run_id=2)
        finally:
            conn.close()

    # Crear run 3 exitoso
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO refresh_runs "
                "(id, status, worker_id, requested_stages_json, current_stage, "
                "requested_at, counters_json, errors_json) "
                "VALUES (3, 'running', 'w-1', '[\"discovery\"]', 'discovery', 'now', '{}', '[]')"
            )
            conn.commit()
        finally:
            conn.close()

    # 2. Intento exitoso (run 3)
    fake_gateway_ok = FakeYouTubeGateway()
    fake_gateway_ok.search_responses["default"] = [
        {
            "youtube_video_id": "vid_retry_1",
            "title": "Fotografía avanzada",
            "description": "Curso avanzado",
            "published_at": "2026-07-30T10:00:00Z",
            "thumbnail_url": "thumb_1",
            "channel_title": "Canal Foto 1",
            "youtube_channel_id": "UC_FOTO_1"
        }
    ]

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=fake_gateway_ok)
            stats3 = service.run_discovery(conn, run_id=3)
        finally:
            conn.close()

    conn = get_db_connection(db_path)
    try:
        old_cand = conn.execute(
            "SELECT status FROM discovery_candidates WHERE video_id = 20 AND category_id = 1"
        ).fetchone()
        assert old_cand["status"] == "expired"

        cands_run3 = conn.execute(
            "SELECT count(*) FROM discovery_candidates WHERE last_refresh_run_id = 3 AND status = 'active'"
        ).fetchone()[0]
        assert cands_run3 == 1

        batch_run3 = conn.execute(
            "SELECT count(*) FROM discovery_batches WHERE refresh_run_id = 3 AND category_id = 1"
        ).fetchone()[0]
        assert batch_run3 == 1

        assert stats3["categories"][1]["selected"] == 1
        assert stats3["categories"][1]["failed"] is False
    finally:
        conn.close()
