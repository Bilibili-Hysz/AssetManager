from pathlib import Path
import sqlite3
from typing import Any, cast

import pytest

from AssetsManager.core import db_migrations as _db_migrations

# Captured before any test can monkeypatch the module attribute, so tests
# that pin successive targets ("migrate to 5, then to 6") always slice the
# pristine migration list instead of an already-pinned MIGRATIONS.
_ALL_MIGRATIONS = _db_migrations.MIGRATIONS


def _migrate_to(monkeypatch: pytest.MonkeyPatch, conn: sqlite3.Connection, target: int) -> int:
    """Pin schema history to ``target`` and migrate ``conn`` onto it."""
    monkeypatch.setattr(_db_migrations, "CURRENT_SCHEMA_VERSION", target)
    monkeypatch.setattr(_db_migrations, "MIGRATIONS", _ALL_MIGRATIONS[:target])
    return _db_migrations.migrate(conn)


def _load_v1_schema(conn: sqlite3.Connection) -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "db" / "v1_schema.sql"
    conn.executescript(fixture.read_text(encoding="utf-8"))


def test_migrate_rejects_empty_database_without_migrations_table():
    from AssetsManager.core.db_migrations import IncompleteSchemaError, migrate

    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(IncompleteSchemaError, match="core baseline is incomplete"):
            migrate(conn)

        assert conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='schema_migrations'"
        ).fetchone() is None
    finally:
        conn.close()


def test_schema_baseline_leaves_directory_cache_to_v5(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import CURRENT_SCHEMA_VERSION, migrate

    conn = memory_db
    conn.executescript(database._SCHEMA)

    assert conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='directory_cache'"
    ).fetchone() is None

    assert migrate(conn) == CURRENT_SCHEMA_VERSION
    assert conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='directory_cache'"
    ).fetchone() is not None


def test_migrate_records_baseline_schema_version(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import (
        CURRENT_SCHEMA_VERSION,
        current_version,
        migrate,
    )

    conn = memory_db
    conn.executescript(database._SCHEMA)

    assert migrate(conn) == CURRENT_SCHEMA_VERSION
    assert current_version(conn) == CURRENT_SCHEMA_VERSION
    row = conn.execute(
        "SELECT name FROM schema_migrations WHERE version=1"
    ).fetchone()
    assert row == ("baseline_current_schema",)
    row2 = conn.execute(
        "SELECT name FROM schema_migrations WHERE version=2"
    ).fetchone()
    assert row2 == ("add_assets_index",)
    row3 = conn.execute(
        "SELECT name FROM schema_migrations WHERE version=3"
    ).fetchone()
    assert row3 == ("add_tag_metadata",)
    row4 = conn.execute(
        "SELECT name FROM schema_migrations WHERE version=4"
    ).fetchone()
    assert row4 == ("add_plugin_metadata",)
    row5 = conn.execute(
        "SELECT name FROM schema_migrations WHERE version=5"
    ).fetchone()
    assert row5 == ("directory_cache",)
    row6 = conn.execute(
        "SELECT name FROM schema_migrations WHERE version=6"
    ).fetchone()
    assert row6 == ("auth_share_schema",)
    row7 = conn.execute(
        "SELECT name FROM schema_migrations WHERE version=7"
    ).fetchone()
    assert row7 == ("library_favorites",)
    row8 = conn.execute(
        "SELECT name FROM schema_migrations WHERE version=8"
    ).fetchone()
    assert row8 == ("commerce_schema",)


def test_import_manifest_recovery_lease_migrates_v33_database_and_is_idempotent(memory_db, monkeypatch):
    from AssetsManager.core import database, db_migrations

    memory_db.executescript(database._SCHEMA)
    original_version = db_migrations.CURRENT_SCHEMA_VERSION
    try:
        monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 33)
        assert db_migrations.migrate(memory_db) == 33
        before = {row[1] for row in memory_db.execute("PRAGMA table_info('import_manifests')")}
        assert "recovery_claim_token" not in before
        memory_db.execute(
            "INSERT INTO import_manifests (operation_id, library_root, destination, state, payload, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("legacy-import", "/library", "/library/dest", "running", "{}", 1.0, 1.0),
        )
        memory_db.commit()
    finally:
        monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", original_version)

    assert db_migrations.migrate(memory_db) == db_migrations.CURRENT_SCHEMA_VERSION
    columns = {row[1] for row in memory_db.execute("PRAGMA table_info('import_manifests')")}
    assert {"recovery_claim_token", "recovery_lease_expires_at"} <= columns
    indexes = {row[1] for row in memory_db.execute("PRAGMA index_list('import_manifests')")}
    assert "idx_import_manifests_recovery_lease" in indexes
    assert memory_db.execute(
        "SELECT payload FROM import_manifests WHERE operation_id='legacy-import'"
    ).fetchone() == ("{}",)
    assert db_migrations.migrate(memory_db) == db_migrations.CURRENT_SCHEMA_VERSION


def test_v34_to_v35_adds_file_count_mtime_and_invalidates_old_rows(memory_db, monkeypatch):
    conn = memory_db
    _load_v1_schema(conn)
    conn.execute(
        "INSERT INTO file_meta (file_path, cached_file_count) VALUES ('/legacy', 7)"
    )
    conn.commit()

    assert _migrate_to(monkeypatch, conn, 34) == 34
    assert "cached_file_count_mtime" not in {
        row[1] for row in conn.execute("PRAGMA table_info('file_meta')")
    }

    assert _migrate_to(monkeypatch, conn, 35) == 35
    assert conn.execute(
        "SELECT name FROM schema_migrations WHERE version=35"
    ).fetchone() == ("file_count_mtime_snapshot",)
    # The column is additive; legacy rows keep a NULL mtime, which the read
    # side treats as a cache miss (recomputed against the live directory).
    assert conn.execute(
        "SELECT cached_file_count, cached_file_count_mtime FROM file_meta "
        "WHERE file_path='/legacy'"
    ).fetchone() == (7, None)
    # The migrated shape satisfies the current schema contract.
    from AssetsManager.core.schema_defs import validate_schema_objects

    validate_schema_objects(conn, ("file_meta",))


