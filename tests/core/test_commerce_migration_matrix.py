from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("target", "migration_name", "tables"),
    [
        (12, "seller_profile", ("seller_profile",)),
        (
            13,
            "storefront_analytics",
            ("shop_storefront_view_days", "shop_storefront_view_visitors"),
        ),
        (
            16,
            "shop_cart_wishlist",
            (
                "shop_carts",
                "shop_cart_items",
                "shop_cart_checkouts",
                "shop_wishlist_owners",
                "shop_wishlist_items",
            ),
        ),
        (18, "shop_order_buyer_owner", ("shop_orders",)),
        (20, "shop_order_receipt_recovery", ("shop_order_receipt_recoveries",)),
        (21, "shop_checkout_fingerprint", ("shop_cart_checkouts",)),
    ],
)
def test_commerce_migration_checkpoint_creates_expected_objects(
    memory_db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    target: int,
    migration_name: str,
    tables: tuple[str, ...],
) -> None:
    from AssetsManager.core import database, db_migrations

    memory_db.executescript(database._SCHEMA)
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", target)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", db_migrations.MIGRATIONS[:target])

    assert db_migrations.migrate(memory_db) == target
    assert memory_db.execute(
        "SELECT name FROM schema_migrations WHERE version=?", (target,)
    ).fetchone() == (migration_name,)

    for table in tables:
        assert memory_db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() == (1,)

    assert memory_db.execute(
        "SELECT COUNT(*) FROM schema_migrations"
    ).fetchone() == (target,)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info('{table}')")}


def test_v8_freezes_pre_owner_and_pre_catalog_index_shape(
    memory_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from AssetsManager.core import db_migrations

    fixture = Path(__file__).parents[1] / "fixtures" / "db" / "v1_schema.sql"
    memory_db.executescript(fixture.read_text(encoding="utf-8"))
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 8)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", db_migrations.MIGRATIONS[:8])

    assert db_migrations.migrate(memory_db) == 8
    assert {"buyer_owner_type", "buyer_owner_key"}.isdisjoint(
        _columns(memory_db, "shop_orders")
    )
    assert memory_db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' "
        "AND name='idx_shop_orders_buyer_owner_created'"
    ).fetchone() is None
    assert memory_db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' "
        "AND name='idx_shop_items_enabled_created'"
    ).fetchone() is None


def test_v16_freezes_pre_generation_checkout_shape(
    memory_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from AssetsManager.core import database, db_migrations

    memory_db.executescript(database._SCHEMA)
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 16)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", db_migrations.MIGRATIONS[:16])

    assert db_migrations.migrate(memory_db) == 16
    assert "checkout_generation" not in _columns(memory_db, "shop_carts")
    assert {"checkout_generation", "request_fingerprint"}.isdisjoint(
        _columns(memory_db, "shop_cart_checkouts")
    )


def test_v19_adds_generation_but_not_v21_fingerprint(
    memory_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from AssetsManager.core import database, db_migrations

    memory_db.executescript(database._SCHEMA)
    all_migrations = db_migrations.MIGRATIONS
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 19)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations[:19])

    assert db_migrations.migrate(memory_db) == 19
    assert "checkout_generation" in _columns(memory_db, "shop_carts")
    assert "checkout_generation" in _columns(memory_db, "shop_cart_checkouts")
    assert "request_fingerprint" not in _columns(memory_db, "shop_cart_checkouts")

    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 21)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations[:21])
    assert db_migrations.migrate(memory_db) == 21
    assert "request_fingerprint" in _columns(memory_db, "shop_cart_checkouts")


def test_v12_seller_profile_has_safe_default_row(
    memory_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from AssetsManager.core import database, db_migrations

    memory_db.executescript(database._SCHEMA)
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 12)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", db_migrations.MIGRATIONS[:12])

    assert db_migrations.migrate(memory_db) == 12
    assert memory_db.execute(
        "SELECT id, store_name, contact_email, description, accept_orders "
        "FROM seller_profile"
    ).fetchone() == (1, "", "", "", 1)


def test_v18_adds_buyer_owner_columns_on_current_schema(
    memory_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from AssetsManager.core import database, db_migrations

    memory_db.executescript(database._SCHEMA)
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 18)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", db_migrations.MIGRATIONS[:18])

    assert db_migrations.migrate(memory_db) == 18
    assert {"buyer_owner_type", "buyer_owner_key"} <= _columns(
        memory_db, "shop_orders"
    )
    assert memory_db.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='index' AND name='idx_shop_orders_buyer_owner_created'"
    ).fetchone() == ("idx_shop_orders_buyer_owner_created",)


def test_v21_adds_request_fingerprint_to_checkout_records(
    memory_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from AssetsManager.core import database, db_migrations

    memory_db.executescript(database._SCHEMA)
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 21)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", db_migrations.MIGRATIONS[:21])

    assert db_migrations.migrate(memory_db) == 21
    assert "request_fingerprint" in _columns(memory_db, "shop_cart_checkouts")


