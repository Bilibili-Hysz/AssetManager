"""SQLite schema migration runner.

The current production schema is created by `core.database._SCHEMA`. This
module records that baseline as version 1 and provides a stable place for
future schema upgrades.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable, cast

from AssetsManager.core.schema_defs import (
    ASSET_INDEX_STATE_SCHEMA,
    RECONCILIATION_QUEUE_STATE_SCHEMA,
    RECONCILIATION_TASKS_SCHEMA,
    COMMERCE_SCHEMAS,
    COMMERCE_SCHEMAS_V8,
    FREE_DOWNLOAD_QUOTA_SCHEMA,
    INVITE_CODES_SCHEMA,
    LIBRARY_FAVORITES_SCHEMA,
    SCHEMA_MIGRATIONS_SCHEMA,
    SCHEMA_OBJECT_CONTRACT,
    SchemaObjectContract,
    SHARE_LINKS_SCHEMA,
    SHOP_ORDER_RECEIPTS_SCHEMA,
    SHOP_ORDER_RECEIPT_RECOVERIES_SCHEMA,
    SHOP_DELIVERY_ATTEMPTS_SCHEMA,
    SHOP_CARTS_SCHEMA_V16,
    SHOP_WISHLIST_SCHEMAS,
    SELLER_PROFILE_SCHEMA,
    STOREFRONT_ANALYTICS_SCHEMAS,
    USERS_SCHEMA,
    InvalidSchemaError,  # noqa: F401 - compatibility export
    validate_schema_object,
    validate_schema_objects,
)


CURRENT_SCHEMA_VERSION = 24
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


def _reconciliation_tasks_contract(*, include_lease_token: bool) -> SchemaObjectContract:
    """Return the schema contract appropriate for a migration boundary."""
    contract = cast(SchemaObjectContract, dict(SCHEMA_OBJECT_CONTRACT["reconciliation_tasks"]))
    if include_lease_token:
        return contract
    contract["columns"] = tuple(
        column for column in contract["columns"] if column != "lease_token"
    )
    contract["column_contracts"] = {
        column: definition
        for column, definition in contract.get("column_contracts", {}).items()
        if column != "lease_token"
    }
    return contract


def _versioned_schema_contract(table: str, version: int) -> SchemaObjectContract:
    """Return the contract that was valid at a recorded migration boundary."""
    contract = cast(SchemaObjectContract, dict(SCHEMA_OBJECT_CONTRACT[table]))

    if table == "reconciliation_tasks" and version < 17:
        return _reconciliation_tasks_contract(include_lease_token=False)

    if table == "shop_orders" and version < 18:
        contract["columns"] = tuple(
            column
            for column in contract["columns"]
            if column not in {"buyer_owner_type", "buyer_owner_key"}
        )
        column_contracts = dict(
            cast(dict[str, Any], contract.get("column_contracts", {}))
        )
        column_contracts.pop("buyer_owner_type", None)
        column_contracts.pop("buyer_owner_key", None)
        contract["column_contracts"] = column_contracts
        contract["indexes"] = {
            name: columns
            for name, columns in contract.get("indexes", {}).items()
            if name != "idx_shop_orders_buyer_owner_created"
        }
        contract["checks"] = tuple(
            check
            for check in contract.get("checks", ())
            if check != (
                "buyer_owner_type IS NULL OR buyer_owner_type IN "
                "('user', 'anonymous')"
            )
        )

    if table == "shop_carts" and version < 19:
        contract["columns"] = tuple(
            column for column in contract["columns"] if column != "checkout_generation"
        )
        column_contracts = dict(
            cast(dict[str, Any], contract.get("column_contracts", {}))
        )
        column_contracts.pop("checkout_generation", None)
        contract["column_contracts"] = column_contracts
        contract["checks"] = tuple(
            check
            for check in contract.get("checks", ())
            if check != "checkout_generation >= 1"
        )

    if table == "shop_cart_checkouts":
        if version < 19:
            contract["columns"] = tuple(
                column
                for column in contract["columns"]
                if column not in {"checkout_generation", "request_fingerprint"}
            )
            column_contracts = dict(
                cast(dict[str, Any], contract.get("column_contracts", {}))
            )
            column_contracts.pop("checkout_generation", None)
            column_contracts.pop("request_fingerprint", None)
            contract["column_contracts"] = column_contracts
            contract["unique_constraints"] = (
                ("cart_id", "request_key"),
                ("checkout_group_id",),
            )
            contract["indexes"] = {
                "idx_shop_cart_checkouts_cart": ("cart_id", "created_at")
            }
            contract["checks"] = ()
        elif version < 21:
            contract["columns"] = tuple(
                column
                for column in contract["columns"]
                if column != "request_fingerprint"
            )
            column_contracts = dict(
                cast(dict[str, Any], contract.get("column_contracts", {}))
            )
            column_contracts.pop("request_fingerprint", None)
            contract["column_contracts"] = column_contracts

    return contract


def _should_defer_index_statement(
    conn: sqlite3.Connection, sql: str
) -> bool:
    """Skip an index that targets columns introduced by a later migration."""
    deferred_indexes = {
        "idx_shop_orders_buyer_owner_created": (
            "shop_orders",
            {"buyer_owner_type", "buyer_owner_key"},
        ),
        "idx_shop_cart_checkouts_cart": (
            "shop_cart_checkouts",
            {"checkout_generation"},
        ),
    }
    for index_name, (table, required_columns) in deferred_indexes.items():
        if index_name not in sql:
            continue
        if (
            index_name == "idx_shop_orders_buyer_owner_created"
            and "buyer_owner_type" not in sql
        ) or (
            index_name == "idx_shop_cart_checkouts_cart"
            and "checkout_generation" not in sql
        ):
            # An older same-named index may still be valid at this boundary.
            continue
        columns = {
            str(row[1]) for row in conn.execute(f"PRAGMA table_info('{table}')")
        }
        return not required_columns <= columns
    return False


def _validate_schema_object_at_version(
    conn: sqlite3.Connection,
    table: str,
    version: int,
    *,
    ignore_indexes: bool = False,
) -> None:
    """Validate current or legacy shape accepted at a migration boundary."""
    current_contract = cast(SchemaObjectContract, dict(SCHEMA_OBJECT_CONTRACT[table]))
    boundary_contract = _versioned_schema_contract(table, version)
    if ignore_indexes:
        current_contract.pop("indexes", None)
        boundary_contract = cast(SchemaObjectContract, dict(boundary_contract))
        boundary_contract.pop("indexes", None)
    try:
        validate_schema_object(conn, table, current_contract)
    except InvalidSchemaError as current_error:
        if boundary_contract == current_contract:
            raise
        try:
            validate_schema_object(conn, table, boundary_contract)
        except InvalidSchemaError:
            raise current_error from None


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


def _add_library_favorites_v7(conn: sqlite3.Connection) -> None:
    """Create principal-scoped favorites inside the library database."""
    if _table_exists(conn, "library_favorites"):
        validate_schema_object(
            conn, "library_favorites", SCHEMA_OBJECT_CONTRACT["library_favorites"]
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_library_favorites_path "
            "ON library_favorites(file_path)"
        )
        return
    # ``executescript`` issues an implicit COMMIT and would destroy the
    # migration runner savepoint.  Execute the central DDL statements one by
    # one so v7 remains atomic inside caller-owned transactions.
    for statement in LIBRARY_FAVORITES_SCHEMA.split(";"):
        if sql := statement.strip():
            conn.execute(sql)


def _add_commerce_schema_v8(conn: sqlite3.Connection) -> None:
    """Create the per-library Commerce aggregate without replacing existing data."""
    tables = tuple(table for table, _schema in COMMERCE_SCHEMAS)

    # Reject colliding/incompatible tables before creating any sibling object.
    # Missing secondary indexes are repairable and are created below.
    for table in tables:
        if not _table_exists(conn, table):
            continue
        _validate_schema_object_at_version(
            conn, table, 8, ignore_indexes=True
        )

    # ``executescript`` implicitly commits. Keep every DDL statement inside the
    # migration runner savepoint so an incompatible object or failed index rolls
    # back both the schema and the v8 history row.
    for _table, schema in COMMERCE_SCHEMAS_V8:
        for statement in schema.split(";"):
            if sql := statement.strip():
                if _should_defer_index_statement(conn, sql):
                    continue
                conn.execute(sql)

    for table in tables:
        _validate_schema_object_at_version(conn, table, 8)


def _add_asset_index_state_v9(conn: sqlite3.Connection) -> None:
    """Add the persistent root revision used by asset-index CAS publishing."""
    for statement in ASSET_INDEX_STATE_SCHEMA.split(";"):
        if sql := statement.strip():
            conn.execute(sql)
    validate_schema_objects(conn, ("asset_index_state",))


def _add_reconciliation_tasks_schema_v14(conn: sqlite3.Connection) -> None:
    """Create the durable, library-scoped reconciliation task queue."""
    table = "reconciliation_tasks"
    legacy_contract = _reconciliation_tasks_contract(include_lease_token=False)
    if _table_exists(conn, table):
        existing_contract = dict(legacy_contract)
        existing_contract.pop("indexes", None)
        validate_schema_object(conn, table, existing_contract)  # type: ignore[arg-type]
    for statement in RECONCILIATION_TASKS_SCHEMA.split(";"):
        if sql := statement.strip():
            conn.execute(sql)
    validate_schema_object(conn, table, legacy_contract)  # type: ignore[arg-type]

def _add_reconciliation_queue_state_schema_v15(conn: sqlite3.Connection) -> None:
    """Add the cross-process snapshot generation used by queue CAS writes."""
    table = "reconciliation_queue_state"
    if _table_exists(conn, table):
        contract = dict(SCHEMA_OBJECT_CONTRACT[table])
        validate_schema_object(conn, table, contract)  # type: ignore[arg-type]
    for statement in RECONCILIATION_QUEUE_STATE_SCHEMA.split(";"):
        if sql := statement.strip():
            conn.execute(sql)
    validate_schema_objects(conn, (table,))


def _add_free_download_quota_schema_v10(conn: sqlite3.Connection) -> None:
    """Create the SQLite-backed ordinary download quota windows."""
    table = "free_download_quota_windows"
    if _table_exists(conn, table):
        contract = dict(SCHEMA_OBJECT_CONTRACT[table])
        contract.pop("indexes", None)
        validate_schema_object(conn, table, contract)  # type: ignore[arg-type]
    for statement in FREE_DOWNLOAD_QUOTA_SCHEMA.split(";"):
        if sql := statement.strip():
            conn.execute(sql)
    validate_schema_objects(conn, (table,))


def _add_shop_order_receipts_v11(conn: sqlite3.Connection) -> None:
    """Add one revocable, expiring buyer receipt per newly-created order."""
    table = "shop_order_receipts"
    if _table_exists(conn, table):
        contract = dict(SCHEMA_OBJECT_CONTRACT[table])
        contract.pop("indexes", None)
        validate_schema_object(conn, table, contract)  # type: ignore[arg-type]
    for statement in SHOP_ORDER_RECEIPTS_SCHEMA.split(";"):
        if sql := statement.strip():
            conn.execute(sql)
    validate_schema_objects(conn, (table,))


def _add_seller_profile_v12(conn: sqlite3.Connection) -> None:
    """Create the one-row per-library seller profile and safe defaults."""
    table = "seller_profile"
    if _table_exists(conn, table):
        contract = dict(SCHEMA_OBJECT_CONTRACT[table])
        contract.pop("indexes", None)
        validate_schema_object(conn, table, contract)  # type: ignore[arg-type]
    for statement in SELLER_PROFILE_SCHEMA.split(";"):
        if sql := statement.strip():
            conn.execute(sql)
    conn.execute(
        "INSERT OR IGNORE INTO seller_profile "
        "(id, store_name, contact_email, description, accept_orders) "
        "VALUES (1, '', '', '', 1)"
    )
    validate_schema_objects(conn, (table,))


def _add_storefront_analytics_v13(conn: sqlite3.Connection) -> None:
    """Create privacy-preserving aggregate storefront analytics tables."""
    tables = tuple(table for table, _schema in STOREFRONT_ANALYTICS_SCHEMAS)
    for table in tables:
        if _table_exists(conn, table):
            contract = dict(SCHEMA_OBJECT_CONTRACT[table])
            contract.pop("indexes", None)
            validate_schema_object(conn, table, contract)  # type: ignore[arg-type]
    for _table, schema in STOREFRONT_ANALYTICS_SCHEMAS:
        for statement in schema.split(";"):
            if sql := statement.strip():
                conn.execute(sql)
    validate_schema_objects(conn, tables)


def _add_shop_cart_wishlist_schema_v16(conn: sqlite3.Connection) -> None:
    """Create additive buyer cart and wishlist ownership tables.

    v19 adds checkout-generation columns to the two cart tables. Keep this
    migration able to open a database whose v16 objects were created by the
    previous contract; the v19 migration performs the actual table upgrade.
    """
    schemas = (("shop_carts", SHOP_CARTS_SCHEMA_V16), *SHOP_WISHLIST_SCHEMAS)
    tables = tuple(name for name, _schema in schemas)

    for table in tables:
        if _table_exists(conn, table):
            _validate_schema_object_at_version(
                conn, table, 16, ignore_indexes=True
            )
    for _table, schema in schemas:
        for statement in schema.split(";"):
            if sql := statement.strip():
                if _should_defer_index_statement(conn, sql):
                    continue
                conn.execute(sql)
    for table in tables:
        _validate_schema_object_at_version(conn, table, 16)



def _add_shop_checkout_generation_schema_v19(conn: sqlite3.Connection) -> None:
    """Scope checkout idempotency keys to a cart lifecycle generation."""
    carts = "shop_carts"
    cart_columns = {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info('{carts}')")
    }
    if "checkout_generation" not in cart_columns:
        conn.execute(
            "ALTER TABLE shop_carts ADD COLUMN checkout_generation INTEGER "
            "NOT NULL DEFAULT 1 CHECK (checkout_generation >= 1)"
        )

    checkouts = "shop_cart_checkouts"
    checkout_columns = {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info('{checkouts}')")
    }
    if "checkout_generation" not in checkout_columns:
        legacy = "shop_cart_checkouts_v18"
        conn.execute(f"ALTER TABLE {checkouts} RENAME TO {legacy}")
        conn.execute(
            """
            CREATE TABLE shop_cart_checkouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cart_id INTEGER NOT NULL,
                checkout_generation INTEGER NOT NULL DEFAULT 1
                    CHECK (checkout_generation >= 1),
                request_key TEXT NOT NULL,
                checkout_group_id TEXT NOT NULL UNIQUE,
                order_ids TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
                UNIQUE (cart_id, checkout_generation, request_key),
                FOREIGN KEY (cart_id) REFERENCES shop_carts(id)
                    ON UPDATE CASCADE ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            INSERT INTO shop_cart_checkouts
                (id, cart_id, checkout_generation, request_key,
                 checkout_group_id, order_ids, created_at)
            SELECT id, cart_id, 1, request_key,
                   checkout_group_id, order_ids, created_at
            FROM shop_cart_checkouts_v18
            """
        )
        conn.execute(f"DROP TABLE {legacy}")

    conn.execute("DROP INDEX IF EXISTS idx_shop_cart_checkouts_cart")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_shop_cart_checkouts_cart "
        "ON shop_cart_checkouts(cart_id, checkout_generation, created_at DESC)"
    )
    for table in (carts, checkouts):
        _validate_schema_object_at_version(conn, table, 19)


def _add_shop_checkout_fingerprint_schema_v21(conn: sqlite3.Connection) -> None:
    """Add optional request fingerprints for safe same-generation replays."""
    table = "shop_cart_checkouts"
    columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info('{table}')")}
    if "request_fingerprint" not in columns:
        conn.execute(
            "ALTER TABLE shop_cart_checkouts ADD COLUMN request_fingerprint TEXT"
        )
    validate_schema_object(conn, table, SCHEMA_OBJECT_CONTRACT[table])


def _add_shop_delivery_attempts_schema_v22(conn: sqlite3.Connection) -> None:
    """Create durable request-level state for guarded delivery downloads."""
    table = "shop_delivery_attempts"
    if _table_exists(conn, table):
        contract = dict(SCHEMA_OBJECT_CONTRACT[table])
        contract.pop("indexes", None)
        validate_schema_object(conn, table, contract)  # type: ignore[arg-type]
    for statement in SHOP_DELIVERY_ATTEMPTS_SCHEMA.split(";"):
        if sql := statement.strip():
            conn.execute(sql)
    validate_schema_objects(conn, (table,))


def _add_shop_catalog_index_schema_v23(conn: sqlite3.Connection) -> None:
    """Add the stable public Catalog ordering index to existing Commerce stores."""
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_shop_items_enabled_created "
        "ON shop_items(enabled, created_at DESC, id DESC)"
    )
    validate_schema_object(conn, "shop_items", SCHEMA_OBJECT_CONTRACT["shop_items"])


def _add_asset_dir_mtime_schema_v24(conn: sqlite3.Connection) -> None:
    """Snapshot directory mtimes for reliable asset-index fast-path checks.

    ``asset_dir_snapshot`` records each scanned directory's own mtime
    (a directory mtime is always >= its newest child mtime, so an equality
    check is a reliable "unchanged" signal).  It is a separate table so the
    ``assets`` entry count / remove / query semantics stay file-only.  The
    thumbnail ordering index serves the /api/home baked-thumbnail scan
    (ORDER BY source_mtime DESC), which previously required a full-table
    temporary sort on every request.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS asset_dir_snapshot ("
        "dir_path TEXT PRIMARY KEY, "
        "library_root TEXT NOT NULL, "
        "mtime REAL NOT NULL, "
        "updated_at REAL DEFAULT (strftime('%s','now'))"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_thumb_cache_mtime "
        "ON thumbnail_cache(source_mtime DESC, cache_key)"
    )