def test_file_count_mtime_migrates_v34_database_and_is_idempotent(memory_db, monkeypatch):
    from AssetsManager.core import database, db_migrations

    memory_db.executescript(database._SCHEMA)
    original_version = db_migrations.CURRENT_SCHEMA_VERSION
    try:
        monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 34)
        assert db_migrations.migrate(memory_db) == 34
        before = {row[1] for row in memory_db.execute("PRAGMA table_info('file_meta')")}
        assert "cached_file_count_mtime" not in before
        memory_db.execute(
            "INSERT INTO file_meta (file_path, cached_file_count) VALUES ('legacy-dir', 3)"
        )
        memory_db.commit()
    finally:
        monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", original_version)

    assert db_migrations.migrate(memory_db) == db_migrations.CURRENT_SCHEMA_VERSION
    columns = {row[1] for row in memory_db.execute("PRAGMA table_info('file_meta')")}
    assert "cached_file_count_mtime" in columns
    assert memory_db.execute(
        "SELECT cached_file_count_mtime FROM file_meta WHERE file_path='legacy-dir'"
    ).fetchone() == (None,)
    assert memory_db.execute(
        "SELECT name FROM schema_migrations WHERE version=35"
    ).fetchone() == ("file_count_mtime_snapshot",)
    assert db_migrations.migrate(memory_db) == db_migrations.CURRENT_SCHEMA_VERSION


def test_thumbnail_cache_lifecycle_schema_is_present_after_migration(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import CURRENT_SCHEMA_VERSION, migrate

    memory_db.executescript(database._SCHEMA)
    assert migrate(memory_db) == CURRENT_SCHEMA_VERSION
    columns = {
        row[1] for row in memory_db.execute("PRAGMA table_info('thumbnail_cache')")
    }
    assert {"source_mtime_ns", "artifact_kind"} <= columns
    indexes = {
        row[1] for row in memory_db.execute("PRAGMA index_list('thumbnail_cache')")
    }
    assert "idx_thumb_last_access" in indexes


def test_migrate_is_idempotent(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import CURRENT_SCHEMA_VERSION, migrate

    conn = memory_db
    conn.executescript(database._SCHEMA)

    assert migrate(conn) == CURRENT_SCHEMA_VERSION
    assert migrate(conn) == CURRENT_SCHEMA_VERSION
    count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert count == CURRENT_SCHEMA_VERSION


def test_preflight_without_migrations_table_is_read_only(memory_db):
    from AssetsManager.core.db_migrations import preflight_recorded_version

    conn = memory_db
    schema_version_before = conn.execute("PRAGMA schema_version").fetchone()

    assert preflight_recorded_version(conn) == 0
    assert conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='schema_migrations'"
    ).fetchone() is None
    assert conn.execute("PRAGMA schema_version").fetchone() == schema_version_before


def test_future_schema_version_is_rejected(memory_db):
    from AssetsManager.core.db_migrations import (
        CURRENT_SCHEMA_VERSION,
        UnsupportedSchemaVersion,
        _ensure_migrations_table,
        current_version,
        migrate,
        preflight_recorded_version,
    )

    conn = memory_db
    _ensure_migrations_table(conn)
    future_version = CURRENT_SCHEMA_VERSION + 1
    conn.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) "
        "VALUES (?, ?, ?)",
        (future_version, "future_schema", 0),
    )
    conn.commit()

    for operation in (preflight_recorded_version, migrate, current_version):
        with pytest.raises(UnsupportedSchemaVersion) as error:
            operation(conn)
        assert error.value.recorded_version == future_version
        assert error.value.supported_version == CURRENT_SCHEMA_VERSION


def test_open_library_runs_migrations(tmp_path, monkeypatch):
    from AssetsManager.core import database, path_resolver
    from AssetsManager.core.db_migrations import (
        CURRENT_SCHEMA_VERSION,
        current_version,
    )

    runtime = tmp_path / "RuntimeData"
    lib = tmp_path / "Library"
    lib.mkdir()

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database, "RUNTIME_ROOT", runtime)
    try:
        manager = database.DatabaseManager()
        conn = manager.connection_for(lib)
        assert current_version(conn) == CURRENT_SCHEMA_VERSION
    finally:
        manager.close()


def test_open_library_rejects_future_schema_before_current_schema_ddl(
    tmp_path, monkeypatch
):
    import sqlite3

    from AssetsManager.core import database, path_resolver
    from AssetsManager.core.db_migrations import (
        CURRENT_SCHEMA_VERSION,
        UnsupportedSchemaVersion,
    )

    runtime = tmp_path / "RuntimeData"
    lib = tmp_path / "Library"
    lib.mkdir()
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database, "RUNTIME_ROOT", runtime)

    path = database.db_path(lib)
    path.parent.mkdir(parents=True, exist_ok=True)
    future_version = CURRENT_SCHEMA_VERSION + 1
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at REAL NOT NULL)"
        )
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) "
            "VALUES (?, 'future_schema', 0)",
            (future_version,),
        )
        conn.execute("CREATE TABLE future_sentinel (value TEXT NOT NULL)")
        conn.execute("INSERT INTO future_sentinel VALUES ('preserve-me')")
        schema_version_before = conn.execute("PRAGMA schema_version").fetchone()
        journal_mode_before = conn.execute("PRAGMA journal_mode").fetchone()

    manager = database.DatabaseManager()
    try:
        with pytest.raises(UnsupportedSchemaVersion) as error:
            manager.connection_for(lib)
        assert error.value.recorded_version == future_version
        assert error.value.supported_version == CURRENT_SCHEMA_VERSION
    finally:
        manager.close()

    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA schema_version").fetchone() == schema_version_before
        assert conn.execute("PRAGMA journal_mode").fetchone() == journal_mode_before
        assert conn.execute("SELECT value FROM future_sentinel").fetchone() == (
            "preserve-me",
        )
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='file_tags'"
        ).fetchone() is None


