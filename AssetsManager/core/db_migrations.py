"""SQLite schema migration runner.

The current production schema is created by `core.database._SCHEMA`. This
module records that baseline as version 1 and provides a stable place for
future schema upgrades.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Callable


CURRENT_SCHEMA_VERSION = 5

MigrationFn = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: MigrationFn


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, "
        "name TEXT NOT NULL, "
        "applied_at REAL NOT NULL"
        ")"
    )


def _current_version(conn: sqlite3.Connection) -> int:
    _ensure_migrations_table(conn)
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0] or 0) if row else 0


def _record(conn: sqlite3.Connection, migration: Migration) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, name, applied_at) "
        "VALUES (?, ?, ?)",
        (migration.version, migration.name, time.time()),
    )


def _baseline_v1(conn: sqlite3.Connection) -> None:
    """Record the current pre-migration schema as version 1.

    `DatabaseManager.open_library()` has already executed the current schema
    before calling the migration runner, so no table changes are required here.
    """


def _add_assets_index_v2(conn: sqlite3.Connection) -> None:
    """Add assets index table for fast file lookup and project listing.

    This table is populated lazily by application services, not by the
    migration itself. The migration only creates the schema.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS assets ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "file_path TEXT NOT NULL UNIQUE, "
        "name TEXT NOT NULL, "
        "extension TEXT NOT NULL DEFAULT '', "
        "kind TEXT NOT NULL DEFAULT 'file', "
        "size INTEGER DEFAULT 0, "
        "mtime REAL DEFAULT 0, "
        "parent_path TEXT NOT NULL, "
        "library_root TEXT NOT NULL, "
        "created_at REAL DEFAULT (strftime('%s','now')), "
        "updated_at REAL DEFAULT (strftime('%s','now'))"
        ")"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_parent ON assets(parent_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_library ON assets(library_root)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_name ON assets(name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_ext ON assets(extension)")


def _add_tag_metadata_v3(conn: sqlite3.Connection) -> None:
    """Add tag_metadata table for tag colors and icons."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tag_metadata ("
        "tag TEXT PRIMARY KEY, "
        "color TEXT DEFAULT '', "
        "icon TEXT DEFAULT '', "
        "category TEXT DEFAULT '', "
        "created_at REAL DEFAULT (strftime('%s','now'))"
        ")"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tag_metadata_category ON tag_metadata(category)")


def _add_plugin_metadata_v4(conn: sqlite3.Connection) -> None:
    """Add plugin_metadata table for plugin-parsed file metadata.

    Stores key-value pairs parsed by plugins (e.g. booth URL, item name, author).
    Data persists even when plugins are disabled, so the InfoPanel can display
    previously parsed metadata without requiring the plugin to be active.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS plugin_metadata ("
        "file_path TEXT NOT NULL, "
        "plugin_id TEXT NOT NULL, "
        "field_key TEXT NOT NULL, "
        "field_value TEXT NOT NULL DEFAULT '', "
        "updated_at REAL DEFAULT (strftime('%s','now')), "
        "PRIMARY KEY (file_path, plugin_id, field_key)"
        ")"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_plugin_metadata_file ON plugin_metadata(file_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_plugin_metadata_plugin ON plugin_metadata(plugin_id)")


def _add_directory_cache_v5(conn: sqlite3.Connection) -> None:
    """Add directory_cache table for cached directory scan results."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS directory_cache ("
        "dir_path TEXT PRIMARY KEY, item_count INTEGER NOT NULL DEFAULT 0, "
        "preview_path TEXT, mtime REAL NOT NULL, "
        "scanned_at REAL NOT NULL DEFAULT (strftime('%s','now')))"
    )
    conn.commit()


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "baseline_current_schema", _baseline_v1),
    Migration(2, "add_assets_index", _add_assets_index_v2),
    Migration(3, "add_tag_metadata", _add_tag_metadata_v3),
    Migration(4, "add_plugin_metadata", _add_plugin_metadata_v4),
    Migration(5, "directory_cache", _add_directory_cache_v5),
)


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations and return the resulting schema version."""
    _ensure_migrations_table(conn)
    version = _current_version(conn)
    for migration in MIGRATIONS:
        if migration.version <= version:
            continue
        migration.apply(conn)
        _record(conn, migration)
        version = migration.version
    conn.commit()
    return version


def current_version(conn: sqlite3.Connection) -> int:
    """Return the recorded schema version for a database connection."""
    return _current_version(conn)
