import pytest


def test_v14_creates_and_validates_reconciliation_tasks(memory_db, monkeypatch):
    from AssetsManager.core import database, db_migrations

    memory_db.executescript(database._SCHEMA)
    all_migrations = db_migrations.MIGRATIONS
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 14)
    monkeypatch.setattr(
        db_migrations,
        "MIGRATIONS",
        tuple(migration for migration in all_migrations if migration.version <= 14),
    )
    assert db_migrations.migrate(memory_db) == 14

    columns = {
        row[1]
        for row in memory_db.execute("PRAGMA table_info('reconciliation_tasks')")
    }
    assert {
        "task_id",
        "library_root",
        "path",
        "kind",
        "reason",
        "state",
        "attempts",
        "next_attempt_at_wallclock",
        "operation_ids",
        "last_error_type",
        "last_error",
        "expected_revision",
        "observed_revision",
        "created_at",
        "updated_at",
        "lease_expires_at_wallclock",
        "max_attempts",
    } <= columns
    assert "lease_token" not in columns
    index_names = {
        row[1] for row in memory_db.execute("PRAGMA index_list('reconciliation_tasks')")
    }
    assert "idx_reconciliation_tasks_due" in index_names
    assert memory_db.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='reconciliation_queue_state'"
    ).fetchone() is None


def test_v15_creates_queue_state_at_its_boundary(memory_db, monkeypatch):
    from AssetsManager.core import database, db_migrations

    memory_db.executescript(database._SCHEMA)
    all_migrations = db_migrations.MIGRATIONS
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 15)
    monkeypatch.setattr(
        db_migrations,
        "MIGRATIONS",
        tuple(migration for migration in all_migrations if migration.version <= 15),
    )
    assert db_migrations.migrate(memory_db) == 15
    assert {
        row[1] for row in memory_db.execute(
            "PRAGMA table_info('reconciliation_queue_state')"
        )
    } == {"library_root", "generation", "updated_at"}
    assert memory_db.execute(
        "SELECT generation FROM reconciliation_queue_state"
    ).fetchone() is None


def test_v14_rejects_preexisting_incompatible_reconciliation_tasks(
    memory_db, monkeypatch
):
    from AssetsManager.core import database, db_migrations
    from AssetsManager.core.schema_defs import InvalidSchemaError

    memory_db.executescript(database._SCHEMA)
    all_migrations = db_migrations.MIGRATIONS
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 13)
    monkeypatch.setattr(
        db_migrations,
        "MIGRATIONS",
        tuple(migration for migration in db_migrations.MIGRATIONS if migration.version <= 13),
    )
    assert db_migrations.migrate(memory_db) == 13
    memory_db.execute(
        "CREATE TABLE reconciliation_tasks (task_id TEXT PRIMARY KEY NOT NULL)"
    )
    memory_db.commit()
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 14)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations)

    with pytest.raises(InvalidSchemaError, match="reconciliation_tasks"):
        db_migrations.migrate(memory_db)

    assert db_migrations.current_version(memory_db) == 13


def test_v14_migration_preserves_outer_transaction_rollback(memory_db):
    from AssetsManager.core import database, db_migrations

    memory_db.executescript(database._SCHEMA)
    memory_db.execute("BEGIN")
    assert db_migrations.migrate(memory_db) == db_migrations.CURRENT_SCHEMA_VERSION
    assert memory_db.in_transaction
    memory_db.rollback()

    assert memory_db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='reconciliation_tasks'"
    ).fetchone() is None
    assert memory_db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone() is None


def test_v15_rejects_preexisting_incompatible_queue_state(memory_db, monkeypatch):
    from AssetsManager.core import database, db_migrations
    from AssetsManager.core.schema_defs import InvalidSchemaError

    memory_db.executescript(database._SCHEMA)
    all_migrations = db_migrations.MIGRATIONS
    monkeypatch.setattr(
        db_migrations,
        "MIGRATIONS",
        tuple(migration for migration in all_migrations if migration.version <= 14),
    )
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 14)
    assert db_migrations.migrate(memory_db) == 14
    memory_db.execute(
        "CREATE TABLE reconciliation_queue_state "
        "(library_root TEXT PRIMARY KEY NOT NULL)"
    )
    memory_db.commit()
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations)
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 15)

    with pytest.raises(InvalidSchemaError, match="reconciliation_queue_state"):
        db_migrations.migrate(memory_db)


def test_v16_to_v17_migration_preserves_existing_tasks(memory_db, monkeypatch):
    from AssetsManager.core import database, db_migrations

    memory_db.executescript(database._SCHEMA)
    all_migrations = db_migrations.MIGRATIONS
    monkeypatch.setattr(
        db_migrations,
        "MIGRATIONS",
        tuple(migration for migration in all_migrations if migration.version <= 16),
    )
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 16)
    assert db_migrations.migrate(memory_db) == 16
    memory_db.execute(
        "INSERT INTO reconciliation_tasks ("
        "task_id, library_root, path, kind, reason, state, attempts, "
        "next_attempt_at_wallclock, operation_ids, created_at, updated_at, "
        "lease_expires_at_wallclock, max_attempts"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "task-v16",
            "C:/library",
            "C:/library/assets",
            "asset_index_root_rescan",
            "busy",
            "pending",
            0,
            1000.0,
            "[]",
            1000.0,
            1000.0,
            None,
            5,
        ),
    )
    memory_db.commit()

    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations)
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 17)
    assert db_migrations.migrate(memory_db) == 17

    columns = {
        row[1]
        for row in memory_db.execute("PRAGMA table_info('reconciliation_tasks')")
    }
    assert "lease_token" in columns
    row = memory_db.execute(
        "SELECT task_id, lease_token, reason FROM reconciliation_tasks"
    ).fetchone()
    assert row == ("task-v16", None, "busy")