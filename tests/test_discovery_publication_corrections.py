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
                    "youtube_channel_id": f"UC_FOTO_{self.search_call_count}",
                }
            ]
        else:
            raise YouTubeQuotaError("Quota exceeded on query")


class TimeoutGateway(FakeYouTubeGateway):
    def search_videos(
        self, access_token, q, published_after=None, limit=25, region_code=None, relevance_language=None
    ):
        raise TimeoutError("YouTube API call timed out: token=SECRET_TOKEN https://private.internal/api")


def setup_base_db(conn, include_topic=True):
    """Auxiliar para inicializar credenciales, categoría 1 y datos del lote previo."""
    conn.execute(
        "INSERT INTO credentials (id, access_token, refresh_token, expires_at, updated_at) "
        "VALUES (1, ?, ?, '2030-01-01T00:00:00Z', 'now')",
        (encrypt_token("access"), encrypt_token("refresh")),
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
    if include_topic:
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


def test_corr_pub_incomplete_search_attempt_aborts_category(app):
    """Corrección 1 — Si la cuota global impide completar las búsquedas de A, A se aborta."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn, include_topic=True)
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

    class IncompleteAttemptGateway(FakeYouTubeGateway):
        def search_videos(
            self, access_token, q, published_after=None, limit=25, region_code="AR", relevance_language="es"
        ):
            if "cine" in q:
                raise YouTubeQuotaError("Quota exhausted during category B search")
            return [
                {
                    "youtube_video_id": "vid_cat1_1",
                    "title": "Fotografía profesional",
                    "description": "Curso completo",
                    "published_at": "2026-07-30T10:00:00Z",
                    "thumbnail_url": "thumb_1",
                    "channel_title": "Canal Foto 1",
                    "youtube_channel_id": "UC_FOTO_1",
                }
            ]

    gateway = IncompleteAttemptGateway()
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
        cand_a = conn.execute(
            "SELECT status FROM discovery_candidates WHERE video_id = 20 AND category_id = 1"
        ).fetchone()
        assert cand_a["status"] == "active", "Category A previous candidate must remain active"

        batch_a_run2 = conn.execute(
            "SELECT count(*) FROM discovery_batches WHERE refresh_run_id = 2 AND category_id = 1"
        ).fetchone()[0]
        assert batch_a_run2 == 0, "Category A partial results must not be published"

        batch_b_run2 = conn.execute(
            "SELECT count(*) FROM discovery_batches WHERE refresh_run_id = 2 AND category_id = 2"
        ).fetchone()[0]
        assert batch_b_run2 == 0, "Category B must retain previous batch"

        run_row = conn.execute("SELECT status, errors_json FROM refresh_runs WHERE id = 2").fetchone()
        assert run_row["status"] == "failed", "Run must fail as both categories were aborted"

        errors = json.loads(run_row["errors_json"])
        assert any(e.get("categoryId") == 1 and e.get("code") == "YOUTUBE_QUOTA_EXHAUSTED" for e in errors)
        assert any(e.get("categoryId") == 2 and e.get("code") == "YOUTUBE_QUOTA_EXHAUSTED" for e in errors)
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
    """CORR-PUB-04 — Hidratación de videos marcada como incompleta aborta la categoría usando HydrationResult."""
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
            "youtube_channel_id": "UC_FOTO_1",
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


def test_corr_pub_individual_disposable_absence_publishes(app):
    """Corrección 3 — Ausencia individual descartable: respuesta completa (complete=True) publica candidato válido."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn)
        finally:
            conn.close()

    fake_gateway = FakeYouTubeGateway()
    fake_gateway.strict_hydration = True
    fake_gateway.search_responses["default"] = [
        {
            "youtube_video_id": "v_exists",
            "title": "Fotografía de retrato",
            "description": "Curso básico",
            "published_at": "2026-07-30T10:00:00Z",
            "thumbnail_url": "thumb_1",
            "channel_title": "Canal A Completo",
            "youtube_channel_id": "UC_A",
        },
        {
            "youtube_video_id": "v_missing",
            "title": "Fotografía borrada",
            "description": "Video no encontrado",
            "published_at": "2026-07-30T10:00:00Z",
            "thumbnail_url": "thumb_2",
            "channel_title": "Canal A Completo",
            "youtube_channel_id": "UC_A",
        },
    ]
    fake_gateway.video_details = [{"youtube_video_id": "v_exists", "duration_seconds": 600, "content_type": "video"}]

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
        assert old_cand["status"] == "expired", "Old candidate must expire"

        active_cands = conn.execute(
            "SELECT count(*) FROM discovery_candidates WHERE status = 'active' AND last_refresh_run_id = 2"
        ).fetchone()[0]
        assert active_cands == 1

        assert stats["categories"][1]["failed"] is False
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
            "youtube_channel_id": "UC_FOTO_1",
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
            "youtube_channel_id": f"UC_FOTO_{i}",
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


def test_corr_pub_empty_batch_insufficient_signals(app):
    """Corrección 2.1 — Batch vacío por falta de señales: persiste batch, expira candidatos anteriores."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO credentials (id, access_token, refresh_token, expires_at, updated_at) "
                "VALUES (1, ?, ?, '2030-01-01T00:00:00Z', 'now')",
                (encrypt_token("access"), encrypt_token("refresh")),
            )
            conn.execute(
                "INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) "
                "VALUES (1, 'Vacia', 'vacia', 1, 'now', 'now')"
            )
            conn.execute(
                "INSERT INTO channels (id, youtube_channel_id, title, created_at, updated_at) "
                "VALUES (10, 'UC_OLD', 'Canal Viejo', 'now', 'now')"
            )
            conn.execute(
                "INSERT INTO videos (id, youtube_video_id, channel_id, title, published_at, created_at, updated_at) "
                "VALUES (20, 'vid_old', 10, 'Video Viejo', '2026-07-20T10:00:00Z', 'now', 'now')"
            )
            conn.execute(
                "INSERT INTO refresh_runs "
                "(id, status, requested_stages_json, current_stage, requested_at, counters_json, errors_json) "
                "VALUES (1, 'succeeded', '[\"discovery\"]', 'discovery', 'now', '{}', '[]')"
            )
            conn.execute("""
                INSERT INTO discovery_candidates (
                    video_id, category_id, score, band, reasons_json, status,
                    last_refresh_run_id, selection_rank, first_seen_at, last_seen_at
                ) VALUES (20, 1, 60.0, 'related', '["Old"]', 'active', 1, 1, 'now', 'now')
            """)
            conn.execute(
                "INSERT INTO refresh_runs "
                "(id, status, requested_stages_json, current_stage, requested_at, counters_json, errors_json) "
                "VALUES (2, 'running', '[\"discovery\"]', 'discovery', 'now', '{}', '[]')"
            )
            conn.commit()
        finally:
            conn.close()

    fake_gateway = FakeYouTubeGateway()
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
        assert old_cand["status"] == "expired", "Previous candidate must be expired"

        batch_row = conn.execute(
            "SELECT selected_total, shortfall_reason FROM discovery_batches "
            "WHERE refresh_run_id = 2 AND category_id = 1"
        ).fetchone()
        assert batch_row is not None, "Empty batch must be persisted"
        assert batch_row["selected_total"] == 0
        assert batch_row["shortfall_reason"] == "insufficient_signals"
        assert stats["categories"][1]["failed"] is False
    finally:
        conn.close()


def test_corr_pub_empty_batch_no_results(app):
    """Corrección 2.2 — Cero resultados externos exitosos: persiste batch con shortfall_reason, expira anteriores."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn, include_topic=False)
        finally:
            conn.close()

    fake_gateway = FakeYouTubeGateway()
    fake_gateway.search_responses["default"] = []

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
        assert old_cand["status"] == "expired", "Previous candidate must be expired"

        batch_row = conn.execute(
            "SELECT selected_total, shortfall_reason FROM discovery_batches "
            "WHERE refresh_run_id = 2 AND category_id = 1"
        ).fetchone()
        assert batch_row is not None, "Empty batch must be persisted"
        assert batch_row["selected_total"] == 0
        assert batch_row["shortfall_reason"] == "insufficient_candidates"
        assert stats["categories"][1]["failed"] is False
    finally:
        conn.close()


def test_corr_pub_empty_batch_transaction_rollback(app):
    """Corrección 2.3 — Fallo durante transacción de batch vacío realiza rollback total dejando lote previo intacto."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn, include_topic=False)
        finally:
            conn.close()

    fake_gateway = FakeYouTubeGateway()
    fake_gateway.search_responses["default"] = []

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=fake_gateway)
            with patch.object(
                DiscoveryRepository, "expire_previous_candidates", side_effect=RuntimeError("Expire crash")
            ):
                stats = service.run_discovery(conn, run_id=2)
        finally:
            conn.close()

    conn = get_db_connection(db_path)
    try:
        old_cand = conn.execute(
            "SELECT status FROM discovery_candidates WHERE video_id = 20 AND category_id = 1"
        ).fetchone()
        assert old_cand["status"] == "active", "Old candidate must remain active after rollback"

        batch_run2 = conn.execute(
            "SELECT count(*) FROM discovery_batches WHERE refresh_run_id = 2 AND category_id = 1"
        ).fetchone()[0]
        assert batch_run2 == 0, "No batch must be created after rollback"
        assert stats["categories"][1]["failed"] is True
    finally:
        conn.close()


def test_corr_pub_07_isolated_categories(app):
    """CORR-PUB-07 — Categoría 1 completa búsquedas; Categoría 2 falla por cuota posteriormente."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn, include_topic=False)
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

    search_items_cat1 = []
    for i in range(1, 6):
        cid = f"UC_{chr(64 + ((i - 1) // 2 + 1))}"
        search_items_cat1.append({
            "youtube_video_id": f"vid_cat1_{i}",
            "title": f"Fotografía de retrato {i}",
            "description": "Curso completo",
            "published_at": f"2026-07-30T{10+i}:00:00Z",
            "thumbnail_url": f"thumb_{i}",
            "channel_title": f"Canal {cid}",
            "youtube_channel_id": cid,
        })
    for i in (6, 7):
        cid = "UC_C" if i == 6 else "UC_D"
        search_items_cat1.append({
            "youtube_video_id": f"vid_cat1_{i}",
            "title": f"Fotografía e iluminación {i}",
            "description": "Iluminación",
            "published_at": f"2026-07-30T{10+i}:00:00Z",
            "thumbnail_url": f"thumb_{i}",
            "channel_title": f"Canal {cid}",
            "youtube_channel_id": cid,
        })
    search_items_cat1.append({
        "youtube_video_id": "vid_cat1_8",
        "title": "Fotografía de estudio 8",
        "description": "Estudio",
        "published_at": "2026-07-30T18:00:00Z",
        "thumbnail_url": "thumb_8",
        "channel_title": "Canal UC_D",
        "youtube_channel_id": "UC_D",
    })

    class IsolatedGateway(FakeYouTubeGateway):
        def search_videos(
            self, access_token, q, published_after=None, limit=25, region_code="AR", relevance_language="es"
        ):
            if "cine" in q:
                raise YouTubeQuotaError("Quota exhausted for cine category")
            return search_items_cat1

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
            "SELECT selected_total, shortfall_reason FROM discovery_batches "
            "WHERE refresh_run_id = 2 AND category_id = 1"
        ).fetchone()
        assert cat1_batch is not None
        assert cat1_batch["selected_total"] == 8
        assert cat1_batch["shortfall_reason"] is None

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
    """CORR-PUB-08 — Excepción en expire_previous_candidates produce rollback atómico real."""
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
            "youtube_channel_id": "UC_FOTO_1",
        }
    ]

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=fake_gateway)
            with patch.object(
                DiscoveryRepository,
                "expire_previous_candidates",
                side_effect=RuntimeError("DB write crash during expire"),
            ):
                stats = service.run_discovery(conn, run_id=2)
        finally:
            conn.close()

    conn = get_db_connection(db_path)
    try:
        chans = conn.execute("SELECT count(*) FROM channels WHERE youtube_channel_id = 'UC_FOTO_1'").fetchone()[0]
        assert chans == 0, "New channel must be rolled back"

        vids = conn.execute("SELECT count(*) FROM videos WHERE youtube_video_id = 'vid_err_1'").fetchone()[0]
        assert vids == 0, "New video must be rolled back"

        cands = conn.execute("SELECT count(*) FROM discovery_candidates WHERE last_refresh_run_id = 2").fetchone()[0]
        assert cands == 0, "New candidate must be rolled back"

        batches = conn.execute("SELECT count(*) FROM discovery_batches WHERE refresh_run_id = 2").fetchone()[0]
        assert batches == 0, "New batch must be rolled back"

        old_cand = conn.execute(
            "SELECT status FROM discovery_candidates WHERE video_id = 20 AND category_id = 1"
        ).fetchone()
        assert old_cand["status"] == "active", "Candidato anterior debe mantenerse activo"

        assert stats["categories"][1]["failed"] is True
    finally:
        conn.close()


