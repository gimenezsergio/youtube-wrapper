import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from app.integrations.youtube.gateway import YouTubeGateway, YouTubeQuotaError, YouTubeAPIError
from app.services.subscription_service import SubscriptionService
from app.services.exploration_topic_service import ExplorationTopicService
from app.repositories.discovery_repository import DiscoveryRepository
from app.domain.discovery.query_builder import build_queries_for_category, schedule_queries_round_robin
from app.domain.discovery.scoring import score_and_classify_candidate
from app.domain.discovery.selection import select_batch_diverse

logger = logging.getLogger(__name__)

class DiscoveryService:
    def __init__(self, gateway=None):
        self.gateway = gateway or YouTubeGateway()

    def run_discovery(self, db, run_id: int) -> dict:
        """
        Ejecuta el motor de descubrimiento para todas las categorías.
        - Genera consultas en round-robin.
        - Busca candidatos usando YouTube API.
        - Filtra, puntúa y selecciona lote 5/2/1.
        - Guarda lotes de forma transaccional.
        """
        # 1. Validar token
        sub_service = SubscriptionService(gateway=self.gateway)
        try:
            access_token = sub_service._get_valid_access_token(db)
        except Exception as e:
            logger.error(f"No se pudo obtener access token para descubrimiento: {e}")
            raise e

        # 2. Cargar configuraciones de presupuestos
        # Usamos los límites de la base de configuración
        from flask import current_app
        global_budget = current_app.config.get("DISCOVERY_MAX_SEARCHES_PER_REFRESH", 10)
        category_budget = current_app.config.get("DISCOVERY_MAX_SEARCHES_PER_CATEGORY", 2)
        signal_window = current_app.config.get("DISCOVERY_SIGNAL_WINDOW_DAYS", 90)
        search_age_days = current_app.config.get("DISCOVERY_MAX_SEARCH_AGE_DAYS", 180)
        
        now = datetime.now(timezone.utc)
        published_after = (now - timedelta(days=search_age_days)).isoformat()[:19] + "Z"

        # 3. Obtener categorías
        cursor = db.execute("SELECT id FROM categories ORDER BY position ASC")
        category_ids = [row["id"] for row in cursor.fetchall()]
        
        category_queries = {}
        category_signals = {}
        
        # 4. Registrar propuestas automáticas y armar snapshot de señales
        for cat_id in category_ids:
            # Proponer nuevos temas (se crean como 'pending', por lo que no afectan el snapshot actual)
            try:
                ExplorationTopicService.generate_automatic_proposals(db, cat_id)
            except Exception as e:
                logger.warning(f"Error generando propuestas de temas para categoría {cat_id}: {e}")

            # Tomar snapshot de señales locales y palabras clave
            signals = DiscoveryRepository.get_category_signals(db, cat_id, signal_window_days=signal_window)
            category_signals[cat_id] = signals
            
            # Generar consultas
            queries = build_queries_for_category(signals, max_queries=category_budget)
            category_queries[cat_id] = queries

        # 5. Programar en round-robin
        scheduled_tasks = schedule_queries_round_robin(category_queries, global_budget=global_budget, max_per_category=category_budget)
        
        quota_exhausted = False
        budget_exhausted = False
        searches_executed = 0
        
        # Guardar candidatos encontrados por categoría
        raw_candidates_by_category = {cat_id: [] for cat_id in category_ids}
        shortfall_reasons = {cat_id: None for cat_id in category_ids}

        # 6. Ejecutar búsquedas
        for cat_id, q_task in scheduled_tasks:
            if quota_exhausted:
                shortfall_reasons[cat_id] = "quota_exhausted"
                continue
                
            q_str = q_task["q"]
            logger.info(f"Ejecutando búsqueda para categoría {cat_id}: '{q_str}'")
            
            try:
                # Llamada externa a YouTube
                items = self.gateway.search_videos(
                    access_token,
                    q=q_str,
                    published_after=published_after,
                    limit=25
                )
                searches_executed += 1
                
                # Procesar cada item
                for item in items:
                    # Upsert del canal y el video en la BD local
                    chan_data = {
                        "youtube_channel_id": item["youtube_channel_id"],
                        "title": item["channel_title"]
                    }
                    video_data = {
                        "youtube_video_id": item["youtube_video_id"],
                        "title": item["title"],
                        "description": item["description"],
                        "published_at": item["published_at"],
                        "thumbnail_url": item["thumbnail_url"]
                    }
                    
                    cid, vid = DiscoveryRepository.upsert_channel_and_video(db, chan_data, video_data)
                    
                    # Armar video dict completo para scoring
                    video_eval = {
                        "video_id": vid,
                        "youtube_video_id": item["youtube_video_id"],
                        "channel_id": cid,
                        "youtube_channel_id": item["youtube_channel_id"],
                        "channel_title": item["channel_title"],
                        "title": item["title"],
                        "description": item["description"],
                        "published_at": item["published_at"],
                        "thumbnail_url": item["thumbnail_url"],
                        "content_type": "video"
                    }
                    
                    # Evaluar con el motor de dominio
                    candidate = score_and_classify_candidate(video_eval, category_signals[cat_id], now=now)
                    if candidate:
                        candidate.category_id = cat_id
                        raw_candidates_by_category[cat_id].append(candidate)
                        
            except YouTubeQuotaError as eq:
                logger.error(f"Cuota de YouTube agotada: {eq}")
                quota_exhausted = True
                shortfall_reasons[cat_id] = "quota_exhausted"
            except Exception as e:
                logger.error(f"Error ejecutando consulta '{q_str}' para categoría {cat_id}: {e}")
                shortfall_reasons[cat_id] = "external_error"

        # 7. Seleccionar y Persistir lotes por categoría
        stats_by_category = {}
        
        for cat_id in category_ids:
            candidates = raw_candidates_by_category[cat_id]
            signals = category_signals[cat_id]
            
            # Si no había palabras clave o señales
            if not signals.positive_keywords and not signals.seed_channel_ids:
                DiscoveryRepository.save_discovery_batch(
                    db, run_id, cat_id, 
                    {"targetByBand": {"related": 5, "adjacent": 2, "exploratory": 1}, 
                     "selectedByBand": {"related": 0, "adjacent": 0, "exploratory": 0}},
                    shortfall_reason="insufficient_signals"
                )
                stats_by_category[cat_id] = {"selected": 0, "shortfall": "insufficient_signals"}
                continue
                
            # Seleccionar lote diverso
            selected, counts, shortfall = select_batch_diverse(candidates, target_total=8)
            
            # Si la búsqueda de esta categoría no llegó a completarse debido a cuota o presupuesto
            if shortfall_reasons[cat_id]:
                shortfall = shortfall_reasons[cat_id]
                
            # Guardar candidatos seleccionados en la base de datos
            for candidate in selected:
                DiscoveryRepository.save_discovery_candidate(db, candidate, run_id)
                
            # Guardar lote batch
            DiscoveryRepository.save_discovery_batch(db, run_id, cat_id, counts, shortfall)
            
            # Expirar candidatos del lote anterior
            DiscoveryRepository.expire_previous_candidates(db, cat_id, run_id)
            
            stats_by_category[cat_id] = {
                "selected": len(selected),
                "shortfall": shortfall
            }
            
        return {
            "searches_executed": searches_executed,
            "quota_exhausted": quota_exhausted,
            "categories": stats_by_category
        }
