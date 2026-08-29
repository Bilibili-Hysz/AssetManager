# Database Migrations

> 状态:**LIVING** · updated: 2026-08-30(v36 新增;逐版本已与 `db_migrations.py` MIGRATIONS 一致)。

AssetManager Next uses versioned SQLite migrations for per-library databases. **当前版本：`CURRENT_SCHEMA_VERSION = 36`**，以 [`AssetsManager/core/db_migrations.py`](../AssetsManager/core/db_migrations.py) 为执行事实源。历史运行结果和批次证据见 [`docs/full-review/`](full-review/)。

## Current State

### Version 1 — Baseline

Records the existing schema created by `AssetsManager.core.database._SCHEMA`:

- `file_tags(file_path, tag)`
- `file_meta(file_path, notes, cached_size, cached_mtime, cached_file_count, urls)`
- `thumbnail_cache(cache_key, source_path, source_mtime, source_size, baked_size, cache_size, created_at, last_access)`
- `library_stats(library_path, total_size, total_files, total_projects, updated_at)`
- `schema_migrations(version, name, applied_at)`

### Version 2 — Assets Index

Adds `assets` table for fast file lookup and project listing:

```sql
CREATE TABLE assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    extension TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'file',
    size INTEGER DEFAULT 0,
    mtime REAL DEFAULT 0,
    parent_path TEXT NOT NULL,
    library_root TEXT NOT NULL,
    created_at REAL DEFAULT (strftime('%s','now')),
    updated_at REAL DEFAULT (strftime('%s','now'))
);
CREATE INDEX idx_assets_parent ON assets(parent_path);
CREATE INDEX idx_assets_library ON assets(library_root);
CREATE INDEX idx_assets_name ON assets(name);
CREATE INDEX idx_assets_ext ON assets(extension);
```

The table is populated lazily by application services, not by the migration.

### Version 3 — Tag Metadata

Adds `tag_metadata` table for tag colors, icons, and categories:

```sql
CREATE TABLE tag_metadata (
    tag TEXT PRIMARY KEY,
    color TEXT DEFAULT '',
    icon TEXT DEFAULT '',
    category TEXT DEFAULT '',
    created_at REAL DEFAULT (strftime('%s','now'))
);
CREATE INDEX idx_tag_metadata_category ON tag_metadata(category);
```

Used by `TagRepository.get_tag_metadata()` and `TagService.get_tags_with_metadata()`.

### Version 4 — Plugin Metadata

Adds `plugin_metadata` for persisted file metadata parsed by enabled plugins:

```sql
CREATE TABLE plugin_metadata (
    file_path TEXT NOT NULL,
    plugin_id TEXT NOT NULL,
    field_key TEXT NOT NULL,
    field_value TEXT NOT NULL DEFAULT '',
    updated_at REAL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (file_path, plugin_id, field_key)
);
CREATE INDEX idx_plugin_metadata_file ON plugin_metadata(file_path);
CREATE INDEX idx_plugin_metadata_plugin ON plugin_metadata(plugin_id);
```

Used by `PluginMetadataRepository` and `InfoController` so plugin-parsed fields can remain visible after parsing.

### Version 5 — Directory Cache

Adds `directory_cache` for cached directory scan results:

```sql
CREATE TABLE directory_cache (
    dir_path TEXT PRIMARY KEY,
    item_count INTEGER NOT NULL DEFAULT 0,
    preview_path TEXT,
    mtime REAL NOT NULL,
    scanned_at REAL NOT NULL DEFAULT (strftime('%s','now'))
);
```

`DirectoryCache` reads and updates this table through the owning library connection. Cache entries are invalidated when the recorded directory mtime no longer matches; the migration only creates the table and does not backfill scan results.

### Version 6 — Auth and Share Schema

Creates the LAN auth/share tables when they are absent: `users`, `invite_codes`, and `share_links`. The v6 migration owns the canonical schema and records it in the main migration history.

For an existing table, v6 performs baseline shape validation before using `CREATE TABLE IF NOT EXISTS`: required columns, primary-key columns, and required unique constraints must match the contract in `AssetsManager/core/schema_defs.py`. Extra columns or indexes remain compatible; an incompatible existing table fails closed with `InvalidSchemaError` rather than being altered or silently accepted.

### Version 7 — Library Favorites

Adds `library_favorites(owner_key, file_path, created_at)` with composite PK `(owner_key, file_path)` and a path index. 逐语句执行（避免 executescript 隐式提交）。

### Version 8 — Commerce Schema

Adds the commerce baseline: `shop_items`、`shop_orders`、`shop_order_events`、`shop_delivery_tokens`（使用冻结的历史快照 `COMMERCE_SCHEMAS_V8`——不得从当前 schema 推导）。`idx_shop_orders_buyer_owner_created` 延迟到 v18 创建。

### Version 9 — Asset Index State

