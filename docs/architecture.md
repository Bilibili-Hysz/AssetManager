# AssetManager Next Architecture

> 状态:**LIVING** · updated: 2026-08-27 · 结构性文档;行数/模块数等实测数字见 `docs/overview-2026-08-27.md` §1;本文不再维护迁移明细表(见 `docs/migrations.md`)。

This refactor treats AssetManager as a platform with two first-class presentations: the PySide6 desktop app and the LAN web app. Both presentations should share application services instead of duplicating business logic.

## Layers

- `presentation`: PySide6 windows, panels, widgets, dialogs, LAN HTTP routes, and React SPA assets served by LAN.
- `application`: use-case services such as opening libraries, browsing assets, editing metadata, generating thumbnails, sharing libraries, and searching.
- `domain`: stable concepts such as libraries, assets, projects, tags, metadata, shares, users, and domain errors.
- `infrastructure`: SQLite, file-system access, settings storage, thumbnail cache, aiohttp, tunnel processes, and path resolution.

The recalibrated Desktop–LAN–WebUI architecture is delivered for the current Runtime/session/LAN/WebUI scope. Existing `core`, `panels`, `widgets`, and `lan` modules remain valid presentation and infrastructure modules; future work is tracked separately in the repository baseline and DeepSeek roadmap.

The B2 thumbnail boundary is part of the local `master` baseline: ThumbnailLoader consumes a scoped ThumbnailService through an immutable runtime snapshot. Post-commit focused regression is reproducible; real-image I/O, performance and wider regression evidence remain tracked separately.

A2 service validation downshift and A3 presentation-specific assembly are delivered. B1 is also implemented: Desktop/shared services and the frozen Runtime sharing bundle are owned by the canonical Runtime; Asset/Project/Search remain a lazy LAN-only projection.

## Boundary Rules

Five separation rules govern new code (from the front/back separation plan; a violation is a defect at bug priority):

1. Application-layer return values and parameters must not carry URL, HTTP, or transport semantics.
2. The presentation layer must not hold a `Connection` or `Repository`.
3. Prefer in-process calls over HTTP when both sides live in one process.
4. Business validation belongs only in the service layer.
5. Each end assembles only the services it consumes.

Static gates are enforced by `scripts/check_boundaries.py` (gates 1/2/3/5), `scripts/gen_ts_types.py --check` (gate 6), `scripts/check_style_sources.py` (D4 local QSS token gate), `scripts/check_route_capabilities.py` (L1 LAN write capability gate), `scripts/check_frontend_data_fetch.py` (S2 page data-layer gate), and `scripts/gen_web_tokens.py --check` (S4 theme-token single source); all run in the CI `lint` job.

## Application Services

