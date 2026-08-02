from datetime import datetime, timedelta, timezone

from app.auth.encryption import decrypt_token, encrypt_token
from app.integrations.youtube.gateway import YouTubeGateway


def get_utc_now_iso():
    """Retorna la fecha y hora UTC actual en formato ISO 8601."""
    return datetime.now(timezone.utc).isoformat()

class SubscriptionService:
    def __init__(self, gateway=None):
        self.gateway = gateway or YouTubeGateway()

    def _get_valid_access_token(self, db) -> str:
        """
        Recupera el access_token desde la base de datos, refrescándolo si ya expiró.
        Retorna el token descifrado en texto plano.
        """
        cursor = db.execute("SELECT id, access_token, refresh_token, expires_at FROM credentials LIMIT 1")
        row = cursor.fetchone()
        if not row:
            raise Exception("No existen credenciales de propietario configuradas. Inicie sesión primero.")

        cred_id = row["id"]
        enc_access = row["access_token"]
        enc_refresh = row["refresh_token"]
        expires_at_str = row["expires_at"]

        access_token = decrypt_token(enc_access)
        refresh_token = decrypt_token(enc_refresh) if enc_refresh else None

        # Comprobar expiración
        expires_at = datetime.fromisoformat(expires_at_str)
        now = datetime.now(timezone.utc)

        # Si el token ya expiró y tenemos refresh_token, refrescarlo de inmediato
        if now >= expires_at:
            if not refresh_token:
                raise Exception("El token de acceso expiró y no hay un token de actualización disponible.")

            try:
                tokens = self.gateway.refresh_access_token(refresh_token)
                new_access = tokens["access_token"]
                expires_in = tokens.get("expires_in", 3600)

                # Guardar nuevas credenciales cifradas
                new_expires_at = (now + timedelta(seconds=expires_in)).isoformat()
                new_enc_access = encrypt_token(new_access)

                db.execute("""
                    UPDATE credentials
                    SET access_token = ?, expires_at = ?, updated_at = ?
                    WHERE id = ?
                """, (new_enc_access, new_expires_at, get_utc_now_iso(), cred_id))
                db.commit()

                return new_access
            except Exception as e:
                raise Exception(f"Fallo al refrescar automáticamente el token de Google: {e}") from e

        return access_token

    def sync_subscriptions(self, db, heartbeat_callback=None) -> dict:
        """
        Sincroniza de forma atómica e idempotente las suscripciones de YouTube en SQLite.
        """
        # 1. Obtener access_token activo
        access_token = self._get_valid_access_token(db)

        # 2. Descargar suscripciones remotas (ids y títulos)
        try:
            subs_list = self.gateway.fetch_subscriptions(access_token)
        except PermissionError:
            # Reintento único: forzar refresco del token si Google retorna 401 a pesar del expires_at local
            access_token = self._force_refresh_token(db)
            subs_list = self.gateway.fetch_subscriptions(access_token)

        if not subs_list:
            # Si no hay suscripciones, marcar todas las suscripciones locales previas como desuscritas
            cursor = db.execute("UPDATE channels SET is_subscribed = 0 WHERE is_subscribed = 1")
            db.commit()
            return {"created": 0, "updated": 0, "unsubscribed": cursor.rowcount}

        if heartbeat_callback:
            heartbeat_callback()

        # 3. Descargar detalles completos en lotes de 50 (snippet, contentDetails)
        remote_ids = [sub["youtube_channel_id"] for sub in subs_list]
        channels_details = self.gateway.fetch_channels_details(access_token, remote_ids)

        # 4. Sincronizar en base de datos de manera transaccional
        created_count = 0
        updated_count = 0
        now_iso = get_utc_now_iso()

        try:
            for chan in channels_details:
                yt_id = chan["youtube_channel_id"]
                title = chan["title"]
                desc = chan["description"]
                thumb = chan["thumbnail_url"]
                playlist = chan["uploads_playlist_id"]

                # Verificar si ya existe el canal en la BD
                cursor = db.execute("SELECT id FROM channels WHERE youtube_channel_id = ?", (yt_id,))
                row = cursor.fetchone()

                if row:
                    # Actualizar metadatos y asegurar is_subscribed = 1
                    # Conservamos categorías locales, is_locally_followed, is_blocked
                    db.execute("""
                        UPDATE channels
                        SET title = ?, description = ?, thumbnail_url = ?, uploads_playlist_id = ?,
                            is_subscribed = 1, updated_at = ?
                        WHERE id = ?
                    """, (title, desc, thumb, playlist, now_iso, row["id"]))
                    updated_count += 1
                else:
                    # Crear nuevo canal
                    db.execute("""
                        INSERT INTO channels (
                            youtube_channel_id, title, description, thumbnail_url, uploads_playlist_id,
                            is_subscribed, is_locally_followed, is_blocked, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 1, 0, 0, ?, ?)
                    """, (yt_id, title, desc, thumb, playlist, now_iso, now_iso))
                    created_count += 1

            # 5. Marcar desuscritos (is_subscribed = 0) sin borrar registros
            # Creamos una lista de marcadores (?, ?, ...) para la query SQL
            placeholders = ",".join("?" for _ in remote_ids)
            query = f"""
                UPDATE channels
                SET is_subscribed = 0
                WHERE is_subscribed = 1 AND youtube_channel_id NOT IN ({placeholders})
            """
            cursor = db.execute(query, remote_ids)
            unsubscribed_count = cursor.rowcount

            db.commit()
            return {
                "created": created_count,
                "updated": updated_count,
                "unsubscribed": unsubscribed_count
            }

        except Exception:
            db.rollback()
            raise

    def _force_refresh_token(self, db) -> str:
        """Fuerza la expiración y el refresco del token de acceso actual en base de datos."""
        cursor = db.execute("SELECT id, refresh_token FROM credentials LIMIT 1")
        row = cursor.fetchone()
        if not row or not row["refresh_token"]:
            raise Exception("No hay refresh_token disponible para reintentar la conexión.")

        cred_id = row["id"]
        refresh_token = decrypt_token(row["refresh_token"])

        tokens = self.gateway.refresh_access_token(refresh_token)
        new_access = tokens["access_token"]
        # Guardar en base de datos con expiración inmediata para asegurar validez en adelante
        new_expires_at = (
            datetime.now(timezone.utc) +
            timedelta(seconds=tokens.get("expires_in", 3600))
        ).isoformat()

        db.execute("""
            UPDATE credentials
            SET access_token = ?, expires_at = ?, updated_at = ?
            WHERE id = ?
        """, (encrypt_token(new_access), new_expires_at, get_utc_now_iso(), cred_id))
        db.commit()
        return new_access