Adds `asset_index_state(library_root PK, revision INTEGER CHECK >= 0, updated_at)` —— revision CAS 发布的权威计数器（配合 `AssetIndexRepository._advance_revision(expected)`）。

### Version 10 — Free Download Quota

Adds `free_download_quota_windows(identity_key, window_start, download_count, last_download_at)`，复合 PK `(identity_key, window_start)` + window 索引——窗口制配额（匿名 cookie 身份）。

### Version 11 — Shop Order Receipts

Adds `shop_order_receipts(token_hash PK, order_id UNIQUE, created_at, expires_at > created_at, revoked_at)` —— 结账回执（HttpOnly cookie，30 天）。

### Version 12 — Seller Profile

Adds 单行 `seller_profile(id = 1 CHECK (id = 1), store_name, contact_email, description, accept_orders, updated_at)` + 默认行。

### Version 13 — Storefront Analytics

Adds `shop_storefront_view_days(day PK, view_count, updated_at)` + `shop_storefront_view_visitors(day, visitor_hash)` 复合 PK——隐私聚合（仅存访客哈希）。

### Version 14 — Reconciliation Tasks

Adds `reconciliation_tasks`（task_id PK、kind/state CHECK、UNIQUE(library_root, path, kind)、due 索引）——跨进程持久化重扫任务队列（v14 契约校验：无 lease_token 的旧表）。

### Version 15 — Reconciliation Queue State

Adds `reconciliation_queue_state(library_root PK, generation CHECK >= 0, updated_at)` —— 队列代数 CAS。

### Version 16 — Shop Cart & Wishlist

Adds `shop_carts`（v16 版：无 checkout_generation）、`shop_cart_items`、`shop_cart_checkouts`（v16 版：UNIQUE(cart_id, request_key)）、`shop_wishlist_owners`、`shop_wishlist_items`。

### Version 17 — Reconciliation Lease Token

`ALTER TABLE reconciliation_tasks ADD COLUMN lease_token TEXT`（可空）——worker 租约令牌。

### Version 18 — Shop Order Buyer Owner

`ALTER TABLE shop_orders ADD buyer_owner_type TEXT CHECK(...IN ('user','anonymous'))` + `ADD buyer_owner_key TEXT` + 创建 `idx_shop_orders_buyer_owner_created`（v8 延迟索引此时落地）。

### Version 19 — Shop Checkout Generation

`ALTER shop_carts ADD checkout_generation INTEGER NOT NULL DEFAULT 1 CHECK (>=1)`；`shop_cart_checkouts` 重建（RENAME v18 → CREATE 新表带 checkout_generation + `UNIQUE(cart_id, checkout_generation, request_key)` → INSERT SELECT → DROP）。

### Version 20 — Shop Order Receipt Recovery

Adds `shop_order_receipt_recoveries(token_hash PK, order_id, created_at, expires_at, revoked_at)` —— 回执丢失恢复。

### Version 21 — Shop Checkout Fingerprint

`ALTER TABLE shop_cart_checkouts ADD COLUMN request_fingerprint TEXT`（可空）——结账幂等指纹。

### Version 22 — Shop Delivery Attempts

Adds `shop_delivery_attempts`（credential_kind/hash 64、request_key_hash 64、state IN (reserved/consumed/failed)、UNIQUE(credential_kind, credential_hash, request_key_hash)、FK 到 orders 与 delivery_tokens）——投递请求级幂等。

### Version 23 — Shop Catalog Ordering Index

`CREATE INDEX idx_shop_items_enabled_created ON shop_items(enabled, created_at DESC, id DESC)` + shop_items 全契约校验。

### Version 24 — Asset Directory Mtime Snapshot

Adds the asset-directory mtime snapshot fields used by bounded incremental index refreshes and validates their schema contract.

### Version 25 — Shop Share Claims

Adds the durable shop-share claim table and indexes used to enforce single-use claim ownership.

### Version 26 — Gallery Home Projection

Adds the gallery home projection tables and indexes used by the LAN gallery home contract.

### Version 27 — Revoked Tokens

Adds the revoked-token persistence used to invalidate previously issued LAN credentials.

### Version 28 — User Write Capability

Adds the persisted user write-capability field used by the LAN authorization boundary.

### Version 29 — Activity Log

Adds the activity log table and indexes used by the activity projection.

### Version 30 — Filesystem Projection Repair

Adds the durable reconciliation payload/state needed to repair filesystem projections after move, delete, and restore failures.

### Version 31 — Import Manifests

Adds the library-scoped `import_manifests` table and recovery index used to persist import intent before filesystem mutation and enqueue restart-time root rescans. The payload and generation fields are validated by `ImportManifestStore`; see [`C6-C10 convergence evidence`](full-review/c6-c10-convergence-2026-08-21.md).

### Version 32 — Thumbnail Cache Lifecycle

Adds precise thumbnail source timing and artifact-kind metadata used by cache lifecycle validation.

### Version 33 — Thumbnail Render Profile

