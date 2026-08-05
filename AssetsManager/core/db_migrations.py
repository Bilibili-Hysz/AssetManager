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

from AssetsManager.core.schema_defs import (
    INVITE_CODES_SCHEMA,
    SCHEMA_MIGRATIONS_SCHEMA,
    SCHEMA_OBJECT_CONTRACT,
    SHARE_LINKS_SCHEMA,
    USERS_SCHEMA,
    SchemaObjectContract,
)


CURRENT_SCHEMA_VERSION = 6
_BASELINE_SCHEMA_CONTRACT = {
    "file_tags": {
        "columns": ("file_path", "tag"),
        "primary_key": ("file_path", "tag"),
        "indexes": {"idx_file_tags_tag": ("tag",)},
    },
    "file_meta": {
        "columns": (
            "file_path",
            "notes",
            "cached_size",
            "cached_mtime",
            "cached_file_count",
            "urls",
        ),
        "primary_key": ("file_path",),
        "indexes": {},
    },
    "thumbnail_cache": {
        "columns": (
            "cache_key",
            "source_path",
            "source_mtime",
            "source_size",
            "baked_size",
            "cache_size",
            "created_at",
            "last_access",
        ),
        "primary_key": ("cache_key",),
        "indexes": {"idx_thumb_source": ("source_path",)},
    },
    "library_stats": {
        "columns": (
            "library_path",
            "total_size",
            "total_files",
            "total_projects",
            "updated_at",
        ),
        "primary_key": ("library_path",),
        "indexes": {},
    },
}
_REQUIRED_BASELINE_TABLES = tuple(_BASELINE_SCHEMA_CONTRACT)

MigrationFn = Callable[[sqlite3.Connection], None]


class UnsupportedSchemaVersion(RuntimeError):
    """Raised when a database was written by a newer schema version."""

    def __init__(self, recorded_version: int, supported_version: int) -> None:
        self.recorded_version = recorded_version
        self.supported_version = supported_version
        super().__init__(
            "Database schema version "
            f"{recorded_version} is newer than supported version {supported_version}"
        )


class MigrationHistoryError(RuntimeError):
    """Raised when the recorded migration history is not a valid prefix."""


class InvalidSchemaError(RuntimeError):
    """Raised when an existing table cannot satisfy a migration contract."""

    def __init__(
        self,
        table: str,
        missing_columns: tuple[str, ...] = (),
        expected_primary_key: tuple[str, ...] = (),
        actual_primary_key: tuple[str, ...] = (),
        missing_unique_constraints: tuple[tuple[str, ...], ...] = (),
        *,
        missing_table: bool = False,
    ) -> None:
        self.table = table
        self.missing_columns = missing_columns
        self.expected_primary_key = expected_primary_key
        self.actual_primary_key = actual_primary_key
        self.missing_unique_constraints = missing_unique_constraints
        self.missing_table = missing_table
        details = []
        if missing_table:
            details.append("table is missing")
        if missing_columns:
            details.append("missing columns " + ", ".join(missing_columns))
        if actual_primary_key != expected_primary_key:
            details.append(
                f"primary key expected {expected_primary_key}, found {actual_primary_key}"
            )
        if missing_unique_constraints:
            details.append(
                "missing unique constraints "
                + ", ".join(map(str, missing_unique_constraints))
            )
        super().__init__(
            f"Database table {table} has incompatible schema; "
            + "; ".join(details)
        )