| Service | Module | Purpose | Desktop | LAN | Tests |
|---|---|---|---|---|---|
| `LibraryService` | `library_service.py` | Open libraries, expose `LibraryContext`, hold per-library QLockFile | `app.py`, `window.py`, `lan_sharing.py` | indirect | 3+ |
| `LibraryRuntime` / `RuntimeEventRouter` | `runtime.py` / `runtime_events.py` | Per-library service snapshot, projection invalidation routing, lifecycle adapters | `window.py`, panels | LAN realtime bridge | unit + integration |
| `AssetService` | `asset_service.py` | Directory listing, filtering, sorting, validated bounded direct-child summaries | — | `/api/files`, `/api/files/summaries` | service + LAN route tests |
| `MetadataService` | `metadata_service.py` | Notes, URLs, dir size (30s TTL), tags-for-asset | `InfoPanel` | `/api/meta`, `/api/projects` | 5+ |
| `TagService` | `tag_service.py` | Tag list, assign, rename, delete | `InfoPanel`, `TagTreePanel` | `/api/tags/*` | 4+ |
| `FileOperationService` | `file_operation_service.py` | Copy, move, rename, trash, duplicate, delete (path locks, moved_pairs) | `_actions.py` (7 ops) | — | 6+ |
| `ThumbnailService` | `thumbnail_service.py` | Session-bound source/blur/image processing and thumbnail-cache metadata API | `FileListPanel`, `_loader.py` | `/api/thumbnails/*` | service + desktop Loader tests |
| `ThumbnailRepository` | `thumbnail_repository.py` | Infrastructure adapter behind thumbnail persistence APIs; not a presentation dependency | — | — | service/repository tests |
| `SearchService` | `search_service.py` | Dual-track search (scanner/indexed), SearchResultSet status semantics, quick_search budget | — | `/api/search`, `/api/quicksearch` | 6+ |
| `PluginService` | `plugin_service.py` | Plugin discovery, load, enable, disable | `app.py` (startup) | — | 7 |
| `ProjectService` | `project_service.py` | Project listing/detail/tree/home, depth rules (clamped 1-32), preview metadata | — | `/api/projects`, `/api/tree`, `/api/home` | 10+ |
| `AssetIndexService` | `asset_index_service.py` | Populate and query `assets` table; revision CAS publish state machine | FileOperationService | indirect (search index) | 9+ |
| `AssetIndexReconciliationService` + `ReconciliationQueue` | `asset_index_reconciliation_service.py` / `reconciliation_queue*.py` | Background rescan worker; cross-process persistent task queue (lease + generation CAS) | runtime lifecycle adapter | — | integration suite |
| `AuthService` | `auth_service.py` | Users, tokens, and invite codes bound to one Runtime/session | Desktop/runtime-owned | `/api/auth/*`, `/api/users/*`, `/api/invites/*` | service + LAN route tests |
| `ShareService` | `share_service.py` | Share-link lifecycle, password strength + brute-force lockout, validation, access tokens | Desktop `ShareCreationTask` | `/api/shares/*`, `/s/*` | service + LAN route tests |
| `UndoService` | `undo_service.py` | Undo/redo stack for file operations; delete backups + projection snapshots | `_actions.py` | — | 8+ |
| `DatabaseIntegrityService` | `database_integrity_service.py` | Session-bound quick check and conservative orphan metadata maintenance | Settings/runtime lifecycle | — | unit + lifecycle tests |
| `DatabaseMaintenanceService` | `database_maintenance_service.py` | Database size, bounded WAL checkpoint, VACUUM boundary, retryable background stop | Settings/runtime lifecycle | — | unit + lifecycle tests |
| `LibraryExportService` | `library_export_service.py` | Metadata export, bounded backup (100k members), validation, closed-session isolated restore (reservation token + ACK) | Settings adapter/runtime | — | export/restore regression tests |
| `LibrarySettingsAdapter` | `library_settings_adapter.py` | Qt-free boundary for integrity, maintenance, export, backup, and restore state | Settings presentation | — | adapter tests |
| `GalleryService` / `FavoriteService` | `gallery_service.py` / `favorite_service.py` | Budget-limited gallery projection / owner-scoped favorites | — | `/api/gallery/*`, `/api/favorites` | LAN route tests |
| ~~Commerce stack~~（`ShopService`/`ShopBuyerService`/`OrderService`/`SellerAuthService`/`SellerProfileService`/`StorefrontAnalyticsService`，**已按 ADR 0005 剥离**；`QuotaService`/`FreeDownloadQuotaService` 保留为访客免费下载配额） | 原 `shop_service.py` etc.（已删除） | 原商城目录/购物车/结算、订单状态机（pending→confirmed→fulfilled/revoked）、交付令牌、卖家会话与隐私聚合分析（已删除；迁移链 v8/v10-v25 与 schema 表定义按 ADR 0005 保留） | — | 原 `/api/shop/*`（54 routes，已删除） | 商城测试已删除；见 ADR 0005 |
| `ImportService` + `ImportManifestStore` | `import_service.py` / `import_manifest_store.py` | External import batches (discover→plan→fingerprint→copy), manifest state machine (prepared/running/completed/degraded/cancelled/recovery_pending), claim/lease recovery, v2 replay idempotency | `window.py` import UI | — | import tests |
| `FilesystemProjectionRepairService` | `filesystem_projection_repair_service.py` | Durable projection repair executor (move/delete/restore intent-vs-reality reconciliation) | FileOperationService | — | repair tests |
| `LibraryWatcherService` | `library_watcher_service.py` | Polling library tree mtime snapshot → `FileSystemChanged(kind=external_watch)` + rescan enqueue (50k dir budget) | Runtime lifecycle adapter | — | watcher tests |
| `ThumbnailCacheLifecycle` | `thumbnail_cache_lifecycle.py` | Thumbnail artifact in-process locks + cross-process owner lease (QLockFile) + safe delete | FileOperationService | — | lifecycle tests |

