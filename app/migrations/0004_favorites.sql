-- Cuarta migración: Añadir soporte para videos favoritos en video_user_state
ALTER TABLE video_user_state ADD COLUMN favorited INTEGER NOT NULL DEFAULT 0;
ALTER TABLE video_user_state ADD COLUMN favorited_at TEXT;

CREATE INDEX IF NOT EXISTS idx_video_user_state_favorited ON video_user_state(favorited, favorited_at DESC);