Adds nullable render-profile metadata for non-destructive profile-aware thumbnail cache writes.

### Version 34 — Import Manifest Recovery Lease

Adds nullable `recovery_claim_token` and `recovery_lease_expires_at` columns plus a recovery lease index. Recovery workers atomically claim unresolved manifests before enqueueing root rescans; completion and failure updates require the claim token and generation/state CAS. Existing v31-v33 rows remain valid and are upgraded additively without replaying filesystem copies.

### Version 35 — File Count Mtime Snapshot

`ALTER TABLE file_meta ADD COLUMN cached_file_count_mtime REAL`（可空）。文件计数缓存此前无新鲜度信号（缓存永不失效），v35 起写入计数时同时记录来源目录的 `st_mtime`；读取端仅在存储 mtime 与实时目录 mtime 一致时信任缓存，不一致或为 `NULL` 一律视为 miss 重算——与 `cached_size`/`cached_mtime` 的双保险模式对齐。v35 前的旧行保留 `NULL`，首次读取即重算并补写时间戳。

### Version 36 — Tag Source Partition

新建 `ai_asset_tags` 与 `plugin_derived_fields` 两张空表，形状镜像 `file_tags`（`(file_path, tag)` 复合主键 + 各自的 `tag` 索引 `idx_ai_asset_tags_tag` / `idx_plugin_derived_fields_tag`），为将来 AI/插件标签提供物理隔离。现有 `file_tags` 语义收敛为"人工标签"目录；本迁移零数据搬移、零行为变化（`TagRepository`/`TagService` 新增 `source` 参数，默认 `"human"` 走 `file_tags`）。`CREATE TABLE IF NOT EXISTS` 幂等；v35 及更早库中的既有标签行原样保留。

## Migration Runner Boundaries

- Before applying pending versions, the runner validates the required v1 core baseline (`file_tags`, `file_meta`, `thumbnail_cache`, and `library_stats`), including required columns, primary keys, and indexes. A missing or incompatible baseline raises `IncompleteSchemaError`; the runner does not reconstruct an incomplete legacy database.
- `migrate()` runs under a named SQLite savepoint (`SAVEPOINT migration_runner`). If the caller already has an outer transaction, the savepoint is released without committing that outer transaction; the caller retains commit/rollback ownership. On a standalone connection, successful migration preserves the historical behavior and commits. Any failure rolls back to and releases the savepoint.
- **历史校验**：`_validate_history` 校验非整数/重复/不连续/名称不匹配 → `MigrationHistoryError`；未来版本 → `UnsupportedSchemaVersion`（先于名称校验）。
- **版本化契约回溯**：每版应用后按版本累积 `required_objects`，用 `_versioned_schema_contract` 回溯该版本边界的合法形状（如 v<17 的 reconciliation_tasks 无 lease_token、v<18 的 shop_orders 无 buyer_owner、v16 的 shop_carts 无 checkout_generation、v16 的 checkouts 无 checkout_generation/fingerprint、v<35 的 file_meta 无 cached_file_count_mtime），逐对象 `_validate_schema_object_at_version` 校验。
- **延迟索引**：`_should_defer_index_statement` 跳过引用未来列的索引语句（如 v8 的 idx_shop_orders_buyer_owner_created 延迟到 v18）。
- `AuthRepository.init_tables()` and `ShareRepository.init_table()` remain compatibility ensures for raw/legacy repository connections and tests. They are idempotent guards at that boundary, not an alternate migration history; the canonical bootstrap path is governed by migration v6, and incompatible pre-existing tables are rejected by its shape validation.

## Rules

- Every schema change must add a migration in `AssetsManager/core/db_migrations.py` or the future migrations package.
- Migration versions must be strictly increasing.
- Migrations must be idempotent where practical.
- Migration tests must cover new empty databases and existing databases.
- User data must not be deleted during migrations unless the migration explicitly documents why.
- Before destructive migrations, add a backup step in the migration runner.
- Auth, invite, user, and share-link tables are canonically owned by migration v6; LAN/auth repository `init_*` methods remain idempotent compatibility ensures only for raw/legacy connections and tests.
- 历史 DDL 快照原则：v8/v16 等"版本冻结"表定义（`SHOP_ITEMS_SCHEMA_V8`/`SHOP_ORDERS_SCHEMA_V8`/`SHOP_CARTS_SCHEMA_V16`/`AUTH_SHARE_SCHEMA_CONTRACT`）是磁盘兼容契约的一部分，**不得从当前 schema 推导**。

## Future Direction

Future schema changes should be added as explicit migrations in `core/db_migrations.py` and covered by tests in `tests/core/test_db_migrations.py`. The next migration hardening step is per-migration transaction/rollback tests, plus a runtime assertion linking `len(MIGRATIONS) == CURRENT_SCHEMA_VERSION`(当前仅由测试侧 frozen signature 兜底;详细开放项见 `docs/overview-2026-08-27.md` §19)。