def _add_shop_order_receipt_recovery_schema_v20(conn: sqlite3.Connection) -> None:
    """Add non-destructive owner-scoped receipt credentials for recovery."""
    table = "shop_order_receipt_recoveries"
    for statement in SHOP_ORDER_RECEIPT_RECOVERIES_SCHEMA.split(";"):
        if sql := statement.strip():
            conn.execute(sql)
    validate_schema_object(conn, table, SCHEMA_OBJECT_CONTRACT[table])


def _add_shop_order_buyer_owner_schema_v18(conn: sqlite3.Connection) -> None:
    """Bind newly-created orders to the buyer principal without backfilling legacy rows."""
    table = "shop_orders"
    columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info('{table}')")}
    if "buyer_owner_type" not in columns:
        conn.execute(
            "ALTER TABLE shop_orders ADD COLUMN buyer_owner_type TEXT "
            "CHECK (buyer_owner_type IS NULL OR buyer_owner_type IN ('user', 'anonymous'))"
        )
    if "buyer_owner_key" not in columns:
        conn.execute("ALTER TABLE shop_orders ADD COLUMN buyer_owner_key TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_shop_orders_buyer_owner_created "
        "ON shop_orders(buyer_owner_type, buyer_owner_key, created_at DESC)"
    )
    validate_schema_object(conn, table, SCHEMA_OBJECT_CONTRACT[table])