def test_corr_pub_09_idempotent_retry_after_aborted_attempt(app):
    """CORR-PUB-09 — Intento abortado (run 2), refresh exitoso (run 3) y reintento con mismos datos (run 4)."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn)
        finally:
            conn.close()

    fake_gateway_quota = QuotaFailureGateway(fail_at_call=1)
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=fake_gateway_quota)
            service.run_discovery(conn, run_id=2)
        finally:
            conn.close()

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

    fake_gateway_ok = FakeYouTubeGateway()
    fake_gateway_ok.search_responses["default"] = [
        {
            "youtube_video_id": "vid_retry_1",
            "title": "Fotografía avanzada",
            "description": "Curso avanzado",
            "published_at": "2026-07-30T10:00:00Z",
            "thumbnail_url": "thumb_1",
            "channel_title": "Canal Foto 1",
            "youtube_channel_id": "UC_FOTO_1",
        }
    ]

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=fake_gateway_ok)
            stats3 = service.run_discovery(conn, run_id=3)
        finally:
            conn.close()

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO refresh_runs "
                "(id, status, worker_id, requested_stages_json, current_stage, "
                "requested_at, counters_json, errors_json) "
                "VALUES (4, 'running', 'w-1', '[\"discovery\"]', 'discovery', 'now', '{}', '[]')"
            )
            conn.commit()
        finally:
            conn.close()

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=fake_gateway_ok)
            stats4 = service.run_discovery(conn, run_id=4)
        finally:
            conn.close()

    conn = get_db_connection(db_path)
    try:
        chans_count = conn.execute(
            "SELECT count(*) FROM channels WHERE youtube_channel_id = 'UC_FOTO_1'"
        ).fetchone()[0]
        assert chans_count == 1, "Exactly 1 channel row per youtube_channel_id"

        vids_count = conn.execute("SELECT count(*) FROM videos WHERE youtube_video_id = 'vid_retry_1'").fetchone()[0]
        assert vids_count == 1, "Exactly 1 video row per youtube_video_id"

        cand_sql = (
            "SELECT count(*) FROM discovery_candidates WHERE category_id = 1 AND video_id = "
            "(SELECT id FROM videos WHERE youtube_video_id = 'vid_retry_1')"
        )
        cand_rows = conn.execute(cand_sql).fetchone()[0]
        assert cand_rows == 1, "Exactly 1 candidate row per video/category"

        active_cands = conn.execute(
            "SELECT count(*) FROM discovery_candidates WHERE category_id = 1 AND status = 'active'"
        ).fetchone()[0]
        assert active_cands == 1, "Exactly 1 active candidate"

        batch_run3 = conn.execute(
            "SELECT count(*) FROM discovery_batches WHERE refresh_run_id = 3 AND category_id = 1"
        ).fetchone()[0]
        assert batch_run3 == 1

        batch_run4 = conn.execute(
            "SELECT count(*) FROM discovery_batches WHERE refresh_run_id = 4 AND category_id = 1"
        ).fetchone()[0]
        assert batch_run4 == 1

        old_cand = conn.execute(
            "SELECT status FROM discovery_candidates WHERE video_id = 20 AND category_id = 1"
        ).fetchone()
        assert old_cand["status"] == "expired"

        assert stats3["categories"][1]["failed"] is False
        assert stats4["categories"][1]["failed"] is False
    finally:
        conn.close()


def test_corr_pub_logs_sanitization(app, caplog):
    """Corrección 6 — Verifica que los errores procesados por DiscoveryService se registren sin datos sensibles."""
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
            service.run_discovery(conn, run_id=2)
        finally:
            conn.close()

    log_text = caplog.text
    assert "SECRET_TOKEN" not in log_text, "SECRET_TOKEN must not leak into logs"
    assert "token=" not in log_text, "token parameter must not leak into logs"
    assert "private.internal" not in log_text, "private host must not leak into logs"
    assert "https://" not in log_text, "URL must not leak into logs"


def test_corr_pub_full_batch_has_no_shortfall(app):
    """Corrección 1 — Lote completo de 8 candidatos debe tener shortfall_reason = None (NULL en BD)."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn, include_topic=True)
        finally:
            conn.close()

    fake_gateway = FakeYouTubeGateway()
    search_items = []
    for i in range(1, 6):
        cid = f"UC_{chr(64 + ((i - 1) // 2 + 1))}"
        search_items.append({
            "youtube_video_id": f"vid_f_{i}",
            "title": f"Fotografía de retrato {i}",
            "description": "Curso completo",
            "published_at": f"2026-07-30T{10+i}:00:00Z",
            "thumbnail_url": f"thumb_{i}",
            "channel_title": f"Canal {cid}",
            "youtube_channel_id": cid,
        })
    for i in (6, 7):
        cid = "UC_C" if i == 6 else "UC_D"
        search_items.append({
            "youtube_video_id": f"vid_f_{i}",
            "title": f"Fotografía e iluminación {i}",
            "description": "Iluminación profesional",
            "published_at": f"2026-07-30T{10+i}:00:00Z",
            "thumbnail_url": f"thumb_{i}",
            "channel_title": f"Canal {cid}",
            "youtube_channel_id": cid,
        })
    search_items.append({
        "youtube_video_id": "vid_f_8",
        "title": "Iluminación de estudio 8",
        "description": "Estudio fotográfico",
        "published_at": "2026-07-30T18:00:00Z",
        "thumbnail_url": "thumb_8",
        "channel_title": "Canal UC_D",
        "youtube_channel_id": "UC_D",
    })
    fake_gateway.search_responses["default"] = search_items

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=fake_gateway)
            stats = service.run_discovery(conn, run_id=2)
        finally:
            conn.close()

    conn = get_db_connection(db_path)
    try:
        batch_row = conn.execute(
            "SELECT selected_total, shortfall_reason FROM discovery_batches "
            "WHERE refresh_run_id = 2 AND category_id = 1"
        ).fetchone()
        assert batch_row["selected_total"] == 8
        assert batch_row["shortfall_reason"] is None, "Shortfall must be NULL when selected == target"

        cat_stats = stats["categories"][1]
        assert cat_stats["selected"] == 8
        assert cat_stats["shortfall"] is None
        assert cat_stats["failed"] is False
    finally:
        conn.close()