def test_v2_creates_assets_table(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    conn = memory_db
    conn.executescript(database._SCHEMA)
    migrate(conn)

    conn.execute(
        "INSERT INTO assets (file_path, name, extension, kind, size, mtime, parent_path, library_root) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("/lib/photo.jpg", "photo.jpg", ".jpg", "file", 1024, 1000.0, "/lib", "/lib"),
    )
    row = conn.execute("SELECT name, extension, kind FROM assets WHERE file_path=?",
                       ("/lib/photo.jpg",)).fetchone()
    assert row == ("photo.jpg", ".jpg", "file")


def test_v2_assets_indexes_exist(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    conn = memory_db
    conn.executescript(database._SCHEMA)
    migrate(conn)

    indexes = {r[1] for r in conn.execute("SELECT * FROM sqlite_master WHERE type='index'").fetchall()}
    assert "idx_assets_parent" in indexes
    assert "idx_assets_library" in indexes
    assert "idx_assets_name" in indexes
    assert "idx_assets_ext" in indexes


def test_v3_creates_tag_metadata_table(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    conn = memory_db
    conn.executescript(database._SCHEMA)
    migrate(conn)

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "tag_metadata" in tables

    indexes = {r[1] for r in conn.execute(
        "SELECT * FROM sqlite_master WHERE type='index'"
    ).fetchall()}
    assert "idx_tag_metadata_category" in indexes


@pytest.mark.parametrize("target_version", [5, 6])
def test_pure_v1_fixture_upgrades_to_v5_and_v6(memory_db, monkeypatch, target_version):
    from AssetsManager.core import db_migrations

    conn = memory_db
    _load_v1_schema(conn)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "directory_cache" not in tables
    assert {"assets", "tag_metadata", "plugin_metadata"}.isdisjoint(tables)

    assert _migrate_to(monkeypatch, conn, target_version) == target_version
    assert db_migrations.current_version(conn) == target_version
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"assets", "tag_metadata", "plugin_metadata", "directory_cache"}.issubset(
        tables
    )
    if target_version == 5:
        assert {"users", "invite_codes", "share_links"}.isdisjoint(tables)
    else:
        assert {"users", "invite_codes", "share_links"}.issubset(tables)
    assert conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(version,) for version in range(1, target_version + 1)]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda conn: conn.execute("DROP INDEX idx_thumb_source"),
            "thumbnail_cache.idx_thumb_source",
        ),
        (
            lambda conn: conn.execute(
                "ALTER TABLE file_meta RENAME COLUMN urls TO legacy_urls"
            ),
            "file_meta.urls",
        ),
    ],
)
def test_migrate_rejects_wrong_baseline_shape(memory_db, mutate, message):
    from AssetsManager.core.db_migrations import IncompleteSchemaError, migrate

    conn = memory_db
    _load_v1_schema(conn)
    mutate(conn)

    with pytest.raises(IncompleteSchemaError, match=message):
        migrate(conn)

    assert conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='schema_migrations'"
    ).fetchone() is None


def test_v5_to_v6_creates_auth_and_share_schema(memory_db, monkeypatch):
    conn = memory_db
    _load_v1_schema(conn)
    assert _migrate_to(monkeypatch, conn, 5) == 5
    assert conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(version,) for version in range(1, 6)]

    assert _migrate_to(monkeypatch, conn, 6) == 6
    assert {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()} >= {"users", "invite_codes", "share_links"}
    assert conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(version,) for version in range(1, 7)]


def test_v6_to_v7_creates_library_favorites_schema(memory_db, monkeypatch):
    conn = memory_db
    _load_v1_schema(conn)
    assert _migrate_to(monkeypatch, conn, 6) == 6

    assert _migrate_to(monkeypatch, conn, 7) == 7
    assert conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='library_favorites'"
    ).fetchone() == (1,)
    assert conn.execute(
        "SELECT name FROM schema_migrations WHERE version=7"
    ).fetchone() == ("library_favorites",)


def test_recorded_v7_revalidates_library_favorites(memory_db, monkeypatch):
    from AssetsManager.core.db_migrations import InvalidSchemaError, migrate

    conn = memory_db
    _load_v1_schema(conn)
    assert _migrate_to(monkeypatch, conn, 7) == 7
    conn.execute("DROP TABLE library_favorites")
    conn.commit()

    with pytest.raises(InvalidSchemaError, match="library_favorites"):
        migrate(conn)

    assert conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(version,) for version in range(1, 8)]


@pytest.mark.parametrize("table", ["users", "invite_codes", "share_links"])
def test_recorded_v6_revalidates_required_auth_share_objects(
    memory_db, table, monkeypatch
):
    from AssetsManager.core.db_migrations import InvalidSchemaError, migrate

    conn = memory_db
    _load_v1_schema(conn)
    assert _migrate_to(monkeypatch, conn, 6) == 6
    conn.execute(f"DROP TABLE {table}")
    conn.commit()

    with pytest.raises(InvalidSchemaError, match=table):
        migrate(conn)

    assert conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(version,) for version in range(1, 7)]
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is None


