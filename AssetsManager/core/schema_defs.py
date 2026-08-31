"""Static SQL definitions owned by the schema migration layer and repositories."""

import re
import sqlite3
from typing import NotRequired, TypedDict


class ForeignKeyContract(TypedDict):
    columns: tuple[str, ...]
    referenced_table: str
    referenced_columns: tuple[str, ...]
    on_update: str
    on_delete: str


class ColumnContract(TypedDict):
    type: str
    not_null: bool


class SchemaObjectContract(TypedDict):
    columns: tuple[str, ...]
    primary_key: tuple[str, ...]
    unique_constraints: tuple[tuple[str, ...], ...]
    indexes: NotRequired[dict[str, tuple[str, ...]]]
    foreign_keys: NotRequired[tuple[ForeignKeyContract, ...]]
    column_contracts: NotRequired[dict[str, ColumnContract]]
    checks: NotRequired[tuple[str, ...]]


SCHEMA_MIGRATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at REAL NOT NULL
);
"""

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,
    email       TEXT,
    role        TEXT DEFAULT 'viewer',
    created_at  REAL DEFAULT (strftime('%s','now')),
    last_login  REAL,
    is_active   INTEGER DEFAULT 1,
    can_write   INTEGER NOT NULL DEFAULT 0
);
"""

# Historical v6 snapshot: migration v6 first created ``users`` without the
# per-user write flag; v28 adds ``can_write``. The shared ``USERS_SCHEMA`` is
# the current shape, so the v6 checkpoint uses this immutable copy to keep
# v1-v27 on-disk history byte-compatible.
USERS_SCHEMA_V6 = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,
    email       TEXT,
    role        TEXT DEFAULT 'viewer',
    created_at  REAL DEFAULT (strftime('%s','now')),
    last_login  REAL,
    is_active   INTEGER DEFAULT 1
);
"""

INVITE_CODES_SCHEMA = """
CREATE TABLE IF NOT EXISTS invite_codes (
    code        TEXT PRIMARY KEY,
    created_by  TEXT,
    used_by     TEXT,
    created_at  REAL DEFAULT (strftime('%s','now')),
    used_at     REAL,
    is_active   INTEGER DEFAULT 1
);
"""

SHARE_LINKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS share_links (
    id              TEXT PRIMARY KEY,
    paths           TEXT NOT NULL,
    password_hash   TEXT,
    expires_at      REAL,
    max_downloads   INTEGER,
    download_count  INTEGER DEFAULT 0,
    allow_preview   INTEGER DEFAULT 1,
    created_by      TEXT,
    created_at      REAL DEFAULT (strftime('%s','now')),
    is_active       INTEGER DEFAULT 1
);
"""

LIBRARY_FAVORITES_SCHEMA = """
CREATE TABLE IF NOT EXISTS library_favorites (
    owner_key  TEXT NOT NULL,
    file_path  TEXT NOT NULL,
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (owner_key, file_path)
);
CREATE INDEX IF NOT EXISTS idx_library_favorites_path
    ON library_favorites(file_path);
"""

ACTIVITY_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS activity_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT NOT NULL DEFAULT 'guest',
    action    TEXT NOT NULL,
    details   TEXT NOT NULL DEFAULT '',
    ip        TEXT NOT NULL DEFAULT 'unknown',
    timestamp REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_log_timestamp
    ON activity_log(timestamp);
"""

ASSET_INDEX_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS asset_index_state (
    library_root TEXT PRIMARY KEY NOT NULL,
    revision     INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    updated_at   REAL NOT NULL DEFAULT (strftime('%s','now'))
);
"""

RECONCILIATION_TASKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS reconciliation_tasks (
    task_id                    TEXT PRIMARY KEY NOT NULL,
    library_root               TEXT NOT NULL,
    path                       TEXT NOT NULL,
    kind                       TEXT NOT NULL
                               CHECK (kind IN ('asset_index_root_rescan', 'filesystem_projection_repair')),
    reason                     TEXT NOT NULL,
    state                      TEXT NOT NULL
                               CHECK (state IN ('pending', 'running', 'retryable', 'succeeded', 'terminal', 'cancelled')),
    attempts                   INTEGER NOT NULL CHECK (attempts >= 0),
    next_attempt_at_wallclock  REAL NOT NULL,
    operation_ids              TEXT NOT NULL DEFAULT '[]',
    last_error_type            TEXT,
    last_error                 TEXT,
    expected_revision          INTEGER,
    observed_revision          INTEGER,
    created_at                 REAL NOT NULL,
    updated_at                 REAL NOT NULL,
    lease_expires_at_wallclock REAL,
    max_attempts               INTEGER NOT NULL CHECK (max_attempts >= 1),
    payload                    TEXT NOT NULL DEFAULT '{}',
    UNIQUE (library_root, path, kind)
);
CREATE INDEX IF NOT EXISTS idx_reconciliation_tasks_due
    ON reconciliation_tasks(library_root, state, next_attempt_at_wallclock);
"""

RECONCILIATION_QUEUE_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS reconciliation_queue_state (
    library_root TEXT PRIMARY KEY NOT NULL,
    generation   INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0),
    updated_at   REAL NOT NULL
);
"""

IMPORT_MANIFESTS_SCHEMA_V31 = """
CREATE TABLE IF NOT EXISTS import_manifests (
    operation_id TEXT PRIMARY KEY NOT NULL,
    library_root TEXT NOT NULL,
    destination  TEXT NOT NULL,
    state        TEXT NOT NULL CHECK (state IN (
        'prepared', 'running', 'completed', 'degraded', 'cancelled',
        'recovery_pending'
    )),
    payload      TEXT NOT NULL,
    generation   INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0),
    attempts     INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error_type TEXT,
    last_error   TEXT,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_import_manifests_recovery
    ON import_manifests(library_root, state, updated_at);
"""

IMPORT_MANIFESTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS import_manifests (
    operation_id TEXT PRIMARY KEY NOT NULL,
    library_root TEXT NOT NULL,
    destination  TEXT NOT NULL,
    state        TEXT NOT NULL CHECK (state IN (
        'prepared', 'running', 'completed', 'degraded', 'cancelled',
        'recovery_pending'
    )),
    payload      TEXT NOT NULL,
    generation   INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0),
    attempts     INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error_type TEXT,
    last_error   TEXT,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    recovery_claim_token TEXT,
    recovery_lease_expires_at REAL
);
CREATE INDEX IF NOT EXISTS idx_import_manifests_recovery
    ON import_manifests(library_root, state, updated_at);
CREATE INDEX IF NOT EXISTS idx_import_manifests_recovery_lease
    ON import_manifests(library_root, state, recovery_lease_expires_at, updated_at);
"""

# Ordinary/free-download quota state is deliberately separate from the
# Commerce delivery-token quota.  The database is already scoped to one
# library, so the identity/window pair is the natural primary key.
FREE_DOWNLOAD_QUOTA_SCHEMA = """
CREATE TABLE IF NOT EXISTS free_download_quota_windows (
    identity_key      TEXT NOT NULL,
    window_start      INTEGER NOT NULL CHECK (window_start >= 0),
    download_count    INTEGER NOT NULL DEFAULT 0 CHECK (download_count >= 0),
    last_download_at  REAL NOT NULL DEFAULT 0 CHECK (last_download_at >= 0),
    PRIMARY KEY (identity_key, window_start)
);
CREATE INDEX IF NOT EXISTS idx_free_download_quota_window
    ON free_download_quota_windows(window_start);
"""

SHOP_ITEMS_SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    currency    TEXT NOT NULL DEFAULT 'CNY'
                CHECK (length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'),
    cover_path  TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  REAL NOT NULL DEFAULT (strftime('%s','now')),
    updated_at  REAL NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_shop_items_enabled_updated
    ON shop_items(enabled, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_shop_items_enabled_created
    ON shop_items(enabled, created_at DESC, id DESC);
"""

