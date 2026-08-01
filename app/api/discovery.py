import os
from flask import Blueprint, jsonify, request, current_app
from app.db import get_db_connection
from app.repositories.discovery_repository import DiscoveryRepository
from app.repositories.refresh_run_repository import RefreshRunRepository
from app.repositories.exploration_topic_repository import ExplorationTopicRepository
from app.services.exploration_topic_service import ExplorationTopicService
from app.services.refresh_orchestrator import RefreshOrchestrator

discovery_bp = Blueprint("discovery", __name__)

@discovery_bp.route("/discoveries", methods=["GET"])
def list_discoveries():
    cat_id = request.args.get("categoryId", type=int)
    band = request.args.get("band", default="all")
    offset = request.args.get("cursor", default="0")
    limit = request.args.get("limit", default="25", type=int)
    
    try:
        offset_int = int(offset)
    except ValueError:
        offset_int = 0

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        recs, batches, next_cursor = DiscoveryRepository.get_active_batch_recommendations(
            db, category_id=cat_id, band=band, offset=offset_int, limit=limit
        )
        return jsonify({
            "items": recs,
            "batches": batches,
            "nextCursor": next_cursor
        })
    finally:
        db.close()

@discovery_bp.route("/discoveries/<int:video_id>/feedback", methods=["POST"])
def submit_discovery_feedback(video_id):
    body = request.get_json() or {}
    category_id = body.get("categoryId")
    action = body.get("action")
    channel_id = body.get("channelId")
    
    if not category_id or not action:
        return jsonify({"error": {"message": "Falta categoryId o action"}}), 400
        
    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        # Si no se pasó channelId, podemos obtenerlo del video
        if not channel_id:
            cursor = db.execute("SELECT channel_id FROM videos WHERE id = ?", (video_id,))
            row = cursor.fetchone()
            if row:
                channel_id = row["channel_id"]
                
        DiscoveryRepository.save_feedback(db, video_id=video_id, channel_id=channel_id, category_id=category_id, action=action)
        db.commit()
        return jsonify({"applied": True})
    finally:
        db.close()

@discovery_bp.route("/discoveries/<int:video_id>/hidden", methods=["DELETE"])
def restore_hidden_discovery(video_id):
    category_id = request.args.get("categoryId", type=int)
    if not category_id:
        return jsonify({"error": {"message": "Falta categoryId"}}), 400
        
    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        # Revertir ocultación: eliminar el feedback 'hide_video' de la categoría
        # y poner el candidato de vuelta en 'active'
        db.execute("""
            DELETE FROM discovery_feedback
            WHERE video_id = ? AND category_id = ? AND action = 'hide_video'
        """, (video_id, category_id))
        
        db.execute("""
            UPDATE discovery_candidates
            SET status = 'active'
            WHERE video_id = ? AND category_id = ? AND status = 'hidden'
        """, (video_id, category_id))
        
        db.commit()
        return "", 204
    finally:
        db.close()

@discovery_bp.route("/settings/discovery-exclusions", methods=["GET"])
def list_discovery_exclusions():
    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        # 1. Canales bloqueados
        cursor = db.execute("SELECT id, youtube_channel_id, title FROM channels WHERE is_blocked = 1")
        blocked_channels = [dict(row) for row in cursor.fetchall()]
        
        # 2. Videos ocultos
        cursor = db.execute("""
            SELECT v.id, v.youtube_video_id, v.title, df.category_id, df.created_at
            FROM discovery_feedback df
            JOIN videos v ON df.video_id = v.id
            WHERE df.action = 'hide_video'
        """)
        hidden_videos = [dict(row) for row in cursor.fetchall()]
        
        return jsonify({
            "blockedChannels": blocked_channels,
            "hiddenVideos": hidden_videos
        })
    finally:
        db.close()

@discovery_bp.route("/refresh-runs", methods=["GET"])
def list_refresh_runs():
    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        runs = RefreshRunRepository.list_all(db)
        return jsonify({"items": runs})
    finally:
        db.close()