def _add_reconciliation_lease_token_schema_v17(conn: sqlite3.Connection) -> None:
    """Add the nullable durable lease identity used by the next queue phase."""
    table = "reconciliation_tasks"
    columns = {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info('{table}')")
    }
    if "lease_token" not in columns:
        conn.execute(
            "ALTER TABLE reconciliation_tasks ADD COLUMN lease_token TEXT"
        )
    validate_schema_objects(conn, (table,))

MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "baseline_current_schema", _baseline_v1),
    Migration(2, "add_assets_index", _add_assets_index_v2),
    Migration(3, "add_tag_metadata", _add_tag_metadata_v3),
    Migration(4, "add_plugin_metadata", _add_plugin_metadata_v4),
    Migration(5, "directory_cache", _add_directory_cache_v5),
    Migration(6, "auth_share_schema", _add_auth_share_schema_v6),
    Migration(7, "library_favorites", _add_library_favorites_v7),
    Migration(8, "commerce_schema", _add_commerce_schema_v8),
    Migration(9, "asset_index_state", _add_asset_index_state_v9),
    Migration(10, "free_download_quota", _add_free_download_quota_schema_v10),
    Migration(11, "shop_order_receipts", _add_shop_order_receipts_v11),
    Migration(12, "seller_profile", _add_seller_profile_v12),
    Migration(13, "storefront_analytics", _add_storefront_analytics_v13),
    Migration(14, "reconciliation_tasks", _add_reconciliation_tasks_schema_v14),
    Migration(15, "reconciliation_queue_state", _add_reconciliation_queue_state_schema_v15),
    Migration(16, "shop_cart_wishlist", _add_shop_cart_wishlist_schema_v16),
    Migration(17, "reconciliation_lease_token", _add_reconciliation_lease_token_schema_v17),
    Migration(18, "shop_order_buyer_owner", _add_shop_order_buyer_owner_schema_v18),
    Migration(19, "shop_checkout_generation", _add_shop_checkout_generation_schema_v19),
    Migration(20, "shop_order_receipt_recovery", _add_shop_order_receipt_recovery_schema_v20),
    Migration(21, "shop_checkout_fingerprint", _add_shop_checkout_fingerprint_schema_v21),
    Migration(22, "shop_delivery_attempts", _add_shop_delivery_attempts_schema_v22),
    Migration(23, "shop_catalog_ordering_index", _add_shop_catalog_index_schema_v23),
    Migration(24, "asset_dir_mtime_snapshot", _add_asset_dir_mtime_schema_v24),
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
            if migration.version <= version or migration.version > CURRENT_SCHEMA_VERSION:
                continue
            migration.apply(conn)
            _record(conn, migration)
            version = migration.version
        required_objects = ("schema_migrations",)
        if version >= 6:
            required_objects += ("users", "invite_codes", "share_links")
        if version >= 7:
            required_objects += ("library_favorites",)
        if version >= 8:
            required_objects += tuple(table for table, _schema in COMMERCE_SCHEMAS)
        if version >= 9:
            required_objects += ("asset_index_state",)
        if version >= 10:
            required_objects += ("free_download_quota_windows",)
        if version >= 11:
            required_objects += ("shop_order_receipts",)
        if version >= 20:
            required_objects += ("shop_order_receipt_recoveries",)
        if version >= 22:
            required_objects += ("shop_delivery_attempts",)
        if version >= 12:
            required_objects += ("seller_profile",)
        if version >= 13:
            required_objects += tuple(table for table, _schema in STOREFRONT_ANALYTICS_SCHEMAS)
        if version >= 14:
            required_objects += ("reconciliation_tasks",)
        if version >= 15:
            required_objects += ("reconciliation_queue_state",)
        if version >= 16:
            required_objects += ("shop_carts", "shop_cart_items", "shop_cart_checkouts", "shop_wishlist_owners", "shop_wishlist_items")
        if version < 17 and "reconciliation_tasks" in required_objects:
            required_objects = tuple(
                table for table in required_objects if table != "reconciliation_tasks"
            )
        for table in required_objects:
            _validate_schema_object_at_version(conn, table, version)
        if 14 <= version < 17:
            validate_schema_object(
                conn,
                "reconciliation_tasks",
                _reconciliation_tasks_contract(include_lease_token=False),
            )  # type: ignore[arg-type]
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
