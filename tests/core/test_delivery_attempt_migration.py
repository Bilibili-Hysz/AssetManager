import sqlite3

import pytest

def test_v21_to_v22_creates_delivery_attempts_table(memory_db, monkeypatch):
    from AssetsManager.core import database, db_migrations

    conn = memory_db
    conn.executescript(database._SCHEMA)
    all_migrations = db_migrations.MIGRATIONS
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 21)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations[:21])
    assert db_migrations.migrate(conn) == 21
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shop_delivery_attempts'"
    ).fetchone() is None

    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 22)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations)
    assert db_migrations.migrate(conn) == 22
    assert {
        row[1] for row in conn.execute("PRAGMA table_info('shop_delivery_attempts')")
    } == {
        "id",
        "credential_kind",
        "credential_hash",
        "request_key_hash",
        "order_id",
        "delivery_token_hash",
        "state",
        "reserved_at",
        "consumed_at",
        "failed_at",
        "failure_code",
    }
    assert conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
    ).fetchone() == (22,)
    from AssetsManager.core.schema_defs import validate_schema_objects

    validate_schema_objects(conn, ("shop_delivery_attempts",))
    index_names = {
        row[1] for row in conn.execute("PRAGMA index_list('shop_delivery_attempts')")
    }
    assert {
        "idx_shop_delivery_attempts_order_created",
        "idx_shop_delivery_attempts_state",
    } <= index_names
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO shop_delivery_attempts(" 
            "credential_kind, credential_hash, request_key_hash, order_id, "
            "delivery_token_hash, state) VALUES (?, ?, ?, ?, ?, ?)",
            ("bearer", "bad", "bad", 1, "bad", "invalid"),
        )



def test_v22_accepts_compatible_preexisting_delivery_attempts(
    memory_db, monkeypatch
):
    from AssetsManager.core import database, db_migrations

    memory_db.executescript(database._SCHEMA)
    all_migrations = db_migrations.MIGRATIONS
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 21)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations[:21])
    assert db_migrations.migrate(memory_db) == 21

    memory_db.executescript(db_migrations.SHOP_DELIVERY_ATTEMPTS_SCHEMA)
    memory_db.commit()
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 22)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations)

    assert db_migrations.migrate(memory_db) == 22
    assert memory_db.execute(
        "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
    ).fetchone() == (22,)


def test_v22_rejects_incompatible_preexisting_delivery_attempts_with_rollback(
    memory_db, monkeypatch
):
    from AssetsManager.core import database, db_migrations
    from AssetsManager.core.schema_defs import InvalidSchemaError

    memory_db.executescript(database._SCHEMA)
    all_migrations = db_migrations.MIGRATIONS
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 21)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations[:21])
    assert db_migrations.migrate(memory_db) == 21

    memory_db.execute(
        "CREATE TABLE shop_delivery_attempts (id INTEGER PRIMARY KEY)"
    )
    memory_db.commit()
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 22)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations)

    with pytest.raises(InvalidSchemaError, match="shop_delivery_attempts"):
        db_migrations.migrate(memory_db)

    assert db_migrations.current_version(memory_db) == 21
    assert memory_db.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='shop_delivery_attempts'"
    ).fetchone() == ("shop_delivery_attempts",)
    assert {
        row[1] for row in memory_db.execute("PRAGMA table_info('shop_delivery_attempts')")
    } == {"id"}