@pytest.mark.parametrize(
    ("table", "schema"),
    [
        (
            "users",
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password TEXT)",
        ),
        (
            "share_links",
            "CREATE TABLE share_links (id TEXT PRIMARY KEY, paths TEXT NOT NULL)",
        ),
    ],
)
def test_recorded_v6_rejects_incompatible_required_object(
    memory_db, table, schema, monkeypatch
):
    from AssetsManager.core.db_migrations import InvalidSchemaError, migrate

    conn = memory_db
    _load_v1_schema(conn)
    assert _migrate_to(monkeypatch, conn, 6) == 6
    conn.execute(f"DROP TABLE {table}")
    conn.execute(schema)
    conn.commit()

    with pytest.raises(InvalidSchemaError, match=table):
        migrate(conn)


@pytest.mark.parametrize(
    ("table", "schema"),
    [
        (
            "users",
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL)",
        ),
        (
            "invite_codes",
            "CREATE TABLE invite_codes (code TEXT PRIMARY KEY)",
        ),
        (
            "share_links",
            "CREATE TABLE share_links (id TEXT PRIMARY KEY, paths TEXT NOT NULL)",
        ),
    ],
)
def test_v6_rejects_incompatible_existing_auth_share_table(
    memory_db, monkeypatch, table, schema
):
    from AssetsManager.core.db_migrations import InvalidSchemaError

    conn = memory_db
    _load_v1_schema(conn)
    assert _migrate_to(monkeypatch, conn, 5) == 5
    conn.execute(schema)
    conn.commit()

    with pytest.raises(InvalidSchemaError, match=table):
        _migrate_to(monkeypatch, conn, 6)

    assert conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(version,) for version in range(1, 6)]
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None



class _FailAfterCreateConnection:
    def __init__(self, conn: sqlite3.Connection, table: str):
        self._conn = conn
        self._table = table
        self._failed = False

    @property
    def in_transaction(self):
        return self._conn.in_transaction

    def execute(self, sql, *parameters):
        cursor = self._conn.execute(sql, *parameters)
        if (
            not self._failed
            and f"CREATE TABLE IF NOT EXISTS {self._table}" in sql
        ):
            self._failed = True
            raise RuntimeError(f"injected {self._table} ensure failure")
        return cursor

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()


@pytest.mark.parametrize(
    ("repository", "method", "failing_table", "tables"),
    [
        (
            "auth",
            "init_tables",
            "invite_codes",
            ("users", "invite_codes"),
        ),
        (
            "share",
            "init_table",
            "share_links",
            ("share_links",),
        ),
    ],
)
def test_repository_init_savepoint_rolls_back_partial_ensure(
    memory_db, repository, method, failing_table, tables
):
    from AssetsManager.repositories import auth_repository, share_repository

    conn = _FailAfterCreateConnection(memory_db, failing_table)
    if repository == "auth":
        repo = auth_repository.AuthRepository(cast(sqlite3.Connection, conn))
    else:
        repo = share_repository.ShareRepository(cast(sqlite3.Connection, conn))

    with pytest.raises(RuntimeError, match="injected"):
        getattr(repo, method)()

    assert conn.in_transaction is False
    for table in tables:
        assert memory_db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is None


@pytest.mark.parametrize(
    ("repository", "method", "schema", "table"),
    [
        (
            "auth",
            "init_tables",
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE)",
            "users",
        ),
        (
            "share",
            "init_table",
            "CREATE TABLE share_links (id TEXT PRIMARY KEY)",
            "share_links",
        ),
    ],
)
def test_repository_init_rejects_existing_incompatible_table(
    memory_db, repository, method, schema, table
):
    from AssetsManager.core import db_migrations
    from AssetsManager.repositories import auth_repository, share_repository

    conn = memory_db
    conn.execute(schema)
    conn.commit()
    repo = (
        auth_repository.AuthRepository(conn)
        if repository == "auth"
        else share_repository.ShareRepository(conn)
    )

    with pytest.raises(db_migrations.InvalidSchemaError, match=table):
        getattr(repo, method)()


def test_repository_init_tables_preserves_outer_transaction(memory_db):
    from AssetsManager.repositories.auth_repository import AuthRepository
    from AssetsManager.repositories.share_repository import ShareRepository

    conn = memory_db
    conn.execute("BEGIN")
    conn.execute("CREATE TABLE caller_data (value TEXT NOT NULL)")
    AuthRepository(conn).init_tables()
    ShareRepository(conn).init_table()
    conn.execute("INSERT INTO caller_data VALUES ('rollback-me')")

    assert conn.in_transaction is True
    conn.rollback()
    for table in ("caller_data", "users", "invite_codes", "share_links"):
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is None


def test_repository_init_tables_commits_raw_legacy_connection():
    from AssetsManager.repositories.auth_repository import AuthRepository
    from AssetsManager.repositories.share_repository import ShareRepository

    conn = sqlite3.connect(":memory:")
    try:
        AuthRepository(conn).init_tables()
        ShareRepository(conn).init_table()
        conn.rollback()
        for table in ("users", "invite_codes", "share_links"):
            assert conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone() is not None
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([(0, "baseline_current_schema")], "non-positive"),
        ([(1, "baseline_current_schema"), (3, "add_tag_metadata")], "contiguous"),
        ([(1, "wrong_name")], "name does not match"),
    ],
)
def test_preflight_rejects_malformed_history_without_writing(
    memory_db, rows, message
):
    from AssetsManager.core.db_migrations import MigrationHistoryError, preflight_recorded_version

    conn = memory_db
    conn.execute(
        "CREATE TABLE schema_migrations ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at REAL NOT NULL)"
    )
    conn.executemany(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, 0)",
        rows,
    )
    conn.commit()
    schema_version_before = conn.execute("PRAGMA schema_version").fetchone()

    with pytest.raises(MigrationHistoryError, match=message):
        preflight_recorded_version(conn)

    assert conn.execute("PRAGMA schema_version").fetchone() == schema_version_before
    assert conn.in_transaction is False