> 应用服务层为 51 个顶层服务模块(另有 `gallery/` 子包 5 文件);完整清单见 `docs/overview-2026-08-27.md` §7-12 与 `docs/full-review/02-module-map.md`(快照,行数已过时)。

`LibraryContext` (`context.py`) is a frozen dataclass bundling root, data_dir, thumb_dir, db_conn, tag_store, and project_data for an opened library. `LibrarySession` is the public opened-library boundary and exposes `connection_for()` so services receive a scoped `ConnectionProvider` without falling back to mutable current-library state. `ApplicationBootstrap.runtime_for(session)` remains the only production assembly path for the cached `LibraryRuntime`; Desktop and LAN consume the same runtime and canonical frozen snapshot. The snapshot object is eager and unique, but A3 splits field materialization: Metadata/Tag/Thumbnail/FileOperation/Undo/Plugin/AssetIndex/DatabaseIntegrity/DatabaseMaintenance/LibraryExport/ReconciliationQueue/ReconciliationService are eager Desktop/shared fields, while one private single-flight holder materializes `LanRuntimeServices` (Asset/Project/Search/Gallery/Favorite) only when LAN is composed. `LibrarySettingsAdapter` remains the Qt-free presentation boundary for the maintenance and recovery services, including execution errors and scheduling rejection reasons. Runtime caching, LAN injection, the pre-close adapter barrier, restart-generation ownership, Task D fallback removal, the Windows Task E cross-surface matrix and the Ubuntu WSL directory-symlink gate are delivered. See [`docs/archive/2026-09/compose-reports/desktop-lan-webui-architecture-migration.md`](archive/2026-09/compose-reports/desktop-lan-webui-architecture-migration.md), [`docs/archive/2026-09/compose-reports/desktop-lan-webui-architecture-recalibration.md`](archive/2026-09/compose-reports/desktop-lan-webui-architecture-recalibration.md), [`docs/archive/2026-09/compose-reports/a3-service-assembly-2026-08-02.md`](archive/2026-09/compose-reports/a3-service-assembly-2026-08-02.md), and [`docs/archive/2026-09/compose-reports/b1-runtime-sharing-2026-08-03.md`](archive/2026-09/compose-reports/b1-runtime-sharing-2026-08-03.md).

`ApplicationBootstrap` creates and owns a frozen `RuntimeSharingServices` bundle for each live Runtime/session. It generates one non-persisted `token_secret`, constructs `AuthService` and `ShareService` with the same session DB connection and secret, and idempotently initializes both tables inside the Runtime creation/session operation lease. LAN stop/start reuses the bundle; session close invalidates it. LAN UI tokens do not use the Runtime secret directly: LAN derives `local_ui_auth_secret` from it plus `access_key/password/auth_mode`; unchanged stop/start is stable and an auth configuration change invalidates old tokens. The public `LanServer.token_secret` is a compatibility alias for the local UI secret; new consumers use `runtime_token_secret` for the Runtime-owned value. Different libraries keep separate sessions, connections, runtimes, secrets, service bundles and databases.

`LibraryService` acquires a stable per-library `QLockFile` before database initialization and releases it only after the canonical session, runtime listeners and database close successfully complete. Initialization failures release the lock; close failures retain it for retry. Multiple service objects in one process share the underlying lock lease, while another process opening the same library is rejected; different libraries remain parallelizable.

