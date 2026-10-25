-- Séptima migración: Tablas para listas de reproducción excluidas y sus videos
CREATE TABLE IF NOT EXISTS excluded_playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    youtube_playlist_id TEXT NOT NULL UNIQUE,
    title TEXT,
    channel_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS excluded_playlist_videos (
    playlist_id TEXT NOT NULL,
    youtube_video_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (playlist_id, youtube_video_id),
    FOREIGN KEY(playlist_id) REFERENCES excluded_playlists(youtube_playlist_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_excluded_playlist_videos_vid ON excluded_playlist_videos(youtube_video_id);

-- Playlist solicitada: 'Los minutos del Odio' (https://www.youtube.com/playlist?list=PLo8Z6taNbZ7MKN7xkJYlHmXBLGDY7sOUu)
INSERT OR IGNORE INTO excluded_playlists (youtube_playlist_id, title, channel_id, created_at, updated_at)
VALUES (
    'PLo8Z6taNbZ7MKN7xkJYlHmXBLGDY7sOUu',
    'Los minutos del Odio',
    (SELECT id FROM channels WHERE youtube_channel_id = 'UCDwflVe6kxtJTDdF8CPs6jw' LIMIT 1),
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
);

-- Si ya existen videos de esta playlist en la tabla videos local, vincularlos inmediatamente
INSERT OR IGNORE INTO excluded_playlist_videos (playlist_id, youtube_video_id, created_at)
SELECT 'PLo8Z6taNbZ7MKN7xkJYlHmXBLGDY7sOUu', youtube_video_id, CURRENT_TIMESTAMP
FROM videos
WHERE title LIKE '%LOS MINUTOS DEL ODIO%';