def test_validate_history_rejects_duplicate_history():
    from AssetsManager.core.db_migrations import MigrationHistoryError, _validate_history

    with pytest.raises(MigrationHistoryError, match="duplicate"):
        _validate_history(
            [(1, "baseline_current_schema"), (1, "baseline_current_schema")]
        )


def test_preflight_rejects_fake_latest_history(memory_db):
    from AssetsManager.core.db_migrations import MigrationHistoryError, preflight_recorded_version

    conn = memory_db
    conn.execute(
        "CREATE TABLE schema_migrations ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at REAL NOT NULL)"
    )
    conn.executemany(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, 0)",
        [(1, "baseline_current_schema"), (2, "add_assets_index")],
    )
    conn.execute("UPDATE schema_migrations SET name='fake_latest' WHERE version=2")
    conn.commit()

    with pytest.raises(MigrationHistoryError, match="name does not match"):
        preflight_recorded_version(conn)


def test_v5_does_not_commit_outer_transaction(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import (
        CURRENT_SCHEMA_VERSION,
        _ensure_migrations_table,
    )

    conn = memory_db
    conn.executescript(database._SCHEMA)
    _ensure_migrations_table(conn)
    conn.executemany(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, 0)",
        [
            (1, "baseline_current_schema"),
            (2, "add_assets_index"),
            (3, "add_tag_metadata"),
            (4, "add_plugin_metadata"),
        ],
    )
    conn.commit()
    conn.execute("CREATE TABLE caller_data (value TEXT NOT NULL)")
    conn.commit()
    conn.execute("INSERT INTO caller_data VALUES ('keep-until-rollback')")

    from AssetsManager.core.db_migrations import migrate

    assert migrate(conn) == CURRENT_SCHEMA_VERSION
    assert conn.execute("SELECT value FROM caller_data").fetchone() == (
        "keep-until-rollback",
    )
    conn.rollback()
    assert conn.execute("SELECT * FROM caller_data").fetchall() == []
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='directory_cache'"
    ).fetchone() is None
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='library_favorites'"
    ).fetchone() is None
    assert conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(1,), (2,), (3,), (4,)]


def test_migration_failure_rolls_back_history_and_probe_ddl(memory_db, monkeypatch):
    from AssetsManager.core import database, db_migrations

    memory_db.executescript(database._SCHEMA)

    def failing_migration(conn):
        conn.execute("CREATE TABLE migration_probe (value TEXT NOT NULL)")
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(
        db_migrations,
        "MIGRATIONS",
        (db_migrations.Migration(1, "failing_probe", failing_migration),),
    )

    with pytest.raises(RuntimeError, match="injected migration failure"):
        db_migrations.migrate(memory_db)

    assert memory_db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone() is None
    assert memory_db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_probe'"
    ).fetchone() is None


def test_v7_to_v8_creates_commerce_schema_with_foreign_keys(memory_db, monkeypatch):
    conn = memory_db
    conn.execute("PRAGMA foreign_keys=ON")
    _load_v1_schema(conn)
    assert _migrate_to(monkeypatch, conn, 7) == 7
    conn.execute(
        "INSERT INTO library_favorites (owner_key, file_path) VALUES (?, ?)",
        ("owner", "kept/path"),
    )
    conn.commit()

    assert _migrate_to(monkeypatch, conn, 8) == 8

    assert {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()} >= {
        "library_favorites",
        "shop_items",
        "shop_orders",
        "shop_order_events",
        "shop_delivery_tokens",
    }
    assert conn.execute(
        "SELECT owner_key, file_path FROM library_favorites"
    ).fetchall() == [("owner", "kept/path")]
    assert conn.execute(
        "SELECT name FROM schema_migrations WHERE version=8"
    ).fetchone() == ("commerce_schema",)

    order_fks = {
        (row[3], row[2], row[4], row[5], row[6])
        for row in conn.execute("PRAGMA foreign_key_list('shop_orders')")
    }
    assert ("item_id", "shop_items", "id", "CASCADE", "RESTRICT") in order_fks
    event_fks = {
        (row[3], row[2], row[4], row[6])
        for row in conn.execute("PRAGMA foreign_key_list('shop_order_events')")
    }
    assert ("order_id", "shop_orders", "id", "CASCADE") in event_fks
    token_fks = {
        (row[3], row[2], row[4], row[6])
        for row in conn.execute("PRAGMA foreign_key_list('shop_delivery_tokens')")
    }
    assert ("order_id", "shop_orders", "id", "CASCADE") in token_fks
    assert ("share_id", "share_links", "id", "SET NULL") in token_fks


def test_v8_to_v9_creates_asset_index_state(memory_db, monkeypatch):
    conn = memory_db
    _load_v1_schema(conn)
    assert _migrate_to(monkeypatch, conn, 8) == 8

    assert _migrate_to(monkeypatch, conn, 9) == 9
    assert conn.execute(
        "SELECT name FROM schema_migrations WHERE version=9"
    ).fetchone() == ("asset_index_state",)
    assert {
        row[1] for row in conn.execute("PRAGMA table_info('asset_index_state')")
    } == {"library_root", "revision", "updated_at"}



def test_asset_index_state_contract_rejects_incompatible_columns(memory_db):
    from AssetsManager.core.schema_defs import InvalidSchemaError, validate_schema_objects

    memory_db.execute(
        "CREATE TABLE asset_index_state ("
        "library_root TEXT PRIMARY KEY NOT NULL, "
        "revision TEXT, "
        "updated_at REAL)"
    )
    with pytest.raises(InvalidSchemaError, match="invalid columns|missing checks"):
        validate_schema_objects(memory_db, ("asset_index_state",))