def test_corr_pub_hydration_quota_in_video_details_stops_subsequent_calls(app):
    """Corrección 2 — Cuota durante get_videos_details detiene hidratación de categorías posteriores."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn, include_topic=False)
            conn.execute(
                "INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) "
                "VALUES (2, 'Cine', 'cine', 2, 'now', 'now')"
            )
            conn.execute(
                "INSERT INTO category_keywords (category_id, term, polarity, weight) "
                "VALUES (2, 'cine', 'positive', 1.0)"
            )
            conn.commit()
        finally:
            conn.close()

    class QuotaInVideoHydrationGateway(FakeYouTubeGateway):
        def get_videos_details(self, access_token, video_ids):
            self.video_hydration_calls += 1
            raise YouTubeQuotaError("Quota exhausted during video hydration")

    gateway = QuotaInVideoHydrationGateway()
    gateway.search_responses["default"] = [
        {
            "youtube_video_id": "vid_q_1",
            "title": "Fotografía de retrato",
            "description": "Curso completo",
            "published_at": "2026-07-30T10:00:00Z",
            "thumbnail_url": "thumb_1",
            "channel_title": "Canal A",
            "youtube_channel_id": "UC_A",
        }
    ]

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=gateway)
            stats = service.run_discovery(conn, run_id=2)
        finally:
            conn.close()

    conn = get_db_connection(db_path)
    try:
        assert gateway.video_hydration_calls == 1
        assert gateway.channel_hydration_calls == 0

        batches = conn.execute("SELECT count(*) FROM discovery_batches WHERE refresh_run_id = 2").fetchone()[0]
        assert batches == 0, "No batch must be created for run 2"

        cand_old = conn.execute(
            "SELECT status FROM discovery_candidates WHERE video_id = 20 AND category_id = 1"
        ).fetchone()
        assert cand_old["status"] == "active", "Old candidate must remain active"

        assert stats["quota_exhausted"] is True
        assert stats["categories"][1]["failed"] is True
        assert stats["categories"][2]["failed"] is True
        assert any(e.get("categoryId") == 1 and e.get("code") == "YOUTUBE_QUOTA_EXHAUSTED" for e in stats["errors"])
        assert any(e.get("categoryId") == 2 and e.get("code") == "YOUTUBE_QUOTA_EXHAUSTED" for e in stats["errors"])
    finally:
        conn.close()


def test_corr_pub_hydration_quota_in_channel_details_stops_subsequent_calls(app):
    """Corrección 2 — Cuota durante get_channels_details detiene hidratación de categorías posteriores."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn, include_topic=False)
            conn.execute(
                "INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) "
                "VALUES (2, 'Cine', 'cine', 2, 'now', 'now')"
            )
            conn.execute(
                "INSERT INTO category_keywords (category_id, term, polarity, weight) "
                "VALUES (2, 'cine', 'positive', 1.0)"
            )
            conn.commit()
        finally:
            conn.close()

    class QuotaInChannelHydrationGateway(FakeYouTubeGateway):
        def get_channels_details(self, access_token, channel_ids):
            self.channel_hydration_calls += 1
            raise YouTubeQuotaError("Quota exhausted during channel hydration")

    gateway = QuotaInChannelHydrationGateway()
    gateway.search_responses["default"] = [
        {
            "youtube_video_id": "vid_qc_1",
            "title": "Fotografía de retrato",
            "description": "Curso completo",
            "published_at": "2026-07-30T10:00:00Z",
            "thumbnail_url": "thumb_1",
            "channel_title": "Canal A",
            "youtube_channel_id": "UC_A",
        }
    ]

    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            service = DiscoveryService(gateway=gateway)
            stats = service.run_discovery(conn, run_id=2)
        finally:
            conn.close()

    conn = get_db_connection(db_path)
    try:
        assert gateway.video_hydration_calls == 1
        assert gateway.channel_hydration_calls == 1

        batches = conn.execute("SELECT count(*) FROM discovery_batches WHERE refresh_run_id = 2").fetchone()[0]
        assert batches == 0

        cand_old = conn.execute(
            "SELECT status FROM discovery_candidates WHERE video_id = 20 AND category_id = 1"
        ).fetchone()
        assert cand_old["status"] == "active"

        assert stats["quota_exhausted"] is True
        assert stats["categories"][1]["failed"] is True
        assert stats["categories"][2]["failed"] is True
    finally:
        conn.close()


