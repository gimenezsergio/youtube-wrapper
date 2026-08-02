-- Migration 0003: Discovery Engine

BEGIN TRANSACTION;

-- Create category_exploration_topics table
CREATE TABLE IF NOT EXISTS category_exploration_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL,
    term TEXT NOT NULL,
    normalized_term TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    source TEXT NOT NULL CHECK(source IN ('manual', 'automatic')),
    status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'rejected')),
    rationale TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(category_id, normalized_term),
    FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
);

-- Create discovery_batches table
CREATE TABLE IF NOT EXISTS discovery_batches (
    refresh_run_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    target_total INTEGER NOT NULL DEFAULT 8,
    selected_total INTEGER NOT NULL DEFAULT 0,
    target_by_band_json TEXT NOT NULL,
    selected_by_band_json TEXT NOT NULL,
    shortfall_reason TEXT CHECK(shortfall_reason IN ('insufficient_candidates', 'insufficient_signals', 'no_approved_topics', 'budget_exhausted', 'quota_exhausted', 'external_error') OR shortfall_reason IS NULL),
    generated_at TEXT NOT NULL,
    PRIMARY KEY (refresh_run_id, category_id),
    FOREIGN KEY(refresh_run_id) REFERENCES refresh_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
);

-- Recreate discovery_candidates with new columns: band, last_refresh_run_id, selection_rank
-- First drop existing index
DROP INDEX IF EXISTS idx_discovery_candidates_cat_status_score;

-- Rename old table
ALTER TABLE discovery_candidates RENAME TO old_discovery_candidates;

-- Create new table
CREATE TABLE discovery_candidates (
    video_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    score REAL NOT NULL CHECK(score >= 0.0 AND score <= 100.0),
    band TEXT NOT NULL CHECK(band IN ('related', 'adjacent', 'exploratory')),
    reasons_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL CHECK(status IN ('active', 'hidden', 'accepted', 'expired')),
    last_refresh_run_id INTEGER,
    selection_rank INTEGER,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (video_id, category_id),
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE,
    FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE,
    FOREIGN KEY(last_refresh_run_id) REFERENCES refresh_runs(id) ON DELETE SET NULL
);

-- Copy existing data to the new table with default values
INSERT INTO discovery_candidates (
    video_id, category_id, score, band, reasons_json, status, last_refresh_run_id, selection_rank, first_seen_at, last_seen_at
)
SELECT 
    video_id, category_id, score, 'related', reasons_json, status, NULL, NULL, first_seen_at, last_seen_at
FROM old_discovery_candidates;

-- Drop old table
DROP TABLE old_discovery_candidates;

-- Create/recreate indexes
CREATE INDEX IF NOT EXISTS idx_discovery_candidates_cat_status_score ON discovery_candidates(category_id, status, score DESC);
CREATE INDEX IF NOT EXISTS idx_discovery_candidates_cat_run_rank ON discovery_candidates(category_id, last_refresh_run_id, selection_rank);
CREATE INDEX IF NOT EXISTS idx_discovery_batches_cat_run ON discovery_batches(category_id, refresh_run_id);
CREATE INDEX IF NOT EXISTS idx_category_exploration_topics_cat_status_term ON category_exploration_topics(category_id, status, normalized_term);
CREATE INDEX IF NOT EXISTS idx_channel_categories_cat_chan ON channel_categories(category_id, channel_id);
CREATE INDEX IF NOT EXISTS idx_classification_suggestions_status_chan ON classification_suggestions(status, channel_id);

COMMIT;