def test_commerce_contract_rejects_weak_shop_items_constraints(memory_db):
    from AssetsManager.core.schema_defs import InvalidSchemaError, validate_schema_objects

    memory_db.execute(
        "CREATE TABLE shop_items ("
        "id INTEGER PRIMARY KEY, "
        "path TEXT UNIQUE, "
        "title TEXT, description TEXT, price_cents INTEGER, currency TEXT, "
        "cover_path TEXT, enabled INTEGER, metadata TEXT, "
        "created_at REAL, updated_at REAL"
        ")"
    )
    memory_db.execute(
        "CREATE INDEX idx_shop_items_enabled_updated "
        "ON shop_items(enabled, updated_at)"
    )

    with pytest.raises(InvalidSchemaError, match="invalid columns|missing checks"):
        validate_schema_objects(memory_db, ("shop_items",))


def test_v9_to_v10_creates_free_download_quota_windows(memory_db, monkeypatch):
    conn = memory_db
    _load_v1_schema(conn)
    assert _migrate_to(monkeypatch, conn, 9) == 9

    assert _migrate_to(monkeypatch, conn, 10) == 10
    assert conn.execute(
        "SELECT name FROM schema_migrations WHERE version=10"
    ).fetchone() == ("free_download_quota",)
    assert {
        row[1] for row in conn.execute("PRAGMA table_info('free_download_quota_windows')")
    } == {"identity_key", "window_start", "download_count", "last_download_at"}


def test_v8_collision_rolls_back_all_commerce_ddl_and_history(memory_db, monkeypatch):
    from AssetsManager.core.db_migrations import InvalidSchemaError

    conn = memory_db
    _load_v1_schema(conn)
    assert _migrate_to(monkeypatch, conn, 7) == 7
    conn.execute("CREATE TABLE shop_orders (id TEXT PRIMARY KEY)")
    conn.commit()

    with pytest.raises(InvalidSchemaError, match="shop_orders"):
        _migrate_to(monkeypatch, conn, 8)

    assert conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(version,) for version in range(1, 8)]
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shop_items'"
    ).fetchone() is None
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shop_order_events'"
    ).fetchone() is None
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shop_delivery_tokens'"
    ).fetchone() is None


@pytest.mark.parametrize(
    "table",
    [
        "shop_items",
        "shop_orders",
        "shop_order_events",
        "shop_delivery_tokens",
        "shop_order_receipts",
    ],
)
def test_latest_schema_revalidates_required_commerce_objects(memory_db, table):
    from AssetsManager.core.db_migrations import (
        CURRENT_SCHEMA_VERSION,
        InvalidSchemaError,
        migrate,
    )

    conn = memory_db
    _load_v1_schema(conn)
    assert migrate(conn) == CURRENT_SCHEMA_VERSION
    conn.execute(f"DROP TABLE {table}")
    conn.commit()

    with pytest.raises(InvalidSchemaError, match=table):
        migrate(conn)


def test_v10_to_v11_creates_order_receipts_without_backfill(memory_db, monkeypatch):
    conn = memory_db
    conn.execute("PRAGMA foreign_keys=ON")
    _load_v1_schema(conn)
    assert _migrate_to(monkeypatch, conn, 10) == 10
    conn.execute(
        "INSERT INTO shop_items (path, title, price_cents, currency) VALUES (?, ?, ?, ?)",
        ("old.txt", "Old", 0, "CNY"),
    )
    item_id = conn.execute("SELECT id FROM shop_items").fetchone()[0]
    conn.execute(
        "INSERT INTO shop_orders "
        "(item_id, item_path, item_title, amount_cents, currency, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (item_id, "old.txt", "Old", 0, "CNY", "pending"),
    )
    conn.commit()

    assert _migrate_to(monkeypatch, conn, 11) == 11

    assert conn.execute(
        "SELECT name FROM schema_migrations WHERE version=11"
    ).fetchone() == ("shop_order_receipts",)
    assert {
        row[1] for row in conn.execute("PRAGMA table_info('shop_order_receipts')")
    } == {"token_hash", "order_id", "created_at", "expires_at", "revoked_at"}
    assert conn.execute("SELECT COUNT(*) FROM shop_order_receipts").fetchone() == (0,)
    receipt_fks = {
        (row[3], row[2], row[4], row[5], row[6])
        for row in conn.execute("PRAGMA foreign_key_list('shop_order_receipts')")
    }
    assert ("order_id", "shop_orders", "id", "CASCADE", "CASCADE") in receipt_fks
    indexes = {
        row[1]: tuple(
            index_row[2]
            for index_row in conn.execute(f"PRAGMA index_info('{row[1]}')")
        )
        for row in conn.execute("PRAGMA index_list('shop_order_receipts')")
    }
    assert ("order_id",) in indexes.values()
    assert indexes["idx_shop_order_receipts_availability"] == (
        "revoked_at",
        "expires_at",
    )


def test_v11_receipt_collision_rolls_back_history(memory_db, monkeypatch):
    from AssetsManager.core.db_migrations import InvalidSchemaError

    conn = memory_db
    _load_v1_schema(conn)
    assert _migrate_to(monkeypatch, conn, 10) == 10
    conn.execute("CREATE TABLE shop_order_receipts (token_hash TEXT PRIMARY KEY)")
    conn.commit()

    with pytest.raises(InvalidSchemaError, match="shop_order_receipts"):
        _migrate_to(monkeypatch, conn, 11)

    assert conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
    ).fetchone() == (10,)