class IncompleteSchemaError(RuntimeError):
    """Raised when migration runs without the required core baseline schema."""

    def __init__(
        self,
        missing_tables: tuple[str, ...],
        missing_columns: tuple[tuple[str, str], ...] = (),
        invalid_primary_keys: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (),
        missing_indexes: tuple[tuple[str, str], ...] = (),
        invalid_indexes: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (),
    ) -> None:
        self.missing_tables = missing_tables
        self.missing_columns = missing_columns
        self.invalid_primary_keys = invalid_primary_keys
        self.missing_indexes = missing_indexes
        self.invalid_indexes = invalid_indexes
        details = list(missing_tables)
        details.extend(f"{table}.{column}" for table, column in missing_columns)
        details.extend(
            f"{table} primary key expected {expected}, found {actual}"
            for table, expected, actual in invalid_primary_keys
        )
        details.extend(f"{table}.{index}" for table, index in missing_indexes)
        details.extend(
            f"{table}.{index} expected columns {expected}, found {actual}"
            for table, index, expected, actual in invalid_indexes
        )
        super().__init__(
            "Database core baseline is incomplete; prepare _SCHEMA before migrate: "
            + ", ".join(details)
        )


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: MigrationFn


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA_MIGRATIONS_SCHEMA)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _validate_history(rows: list[tuple[object, object]]) -> int:
    """Validate and return the latest recorded version.

    The future-version check intentionally happens before validating names so a
    database written by a newer build keeps raising ``UnsupportedSchemaVersion``.
    """
    if not rows:
        return 0

    versions = [row[0] for row in rows]
    integer_versions = [
        version
        for version in versions
        if isinstance(version, int) and not isinstance(version, bool)
    ]
    if len(integer_versions) != len(versions):
        raise MigrationHistoryError("schema_migrations contains a non-integer version")

    max_version = max(integer_versions)
    if max_version > CURRENT_SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(max_version, CURRENT_SCHEMA_VERSION)

    expected_versions = set(range(1, max_version + 1))
    actual_versions = set(integer_versions)
    if any(version < 1 for version in integer_versions):
        raise MigrationHistoryError("schema_migrations contains a non-positive version")
    if len(actual_versions) != len(integer_versions):
        raise MigrationHistoryError("schema_migrations contains duplicate versions")
    if actual_versions != expected_versions:
        raise MigrationHistoryError("schema_migrations versions must be contiguous from 1")

    expected_names = {migration.version: migration.name for migration in MIGRATIONS}
    for version, name in rows:
        expected_name = expected_names.get(version if isinstance(version, int) else -1)
        if expected_name != name:
            raise MigrationHistoryError(
                f"schema_migrations name does not match migration version {version}"
            )
    return max_version


def _read_history(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT version, name FROM schema_migrations ORDER BY version"
    ).fetchall()
    return _validate_history(rows)


def preflight_recorded_version(conn: sqlite3.Connection) -> int:
    """Read and validate recorded history without creating or modifying schema."""
    if not _table_exists(conn, "schema_migrations"):
        return 0

    validate_schema_objects(conn, ("schema_migrations",))
    return _read_history(conn)


def _current_version(conn: sqlite3.Connection) -> int:
    _ensure_migrations_table(conn)
    validate_schema_objects(conn, ("schema_migrations",))
    return _read_history(conn)


def _index_columns(conn: sqlite3.Connection, index_name: str) -> tuple[str, ...]:
    escaped_name = index_name.replace("'", "''")
    rows = conn.execute(f"PRAGMA index_info('{escaped_name}')").fetchall()
    return tuple(row[2] for row in rows)


def validate_schema_object(
    conn: sqlite3.Connection,
    table: str,
    contract: SchemaObjectContract,
) -> None:
    """Validate one required table object without changing the database."""
    if not _table_exists(conn, table):
        raise InvalidSchemaError(table, missing_table=True)

    table_info = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    columns = {row[1] for row in table_info}
    expected_columns = contract["columns"]
    missing_columns = tuple(
        column for column in expected_columns if column not in columns
    )
    primary_key = tuple(
        row[1] for row in sorted(table_info, key=lambda row: row[5]) if row[5]
    )
    expected_primary_key = contract["primary_key"]

    unique_indexes = []
    for row in conn.execute(f"PRAGMA index_list('{table}')").fetchall():
        if row[2]:
            unique_indexes.append(_index_columns(conn, row[1]))
    missing_unique_constraints = tuple(
        constraint
        for constraint in contract["unique_constraints"]
        if constraint not in unique_indexes
    )

    if missing_columns or primary_key != expected_primary_key or missing_unique_constraints:
        raise InvalidSchemaError(
            table,
            missing_columns,
            expected_primary_key,
            primary_key,
            missing_unique_constraints,
        )


