-- Primera migración: Esquema base de YouTube Curator

BEGIN TRANSACTION;

-- 1. Canales
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    youtube_channel_id TEXT UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    thumbnail_url TEXT,
    uploads_playlist_id TEXT,
    is_subscribed INTEGER NOT NULL DEFAULT 0,
    is_locally_followed INTEGER NOT NULL DEFAULT 0,
    is_blocked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 2. Categorías
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    description TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 3. Palabras clave de categoría
CREATE TABLE IF NOT EXISTS category_keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL,
    term TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    polarity TEXT NOT NULL CHECK(polarity IN ('positive', 'negative')),
    FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
);

-- 4. Asociación Canal-Categoría
CREATE TABLE IF NOT EXISTS channel_categories (
    channel_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('manual', 'automatic', 'accepted_suggestion', 'accepted_discovery')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (channel_id, category_id),
    FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
);

-- 5. Sugerencias de clasificación automática
CREATE TABLE IF NOT EXISTS classification_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    confidence REAL NOT NULL CHECK(confidence >= 0.0 AND confidence <= 1.0),
    explanation TEXT,
    classifier_version TEXT,
    status TEXT NOT NULL CHECK(status IN ('pending', 'accepted', 'rejected', 'superseded')),
    auto_applied INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
);

-- 6. Decisiones de clasificación manual (para evitar pisar decisiones del usuario)
CREATE TABLE IF NOT EXISTS classification_decisions (
    channel_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('include', 'exclude')),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (channel_id, category_id),
    FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
);

-- 7. Videos
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    youtube_video_id TEXT NOT NULL UNIQUE,
    channel_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    published_at TEXT NOT NULL,
    duration_seconds INTEGER,
    thumbnail_url TEXT,
    content_type TEXT NOT NULL DEFAULT 'unknown' CHECK(content_type IN ('video', 'live', 'upcoming', 'unknown')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE CASCADE
);

-- 8. Candidatos de descubrimiento
CREATE TABLE IF NOT EXISTS discovery_candidates (
    video_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    score REAL NOT NULL CHECK(score >= 0.0 AND score <= 100.0),
    reasons_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL CHECK(status IN ('active', 'hidden', 'accepted', 'expired')),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (video_id, category_id),
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE,
    FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
);

-- 9. Estado visto del video
CREATE TABLE IF NOT EXISTS video_user_state (
    video_id INTEGER PRIMARY KEY,
    opened_at TEXT,
    open_count INTEGER NOT NULL DEFAULT 0,
    watched INTEGER NOT NULL DEFAULT 0,
    watched_source TEXT CHECK(watched_source IN ('opened', 'manual', 'youtube_import')),
    updated_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
);

-- 10. Feedback de descubrimiento
CREATE TABLE IF NOT EXISTS discovery_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER,
    channel_id INTEGER,
    category_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('more_like_this', 'less_like_this', 'hide_video', 'block_channel', 'accept_channel')),
    created_at TEXT NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE SET NULL,
    FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE SET NULL,
    FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
);

-- 11. Registro de ejecuciones de actualización (refresh runs)
CREATE TABLE IF NOT EXISTS refresh_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'succeeded', 'partial', 'failed')),
    requested_stages_json TEXT NOT NULL DEFAULT '[]',
    current_stage TEXT,
    requested_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    counters_json TEXT NOT NULL DEFAULT '{}',
    errors_json TEXT NOT NULL DEFAULT '[]',
    heartbeat_at TEXT,
    lease_expires_at TEXT,
    worker_id TEXT
);

-- Índices mínimos sugeridos para optimización
CREATE INDEX IF NOT EXISTS idx_videos_published_at ON videos(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_videos_channel_published ON videos(channel_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_discovery_candidates_cat_status_score ON discovery_candidates(category_id, status, score DESC);
CREATE INDEX IF NOT EXISTS idx_channel_categories_cat_chan ON channel_categories(category_id, channel_id);
CREATE INDEX IF NOT EXISTS idx_class_suggestions_status_chan ON classification_suggestions(status, channel_id);
CREATE INDEX IF NOT EXISTS idx_channels_subscribed_blocked ON channels(is_subscribed, is_blocked);

COMMIT;