def test_v19_upgrades_legacy_cart_checkout_schema_and_preserves_records(memory_db, monkeypatch):
    from copy import deepcopy

    from AssetsManager.core import database, db_migrations, schema_defs

    conn = memory_db
    conn.executescript(database._SCHEMA)
    legacy_schema = db_migrations.SHOP_CARTS_SCHEMA_V16
    current_contract = schema_defs.SCHEMA_OBJECT_CONTRACT
    legacy_contracts = deepcopy(current_contract)
    legacy_shop_carts = cast(dict[str, Any], legacy_contracts["shop_carts"])
    legacy_shop_carts["columns"] = tuple(
        value for value in legacy_shop_carts["columns"]
        if value != "checkout_generation"
    )
    cast(dict[str, Any], legacy_shop_carts["column_contracts"]).pop(
        "checkout_generation"
    )
    legacy_shop_carts["checks"] = tuple(
        value for value in legacy_shop_carts["checks"]
        if value != "checkout_generation >= 1"
    )
    legacy_contracts["shop_cart_checkouts"]["columns"] = tuple(
        value
        for value in legacy_contracts["shop_cart_checkouts"]["columns"]
        if value not in {"checkout_generation", "request_fingerprint"}
    )
    cast(dict[str, Any], legacy_contracts["shop_cart_checkouts"]["column_contracts"]).pop(
        "checkout_generation"
    )
    cast(dict[str, Any], legacy_contracts["shop_cart_checkouts"]["column_contracts"]).pop(
        "request_fingerprint"
    )
    legacy_contracts["shop_cart_checkouts"]["unique_constraints"] = (
        ("cart_id", "request_key"),
        ("checkout_group_id",),
    )
    legacy_contracts["shop_cart_checkouts"]["checks"] = ()
    legacy_contracts["shop_cart_checkouts"]["indexes"] = {
        "idx_shop_cart_checkouts_cart": ("cart_id", "created_at")
    }

    monkeypatch.setattr(db_migrations, "SHOP_CARTS_SCHEMA_V16", legacy_schema)
    monkeypatch.setattr(db_migrations, "SCHEMA_OBJECT_CONTRACT", legacy_contracts)
    monkeypatch.setattr(schema_defs, "SCHEMA_OBJECT_CONTRACT", legacy_contracts)
    assert _migrate_to(monkeypatch, conn, 18) == 18

    conn.execute(
        "INSERT INTO shop_carts(owner_type,owner_key,expires_at,created_at,updated_at) VALUES('anonymous','legacy-owner',100,1,1)"
    )
    cart_id = conn.execute("SELECT id FROM shop_carts WHERE owner_key='legacy-owner'").fetchone()[0]
    conn.execute(
        "INSERT INTO shop_cart_checkouts(cart_id,request_key,checkout_group_id,order_ids,created_at) VALUES(?,?,?,?,?)",
        (cart_id, "legacy-key", "legacy-group", "[1]", 2),
    )
    conn.commit()

    # Restore the current contract in both modules; the migration must validate
    # the upgraded shape rather than the legacy copy.
    monkeypatch.setattr(db_migrations, "SCHEMA_OBJECT_CONTRACT", current_contract)
    monkeypatch.setattr(schema_defs, "SCHEMA_OBJECT_CONTRACT", current_contract)

    assert _migrate_to(monkeypatch, conn, 19) == 19
    assert conn.execute(
        "SELECT checkout_generation,request_key,checkout_group_id FROM shop_cart_checkouts"
    ).fetchone() == (1, "legacy-key", "legacy-group")
    assert conn.execute(
        "SELECT checkout_generation FROM shop_carts WHERE id=?", (cart_id,)
    ).fetchone() == (1,)


def test_v23_adds_catalog_ordering_index_to_existing_commerce_schema(memory_db, monkeypatch):
    from AssetsManager.core import database

    conn = memory_db
    conn.executescript(database._SCHEMA)

    assert _migrate_to(monkeypatch, conn, 22) == 22

    conn.execute("DROP INDEX IF EXISTS idx_shop_items_enabled_created")
    conn.commit()
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        ("idx_shop_items_enabled_created",),
    ).fetchone() is None

    assert _migrate_to(monkeypatch, conn, 23) == 23
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        ("idx_shop_items_enabled_created",),
    ).fetchone() is not None


def test_v24_to_v25_creates_shop_share_claims(memory_db, monkeypatch):
    from AssetsManager.core import database

    conn = memory_db
    conn.executescript(database._SCHEMA)

    assert _migrate_to(monkeypatch, conn, 24) == 24
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shop_share_claims'"
    ).fetchone() is None

    assert _migrate_to(monkeypatch, conn, 25) == 25
    assert conn.execute(
        "SELECT name FROM schema_migrations WHERE version=25"
    ).fetchone() == ("shop_share_claims",)
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info('shop_share_claims')")
    }
    assert columns == {
        "claim_hash",
        "order_id",
        "expires_at",
        "claimed_at",
        "revoked_at",
        "created_at",
    }
    claim_fks = {
        (row[3], row[2], row[4], row[5], row[6])
        for row in conn.execute("PRAGMA foreign_key_list('shop_share_claims')")
    }
    assert ("order_id", "shop_orders", "id", "CASCADE", "CASCADE") in claim_fks
    indexes = {
        row[1]: tuple(
            index_row[2]
            for index_row in conn.execute(f"PRAGMA index_info('{row[1]}')")
        )
        for row in conn.execute("PRAGMA index_list('shop_share_claims')")
    }
    assert indexes["idx_shop_share_claims_order_created"] == (
        "order_id",
        "created_at",
    )
    # The migrated table satisfies the current schema contract.
    from AssetsManager.core.schema_defs import validate_schema_objects

    validate_schema_objects(conn, ("shop_share_claims",))


