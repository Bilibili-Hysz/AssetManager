from pathlib import Path
import sqlite3
from typing import cast

import pytest


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
    from AssetsManager.core.db_migrations import migrate

    conn = memory_db
    conn.executescript(database._SCHEMA)

    assert conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='directory_cache'"
    ).fetchone() is None

    assert migrate(conn) == 6
    assert conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='directory_cache'"
    ).fetchone() is not None


def test_migrate_records_baseline_schema_version(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import current_version, migrate

    conn = memory_db
    conn.executescript(database._SCHEMA)

    assert migrate(conn) == 6
    assert current_version(conn) == 6
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


def test_migrate_is_idempotent(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    conn = memory_db
    conn.executescript(database._SCHEMA)

    assert migrate(conn) == 6
    assert migrate(conn) == 6
    count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert count == 6


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
    from AssetsManager.core.db_migrations import current_version

    runtime = tmp_path / "RuntimeData"
    lib = tmp_path / "Library"
    lib.mkdir()

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database, "RUNTIME_ROOT", runtime)
    try:
        manager = database.DatabaseManager()
        conn = manager.connection_for(lib)
        assert current_version(conn) == 6
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

    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", target_version)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", db_migrations.MIGRATIONS[:target_version])

    assert db_migrations.migrate(conn) == target_version
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
    from AssetsManager.core import db_migrations

    conn = memory_db
    _load_v1_schema(conn)
    all_migrations = db_migrations.MIGRATIONS
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 5)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations[:5])
    assert db_migrations.migrate(conn) == 5
    assert conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(version,) for version in range(1, 6)]

    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 6)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations)
    assert db_migrations.migrate(conn) == 6
    assert {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()} >= {"users", "invite_codes", "share_links"}
    assert conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(version,) for version in range(1, 7)]


@pytest.mark.parametrize("table", ["users", "invite_codes", "share_links"])
def test_recorded_v6_revalidates_required_auth_share_objects(memory_db, table):
    from AssetsManager.core.db_migrations import InvalidSchemaError, migrate

    conn = memory_db
    _load_v1_schema(conn)
    assert migrate(conn) == 6
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
    memory_db, table, schema
):
    from AssetsManager.core.db_migrations import InvalidSchemaError, migrate

    conn = memory_db
    _load_v1_schema(conn)
    assert migrate(conn) == 6
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
    from AssetsManager.core import db_migrations

    conn = memory_db
    _load_v1_schema(conn)
    all_migrations = db_migrations.MIGRATIONS
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 5)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations[:5])
    assert db_migrations.migrate(conn) == 5
    conn.execute(schema)
    conn.commit()

    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 6)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations)
    with pytest.raises(db_migrations.InvalidSchemaError, match=table):
        db_migrations.migrate(conn)

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
    from AssetsManager.core.db_migrations import _ensure_migrations_table

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

    assert migrate(conn) == 6
    assert conn.execute("SELECT value FROM caller_data").fetchone() == (
        "keep-until-rollback",
    )
    conn.rollback()
    assert conn.execute("SELECT * FROM caller_data").fetchall() == []
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='directory_cache'"
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
