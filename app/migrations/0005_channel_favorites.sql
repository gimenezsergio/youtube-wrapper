-- Quinta migración: Añadir soporte para canales preferidos / favoritos
ALTER TABLE channels ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_channels_favorite ON channels(is_favorite);