def test_latest_schema_revalidates_shop_share_claims(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import (
        CURRENT_SCHEMA_VERSION,
        InvalidSchemaError,
        migrate,
    )

    conn = memory_db
    conn.executescript(database._SCHEMA)
    assert migrate(conn) == CURRENT_SCHEMA_VERSION
    conn.execute("DROP TABLE shop_share_claims")
    conn.commit()

    with pytest.raises(InvalidSchemaError, match="shop_share_claims"):
        migrate(conn)


def test_fresh_schema_contains_user_can_write_column(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import CURRENT_SCHEMA_VERSION, migrate

    conn = memory_db
    conn.executescript(database._SCHEMA)
    assert migrate(conn) == CURRENT_SCHEMA_VERSION

    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info('users')")
    }
    assert "can_write" in columns
    not_null = {
        str(row[1]): row[3] for row in conn.execute("PRAGMA table_info('users')")
    }
    assert not_null["can_write"] == 1  # NOT NULL
    default = {
        str(row[1]): row[4] for row in conn.execute("PRAGMA table_info('users')")
    }
    assert default["can_write"] == "0"  # DEFAULT 0


def test_v28_upgrades_users_with_existing_rows_defaulting_to_zero(memory_db, monkeypatch):
    conn = memory_db
    _load_v1_schema(conn)

    assert _migrate_to(monkeypatch, conn, 27) == 27

    # Existing users created at v27 have no can_write value yet.
    conn.execute(
        "INSERT INTO users (username, password, email, role, is_active) "
        "VALUES ('alice', 'hash', NULL, 'viewer', 1)"
    )
    conn.commit()
    columns_before = {
        str(row[1]) for row in conn.execute("PRAGMA table_info('users')")
    }
    assert "can_write" not in columns_before

    assert _migrate_to(monkeypatch, conn, 28) == 28

    assert conn.execute(
        "SELECT name FROM schema_migrations WHERE version=28"
    ).fetchone() == ("user_can_write",)
    assert conn.execute(
        "SELECT can_write FROM users WHERE username='alice'"
    ).fetchone() == (0,)


def test_v28_upgrade_revalidates_users_contract(memory_db, monkeypatch):
    from AssetsManager.core import db_migrations
    from AssetsManager.core.db_migrations import InvalidSchemaError

    conn = memory_db
    _load_v1_schema(conn)

    assert _migrate_to(monkeypatch, conn, 28) == 28

    # A users table missing can_write fails the current-contract revalidation.
    conn.execute("DROP TABLE users")
    conn.commit()
    conn.execute(
        "CREATE TABLE users ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, "
        "password TEXT NOT NULL, email TEXT, role TEXT DEFAULT 'viewer', "
        "created_at REAL DEFAULT (strftime('%s','now')), last_login REAL, "
        "is_active INTEGER DEFAULT 1)"
    )
    conn.commit()

    with pytest.raises(InvalidSchemaError, match="users"):
        db_migrations.migrate(conn)


def test_v36_creates_tag_source_partition_tables(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import (
        CURRENT_SCHEMA_VERSION,
        current_version,
        migrate,
    )
    from AssetsManager.core.schema_defs import validate_schema_objects

    conn = memory_db
    conn.executescript(database._SCHEMA)

    assert migrate(conn) == CURRENT_SCHEMA_VERSION
    assert current_version(conn) == 36
    assert conn.execute(
        "SELECT name FROM schema_migrations WHERE version=36"
    ).fetchone() == ("tag_source_partition",)

    # Both partitions mirror the file_tags shape and satisfy the contract.
    validate_schema_objects(conn, ("ai_asset_tags", "plugin_derived_fields"))
    assert {row[1] for row in conn.execute("PRAGMA index_list('ai_asset_tags')")} >= {
        "idx_ai_asset_tags_tag"
    }
    assert {
        row[1] for row in conn.execute("PRAGMA index_list('plugin_derived_fields')")
    } >= {"idx_plugin_derived_fields_tag"}


def test_v35_database_with_human_tag_rows_upgrades_to_v36_untouched(memory_db, monkeypatch):
    from AssetsManager.core import database, db_migrations
    from AssetsManager.core.schema_defs import validate_schema_objects

    conn = memory_db
    conn.executescript(database._SCHEMA)
    original_version = db_migrations.CURRENT_SCHEMA_VERSION
    try:
        monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 35)
        assert db_migrations.migrate(conn) == 35
    finally:
        monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", original_version)

    conn.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES ('/lib/asset.txt', 'hero')"
    )
    conn.commit()

    assert db_migrations.migrate(conn) == 36
    # Human rows survive byte-identical; the new partitions start empty.
    assert conn.execute(
        "SELECT file_path, tag FROM file_tags"
    ).fetchall() == [("/lib/asset.txt", "hero")]
    assert conn.execute("SELECT COUNT(*) FROM ai_asset_tags").fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM plugin_derived_fields").fetchone() == (0,)
    validate_schema_objects(conn, ("ai_asset_tags", "plugin_derived_fields"))


def test_v36_tag_source_partition_is_idempotent(memory_db, monkeypatch):
    from AssetsManager.core import database, db_migrations
    from AssetsManager.core.schema_defs import validate_schema_objects

    conn = memory_db
    conn.executescript(database._SCHEMA)
    original_version = db_migrations.CURRENT_SCHEMA_VERSION
    try:
        monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 35)
        assert db_migrations.migrate(conn) == 35
    finally:
        monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", original_version)

    # The raw step runs twice back-to-back without changing any shape.
    db_migrations._add_tag_source_partition_v36(conn)
    db_migrations._add_tag_source_partition_v36(conn)
    conn.commit()
    validate_schema_objects(conn, ("ai_asset_tags", "plugin_derived_fields"))

    # Full runner passes on the already-migrated database are also no-ops.
    assert db_migrations.migrate(conn) == 36
    assert db_migrations.migrate(conn) == 36
    validate_schema_objects(conn, ("ai_asset_tags", "plugin_derived_fields"))