def test_legacy_v8_shop_orders_can_reach_v17_before_owner_upgrade(
    memory_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from AssetsManager.core import database, db_migrations

    memory_db.execute("PRAGMA foreign_keys=ON")
    memory_db.executescript(database._SCHEMA)
    all_migrations = db_migrations.MIGRATIONS
    current_commerce = tuple(db_migrations.COMMERCE_SCHEMAS)
    table, current_schema = next(
        item for item in current_commerce if item[0] == "shop_orders"
    )
    legacy_schema = (
        current_schema.replace(
            "    buyer_owner_type TEXT CHECK (buyer_owner_type IS NULL OR buyer_owner_type IN ('user', 'anonymous')),\n",
            "",
            1,
        )
        .replace("    buyer_owner_key TEXT,\n", "", 1)
        .replace(
            "CREATE INDEX IF NOT EXISTS idx_shop_orders_buyer_owner_created\n"
            "    ON shop_orders(buyer_owner_type, buyer_owner_key, created_at DESC);\n",
            "",
            1,
        )
    )
    legacy_commerce = [
        (name, legacy_schema if name == table else schema)
        for name, schema in current_commerce
    ]

    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 7)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations[:7])
    assert db_migrations.migrate(memory_db) == 7
    for _name, schema in legacy_commerce:
        memory_db.executescript(schema)
    memory_db.commit()

    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 8)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations[:8])
    assert db_migrations.migrate(memory_db) == 8

    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 17)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations[:17])
    assert db_migrations.migrate(memory_db) == 17
    assert "buyer_owner_type" not in {
        row[1] for row in memory_db.execute("PRAGMA table_info('shop_orders')")
    }
    memory_db.execute(
        "INSERT INTO shop_items(path, title, price_cents) VALUES (?, ?, ?)",
        ("legacy.bin", "Legacy", 100),
    )
    item_id = memory_db.execute(
        "SELECT id FROM shop_items WHERE path=?", ("legacy.bin",)
    ).fetchone()[0]
    memory_db.execute(
        "INSERT INTO shop_orders(" 
        "item_id, item_path, item_title, buyer_name, buyer_email, amount_cents, currency) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (item_id, "legacy.bin", "Legacy", "Buyer", "buyer@example.test", 100, "CNY"),
    )
    legacy_order_id = memory_db.execute(
        "SELECT id FROM shop_orders WHERE item_path=?", ("legacy.bin",)
    ).fetchone()[0]
    memory_db.commit()

    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 22)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", all_migrations)
    assert db_migrations.migrate(memory_db) == 22
    assert {"buyer_owner_type", "buyer_owner_key"} <= {
        row[1] for row in memory_db.execute("PRAGMA table_info('shop_orders')")
    }
    assert memory_db.execute(
        "SELECT buyer_owner_type, buyer_owner_key "
        "FROM shop_orders WHERE id=?",
        (legacy_order_id,),
    ).fetchone() == (None, None)


def test_v13_analytics_contract_enforces_checks(
    memory_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from AssetsManager.core import database, db_migrations

    memory_db.executescript(database._SCHEMA)
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 13)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", db_migrations.MIGRATIONS[:13])
    assert db_migrations.migrate(memory_db) == 13

    memory_db.execute(
        "INSERT INTO shop_storefront_view_days(day, view_count) VALUES (?, ?)",
        ("2026-08-08", 0),
    )
    with pytest.raises(sqlite3.IntegrityError):
        memory_db.execute(
            "INSERT INTO shop_storefront_view_days(day, view_count) VALUES (?, ?)",
            ("2026-08-09", -1),
        )
    with pytest.raises(sqlite3.IntegrityError):
        memory_db.execute(
            "INSERT INTO shop_storefront_view_visitors(day, visitor_hash) VALUES (?, ?)",
            ("2026-08-08", "short"),
        )


def test_v20_receipt_recovery_contract_enforces_expiry_and_foreign_key(
    memory_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from AssetsManager.core import database, db_migrations

    memory_db.execute("PRAGMA foreign_keys=ON")
    memory_db.executescript(database._SCHEMA)
    monkeypatch.setattr(db_migrations, "CURRENT_SCHEMA_VERSION", 20)
    monkeypatch.setattr(db_migrations, "MIGRATIONS", db_migrations.MIGRATIONS[:20])
    assert db_migrations.migrate(memory_db) == 20

    memory_db.execute(
        "INSERT INTO shop_items(path, title, price_cents) VALUES (?, ?, ?)",
        ("recovery.bin", "Recovery", 100),
    )
    item_id = memory_db.execute(
        "SELECT id FROM shop_items WHERE path=?", ("recovery.bin",)
    ).fetchone()[0]
    memory_db.execute(
        "INSERT INTO shop_orders(item_id, item_path, item_title, amount_cents, currency) "
        "VALUES (?, ?, ?, ?, ?)",
        (item_id, "recovery.bin", "Recovery", 100, "CNY"),
    )
    order_id = memory_db.execute(
        "SELECT id FROM shop_orders WHERE item_path=?", ("recovery.bin",)
    ).fetchone()[0]
    memory_db.execute(
        "INSERT INTO shop_order_receipt_recoveries "
        "(token_hash, order_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        ("recovery-token", order_id, 100.0, 200.0),
    )
    with pytest.raises(sqlite3.IntegrityError):
        memory_db.execute(
            "INSERT INTO shop_order_receipt_recoveries "
            "(token_hash, order_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            ("expired-token", order_id, 100.0, 50.0),
        )
    with pytest.raises(sqlite3.IntegrityError):
        memory_db.execute(
            "INSERT INTO shop_order_receipt_recoveries "
            "(token_hash, order_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            ("foreign-token", 999999, 100.0, 200.0),
        )