## LAN Route Structure

LAN API routes are split into focused modules under `AssetsManager/lan/routes/` (22 个顶层模块,70 条注册路由 = GET 43/POST 18/PUT 2/PATCH 2/DELETE 5;页面 8;原 Commerce 54 条已按 ADR 0005 剥离):

| Module | Routes | Application Service |
|---|---|---|
| `pages.py` | SPA pages: `/`, `/browse`, `/detail`, `/login`, `/gallery*`, `/app*`, `/s/{id}` (8; 原 `/storefront*`、`/store*`、`/seller*` 已按 ADR 0005 剥离) | — (SPA fallback to `webui/dist`) |
| `files.py` | `/api/files`, `/api/files/summaries` | `AssetService` |
| `metadata.py` | `/api/meta`, `/api/search`, `/api/home`, `/api/tree`, `/api/projects*`, `/api/notes` | `MetadataService`, `SearchService`, `TagService`, `ProjectService` |
| `tags.py` | `/api/tags/*` | `TagService` |
| `thumbnails.py` | `/api/thumbnails/*` (+ batch) | `ThumbnailService` |
| `image.py` | `/api/image` | `ThumbnailService` (Pillow content gate) |
| `downloads.py` | `/api/download/*`, `/api/download/batch` | free-download quota + file/zip responses |
| `quicksearch.py` | `/api/quicksearch` | `SearchService.quick_search` |
| `gallery.py` / `favorites.py` | `/api/gallery/*`, `/api/favorites*` | `GalleryService`, `FavoriteService` |
| `auth.py` | `/api/auth/*` | `AuthService` |
| `users.py` | `/api/users/*`, `/api/invites/*`, `/api/activity`, `/api/online-users` | `AuthService` |
| `shares.py` | `/api/shares/*`, `/s/{id}` | `ShareService`; principal helpers |
| `system.py` | `/api/info`, `/api/tunnel/status`, `/api/stats`, `/api/revision` | runtime cursor / tunnel |
| `quota.py` | `/api/quota` | `FreeDownloadQuotaService` |
| ~~`shop.py`~~（已按 ADR 0005 剥离） | 原 `/api/shop/*` (55 routes: catalog/cart/checkout/orders/delivery/seller，已删除) | 原 Commerce stack（order/shop/shop_buyer/quota/seller services，已删除；quota 链并入 `quota.py` 保留） |
| ~~`commerce_policy.py` / `seller_auth.py` / `seller_profile.py` / `storefront_analytics.py`~~（已按 ADR 0005 剥离） | 原 commerce policy / seller login / seller profile / analytics（已删除） | 原 Commerce services（已删除） |
| `websocket.py` | `/ws` | `WebSocketManager` |
| `_helpers.py` / `_resource_urls.py` | Shared: `validate_path`, `get_auth_token`, `LanScopedServices`, `build_zip_async`, URL projection | — |

`AssetsManager/lan/api.py` (463 行) imports all handlers from `routes/` and registers them in `setup_routes()` (70 routes) plus the runtime realtime bridge (`on_invalidation` → `ws_manager.broadcast`). A2 business rules belong to application services: `TagService` owns tag-name validation, `ShareService` owns password/expiry/download-limit validation, and `AssetService` owns bounded directory-summary validation. LAN routes retain permission, JSON, `PathGuard`, and transport-normalization responsibilities, translate `ValidationError`/`DuplicateError` to HTTP 400/409 contracts, and preserve unrelated failures as 500. Desktop creates shares through `ShareCreationTask` → Runtime `ShareService` directly; LAN retains `/api/shares/*` management and `/s/{id}` remote links.

> 完整路由表（方法+路径+权限+handler+服务）见 `docs/full-review/02-module-map.md` §7 与 LAN 审查素材。

## Desktop File List Integration

`AssetsManager/panels/file_list/_actions.py` delegates these operations to `FileOperationService`:

- **Rename** → `FileOperationService().move()` with metadata migration
- **Duplicate** → `FileOperationService().duplicate()`
- **Permanent delete** → `FileOperationService().delete_permanent()`
- **Paste (copy)** → `FileOperationService().copy_to_directory()`
- **Paste (cut)** → `FileOperationService().move_to_directory()` with metadata migration
- **Delete to trash** → `FileOperationService().delete_to_trash()`
- **New folder** → `FileOperationService().create_folder()`

Undo/redo stack management delegates to `UndoService` (`application/undo_service.py`). The `_actions.py` records rename/delete operations via `UndoService.record_rename()` and `UndoService.record_delete()`, then executes undo/redo via `execute_undo()` and `execute_redo()` in background threads.

## Shared Utilities

- `core/format_utils.py` — `format_size()` used by both application and LAN layers
- `application/asset_filters.py` — shared sort/filter/category rules for desktop and LAN browsing
- `lan/routes/_helpers.py` — `validate_path()`, `get_auth_token()`, `get_auth_service()`, `build_zip_async()`, `CATEGORY_MAP`, `IMAGE_EXTS`
- `lan/path_guard.py` — `PathGuard`, `PathEscapeError`, `MissingPathError`

## Database Migrations

Per-library SQLite databases are migration-aware through `AssetsManager.core.db_migrations` (`CURRENT_SCHEMA_VERSION = 34`)。**逐版本明细不再在此维护**:权威为 `docs/migrations.md`(v1-v34 各版本 DDL 与要点),机制说明与全表速览见 `docs/overview-2026-08-27.md` §15。要点:迁移在 SAVEPOINT 内执行(保留调用方事务);历史冻结校验(`MigrationHistoryError`/未来版本 `UnsupportedSchemaVersion`,名称不可变);每版本结果形状经 `_versioned_schema_contract` 契约回溯校验(按 version 剪列,如 v<17 `reconciliation_tasks` 无 lease_token);`assets` 表由服务层惰性填充,非迁移本身。未来 schema 变更必须显式迁移 + 测试。

## Plugin System

`AssetsManager.core.plugins` provides the plugin infrastructure:

- `descriptor.py` — manifest parsing, `PluginDescriptor`, `PluginRecord`, lifecycle states
- `host_context.py` — `PluginHostContext` with command/menu/tool_window contributions
- `loader.py` — `PluginLoader` using `importlib` for dynamic module loading
- `manager.py` — `PluginManagerService` orchestrating discover/enable/disable/load/unload

`AssetsManager.application.plugin_service` wraps `PluginManagerService` as an application-layer service. Plugins are directories in `RuntimeData/Shared/plugins/` with a `plugin.json` manifest.

## Thread Safety

- `TagStore` and `ProjectData` instance caches use `threading.Lock` for safe concurrent access.
- `DatabaseManager` uses `threading.RLock` for cross-thread SQLite writes.
- `LibraryService` uses a per-library `QLockFile` lease for cross-process open admission; lock ownership follows the canonical session lifecycle.
- `EventBus` uses `threading.Lock` for subscribe/unsubscribe/publish.
- `ServiceContainer` uses `threading.RLock` for reentrant resolution.
- `conftest.py` provides `_cleanup_stores` autouse fixture to close DB connections and reset EventBus after each test.

## Controllers

Controllers provide testable business logic that panels delegate to. They have no Qt dependencies and can be tested with pure Python.

| Controller | Panel | Responsibilities |
|-----------|-------|-----------------|
| `InfoController` | `InfoPanel` | Metadata, tags, notes, URLs, plugin fields, URL discovery |
| `FileListController` | `FileListPanel` | Search history, status text, first-image cache, total size |
| `TagTreeController` | `TagTreePanel` | Tag CRUD, file lookup by tag |
| `SidebarController` | `SidebarPanel` | Search generation counter(近空壳,保留为控制器占位) |

(2026-08-27:controllers 实为 4 个文件,均零 Qt import;README 早期文档漏列 SidebarController。)