SHOP_ORDERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      INTEGER NOT NULL,
    item_path    TEXT NOT NULL,
    item_title   TEXT NOT NULL,
    buyer_name   TEXT,
    buyer_email  TEXT,
    buyer_owner_type TEXT CHECK (buyer_owner_type IS NULL OR buyer_owner_type IN ('user', 'anonymous')),
    buyer_owner_key TEXT,
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    currency     TEXT NOT NULL
                 CHECK (length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'),
    status       TEXT NOT NULL DEFAULT 'pending' CHECK (length(trim(status)) > 0),
    metadata     TEXT NOT NULL DEFAULT '{}',
    created_at   REAL NOT NULL DEFAULT (strftime('%s','now')),
    updated_at   REAL NOT NULL DEFAULT (strftime('%s','now')),
    FOREIGN KEY (item_id) REFERENCES shop_items(id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_shop_orders_status_created
    ON shop_orders(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shop_orders_buyer_created
    ON shop_orders(buyer_email, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shop_orders_buyer_owner_created
    ON shop_orders(buyer_owner_type, buyer_owner_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shop_orders_item_created
    ON shop_orders(item_id, created_at DESC);
"""

SHOP_ORDER_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_order_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL,
    event_type  TEXT NOT NULL CHECK (length(trim(event_type)) > 0),
    from_status TEXT,
    to_status   TEXT,
    actor_key   TEXT,
    payload     TEXT NOT NULL DEFAULT '{}',
    created_at  REAL NOT NULL DEFAULT (strftime('%s','now')),
    FOREIGN KEY (order_id) REFERENCES shop_orders(id)
        ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shop_order_events_order_created
    ON shop_order_events(order_id, created_at, id);
"""

SHOP_DELIVERY_TOKENS_SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_delivery_tokens (
    token_hash       TEXT PRIMARY KEY NOT NULL CHECK (length(trim(token_hash)) > 0),
    order_id         INTEGER NOT NULL,
    share_id         TEXT,
    delivery_path    TEXT NOT NULL,
    max_downloads    INTEGER NOT NULL CHECK (max_downloads > 0),
    download_count   INTEGER NOT NULL DEFAULT 0
                     CHECK (download_count >= 0 AND download_count <= max_downloads),
    expires_at       REAL,
    revoked_at       REAL,
    created_at       REAL NOT NULL DEFAULT (strftime('%s','now')),
    last_download_at REAL,
    FOREIGN KEY (order_id) REFERENCES shop_orders(id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (share_id) REFERENCES share_links(id)
        ON UPDATE CASCADE ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_shop_delivery_tokens_order_created
    ON shop_delivery_tokens(order_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shop_delivery_tokens_share
    ON shop_delivery_tokens(share_id);
CREATE INDEX IF NOT EXISTS idx_shop_delivery_tokens_availability
    ON shop_delivery_tokens(revoked_at, expires_at);
"""

SHOP_DELIVERY_ATTEMPTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_delivery_attempts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    credential_kind     TEXT NOT NULL CHECK (credential_kind IN ('bearer', 'receipt')),
    credential_hash     TEXT NOT NULL CHECK (length(trim(credential_hash)) = 64),
    request_key_hash    TEXT NOT NULL CHECK (length(trim(request_key_hash)) = 64),
    order_id            INTEGER NOT NULL,
    delivery_token_hash TEXT NOT NULL CHECK (length(trim(delivery_token_hash)) = 64),
    state               TEXT NOT NULL CHECK (state IN ('reserved', 'consumed', 'failed')),
    reserved_at         REAL NOT NULL DEFAULT (strftime('%s','now')),
    consumed_at        REAL,
    failed_at          REAL,
    failure_code       TEXT,
    UNIQUE (credential_kind, credential_hash, request_key_hash),
    FOREIGN KEY (order_id) REFERENCES shop_orders(id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (delivery_token_hash) REFERENCES shop_delivery_tokens(token_hash)
        ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shop_delivery_attempts_order_created
    ON shop_delivery_attempts(order_id, reserved_at DESC);
CREATE INDEX IF NOT EXISTS idx_shop_delivery_attempts_state
    ON shop_delivery_attempts(state, reserved_at);
"""


SHOP_ORDER_RECEIPTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_order_receipts (
    token_hash TEXT PRIMARY KEY NOT NULL CHECK (length(trim(token_hash)) > 0),
    order_id   INTEGER NOT NULL UNIQUE,
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    expires_at REAL NOT NULL CHECK (expires_at > created_at),
    revoked_at REAL CHECK (revoked_at IS NULL OR revoked_at >= created_at),
    FOREIGN KEY (order_id) REFERENCES shop_orders(id)
        ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shop_order_receipts_availability
    ON shop_order_receipts(revoked_at, expires_at);
"""


GALLERY_HOME_SCHEMA = """
CREATE TABLE IF NOT EXISTS gallery_home (
    id         INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
    saved_at   REAL NOT NULL,
    projection TEXT NOT NULL
);
"""


REVOKED_TOKENS_SCHEMA = """
CREATE TABLE IF NOT EXISTS revoked_tokens (
    token_digest TEXT PRIMARY KEY NOT NULL
                 CHECK (length(trim(token_digest)) = 64),
    expires_at   REAL NOT NULL,
    revoked_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_revoked_tokens_expires
    ON revoked_tokens(expires_at);
"""


SHOP_SHARE_CLAIMS_SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_share_claims (
    claim_hash TEXT PRIMARY KEY NOT NULL
               CHECK (length(trim(claim_hash)) = 64),
    order_id   INTEGER NOT NULL,
    expires_at REAL NOT NULL CHECK (expires_at > created_at),
    claimed_at REAL,
    revoked_at REAL,
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    FOREIGN KEY (order_id) REFERENCES shop_orders(id)
        ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shop_share_claims_order_created
    ON shop_share_claims(order_id, created_at DESC);
"""


SHOP_ORDER_RECEIPT_RECOVERIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_order_receipt_recoveries (
    token_hash TEXT PRIMARY KEY NOT NULL CHECK (length(trim(token_hash)) > 0),
    order_id   INTEGER NOT NULL,
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    expires_at REAL NOT NULL CHECK (expires_at > created_at),
    revoked_at REAL CHECK (revoked_at IS NULL OR revoked_at >= created_at),
    FOREIGN KEY (order_id) REFERENCES shop_orders(id)
        ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shop_order_receipt_recoveries_order
    ON shop_order_receipt_recoveries(order_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shop_order_receipt_recoveries_availability
    ON shop_order_receipt_recoveries(revoked_at, expires_at);
"""


SHOP_CARTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_carts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_type TEXT NOT NULL CHECK (owner_type IN ('user', 'anonymous')),
    owner_key TEXT NOT NULL CHECK (length(trim(owner_key)) > 0),
    user_id INTEGER,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'converted', 'expired', 'merged')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    checkout_generation INTEGER NOT NULL DEFAULT 1 CHECK (checkout_generation >= 1),
    expires_at REAL,
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    updated_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    UNIQUE (owner_type, owner_key),
    FOREIGN KEY (user_id) REFERENCES users(id) ON UPDATE CASCADE ON DELETE CASCADE,
    CHECK ((owner_type = 'user' AND user_id IS NOT NULL AND owner_key = CAST(user_id AS TEXT))
        OR (owner_type = 'anonymous' AND user_id IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_shop_carts_user ON shop_carts(user_id) WHERE owner_type = 'user';
CREATE INDEX IF NOT EXISTS idx_shop_carts_status_expiry ON shop_carts(status, expires_at);

CREATE TABLE IF NOT EXISTS shop_cart_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cart_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0 AND quantity <= 999),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    currency TEXT NOT NULL CHECK (length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'),
    item_path TEXT NOT NULL,
    item_title TEXT NOT NULL,
    line_status TEXT NOT NULL DEFAULT 'active' CHECK (line_status IN ('active', 'unavailable', 'removed')),
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    updated_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    UNIQUE (cart_id, item_id),
    FOREIGN KEY (cart_id) REFERENCES shop_carts(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES shop_items(id) ON UPDATE CASCADE ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_shop_cart_items_cart_status ON shop_cart_items(cart_id, line_status, id);

CREATE TABLE IF NOT EXISTS shop_cart_checkouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cart_id INTEGER NOT NULL,
    checkout_generation INTEGER NOT NULL DEFAULT 1 CHECK (checkout_generation >= 1),
    request_fingerprint TEXT,
    request_key TEXT NOT NULL,
    checkout_group_id TEXT NOT NULL UNIQUE,
    order_ids TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    UNIQUE (cart_id, checkout_generation, request_key),
    FOREIGN KEY (cart_id) REFERENCES shop_carts(id) ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shop_cart_checkouts_cart ON shop_cart_checkouts(cart_id, checkout_generation, created_at DESC);
"""

SHOP_WISHLIST_SCHEMAS = (
    ("shop_wishlist_owners", """
CREATE TABLE IF NOT EXISTS shop_wishlist_owners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_kind TEXT NOT NULL CHECK (owner_kind IN ('user', 'anonymous')),
    user_id INTEGER,
    token_hash TEXT,
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    updated_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON UPDATE CASCADE ON DELETE CASCADE,
    CHECK ((owner_kind = 'user' AND user_id IS NOT NULL AND token_hash IS NULL)
        OR (owner_kind = 'anonymous' AND user_id IS NULL AND token_hash IS NOT NULL AND length(trim(token_hash)) = 64))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_shop_wishlist_user ON shop_wishlist_owners(user_id) WHERE owner_kind = 'user';
CREATE UNIQUE INDEX IF NOT EXISTS uq_shop_wishlist_token ON shop_wishlist_owners(token_hash) WHERE owner_kind = 'anonymous';
CREATE INDEX IF NOT EXISTS idx_shop_wishlist_owner_kind ON shop_wishlist_owners(owner_kind, id);
"""),
    ("shop_wishlist_items", """
CREATE TABLE IF NOT EXISTS shop_wishlist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    added_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    UNIQUE (owner_id, item_id),
    FOREIGN KEY (owner_id) REFERENCES shop_wishlist_owners(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES shop_items(id) ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shop_wishlist_items_order ON shop_wishlist_items(owner_id, added_at DESC, item_id DESC);
"""),
)

SELLER_PROFILE_SCHEMA = """
CREATE TABLE IF NOT EXISTS seller_profile (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    store_name     TEXT NOT NULL DEFAULT '',
    contact_email  TEXT NOT NULL DEFAULT '',
    description    TEXT NOT NULL DEFAULT '',
    accept_orders  INTEGER NOT NULL DEFAULT 1 CHECK (accept_orders IN (0, 1)),
    updated_at     REAL NOT NULL DEFAULT (strftime('%s','now'))
);
"""


# v38: user collections. A row is either a manual reference set (query_json
# stays '{}') or a smart collection whose query_json holds the structured
# predicate dict evaluated against the ``assets`` index at read time. The
# smart variant deliberately has no physical membership rows — a collection
# is a query view / reference set, never a file move or copy.
ASSET_COLLECTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS asset_collections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('manual', 'smart')),
    query_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE (name)
);
CREATE TABLE IF NOT EXISTS asset_collection_members (
    collection_id INTEGER NOT NULL
                  REFERENCES asset_collections(id) ON DELETE CASCADE,
    file_path     TEXT NOT NULL,
    added_at      REAL NOT NULL,
    PRIMARY KEY (collection_id, file_path)
);
CREATE INDEX IF NOT EXISTS idx_asset_collection_members_path
    ON asset_collection_members(file_path);
"""

# v39/v40: application-maintained FTS5 full-text index over the asset document
# sources (assets.name + file_tags + file_meta.notes). A self-maintained
# content table was chosen over an external-content table: the document
# spans three tables, so requiring rowid alignment with one content table
# is too fragile. The index owns its rowids and is maintained incrementally
# by the application layer (delete-by-key + re-insert); a full rebuild is
# DELETE-all + re-seed. file_path is the document key, declared UNINDEXED
# so it is never a matchable token — only name/tags/notes text matches.
#
# v40 switched the tokenizer from the default unicode61 to trigram
# (case-insensitive). unicode61 keeps a contiguous CJK run as ONE token, so
# only whole-run queries ever matched; trigram makes every >=3-character
# phrase a substring match. Queries shorter than 3 code points cannot form
# a trigram — those are served by the application-side post-verification
# path (application/search_syntax.py), not by MATCH.
ASSET_SEARCH_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS asset_search USING fts5(
    file_path UNINDEXED,
    name,
    tags,
    notes,
    tokenize='trigram case_sensitive 0'
);
"""

# Seed/rebuild SQL shared by migration v39 and
# application/search_index_service.py reindex_all(). Documents are grouped
# by the UNION of all three source keys, so a path known only to one source
# (e.g. a tagged file that was never scanned) still becomes a document.
# Tags are aggregated in the (file_path, tag) index order; the space
# separator means phrase queries cannot distinguish a multi-word tag from
# two adjacent tags (documented limitation of the space-joined document).
# The NOT IN guard makes re-running the step on an already-seeded table a
# no-op, which keeps the migration idempotent.
ASSET_SEARCH_SEED_SQL = """
INSERT INTO asset_search(file_path, name, tags, notes)
SELECT p.file_path,
       COALESCE(a.name, ''),
       COALESCE(t.tags, ''),
       COALESCE(m.notes, '')
FROM (
    SELECT file_path FROM assets
    UNION
    SELECT file_path FROM file_tags
    UNION
    SELECT file_path FROM file_meta
) AS p
LEFT JOIN (
    SELECT file_path, group_concat(tag, ' ') AS tags
    FROM file_tags GROUP BY file_path
) AS t ON t.file_path = p.file_path
LEFT JOIN assets AS a ON a.file_path = p.file_path
LEFT JOIN file_meta AS m ON m.file_path = p.file_path
WHERE p.file_path NOT IN (SELECT file_path FROM asset_search)
"""

SHOP_STOREFRONT_VIEW_DAYS_SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_storefront_view_days (
    day        TEXT PRIMARY KEY CHECK (length(day) = 10),
    view_count INTEGER NOT NULL DEFAULT 0 CHECK (view_count >= 0),
    updated_at REAL NOT NULL DEFAULT (strftime('%s','now'))
);
"""

SHOP_STOREFRONT_VIEW_VISITORS_SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_storefront_view_visitors (
    day          TEXT NOT NULL CHECK (length(day) = 10),
    visitor_hash TEXT NOT NULL CHECK (length(visitor_hash) = 64),
    created_at   REAL NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (day, visitor_hash)
);
CREATE INDEX IF NOT EXISTS idx_shop_storefront_view_visitors_created
    ON shop_storefront_view_visitors(created_at);
"""

STOREFRONT_ANALYTICS_SCHEMAS: tuple[tuple[str, str], ...] = (
    ("shop_storefront_view_days", SHOP_STOREFRONT_VIEW_DAYS_SCHEMA),
    ("shop_storefront_view_visitors", SHOP_STOREFRONT_VIEW_VISITORS_SCHEMA),
)


COMMERCE_SCHEMAS: tuple[tuple[str, str], ...] = (
    ("shop_items", SHOP_ITEMS_SCHEMA),
    ("shop_orders", SHOP_ORDERS_SCHEMA),
    ("shop_order_events", SHOP_ORDER_EVENTS_SCHEMA),
    ("shop_delivery_tokens", SHOP_DELIVERY_TOKENS_SCHEMA),
)

# Historical DDL snapshots.  These must not be derived from the current schema:
# migration checkpoints are part of the on-disk compatibility contract.
SHOP_ITEMS_SCHEMA_V8 = """
CREATE TABLE IF NOT EXISTS shop_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    currency    TEXT NOT NULL DEFAULT 'CNY'
                CHECK (length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'),
    cover_path  TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  REAL NOT NULL DEFAULT (strftime('%s','now')),
    updated_at  REAL NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_shop_items_enabled_updated
    ON shop_items(enabled, updated_at DESC);
"""

SHOP_ORDERS_SCHEMA_V8 = """
CREATE TABLE IF NOT EXISTS shop_orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      INTEGER NOT NULL,
    item_path    TEXT NOT NULL,
    item_title   TEXT NOT NULL,
    buyer_name   TEXT,
    buyer_email  TEXT,
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    currency     TEXT NOT NULL
                 CHECK (length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'),
    status       TEXT NOT NULL DEFAULT 'pending' CHECK (length(trim(status)) > 0),
    metadata     TEXT NOT NULL DEFAULT '{}',
    created_at   REAL NOT NULL DEFAULT (strftime('%s','now')),
    updated_at   REAL NOT NULL DEFAULT (strftime('%s','now')),
    FOREIGN KEY (item_id) REFERENCES shop_items(id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_shop_orders_status_created
    ON shop_orders(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shop_orders_buyer_created
    ON shop_orders(buyer_email, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shop_orders_item_created
    ON shop_orders(item_id, created_at DESC);
"""

COMMERCE_SCHEMAS_V8: tuple[tuple[str, str], ...] = (
    ("shop_items", SHOP_ITEMS_SCHEMA_V8),
    ("shop_orders", SHOP_ORDERS_SCHEMA_V8),
    ("shop_order_events", SHOP_ORDER_EVENTS_SCHEMA),
    ("shop_delivery_tokens", SHOP_DELIVERY_TOKENS_SCHEMA),
)

SHOP_CARTS_SCHEMA_V16 = """
CREATE TABLE IF NOT EXISTS shop_carts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_type TEXT NOT NULL CHECK (owner_type IN ('user', 'anonymous')),
    owner_key TEXT NOT NULL CHECK (length(trim(owner_key)) > 0),
    user_id INTEGER,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'converted', 'expired', 'merged')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    expires_at REAL,
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    updated_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    UNIQUE (owner_type, owner_key),
    FOREIGN KEY (user_id) REFERENCES users(id) ON UPDATE CASCADE ON DELETE CASCADE,
    CHECK ((owner_type = 'user' AND user_id IS NOT NULL AND owner_key = CAST(user_id AS TEXT))
        OR (owner_type = 'anonymous' AND user_id IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_shop_carts_user ON shop_carts(user_id) WHERE owner_type = 'user';
CREATE INDEX IF NOT EXISTS idx_shop_carts_status_expiry ON shop_carts(status, expires_at);

CREATE TABLE IF NOT EXISTS shop_cart_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cart_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0 AND quantity <= 999),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    currency TEXT NOT NULL CHECK (length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'),
    item_path TEXT NOT NULL,
    item_title TEXT NOT NULL,
    line_status TEXT NOT NULL DEFAULT 'active' CHECK (line_status IN ('active', 'unavailable', 'removed')),
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    updated_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    UNIQUE (cart_id, item_id),
    FOREIGN KEY (cart_id) REFERENCES shop_carts(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES shop_items(id) ON UPDATE CASCADE ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_shop_cart_items_cart_status ON shop_cart_items(cart_id, line_status, id);

CREATE TABLE IF NOT EXISTS shop_cart_checkouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cart_id INTEGER NOT NULL,
    request_key TEXT NOT NULL,
    checkout_group_id TEXT NOT NULL UNIQUE,
    order_ids TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    UNIQUE (cart_id, request_key),
    FOREIGN KEY (cart_id) REFERENCES shop_carts(id) ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shop_cart_checkouts_cart ON shop_cart_checkouts(cart_id, created_at DESC);
"""

# Minimal shape contracts used before migration v6 reuses CREATE IF NOT EXISTS.
# Extra columns/indexes remain compatible; required keys and constraints do not.
AUTH_SHARE_SCHEMA_CONTRACT: dict[str, SchemaObjectContract] = {
    "users": {
        "columns": (
            "id",
            "username",
            "password",
            "email",
            "role",
            "created_at",
            "last_login",
            "is_active",
            "can_write",
        ),
        "primary_key": ("id",),
        "unique_constraints": (("username",),),
    },
    "invite_codes": {
        "columns": (
            "code",
            "created_by",
            "used_by",
            "created_at",
            "used_at",
            "is_active",
        ),
        "primary_key": ("code",),
        "unique_constraints": (),
    },
    "share_links": {
        "columns": (
            "id",
            "paths",
            "password_hash",
            "expires_at",
            "max_downloads",
            "download_count",
            "allow_preview",
            "created_by",
            "created_at",
            "is_active",
        ),
        "primary_key": ("id",),
        "unique_constraints": (),
    },
}

# Small, shared object manifest used by migration and repository compatibility
# paths. Contracts describe required shape only; additive columns remain valid.
SCHEMA_OBJECT_CONTRACT: dict[str, SchemaObjectContract] = {
    "file_meta": {
        "columns": (
            "file_path", "notes", "cached_size", "cached_mtime",
            "cached_file_count", "urls", "cached_file_count_mtime",
            "rating",
        ),
        "primary_key": ("file_path",),
        "unique_constraints": (),
        "column_contracts": {
            # file_path is the PRIMARY KEY without an explicit NOT NULL, so
            # PRAGMA table_info reports notnull=0 for it (rowid-table rule).
            "file_path": {"type": "TEXT", "not_null": False},
            "notes": {"type": "TEXT", "not_null": True},
            "cached_size": {"type": "INTEGER", "not_null": False},
            "cached_mtime": {"type": "REAL", "not_null": False},
            "cached_file_count": {"type": "INTEGER", "not_null": False},
            "urls": {"type": "TEXT", "not_null": True},
            # v35: source-directory mtime stamped alongside cached_file_count;
            # NULL marks a stale/legacy entry that must be recomputed.
            "cached_file_count_mtime": {"type": "REAL", "not_null": False},
            # v37: user rating 0-5; NULL means "unrated" (the default state),
            # so legacy rows keep their meaning without a backfill.
            "rating": {"type": "INTEGER", "not_null": False},
        },
    },
    "thumbnail_cache": {
        "columns": (
            "cache_key", "source_path", "source_mtime", "source_size",
            "baked_size", "cache_size", "created_at", "last_access",
            "source_mtime_ns", "artifact_kind", "render_profile",
        ),
        "primary_key": ("cache_key",),
        "unique_constraints": (),
        "indexes": {
            "idx_thumb_source": ("source_path",),
            "idx_thumb_last_access": ("last_access", "created_at", "cache_key"),
        },
        "column_contracts": {
            "cache_key": {"type": "TEXT", "not_null": False},
            "source_path": {"type": "TEXT", "not_null": True},
            "source_mtime": {"type": "REAL", "not_null": False},
            "source_size": {"type": "INTEGER", "not_null": False},
            "baked_size": {"type": "INTEGER", "not_null": False},
            "cache_size": {"type": "INTEGER", "not_null": False},
            "created_at": {"type": "REAL", "not_null": False},
            "last_access": {"type": "REAL", "not_null": False},
            "source_mtime_ns": {"type": "INTEGER", "not_null": False},
            "artifact_kind": {"type": "TEXT", "not_null": True},
            "render_profile": {"type": "TEXT", "not_null": False},
        },
    },
    "activity_log": {
        "columns": ("id", "username", "action", "details", "ip", "timestamp"),
        "primary_key": ("id",),
        "unique_constraints": (),
        "indexes": {
            "idx_activity_log_timestamp": ("timestamp",),
        },
        "column_contracts": {
            "id": {"type": "INTEGER", "not_null": True},
            "username": {"type": "TEXT", "not_null": True},
            "action": {"type": "TEXT", "not_null": True},
            "details": {"type": "TEXT", "not_null": True},
            "ip": {"type": "TEXT", "not_null": True},
            "timestamp": {"type": "REAL", "not_null": True},
        },
    },
    "asset_index_state": {
        "columns": ("library_root", "revision", "updated_at"),
        "primary_key": ("library_root",),
        "unique_constraints": (),
        "column_contracts": {
            "library_root": {"type": "TEXT", "not_null": True},
            "revision": {"type": "INTEGER", "not_null": True},
            "updated_at": {"type": "REAL", "not_null": True},
        },
        "checks": ("CHECK (revision >= 0)",),
    },
    "reconciliation_tasks": {
        "columns": (
            "task_id", "library_root", "path", "kind", "reason", "state",
            "attempts", "next_attempt_at_wallclock", "operation_ids",
            "last_error_type", "last_error", "expected_revision",
            "observed_revision", "created_at", "updated_at",
            "lease_expires_at_wallclock", "lease_token", "max_attempts",
            "payload",
        ),
        "primary_key": ("task_id",),
        "unique_constraints": (("library_root", "path", "kind"),),
        "indexes": {
            "idx_reconciliation_tasks_due": (
                "library_root", "state", "next_attempt_at_wallclock",
            ),
        },
        "column_contracts": {
            "task_id": {"type": "TEXT", "not_null": True},
            "library_root": {"type": "TEXT", "not_null": True},
            "path": {"type": "TEXT", "not_null": True},
            "kind": {"type": "TEXT", "not_null": True},
            "reason": {"type": "TEXT", "not_null": True},
            "state": {"type": "TEXT", "not_null": True},
            "attempts": {"type": "INTEGER", "not_null": True},
            "next_attempt_at_wallclock": {"type": "REAL", "not_null": True},
            "operation_ids": {"type": "TEXT", "not_null": True},
            "created_at": {"type": "REAL", "not_null": True},
            "updated_at": {"type": "REAL", "not_null": True},
            "lease_token": {"type": "TEXT", "not_null": False},
            "max_attempts": {"type": "INTEGER", "not_null": True},
            "payload": {"type": "TEXT", "not_null": True},
        },
        "checks": (
            "kind IN ('asset_index_root_rescan', 'filesystem_projection_repair')",
            "state IN ('pending', 'running', 'retryable', 'succeeded', 'terminal', 'cancelled')",
            "attempts >= 0",
            "max_attempts >= 1",
        ),
    },
    "reconciliation_queue_state": {
        "columns": ("library_root", "generation", "updated_at"),
        "primary_key": ("library_root",),
        "unique_constraints": (),
        "column_contracts": {
            "library_root": {"type": "TEXT", "not_null": True},
            "generation": {"type": "INTEGER", "not_null": True},
            "updated_at": {"type": "REAL", "not_null": True},
        },
        "checks": ("generation >= 0",),
    },
    "import_manifests": {
        "columns": (
            "operation_id", "library_root", "destination", "state", "payload",
            "generation", "attempts", "last_error_type", "last_error",
            "created_at", "updated_at", "recovery_claim_token",
            "recovery_lease_expires_at",
        ),
        "primary_key": ("operation_id",),
        "unique_constraints": (),
        "indexes": {
            "idx_import_manifests_recovery": ("library_root", "state", "updated_at"),
            "idx_import_manifests_recovery_lease": (
                "library_root", "state", "recovery_lease_expires_at", "updated_at"
            ),
        },
        "column_contracts": {
            "operation_id": {"type": "TEXT", "not_null": True},
            "library_root": {"type": "TEXT", "not_null": True},
            "destination": {"type": "TEXT", "not_null": True},
            "state": {"type": "TEXT", "not_null": True},
            "payload": {"type": "TEXT", "not_null": True},
            "generation": {"type": "INTEGER", "not_null": True},
            "attempts": {"type": "INTEGER", "not_null": True},
            "created_at": {"type": "REAL", "not_null": True},
            "updated_at": {"type": "REAL", "not_null": True},
            "recovery_claim_token": {"type": "TEXT", "not_null": False},
            "recovery_lease_expires_at": {"type": "REAL", "not_null": False},
        },
        "checks": (
            "state IN ('prepared', 'running', 'completed', 'degraded', 'cancelled', 'recovery_pending')",
            "generation >= 0",
            "attempts >= 0",
        ),
    },
    "free_download_quota_windows": {
        "columns": (
            "identity_key", "window_start", "download_count", "last_download_at",
        ),
        "primary_key": ("identity_key", "window_start"),
        "unique_constraints": (),
        "indexes": {
            "idx_free_download_quota_window": ("window_start",),
        },
    },
    "schema_migrations": {
        "columns": ("version", "name", "applied_at"),
        "primary_key": ("version",),
        "unique_constraints": (),
    },
    "library_favorites": {
        "columns": ("owner_key", "file_path", "created_at"),
        "primary_key": ("owner_key", "file_path"),
        "unique_constraints": (),
    },
    "shop_items": {
        "columns": (
            "id", "path", "title", "description", "price_cents", "currency",
            "cover_path", "enabled", "metadata", "created_at", "updated_at",
        ),
        "primary_key": ("id",),
        "unique_constraints": (("path",),),
        "indexes": {"idx_shop_items_enabled_updated": ("enabled", "updated_at")},
        "column_contracts": {
            "id": {"type": "INTEGER", "not_null": False},
            "path": {"type": "TEXT", "not_null": True},
            "title": {"type": "TEXT", "not_null": True},
            "description": {"type": "TEXT", "not_null": True},
            "price_cents": {"type": "INTEGER", "not_null": True},
            "currency": {"type": "TEXT", "not_null": True},
            "cover_path": {"type": "TEXT", "not_null": False},
            "enabled": {"type": "INTEGER", "not_null": True},
            "metadata": {"type": "TEXT", "not_null": True},
            "created_at": {"type": "REAL", "not_null": True},
            "updated_at": {"type": "REAL", "not_null": True},
        },
        "checks": (
            "price_cents >= 0",
            "length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'",
            "enabled IN (0, 1)",
        ),
    },
    "shop_orders": {
        "columns": (
            "id", "item_id", "item_path", "item_title", "buyer_name", "buyer_email",
            "buyer_owner_type", "buyer_owner_key", "amount_cents", "currency", "status", "metadata", "created_at", "updated_at",
        ),
        "primary_key": ("id",),
        "unique_constraints": (),
        "indexes": {
            "idx_shop_orders_status_created": ("status", "created_at"),
            "idx_shop_orders_buyer_created": ("buyer_email", "created_at"),
            "idx_shop_orders_buyer_owner_created": ("buyer_owner_type", "buyer_owner_key", "created_at"),
            "idx_shop_orders_item_created": ("item_id", "created_at"),
        },
        "foreign_keys": ({
            "columns": ("item_id",),
            "referenced_table": "shop_items",
            "referenced_columns": ("id",),
            "on_update": "CASCADE",
            "on_delete": "RESTRICT",
        },),
        "column_contracts": {
            "id": {"type": "INTEGER", "not_null": False},
            "item_id": {"type": "INTEGER", "not_null": True},
            "item_path": {"type": "TEXT", "not_null": True},
            "item_title": {"type": "TEXT", "not_null": True},
            "buyer_name": {"type": "TEXT", "not_null": False},
            "buyer_email": {"type": "TEXT", "not_null": False},
            "buyer_owner_type": {"type": "TEXT", "not_null": False},
            "buyer_owner_key": {"type": "TEXT", "not_null": False},
            "amount_cents": {"type": "INTEGER", "not_null": True},
            "currency": {"type": "TEXT", "not_null": True},
            "status": {"type": "TEXT", "not_null": True},
            "metadata": {"type": "TEXT", "not_null": True},
            "created_at": {"type": "REAL", "not_null": True},
            "updated_at": {"type": "REAL", "not_null": True},
        },
        "checks": (
            "amount_cents >= 0",
            "length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'",
            "length(trim(status)) > 0",
            "buyer_owner_type IS NULL OR buyer_owner_type IN ('user', 'anonymous')",
        ),
    },
    "shop_order_events": {
        "columns": (
            "id", "order_id", "event_type", "from_status", "to_status",
            "actor_key", "payload", "created_at",
        ),
        "primary_key": ("id",),
        "unique_constraints": (),
        "indexes": {
            "idx_shop_order_events_order_created": ("order_id", "created_at", "id")
        },
        "foreign_keys": ({
            "columns": ("order_id",),
            "referenced_table": "shop_orders",
            "referenced_columns": ("id",),
            "on_update": "CASCADE",
            "on_delete": "CASCADE",
        },),
        "column_contracts": {
            "id": {"type": "INTEGER", "not_null": False},
            "order_id": {"type": "INTEGER", "not_null": True},
            "event_type": {"type": "TEXT", "not_null": True},
            "from_status": {"type": "TEXT", "not_null": False},
            "to_status": {"type": "TEXT", "not_null": False},
            "actor_key": {"type": "TEXT", "not_null": False},
            "payload": {"type": "TEXT", "not_null": True},
            "created_at": {"type": "REAL", "not_null": True},
        },
        "checks": ("length(trim(event_type)) > 0",),
    },
    "shop_delivery_tokens": {
        "columns": (
            "token_hash", "order_id", "share_id", "delivery_path", "max_downloads",
            "download_count", "expires_at", "revoked_at", "created_at",
            "last_download_at",
        ),
        "primary_key": ("token_hash",),
        "unique_constraints": (),
        "indexes": {
            "idx_shop_delivery_tokens_order_created": ("order_id", "created_at"),
            "idx_shop_delivery_tokens_share": ("share_id",),
            "idx_shop_delivery_tokens_availability": ("revoked_at", "expires_at"),
        },
        "foreign_keys": (
            {
                "columns": ("order_id",),
                "referenced_table": "shop_orders",
                "referenced_columns": ("id",),
                "on_update": "CASCADE",
                "on_delete": "CASCADE",
            },
            {
                "columns": ("share_id",),
                "referenced_table": "share_links",
                "referenced_columns": ("id",),
                "on_update": "CASCADE",
                "on_delete": "SET NULL",
            },
        ),
        "column_contracts": {
            "token_hash": {"type": "TEXT", "not_null": True},
            "order_id": {"type": "INTEGER", "not_null": True},
            "share_id": {"type": "TEXT", "not_null": False},
            "delivery_path": {"type": "TEXT", "not_null": True},
            "max_downloads": {"type": "INTEGER", "not_null": True},
            "download_count": {"type": "INTEGER", "not_null": True},
            "expires_at": {"type": "REAL", "not_null": False},
            "revoked_at": {"type": "REAL", "not_null": False},
            "created_at": {"type": "REAL", "not_null": True},
            "last_download_at": {"type": "REAL", "not_null": False},
        },
        "checks": (
            "length(trim(token_hash)) > 0",
            "max_downloads > 0",
            "download_count >= 0 AND download_count <= max_downloads",
        ),
    },
    "shop_delivery_attempts": {
        "columns": (
            "id", "credential_kind", "credential_hash", "request_key_hash",
            "order_id", "delivery_token_hash", "state", "reserved_at",
            "consumed_at", "failed_at", "failure_code",
        ),
        "primary_key": ("id",),
        "unique_constraints": (("credential_kind", "credential_hash", "request_key_hash"),),
        "indexes": {
            "idx_shop_delivery_attempts_order_created": ("order_id", "reserved_at"),
            "idx_shop_delivery_attempts_state": ("state", "reserved_at"),
        },
        "foreign_keys": (
            {
                "columns": ("order_id",),
                "referenced_table": "shop_orders",
                "referenced_columns": ("id",),
                "on_update": "CASCADE",
                "on_delete": "CASCADE",
            },
            {
                "columns": ("delivery_token_hash",),
                "referenced_table": "shop_delivery_tokens",
                "referenced_columns": ("token_hash",),
                "on_update": "CASCADE",
                "on_delete": "CASCADE",
            },
        ),
        "column_contracts": {
            "id": {"type": "INTEGER", "not_null": False},
            "credential_kind": {"type": "TEXT", "not_null": True},
            "credential_hash": {"type": "TEXT", "not_null": True},
            "request_key_hash": {"type": "TEXT", "not_null": True},
            "order_id": {"type": "INTEGER", "not_null": True},
            "delivery_token_hash": {"type": "TEXT", "not_null": True},
            "state": {"type": "TEXT", "not_null": True},
            "reserved_at": {"type": "REAL", "not_null": True},
            "consumed_at": {"type": "REAL", "not_null": False},
            "failed_at": {"type": "REAL", "not_null": False},
            "failure_code": {"type": "TEXT", "not_null": False},
        },
        "checks": (
            "credential_kind IN ('bearer', 'receipt')",
            "length(trim(credential_hash)) = 64",
            "length(trim(request_key_hash)) = 64",
            "length(trim(delivery_token_hash)) = 64",
            "state IN ('reserved', 'consumed', 'failed')",
        ),
    },
    "shop_share_claims": {
        "columns": (
            "claim_hash", "order_id", "expires_at", "claimed_at",
            "revoked_at", "created_at",
        ),
        "primary_key": ("claim_hash",),
        "unique_constraints": (),
        "indexes": {
            "idx_shop_share_claims_order_created": ("order_id", "created_at"),
        },
        "foreign_keys": ({
            "columns": ("order_id",),
            "referenced_table": "shop_orders",
            "referenced_columns": ("id",),
            "on_update": "CASCADE",
            "on_delete": "CASCADE",
        },),
        "column_contracts": {
            "claim_hash": {"type": "TEXT", "not_null": True},
            "order_id": {"type": "INTEGER", "not_null": True},
            "expires_at": {"type": "REAL", "not_null": True},
            "claimed_at": {"type": "REAL", "not_null": False},
            "revoked_at": {"type": "REAL", "not_null": False},
            "created_at": {"type": "REAL", "not_null": True},
        },
        "checks": (
            "length(trim(claim_hash)) = 64",
            "expires_at > created_at",
        ),
    },
    "shop_order_receipts": {
        "columns": ("token_hash", "order_id", "created_at", "expires_at", "revoked_at"),
        "primary_key": ("token_hash",),
        "unique_constraints": (("order_id",),),
        "indexes": {
            "idx_shop_order_receipts_availability": ("revoked_at", "expires_at"),
        },
        "foreign_keys": ({
            "columns": ("order_id",),
            "referenced_table": "shop_orders",
            "referenced_columns": ("id",),
            "on_update": "CASCADE",
            "on_delete": "CASCADE",
        },),
        "checks": (
            "length(trim(token_hash)) > 0",
            "expires_at > created_at",
            "revoked_at is null or revoked_at >= created_at",
        ),
    },
    "shop_order_receipt_recoveries": {
        "columns": ("token_hash", "order_id", "created_at", "expires_at", "revoked_at"),
        "primary_key": ("token_hash",),
        "unique_constraints": (),
        "indexes": {
            "idx_shop_order_receipt_recoveries_order": ("order_id", "created_at"),
            "idx_shop_order_receipt_recoveries_availability": ("revoked_at", "expires_at"),
        },
        "foreign_keys": ({
            "columns": ("order_id",),
            "referenced_table": "shop_orders",
            "referenced_columns": ("id",),
            "on_update": "CASCADE",
            "on_delete": "CASCADE",
        },),
        "checks": (
            "length(trim(token_hash)) > 0",
            "expires_at > created_at",
            "revoked_at is null or revoked_at >= created_at",
        ),
    },
    "seller_profile": {
        "columns": ("id", "store_name", "contact_email", "description", "accept_orders", "updated_at"),
        "primary_key": ("id",),
        "unique_constraints": (),
        "column_contracts": {
            "id": {"type": "INTEGER", "not_null": False},
            "store_name": {"type": "TEXT", "not_null": True},
            "contact_email": {"type": "TEXT", "not_null": True},
            "description": {"type": "TEXT", "not_null": True},
            "accept_orders": {"type": "INTEGER", "not_null": True},
            "updated_at": {"type": "REAL", "not_null": True},
        },
        "checks": ("id = 1", "accept_orders IN (0, 1)"),
    },
    "shop_storefront_view_days": {
        "columns": ("day", "view_count", "updated_at"),
        "primary_key": ("day",),
        "unique_constraints": (),
        "column_contracts": {
            "day": {"type": "TEXT", "not_null": False},
            "view_count": {"type": "INTEGER", "not_null": True},
            "updated_at": {"type": "REAL", "not_null": True},
        },
        "checks": ("length(day) = 10", "view_count >= 0"),
    },
    "shop_storefront_view_visitors": {
        "columns": ("day", "visitor_hash", "created_at"),
        "primary_key": ("day", "visitor_hash"),
        "unique_constraints": (),
        "indexes": {
            "idx_shop_storefront_view_visitors_created": ("created_at",),
        },
        "column_contracts": {
            "day": {"type": "TEXT", "not_null": True},
            "visitor_hash": {"type": "TEXT", "not_null": True},
            "created_at": {"type": "REAL", "not_null": True},
        },
        "checks": ("length(day) = 10", "length(visitor_hash) = 64"),
    },
    "shop_carts": {
        "columns": ("id", "owner_type", "owner_key", "user_id", "status", "version", "checkout_generation", "expires_at", "created_at", "updated_at"),
        "primary_key": ("id",),
        "unique_constraints": (("owner_type", "owner_key"), ("user_id",)),
        "indexes": {
            "uq_shop_carts_user": ("user_id",),
            "idx_shop_carts_status_expiry": ("status", "expires_at"),
        },
        "foreign_keys": ({"columns": ("user_id",), "referenced_table": "users", "referenced_columns": ("id",), "on_update": "CASCADE", "on_delete": "CASCADE"},),
        "column_contracts": {"owner_type": {"type": "TEXT", "not_null": True}, "owner_key": {"type": "TEXT", "not_null": True}, "status": {"type": "TEXT", "not_null": True}, "version": {"type": "INTEGER", "not_null": True}, "checkout_generation": {"type": "INTEGER", "not_null": True}, "created_at": {"type": "REAL", "not_null": True}, "updated_at": {"type": "REAL", "not_null": True}},
        "checks": (
            "owner_type IN ('user', 'anonymous')",
            "length(trim(owner_key)) > 0",
            "status IN ('active', 'converted', 'expired', 'merged')",
            "version >= 1",
            "checkout_generation >= 1",
        ),
    },
    "shop_cart_items": {
        "columns": ("id", "cart_id", "item_id", "quantity", "unit_price_cents", "currency", "item_path", "item_title", "line_status", "created_at", "updated_at"),
        "primary_key": ("id",), "unique_constraints": (("cart_id", "item_id"),),
        "indexes": {"idx_shop_cart_items_cart_status": ("cart_id", "line_status", "id")},
        "foreign_keys": ({"columns": ("cart_id",), "referenced_table": "shop_carts", "referenced_columns": ("id",), "on_update": "CASCADE", "on_delete": "CASCADE"}, {"columns": ("item_id",), "referenced_table": "shop_items", "referenced_columns": ("id",), "on_update": "CASCADE", "on_delete": "RESTRICT"}),
        "column_contracts": {"cart_id": {"type": "INTEGER", "not_null": True}, "item_id": {"type": "INTEGER", "not_null": True}, "quantity": {"type": "INTEGER", "not_null": True}, "unit_price_cents": {"type": "INTEGER", "not_null": True}, "currency": {"type": "TEXT", "not_null": True}, "item_path": {"type": "TEXT", "not_null": True}, "item_title": {"type": "TEXT", "not_null": True}, "line_status": {"type": "TEXT", "not_null": True}},
        "checks": (
            "quantity > 0 AND quantity <= 999",
            "unit_price_cents >= 0",
            "length(currency) = 3",
            "currency NOT GLOB '*[^A-Z]*'",
            "line_status IN ('active', 'unavailable', 'removed')",
        ),
    },
    "shop_cart_checkouts": {
        "columns": ("id", "cart_id", "checkout_generation", "request_fingerprint", "request_key", "checkout_group_id", "order_ids", "created_at"),
        "primary_key": ("id",), "unique_constraints": (("cart_id", "checkout_generation", "request_key"), ("checkout_group_id",)),
        "indexes": {"idx_shop_cart_checkouts_cart": ("cart_id", "checkout_generation", "created_at")},
        "foreign_keys": ({"columns": ("cart_id",), "referenced_table": "shop_carts", "referenced_columns": ("id",), "on_update": "CASCADE", "on_delete": "CASCADE"},),
        "column_contracts": {"cart_id": {"type": "INTEGER", "not_null": True}, "checkout_generation": {"type": "INTEGER", "not_null": True}, "request_fingerprint": {"type": "TEXT", "not_null": False}, "request_key": {"type": "TEXT", "not_null": True}, "checkout_group_id": {"type": "TEXT", "not_null": True}, "order_ids": {"type": "TEXT", "not_null": True}, "created_at": {"type": "REAL", "not_null": True}},
        "checks": ("checkout_generation >= 1",),
    },
    "shop_wishlist_owners": {
        "columns": ("id", "owner_kind", "user_id", "token_hash", "created_at", "updated_at"),
        "primary_key": ("id",),
        "unique_constraints": (("user_id",), ("token_hash",)),
        "indexes": {
            "uq_shop_wishlist_user": ("user_id",),
            "uq_shop_wishlist_token": ("token_hash",),
            "idx_shop_wishlist_owner_kind": ("owner_kind", "id"),
        },
        "foreign_keys": ({"columns": ("user_id",), "referenced_table": "users", "referenced_columns": ("id",), "on_update": "CASCADE", "on_delete": "CASCADE"},),
        "checks": (
            "owner_kind IN ('user', 'anonymous')",
            "length(trim(token_hash)) = 64",
        ),
    },
    "shop_wishlist_items": {
        "columns": ("id", "owner_id", "item_id", "added_at"),
        "primary_key": ("id",),
        "unique_constraints": (("owner_id", "item_id"),),
        "indexes": {"idx_shop_wishlist_items_order": ("owner_id", "added_at", "item_id")},
        "column_contracts": {
            "owner_id": {"type": "INTEGER", "not_null": True},
            "item_id": {"type": "INTEGER", "not_null": True},
            "added_at": {"type": "REAL", "not_null": True},
        },
        "foreign_keys": ({"columns": ("owner_id",), "referenced_table": "shop_wishlist_owners", "referenced_columns": ("id",), "on_update": "CASCADE", "on_delete": "CASCADE"}, {"columns": ("item_id",), "referenced_table": "shop_items", "referenced_columns": ("id",), "on_update": "CASCADE", "on_delete": "CASCADE"}),
    },
    # Persisted gallery home projection (one row per library): the
    # full-library walk takes tens of seconds on very large libraries, so
    # the result survives process restarts. FileSystemChanged events delete
    # it; saved_at provides a TTL safety net.
    "gallery_home": {
        "columns": ("id", "saved_at", "projection"),
        "primary_key": ("id",),
        "unique_constraints": (),
        "column_contracts": {
            "id": {"type": "INTEGER", "not_null": True},
            "saved_at": {"type": "REAL", "not_null": True},
            "projection": {"type": "TEXT", "not_null": True},
        },
        "checks": ("CHECK (id = 1)",),
    },
    # Persistent auth-token revocation: rows survive app restarts so a
    # revoked simple-password token (signed with the persisted password
    # hash) cannot resurrect before its TTL expires.
    "revoked_tokens": {
        "columns": ("token_digest", "expires_at", "revoked_at"),
        "primary_key": ("token_digest",),
        "unique_constraints": (),
        "indexes": {"idx_revoked_tokens_expires": ("expires_at",)},
        "column_contracts": {
            "token_digest": {"type": "TEXT", "not_null": True},
            "expires_at": {"type": "REAL", "not_null": True},
            "revoked_at": {"type": "REAL", "not_null": True},
        },
        "checks": ("CHECK (length(trim(token_digest)) = 64)",),
    },
    # v36: physical tag partitions reserved for non-human sources. Both
    # mirror the ``file_tags`` baseline shape (file_path, tag composite PK
    # plus a ``tag`` index) so AI/plugin writers stay isolated from the
    # human-curated catalog in ``file_tags``.
    "ai_asset_tags": {
        "columns": ("file_path", "tag"),
        "primary_key": ("file_path", "tag"),
        "unique_constraints": (),
        "indexes": {"idx_ai_asset_tags_tag": ("tag",)},
    },
    "plugin_derived_fields": {
        "columns": ("file_path", "tag"),
        "primary_key": ("file_path", "tag"),
        "unique_constraints": (),
        "indexes": {"idx_plugin_derived_fields_tag": ("tag",)},
    },
    # v37: regenerable media derivatives ("asset résumé", distinct from the
    # evictable thumbnail_cache). One row per (asset, kind); re-deriving the
    # same kind overwrites the row and its file. ``file_path`` is the absolute
    # library-asset key (file_meta style); ``rel_path`` is the stored file
    # relative to <data_dir>/derivatives with POSIX slashes.
    #
    # v41 adds the lifecycle columns: ``status`` ('ready' | 'failed'),
    # ``error_code`` (why the last generation attempt failed) and
    # ``invalidated_at`` (soft-retire timestamp — a row whose source changed
    # is retired, its payload deleted, but the row kept for observability;
    # readers only serve rows with ``invalidated_at IS NULL`` AND
    # ``status='ready'``). The two-state CHECK deliberately does NOT admit the
    # future async states ('pending'/'generating'): enum evolution goes through
    # the application-layer whitelist first and is appended to the CHECK only
    # by a dedicated migration when the async generator actually ships, so we
    # never pay SQLite's CHECK-rebuild debt speculatively.
    "asset_derivatives": {
        "columns": (
            "file_path", "kind", "rel_path", "params", "source_mtime",
            "created_at", "status", "error_code", "invalidated_at",
        ),
        "primary_key": ("file_path", "kind"),
        "unique_constraints": (),
        "indexes": {"idx_asset_derivatives_kind": ("kind",)},
        "column_contracts": {
            "file_path": {"type": "TEXT", "not_null": True},
            "kind": {"type": "TEXT", "not_null": True},
            "rel_path": {"type": "TEXT", "not_null": True},
            # JSON blob of generation parameters (width/height/colors, ...);
            # NOT NULL with a DEFAULT '{}' so the column is always decodable.
            "params": {"type": "TEXT", "not_null": True},
            "source_mtime": {"type": "REAL", "not_null": False},
            "created_at": {"type": "REAL", "not_null": True},
            "status": {"type": "TEXT", "not_null": True},
            "error_code": {"type": "TEXT", "not_null": False},
            "invalidated_at": {"type": "REAL", "not_null": False},
        },
        "checks": (
            "kind IN ('viewer_image', 'video_poster', 'contact_sheet', "
            "'audio_waveform', 'extracted_palette', 'sequence_manifest')",
            "status IN ('ready', 'failed')",
        ),
    },
    # v42: batch-command plan dedup + execution journal (T8). One row per
    # executed plan fingerprint; only successful executions are remembered
    # (failed runs clear their row to allow retry) and the store FIFO-caps
    # the table, so it cannot grow without bound.
    "command_executions": {
        "columns": (
            "plan_hash", "command_id", "targets_json", "status",
            "executed_at", "result_summary",
        ),
        "primary_key": ("plan_hash",),
        "unique_constraints": (),
        "indexes": {
            "idx_command_executions_executed": ("executed_at",),
        },
        "column_contracts": {
            "plan_hash": {"type": "TEXT", "not_null": True},
            "command_id": {"type": "TEXT", "not_null": True},
            "targets_json": {"type": "TEXT", "not_null": True},
            "status": {"type": "TEXT", "not_null": True},
            "executed_at": {"type": "REAL", "not_null": True},
            "result_summary": {"type": "TEXT", "not_null": True},
        },
        "checks": (
            "status IN ('executing', 'succeeded', 'failed')",
        ),
    },
    # v37: file sequences (frame stacks). The anchor is the "directory +
    # common prefix" pair rather than a representative frame, so re-scans and
    # first-frame renames keep hitting the same sequence row.
    "asset_sequences": {
        "columns": (
            "id", "dir_path", "prefix", "extension", "frame_count", "fps",
            "created_at",
        ),
        "primary_key": ("id",),
        "unique_constraints": (("dir_path", "prefix"),),
        "column_contracts": {
            # INTEGER PRIMARY KEY AUTOINCREMENT reports notnull=0 in
            # PRAGMA table_info (rowid-alias rule), like activity_log.
            "id": {"type": "INTEGER", "not_null": False},
            "dir_path": {"type": "TEXT", "not_null": True},
            "prefix": {"type": "TEXT", "not_null": True},
            "extension": {"type": "TEXT", "not_null": True},
            "frame_count": {"type": "INTEGER", "not_null": True},
            "fps": {"type": "INTEGER", "not_null": False},
            "created_at": {"type": "REAL", "not_null": True},
        },
    },
    # v37: ordered frames belonging to a sequence. ``file_path`` is UNIQUE so
    # a file can only ever belong to one sequence row.
    "asset_sequence_frames": {
        "columns": ("sequence_id", "frame_index", "file_path", "mtime"),
        "primary_key": ("sequence_id", "frame_index"),
        "unique_constraints": (("file_path",),),
        "column_contracts": {
            "sequence_id": {"type": "INTEGER", "not_null": True},
            "frame_index": {"type": "INTEGER", "not_null": True},
            "file_path": {"type": "TEXT", "not_null": True},
            "mtime": {"type": "REAL", "not_null": False},
        },
        "foreign_keys": (
            {
                "columns": ("sequence_id",),
                "referenced_table": "asset_sequences",
                "referenced_columns": ("id",),
                "on_update": "NO ACTION",
                "on_delete": "CASCADE",
            },
        ),
    },
    # v38: user collections. ``kind`` splits the manual reference sets from
    # the smart query views; smart rows keep their structured predicate JSON
    # in ``query_json`` (manual rows keep '{}') so no separate smart table
    # exists. Membership is physical only for manual collections.
    "asset_collections": {
        "columns": ("id", "name", "kind", "query_json", "created_at", "updated_at"),
        "primary_key": ("id",),
        "unique_constraints": (("name",),),
        "column_contracts": {
            # INTEGER PRIMARY KEY AUTOINCREMENT reports notnull=0 in
            # PRAGMA table_info (rowid-alias rule), like activity_log.
            "id": {"type": "INTEGER", "not_null": False},
            "name": {"type": "TEXT", "not_null": True},
            "kind": {"type": "TEXT", "not_null": True},
            "query_json": {"type": "TEXT", "not_null": True},
            "created_at": {"type": "REAL", "not_null": True},
            "updated_at": {"type": "REAL", "not_null": True},
        },
        "checks": ("kind IN ('manual', 'smart')",),
    },
    "asset_collection_members": {
        "columns": ("collection_id", "file_path", "added_at"),
        "primary_key": ("collection_id", "file_path"),
        "unique_constraints": (),
        "indexes": {
            "idx_asset_collection_members_path": ("file_path",),
        },
        "column_contracts": {
            "collection_id": {"type": "INTEGER", "not_null": True},
            "file_path": {"type": "TEXT", "not_null": True},
            "added_at": {"type": "REAL", "not_null": True},
        },
        "foreign_keys": (
            {
                "columns": ("collection_id",),
                "referenced_table": "asset_collections",
                "referenced_columns": ("id",),
                "on_update": "NO ACTION",
                "on_delete": "CASCADE",
            },
        ),
    },
    # v39: FTS5 virtual table. A virtual table reports no primary key, no
    # unique indexes, no declared column types and empty index/FK lists via
    # PRAGMA, so the contract pins only the column set and shapelessness —
    # rebuilding it with a different column list must fail validation.
    "asset_search": {
        "columns": ("file_path", "name", "tags", "notes"),
        "primary_key": (),
        "unique_constraints": (),
    },
    **AUTH_SHARE_SCHEMA_CONTRACT,
}


class InvalidSchemaError(RuntimeError):
    """Raised when an existing table cannot satisfy a schema contract."""

    def __init__(
        self,
        table: str,
        missing_columns: tuple[str, ...] = (),
        expected_primary_key: tuple[str, ...] = (),
        actual_primary_key: tuple[str, ...] = (),
        missing_unique_constraints: tuple[tuple[str, ...], ...] = (),
        missing_indexes: tuple[str, ...] = (),
        invalid_foreign_keys: tuple[ForeignKeyContract, ...] = (),
        invalid_columns: tuple[str, ...] = (),
        missing_checks: tuple[str, ...] = (),
        *,
        missing_table: bool = False,
    ) -> None:
        self.table = table
        self.missing_columns = missing_columns
        self.expected_primary_key = expected_primary_key
        self.actual_primary_key = actual_primary_key
        self.missing_unique_constraints = missing_unique_constraints
        self.missing_indexes = missing_indexes
        self.invalid_foreign_keys = invalid_foreign_keys
        self.invalid_columns = invalid_columns
        self.missing_checks = missing_checks
        self.missing_table = missing_table
        details: list[str] = []
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
        if missing_indexes:
            details.append("missing or invalid indexes " + ", ".join(missing_indexes))
        if invalid_foreign_keys:
            details.append(
                "missing or invalid foreign keys "
                + ", ".join(
                    f"{fk['columns']}->{fk['referenced_table']}{fk['referenced_columns']}"
                    for fk in invalid_foreign_keys
                )
            )
        if invalid_columns:
            details.append("invalid columns " + ", ".join(invalid_columns))
        if missing_checks:
            details.append("missing checks " + ", ".join(missing_checks))
        super().__init__(
            f"Database table {table} has incompatible schema; "
            + "; ".join(details)
        )


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _index_columns(conn: sqlite3.Connection, index_name: str) -> tuple[str, ...]:
    escaped_name = index_name.replace("'", "''")
    rows = conn.execute(f"PRAGMA index_info('{escaped_name}')").fetchall()
    return tuple(row[2] for row in rows)


# Tokenizer for CHECK-constraint comparison: string literals stay whole,
# identifiers/numbers are single tokens, multi-char operators (>=, <=,
# <>, !=, ...) stay attached, remaining punctuation splits per character.
_SQL_TOKEN_RE = re.compile(
    r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\""
    r"|[A-Za-z_][A-Za-z0-9_]*"
    r"|\d+(?:\.\d+)?"
    r"|<=>|<>|<=|>=|!=|<<|>>"
    r"|[()\[\],;.+\-*/%&|^~]"
)


def _sql_contains_tokens(table_sql: str, fragment: str) -> bool:
    """True when *fragment* occurs in *table_sql* as a token sequence.

    Tokens are compared case-insensitively and whitespace is ignored, so an
    equivalent table rebuilt with different spacing still matches — a raw
    substring comparison would falsely flag such a rebuild as missing a
    CHECK constraint.
    """
    haystack = _SQL_TOKEN_RE.findall(table_sql.upper())
    needle = _SQL_TOKEN_RE.findall(fragment.upper())
    if not needle:
        return True
    if len(needle) > len(haystack):
        return False
    window = len(needle)
    return any(
        haystack[i : i + window] == needle
        for i in range(len(haystack) - window + 1)
    )


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
    invalid_columns: list[str] = []
    table_sql_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    column_by_name = {str(row[1]): row for row in table_info}
    for column_name, column_contract in contract.get("column_contracts", {}).items():
        row = column_by_name.get(column_name)
        if row is None:
            continue
        actual_type = str(row[2] or "").upper()
        expected_type = column_contract["type"].upper()
        if actual_type != expected_type:
            invalid_columns.append(
                f"{column_name}.type expected {expected_type}, found {actual_type or '<empty>'}"
            )
        if column_contract["not_null"] and not bool(row[3]):
            invalid_columns.append(f"{column_name}.not_null expected true")
    table_sql = str(table_sql_row[0] if table_sql_row else "")
    missing_checks = tuple(
        check
        for check in contract.get("checks", ())
        if not _sql_contains_tokens(table_sql, check)
    )
    primary_key = tuple(
        row[1] for row in sorted(table_info, key=lambda row: row[5]) if row[5]
    )
    expected_primary_key = contract["primary_key"]

    unique_indexes: list[tuple[str, ...]] = []
    for row in conn.execute(f"PRAGMA index_list('{table}')").fetchall():
        if row[2]:
            unique_indexes.append(_index_columns(conn, row[1]))
    missing_unique_constraints = tuple(
        constraint
        for constraint in contract["unique_constraints"]
        if constraint not in unique_indexes
    )
    table_indexes = {
        str(row[1]): _index_columns(conn, str(row[1]))
        for row in conn.execute(f"PRAGMA index_list('{table}')").fetchall()
    }
    missing_indexes = tuple(
        index_name
        for index_name, expected_columns in contract.get("indexes", {}).items()
        if table_indexes.get(index_name) != expected_columns
    )

    foreign_key_rows = conn.execute(f"PRAGMA foreign_key_list('{table}')").fetchall()
    actual_foreign_keys: set[
        tuple[tuple[str, ...], str, tuple[str, ...], str, str]
    ] = set()
    grouped_foreign_keys: dict[int, list[tuple[object, ...]]] = {}
    for row in foreign_key_rows:
        grouped_foreign_keys.setdefault(int(row[0]), []).append(row)
    for rows in grouped_foreign_keys.values():
        ordered = sorted(rows, key=lambda row: int(str(row[1])))
        actual_foreign_keys.add(
            (
                tuple(str(row[3]) for row in ordered),
                str(ordered[0][2]),
                tuple(str(row[4]) for row in ordered),
                str(ordered[0][5]).upper(),
                str(ordered[0][6]).upper(),
            )
        )
    invalid_foreign_keys = tuple(
        foreign_key
        for foreign_key in contract.get("foreign_keys", ())
        if (
            foreign_key["columns"],
            foreign_key["referenced_table"],
            foreign_key["referenced_columns"],
            foreign_key["on_update"].upper(),
            foreign_key["on_delete"].upper(),
        )
        not in actual_foreign_keys
    )

    if (
        missing_columns
        or primary_key != expected_primary_key
        or missing_unique_constraints
        or missing_indexes
        or invalid_foreign_keys
        or invalid_columns
        or missing_checks
    ):
        raise InvalidSchemaError(
            table,
            missing_columns,
            expected_primary_key,
            primary_key,
            missing_unique_constraints,
            missing_indexes,
            invalid_foreign_keys,
            tuple(invalid_columns),
            missing_checks,
        )


def validate_schema_objects(
    conn: sqlite3.Connection,
    tables: tuple[str, ...],
) -> None:
    """Validate a subset of the shared schema-object manifest."""
    for table in tables:
        validate_schema_object(conn, table, SCHEMA_OBJECT_CONTRACT[table])