@discovery_bp.route("/refresh-runs", methods=["POST"])
def start_refresh():
    body = request.get_json() or {}
    stages = body.get("stages") or ["subscriptions", "followed_videos", "discovery"]
    
    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        if RefreshRunRepository.has_active_run(db):
            return jsonify({"error": {"message": "Ya hay una actualización activa en curso."}}), 409
            
        run_id = RefreshRunRepository.create(db, stages)
        db.commit()
        run = RefreshRunRepository.get_by_id(db, run_id)
        
        # Desencadenar el procesamiento en segundo plano si no es testing
        if not current_app.config.get("TESTING"):
            import threading
            worker_id = f"web_thread_{os.getpid()}"
            def bg_job():
                # Nueva conexión en el hilo de fondo
                bg_db = get_db_connection(current_app.config["DATABASE_PATH"])
                try:
                    orchestrator = RefreshOrchestrator()
                    orchestrator.run_refresh(bg_db, run_id, worker_id)
                    bg_db.commit()
                except Exception as e:
                    current_app.logger.error(f"Error en worker en background: {e}")
                finally:
                    bg_db.close()
            threading.Thread(target=bg_job, daemon=True).start()
            
        return jsonify(run), 202
    finally:
        db.close()

@discovery_bp.route("/refresh-runs/<int:run_id>", methods=["GET"])
def get_refresh_run(run_id):
    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        run = RefreshRunRepository.get_by_id(db, run_id)
        if not run:
            return jsonify({"error": {"message": "Actualización no encontrada."}}), 404
        return jsonify(run)
    finally:
        db.close()

@discovery_bp.route("/categories/<int:category_id>/exploration-topics", methods=["GET"])
def list_exploration_topics(category_id):
    status = request.args.get("status", default="all")
    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        all_topics = ExplorationTopicService.list_topics(db, category_id)
        if status != "all":
            all_topics = [t for t in all_topics if t["status"] == status]
        return jsonify({"items": all_topics})
    finally:
        db.close()

@discovery_bp.route("/categories/<int:category_id>/exploration-topics", methods=["POST"])
def create_exploration_topic(category_id):
    body = request.get_json() or {}
    term = body.get("term")
    weight = body.get("weight", 1.0)
    
    if not term:
        return jsonify({"error": {"message": "Falta el término"}}), 400
        
    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        # Validar si ya existe
        norm = normalize_term(term)
        existing = ExplorationTopicRepository.get_by_category_and_term(db, category_id, norm)
        if existing:
            return jsonify({"error": {"message": "El tema ya existe en esta categoría."}}), 409
            
        topic_id = ExplorationTopicService.create_manual_topic(db, category_id, term, weight)
        db.commit()
        topic = ExplorationTopicRepository.get_by_category_and_term(db, category_id, norm)
        return jsonify(topic), 201
    finally:
        db.close()

@discovery_bp.route("/categories/<int:category_id>/exploration-topics/<int:topic_id>", methods=["PATCH"])
def update_exploration_topic(category_id, topic_id):
    body = request.get_json() or {}
    status = body.get("status")
    weight = body.get("weight")
    
    if not status and weight is None:
        return jsonify({"error": {"message": "Falta status o weight"}}), 400
        
    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        # Validar pertenencia del tema
        cursor = db.execute("SELECT id, term FROM category_exploration_topics WHERE id = ? AND category_id = ?", (topic_id, category_id))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": {"message": "Tema no encontrado en esta categoría."}}), 404
            
        if status:
            ExplorationTopicService.update_topic_status(db, topic_id, status)
        if weight is not None:
            db.execute("UPDATE category_exploration_topics SET weight = ? WHERE id = ?", (weight, topic_id))
            
        db.commit()
        # Obtener tema actualizado
        cursor = db.execute("SELECT * FROM category_exploration_topics WHERE id = ?", (topic_id,))
        topic = dict(cursor.fetchone())
        return jsonify(topic)
    finally:
        db.close()

@discovery_bp.route("/channels/<int:channel_id>/suggest-follow", methods=["GET"])
def suggest_follow_channel(channel_id):
    category_id = request.args.get("categoryId", type=int)
    if not category_id:
        return jsonify({"error": {"message": "Falta categoryId"}}), 400
        
    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        count = DiscoveryRepository.get_channel_positive_videos_count(db, category_id, channel_id)
        suggest = count >= 2
        return jsonify({
            "channelId": channel_id,
            "categoryId": category_id,
            "positiveVideosCount": count,
            "suggestFollow": suggest
        })
    finally:
        db.close()