Panels receive controllers via library-scoped initialization paths. `InfoPanel` and `TagTreePanel` initialize from `library_opened` with scoped services and no global store fallback. `FileListPanel` configures its model metadata service and binds an immutable thumbnail runtime through `_configure_library_runtime(root)` / scoped service injection; the panel and `ThumbnailLoader` do not receive SQLite connections or `ThumbnailRepository`. All data operations go through controllers or scoped application services; panels remain UI renderers.

## Domain Events

Application services publish immutable facts via `AssetsManager.domain.event_bus.get_event_bus()`. Session-bound UI refresh uses the scoped event set below:

| Service | Method | Event |
|---------|--------|-------|
| `LibraryService` | `open_session()` | `LibraryOpened` |
| `TagService` | asset mutation | `AssetTagsChanged` and `TagCatalogChanged` |
| `MetadataService` | note or URL mutation | `AssetNotesChanged` or `AssetUrlsChanged` |
| `FileOperationService` | bound file mutation after projection updates | `FileSystemChanged` |

Desktop panels subscribe to session-scoped mutation facts through `panels/_event_bridge.py`. The normal path forwards domain events via Qt signals before invoking UI handlers; the B3 TagTree pilot instead subscribes to `LibraryRuntime.event_router` through `RuntimeEventSubscription`, filters `ProjectionDomain.TAGS`, and still queues delivery onto the Qt thread. WebUI Browse uses the same TAGS invalidation to re-run the active tag search, and treats realtime recovery `null` as an all-projections authoritative refetch. Panel handlers reject stale session/runtime identity, while asset-detail handlers also reject unrelated paths. `EventBus.subscribe()` returns a subscription token, `subscribe_weak()` avoids keeping bound-method owners alive, and both bridge types close their tokens during panel shutdown.

Legacy unscoped events (`FileCreated`, `FileRenamed`, `FileDeleted`, `FileCopied`, `TagsChanged`, `NotesChanged`, `UrlsChanged`) remain available for plugins and compatibility consumers. Panels must not subscribe to them because they do not carry session identity. `core.signal_bus` remains a separate Qt-only presentation mechanism for navigation, focused-file, theme, language, and UI-scale coordination; it must not carry application mutation facts.

## Application Bootstrap

`ApplicationBootstrap` (`application/bootstrap.py`) owns the one application-service assembly path. `ApplicationBootstrap.runtime_for(session)` composes one canonical `LibraryRuntime` and one eager `LibraryScopedServices` snapshot object. The snapshot owns a frozen `RuntimeSharingServices` bundle: one `token_secret` is generated per Runtime/session, shared by `AuthService` and `ShareService` over the same session DB connection, and never persisted. Auth/Share tables are initialized idempotently during Runtime creation inside the session operation lease. LAN stop/start reuses this bundle; session close invalidates it. A private holder inside that snapshot provides generation-based single-flight materialization for `LanRuntimeServices`; success is cached once, one failed generation is shared by all of its waiters, later calls may retry, recursive materialization fails loudly, and session close wins through the operation/publication barrier. Compatibility properties for Asset/Project/Search read through to that same lazy bundle and do not create a second Runtime or composition root. A runtime LAN server prefers `services_snapshot`, materializes the LAN-only bundle inside the session lease, validates common, LAN-only and sharing provider/session/cache identity, consumes Runtime-owned Auth/Share, then atomically publishes `LanScopedServices` before routes are installed. The `.services` fallback is restricted to legacy runtime-shaped test doubles whose `services_snapshot` attribute is statically absent. Route helpers still perform only direct lookup of `lan.services`; a missing bundle is a loud lifecycle error. Task E's Windows lifecycle, identity, realtime and Ubuntu WSL directory-symlink acceptance is recorded in the recalibration final report.