def validate_schema_objects(
    conn: sqlite3.Connection,
    tables: tuple[str, ...],
) -> None:
    """Validate a manifest subset, preserving the caller transaction."""
    for table in tables:
        validate_schema_object(conn, table, SCHEMA_OBJECT_CONTRACT[table])


def _validate_baseline_schema(conn: sqlite3.Connection) -> None:
    missing_tables: list[str] = []
    missing_columns: list[tuple[str, str]] = []
    invalid_primary_keys: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    missing_indexes: list[tuple[str, str]] = []
    invalid_indexes: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = []

    for table, contract in _BASELINE_SCHEMA_CONTRACT.items():
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if exists is None:
            missing_tables.append(table)
            continue

        table_info = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
        columns = {row[1] for row in table_info}
        missing_columns.extend(
            (table, column)
            for column in contract["columns"]
            if column not in columns
        )
        primary_key = tuple(
            row[1] for row in sorted(table_info, key=lambda row: row[5]) if row[5]
        )
        expected_primary_key = contract["primary_key"]
        if primary_key != expected_primary_key:
            invalid_primary_keys.append((table, expected_primary_key, primary_key))

        for index_name, expected_columns in contract["indexes"].items():
            index_exists = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='index' AND tbl_name=? AND name=?",
                (table, index_name),
            ).fetchone()
            if index_exists is None:
                missing_indexes.append((table, index_name))
                continue
            actual_columns = _index_columns(conn, index_name)
            if actual_columns != expected_columns:
                invalid_indexes.append(
                    (table, index_name, expected_columns, actual_columns)
                )

    if any((missing_tables, missing_columns, invalid_primary_keys, missing_indexes, invalid_indexes)):
        raise IncompleteSchemaError(
            tuple(missing_tables),
            tuple(missing_columns),
            tuple(invalid_primary_keys),
            tuple(missing_indexes),
            tuple(invalid_indexes),
        )


def _supported_version(conn: sqlite3.Connection) -> int:
    return _current_version(conn)



def _record(conn: sqlite3.Connection, migration: Migration) -> None:
    conn.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) "
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


def _add_auth_share_schema_v6(conn: sqlite3.Connection) -> None:
    """Create auth/share tables, rejecting incompatible existing tables."""
    schemas = (
        ("users", USERS_SCHEMA),
        ("invite_codes", INVITE_CODES_SCHEMA),
        ("share_links", SHARE_LINKS_SCHEMA),
    )
    missing_tables = []
    for table, _schema in schemas:
        if not _table_exists(conn, table):
            missing_tables.append(table)
            continue
        validate_schema_object(conn, table, SCHEMA_OBJECT_CONTRACT[table])

    for table, schema in schemas:
        if table in missing_tables:
            conn.execute(schema)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "baseline_current_schema", _baseline_v1),
    Migration(2, "add_assets_index", _add_assets_index_v2),
    Migration(3, "add_tag_metadata", _add_tag_metadata_v3),
    Migration(4, "add_plugin_metadata", _add_plugin_metadata_v4),
    Migration(5, "directory_cache", _add_directory_cache_v5),
    Migration(6, "auth_share_schema", _add_auth_share_schema_v6),
)


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations atomically and return the resulting version.

    A savepoint preserves an existing caller transaction. On a fresh connection
    the savepoint is committed, retaining the historical migration behavior.
    """
    savepoint = "migration_runner"
    outer_transaction = conn.in_transaction
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        _ensure_migrations_table(conn)
        version = _supported_version(conn)
        _validate_baseline_schema(conn)
        for migration in MIGRATIONS:
            if migration.version <= version:
                continue
            migration.apply(conn)
            _record(conn, migration)
            version = migration.version
        required_objects = ("schema_migrations",)
        if version >= 6:
            required_objects += ("users", "invite_codes", "share_links")
        validate_schema_objects(conn, required_objects)
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        if not outer_transaction:
            conn.commit()
        return version
    except BaseException:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise


def current_version(conn: sqlite3.Connection) -> int:
    """Return the recorded version, rejecting schemas newer than this build."""
    return _supported_version(conn)
