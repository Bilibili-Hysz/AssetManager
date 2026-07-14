# Database Migrations

AssetManager Next uses versioned SQLite migrations for per-library databases.

## Current State

### Version 1 — Baseline

Records the existing schema created by `AssetsManager.core.database._SCHEMA`:

- `file_tags(file_path, tag)`
- `file_meta(file_path, notes, cached_size, cached_mtime, cached_file_count, urls)`
- `thumbnail_cache(cache_key, source_path, source_mtime, source_size, baked_size, cache_size, created_at, last_access)`
- `library_stats(library_path, total_size, total_files, total_projects, updated_at)`
- `schema_migrations(version, name, applied_at)`

### Version 2 — Assets Index

Adds `assets` table for fast file lookup and project listing:

```sql
CREATE TABLE assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    extension TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'file',
    size INTEGER DEFAULT 0,
    mtime REAL DEFAULT 0,
    parent_path TEXT NOT NULL,
    library_root TEXT NOT NULL,
    created_at REAL,
    updated_at REAL
);
CREATE INDEX idx_assets_parent ON assets(parent_path);
CREATE INDEX idx_assets_library ON assets(library_root);
CREATE INDEX idx_assets_name ON assets(name);
CREATE INDEX idx_assets_ext ON assets(extension);
```

The table is populated lazily by application services, not by the migration.

### Version 3 — Tag Metadata

Adds `tag_metadata` table for tag colors, icons, and categories:

```sql
CREATE TABLE tag_metadata (
    tag TEXT PRIMARY KEY,
    color TEXT DEFAULT '',
    icon TEXT DEFAULT '',
    category TEXT DEFAULT '',
    created_at REAL DEFAULT (strftime('%s','now'))
);
CREATE INDEX idx_tag_metadata_category ON tag_metadata(category);
```

Used by `TagRepository.get_tag_metadata()` and `TagService.get_tags_with_metadata()`.

### Version 4 — Plugin Metadata

Adds `plugin_metadata` for persisted file metadata parsed by enabled plugins:

```sql
CREATE TABLE plugin_metadata (
    file_path TEXT NOT NULL,
    plugin_id TEXT NOT NULL,
    field_key TEXT NOT NULL,
    field_value TEXT NOT NULL DEFAULT '',
    updated_at REAL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (file_path, plugin_id, field_key)
);
CREATE INDEX idx_plugin_metadata_file ON plugin_metadata(file_path);
CREATE INDEX idx_plugin_metadata_plugin ON plugin_metadata(plugin_id);
```

Used by `PluginMetadataRepository` and `InfoController` so plugin-parsed fields can remain visible after parsing.

## Rules

- Every schema change must add a migration in `AssetsManager/core/db_migrations.py` or the future migrations package.
- Migration versions must be strictly increasing.
- Migrations must be idempotent where practical.
- Migration tests must cover new empty databases and existing databases.
- User data must not be deleted during migrations unless the migration explicitly documents why.
- Before destructive migrations, add a backup step in the migration runner.
- Auth, invite, user, and share-link tables are still initialized by the LAN/auth repository path. Moving those tables under the main migration runner is tracked as architecture work, not as a behavior change.

## Future Direction

Future schema changes should be added as explicit migrations in `core/db_migrations.py` and covered by tests in `tests/core/test_db_migrations.py`. The next migration hardening step is per-migration transaction/rollback tests.