LAN server stop closes websocket/site and scanner resources when supported. It does not close an injected `LibraryRuntime`, `LibrarySession`, or database connection; runtime adapters and database close belong to the `ApplicationBootstrap`/`LibraryService` session lifecycle. The required ordering is `session._begin_close()` → closing listeners/`Runtime.close_adapters()` (LAN stop) → lease drain → session-close listeners/`Runtime.close()` → database close, and the pre-close failure/retry, restart-generation and Windows cross-surface contracts are covered by the delivered lifecycle work. Without both a certificate and key, the endpoint and generated share URLs use `http://`; with both, they use `https://`. `LanServer`, `ShareManager`, and desktop sharing use the canonical runtime on the primary path. The Linux directory-symlink validation passed in Ubuntu WSL, so no release gate remains open for this scope.

### Realtime lifecycle hardening

The canonical realtime path is `LibraryRuntime` → `RuntimeEventRouter` → authenticated LAN WebSocket → React `RealtimeContext` projection invalidation. WebSocket payloads carry only `epoch`, `revision`, domains, and relative paths; SQLite and the filesystem remain authoritative. Consumers therefore refetch rather than treating invalidation payloads as data: explicit `tags` events and cursor recovery both refresh an active tag-filter projection.

WebSocket admission uses a pending-client barrier and reconciles the cursor after registration. Active connections retain canonical principal authority and are revalidated across authority transitions, heartbeat, and delivery; revocation uses the same idempotent eviction path as transport failure. The initial application frame is sent before the final authoritative admission step; this is a known P2 protocol note covered by the completed Task E acceptance evidence. Eviction removes clients and pong waiters, closes the socket, updates connection accounting, and releases `OnlineUsers` presence exactly once.

`LanServer.stop()` retains an explicit lifecycle state and actionable owner thread/loop references until shutdown and thread termination are confirmed. Shutdown timeout, join timeout, and failed startup cleanup remain observable as non-stopped states; a failed startup cleanup is retried on the original owner loop without overlapping pending cleanup or automatically retrying ordinary stop failures. See [`docs/archive/2026-09/compose-reports/realtime-dataflow-hardening.md`](archive/2026-09/compose-reports/realtime-dataflow-hardening.md) for the final evidence.

## Architecture Governance

- `tests/unit/test_architecture_boundaries.py` guards key dependency rules and documents the small set of transitional exceptions. Non-presentation layers are not allowed to import PySide6. Repository adapters may depend on `core.database` and pure core infrastructure such as `core.path_resolver`, plus domain/repository modules; they do not depend on application, LAN, or presentation.
- `docs/adr/0001-architecture-governance.md` records the current DB lifecycle, EventBus, plugin trust model, and LAN exposure decisions.
- `docs/adr/0002-library-session.md` records the target opened-library session boundary and migration sequence away from implicit current-library state.
- Existing transitional exceptions should shrink over time; new exceptions require an explicit ADR update.

## Crypto Layer

All pure crypto functions (password hashing, token generation/verification) live in `AssetsManager.domain.auth`. The LAN layer (`lan/auth.py`) re-exports them. `AuthService` and `ShareService` import crypto from `domain.auth` and DB operations from `lan/auth.py`.

## Future Work

- **Type checking**: CI typecheck runs pyright with a scoped whitelist (`application/controllers/core(部分)/di/domain/lan/repositories` + selected panels/widgets/dialogs, `basic` mode) and reports **0 errors**. The remaining type-noise in mixed LAN/panel/widget compatibility domains is tracked outside the whitelist and is not a release-completion claim.
- **Desktop/service unification**: `FileSystemModel` and `AssetService` now share sort/filter/category rules via `application/asset_filters.py`; `ThumbnailLoader` also uses the scoped `ThumbnailService` for cache metadata and the shared `thumbnail_cache_key`. Remaining work is stat/file-count cache unification plus real-image performance baselines (e.g. M6a-8 `get_home` full-table scan).
- **Performance baselines**: Track large directory listing, search, thumbnail cache, and LAN response times with real libraries (`tests/perf/` + nightly grid telemetry).
- **P2 defect round**: ~121 low-severity items across file_list/info/sidebar/dialogs/windows/controllers/domain (see `docs/reports/module-*.md`); delivery-token URL plaintext removal needs frontend coordination.
