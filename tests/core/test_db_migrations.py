def test_migrate_records_baseline_schema_version(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import current_version, migrate

    conn = memory_db
    conn.executescript(database._SCHEMA)

    assert migrate(conn) == 5
    assert current_version(conn) == 5
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


def test_migrate_is_idempotent(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    conn = memory_db
    conn.executescript(database._SCHEMA)

    assert migrate(conn) == 5
    assert migrate(conn) == 5
    count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert count == 5


def test_open_library_runs_migrations(tmp_path, monkeypatch):
    from AssetsManager.core import database, path_resolver
    from AssetsManager.core.db_migrations import current_version

    runtime = tmp_path / "RuntimeData"
    lib = tmp_path / "Library"
    lib.mkdir()

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database, "RUNTIME_ROOT", runtime)
    try:
        conn = database.get_lib_db(str(lib))
        assert current_version(conn) == 5
    finally:
        database.close_all_dbs()


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


def test_v2_upgrade_from_v1(memory_db):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate, current_version, _ensure_migrations_table

    conn = memory_db
    conn.executescript(database._SCHEMA)

    _ensure_migrations_table(conn)
    conn.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (1, 'baseline_current_schema', 0)"
    )
    conn.commit()
    assert current_version(conn) == 1

    assert migrate(conn) == 5
    assert current_version(conn) == 5
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "assets" in tables
    assert "tag_metadata" in tables
    assert "plugin_metadata" in tables
    assert "directory_cache" in tables
