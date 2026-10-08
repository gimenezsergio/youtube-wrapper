-- Sexta migración: Añadir soporte para videos con Me Gusta (liked) en video_user_state
ALTER TABLE video_user_state ADD COLUMN liked INTEGER NOT NULL DEFAULT 0;
ALTER TABLE video_user_state ADD COLUMN liked_at TEXT;

CREATE INDEX IF NOT EXISTS idx_video_user_state_liked ON video_user_state(liked);