def test_corr_pub_hydration_quota_isolated_successful_category(app):
    """Corrección 2 — Categoría A completa hidratación y publica; Categoría B falla por cuota durante hidratación."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            setup_base_db(conn, include_topic=True)
            conn.execute(
                "INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) "
                "VALUES (2, 'Cine', 'cine', 2, 'now', 'now')"
            )
            conn.execute(
                "INSERT INTO category_keywords (category_id, term, polarity, weight) "
                "VALUES (2, 'cine', 'positive', 1.0)"
            )
            conn.commit()
        finally:
            conn.close()

    class QuotaOnCatBVideoHydrationGateway(FakeYouTubeGateway):
        def get_videos_details(self, access_token, video_ids):
            self.video_hydration_calls += 1
            if "vid_cat2_1" in video_ids:
                raise YouTubeQuotaError("Quota exhausted on Category B video hydration")
            return super().get_videos_details(access_token, video_ids)

    gateway = QuotaOnCatBVideoHydrationGateway()
    search_items_cat1 = []
    for i in range(1, 6):
        cid = f"UC_{chr(64 + ((i - 1) // 2 + 1))}"
        search_items_cat1.append({
            "youtube_video_id": f"vid_cat1_{i}",
            "title": f"Fotografía de retrato {i}",
            "description": "Curso completo",
            "published_at": f"2026-07-30T{10+i}:00:00Z",
            "thumbnail_url": f"thumb_{i}",
            "channel_title": f"Canal {cid}",
            "youtube_channel_id": cid,
        })
    for i in (6, 7):
        cid = "UC_C" if i == 6 else "UC_D"
        search_items_cat1.append({
            "youtube_video_id": f"vid_cat1_{i}",
            "title": f"Fotografía e iluminación {i}",
            "description": "Iluminación",
            "published_at": f"2026-07-30T{10+i}:00:00Z",
            "thumbnail_url": f"thumb_{i}",
            "channel_title": f"Canal {cid}",
            "youtube_channel_id": cid,
        })
    search_items_cat1.append({
        "youtube_video_id": "vid_cat1_8",
        "title": "Iluminación de estudio 8",
        "description": "Estudio",
        "published_at": "2026-07-30T18:00:00Z",
        "thumbnail_url": "thumb_8",
        "channel_title": "Canal UC_D",
        "youtube_channel_id": "UC_D",
    })

    search_items_cat2 = [
        {
            "youtube_video_id": "vid_cat2_1",
            "title": "Cine documental",
            "description": "Documental",
            "published_at": "2026-07-30T10:00:00Z",
            "thumbnail_url": "thumb_c2",
            "channel_title": "Canal Cine",
            "youtube_channel_id": "UC_CINE",
        }
    ]

    gateway.search_responses["fotografia"] = search_items_cat1
    gateway.search_responses["fotografia retrato"] = search_items_cat1
    gateway.search_responses["fotografia iluminacion"] = search_items_cat1
    gateway.search_responses["cine"] = search_items_cat2

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
        run_row = conn.execute("SELECT status FROM refresh_runs WHERE id = 2").fetchone()
        assert run_row["status"] == "partial"

        cat1_batch = conn.execute(
            "SELECT selected_total, shortfall_reason FROM discovery_batches "
            "WHERE refresh_run_id = 2 AND category_id = 1"
        ).fetchone()
        assert cat1_batch is not None
        assert cat1_batch["selected_total"] == 8
        assert cat1_batch["shortfall_reason"] is None

        cat2_batch = conn.execute(
            "SELECT count(*) FROM discovery_batches WHERE refresh_run_id = 2 AND category_id = 2"
        ).fetchone()[0]
        assert cat2_batch == 0
    finally:
        conn.close()
