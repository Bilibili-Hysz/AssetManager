-- Frozen v1 schema fixture.
-- Source: HEAD 51e50203eebf582dcf480ed5b378e0f7156e6611
-- This is the pure v1 baseline; directory_cache is introduced by migration v5.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS file_tags (
    file_path TEXT NOT NULL,
    tag       TEXT NOT NULL,
    PRIMARY KEY (file_path, tag)
);
CREATE INDEX IF NOT EXISTS idx_file_tags_tag ON file_tags(tag);

CREATE TABLE IF NOT EXISTS file_meta (
    file_path         TEXT PRIMARY KEY,
    notes             TEXT NOT NULL DEFAULT '',
    cached_size       INTEGER,
    cached_mtime      REAL,
    cached_file_count INTEGER,
    urls              TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS thumbnail_cache (
    cache_key    TEXT PRIMARY KEY,
    source_path  TEXT NOT NULL,
    source_mtime REAL NOT NULL,
    source_size  INTEGER DEFAULT 0,
    baked_size   INTEGER DEFAULT 256,
    cache_size   INTEGER DEFAULT 0,
    created_at   REAL DEFAULT (strftime('%s','now')),
    last_access  REAL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_thumb_source ON thumbnail_cache(source_path);

CREATE TABLE IF NOT EXISTS library_stats (
    library_path   TEXT PRIMARY KEY,
    total_size     INTEGER DEFAULT 0,
    total_files    INTEGER DEFAULT 0,
    total_projects INTEGER DEFAULT 0,
    updated_at     REAL DEFAULT (strftime('%s','now'))
);
