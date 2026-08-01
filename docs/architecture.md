# AssetManager Next Architecture

This refactor treats AssetManager as a platform with two first-class presentations: the PySide6 desktop app and the LAN web app. Both presentations should share application services instead of duplicating business logic.

## Layers

- `presentation`: PySide6 windows, panels, widgets, dialogs, LAN HTTP routes, and React SPA assets served by LAN.
- `application`: use-case services such as opening libraries, browsing assets, editing metadata, generating thumbnails, sharing libraries, and searching.
- `domain`: stable concepts such as libraries, assets, projects, tags, metadata, shares, users, and domain errors.
- `infrastructure`: SQLite, file-system access, settings storage, thumbnail cache, aiohttp, tunnel processes, and path resolution.

The recalibrated Desktop–LAN–WebUI architecture is delivered for the current Runtime/session/LAN/WebUI scope. Existing `core`, `panels`, `widgets`, and `lan` modules remain valid presentation and infrastructure modules; future work is tracked separately in the repository baseline and DeepSeek roadmap.

## Application Services

| Service | Module | Purpose | Desktop | LAN | Tests |
|---|---|---|---|---|---|
| `LibraryService` | `library_service.py` | Open libraries, expose `LibraryContext` | `app.py`, `window.py`, `lan_sharing.py` | indirect | 3 |
| `AssetService` | `asset_service.py` | Directory listing, filtering, sorting | — | `/api/files` | 4 |
| `MetadataService` | `metadata_service.py` | Notes, URLs, dir size, tags-for-asset | — | `/api/meta`, `/api/projects` | 5 |
| `TagService` | `tag_service.py` | Tag list, assign, rename, delete | — | `/api/tags/*` | 4 |
| `FileOperationService` | `file_operation_service.py` | Copy, move, rename, trash, duplicate, delete | `_actions.py` (7 ops) | — | 6 |
| `ThumbnailService` | `thumbnail_service.py` | Resolve source, blur check, image processing | — | `/api/thumbnails/*` | 7 |
| `ThumbnailRepository` | `thumbnail_repository.py` | Desktop thumbnail cache table access | `_loader.py` | — | via loader tests |
| `SearchService` | `search_service.py` | Search by tags or name | — | `/api/search` | 6 |
| `PluginService` | `plugin_service.py` | Plugin discovery, load, enable, disable | `app.py` (startup) | — | 7 |
| `ProjectService` | `project_service.py` | Project listing/detail/tree/home, depth rules, preview metadata | — | `/api/projects`, `/api/projects/{path}`, `/api/tree`, `/api/home` | 10 |
| `AssetIndexService` | `asset_index_service.py` | Populate and query `assets` table | — | — | 9 |
| `AuthService` | `auth_service.py` | LAN users, tokens, invite codes, share links | — | `/api/auth/*`, `/api/users/*`, `/api/invites/*`, `/api/shares/*` | 8 |
| `UndoService` | `undo_service.py` | Undo/redo stack for file operations | `_actions.py` | — | 8 |

`LibraryContext` (`context.py`) is a frozen dataclass bundling root, data_dir, thumb_dir, db_conn, tag_store, and project_data for an opened library. `LibrarySession` is the public opened-library boundary and exposes `connection_for()` so services receive a scoped `ConnectionProvider` without falling back to mutable current-library state. `ApplicationBootstrap.runtime_for(session)` is the canonical production assembly path for the cached `LibraryRuntime`; Desktop and LAN consume the same runtime and its session-bound service bundle. Runtime caching, LAN injection, the pre-close adapter barrier, restart-generation ownership, Task D fallback removal, the Windows Task E cross-surface matrix and the Ubuntu WSL directory-symlink gate are delivered. See [`docs/compose/reports/desktop-lan-webui-architecture-migration.md`](compose/reports/desktop-lan-webui-architecture-migration.md) and [`docs/compose/reports/desktop-lan-webui-architecture-recalibration.md`](compose/reports/desktop-lan-webui-architecture-recalibration.md).

## LAN Route Structure

LAN API routes are split into focused modules under `AssetsManager/lan/routes/`:

| Module | Routes | Application Service |
|---|---|---|
| `pages.py` | `/`, `/detail` | — |
| `files.py` | `/api/files` | `AssetService` |
| `metadata.py` | `/api/meta`, `/api/search`, `/api/home`, `/api/tree`, `/api/projects` | `MetadataService`, `SearchService`, `TagService`, `ProjectService` |
| `tags.py` | `/api/tags/*` | `TagService` |
| `thumbnails.py` | `/api/thumbnails/*` | `ThumbnailService` |
| `downloads.py` | `/api/download/*` | — |
| `auth.py` | `/api/auth/*` | `AuthService` |
| `users.py` | `/api/users/*`, `/api/invites/*` | `AuthService` |
| `shares.py` | `/api/shares/*`, `/s/*` | `AuthService` |
| `system.py` | `/api/info`, `/api/tunnel/status`, `/api/stats` | — |
| `websocket.py` | `/ws` | — |
| `_helpers.py` | Shared: `validate_path`, `get_auth_token`, `build_zip_async`, etc. | — |

`AssetsManager/lan/api.py` is a thin wrapper (~98 lines) that imports all handlers from `routes/` and registers them in `setup_routes()`.

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

Per-library SQLite databases are migration-aware through `AssetsManager.core.db_migrations`.

| Version | Name | Description |
|---|---|---|
| 1 | `baseline_current_schema` | Records existing schema (file_tags, file_meta, thumbnail_cache, library_stats) |
| 2 | `add_assets_index` | Adds `assets` table with indexes on parent_path, library_root, name, extension |
| 3 | `add_tag_metadata` | Adds `tag_metadata` for tag color, icon, and category metadata |
| 4 | `add_plugin_metadata` | Adds `plugin_metadata` for persisted plugin-parsed file metadata |

The assets table is populated lazily by application services, not by the migration itself. Future schema changes must be added as explicit migrations and covered by tests.

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

Panels receive controllers via library-scoped initialization paths. `InfoPanel` and `TagTreePanel` initialize from `library_opened` with scoped services and no global store fallback. `FileListPanel` configures its model metadata service and thumbnail cache through `_configure_library_runtime(root)`, using scoped runtime whenever the QApplication bootstrap exists. All data operations go through controllers or scoped application services; panels remain UI renderers.

## Domain Events

Application services publish immutable facts via `AssetsManager.domain.event_bus.get_event_bus()`. Session-bound UI refresh uses the scoped event set below:

| Service | Method | Event |
|---------|--------|-------|
| `LibraryService` | `open_session()` | `LibraryOpened` |
| `TagService` | asset mutation | `AssetTagsChanged` and `TagCatalogChanged` |
| `MetadataService` | note or URL mutation | `AssetNotesChanged` or `AssetUrlsChanged` |
| `FileOperationService` | bound file mutation after projection updates | `FileSystemChanged` |

Desktop panels subscribe only to session-scoped domain events through `panels/_event_bridge.py`, which forwards domain events via Qt signals before invoking UI handlers. Handlers reject events whose `session_token` does not match the active scoped session; asset-detail handlers also reject unrelated paths. This keeps UI mutation on the Qt thread when events are published by worker or LAN threads. `EventBus.subscribe()` returns a subscription token, `subscribe_weak()` avoids keeping bound-method owners alive, and the Qt bridge closes its token during panel shutdown.

Legacy unscoped events (`FileCreated`, `FileRenamed`, `FileDeleted`, `FileCopied`, `TagsChanged`, `NotesChanged`, `UrlsChanged`) remain available for plugins and compatibility consumers. Panels must not subscribe to them because they do not carry session identity. `core.signal_bus` remains a separate Qt-only presentation mechanism for navigation, focused-file, theme, language, and UI-scale coordination; it must not carry application mutation facts.

## Application Bootstrap

`ApplicationBootstrap` (`application/bootstrap.py`) owns the one application-service assembly path. `ApplicationBootstrap.runtime_for(session)` composes a canonical `LibraryRuntime` and its eager `LibraryScopedServices` bundle. A runtime LAN server receives that object, wraps the runtime bundle with its LAN auth/share services, and eagerly attaches `LanScopedServices` before routes are installed. Route helpers only perform direct lookup of `lan.services`; a missing bundle is a loud lifecycle error. Raw LAN service construction and the removed bootstrap composition compatibility callers are absent from the production path. Task E's Windows lifecycle, identity, realtime and Ubuntu WSL directory-symlink acceptance is recorded in the recalibration final report.

LAN server stop closes websocket/site and scanner resources when supported. It does not close an injected `LibraryRuntime` or `LibrarySession`; runtime adapters and database close belong to the `ApplicationBootstrap`/`LibraryService` session lifecycle. The required ordering is adapter stop → lease drain/session cleanup → database close, and the pre-close failure/retry, restart-generation and Windows cross-surface contracts are covered by the delivered lifecycle work. `LanServer`, `ShareManager`, and desktop sharing use the canonical runtime on the primary path. The Linux directory-symlink validation passed in Ubuntu WSL, so no release gate remains open for this scope.

### Realtime lifecycle hardening

The canonical realtime path is `LibraryRuntime` → `RuntimeEventRouter` → authenticated LAN WebSocket → React `RealtimeContext` projection invalidation. WebSocket payloads carry only `epoch`, `revision`, domains, and relative paths; SQLite and the filesystem remain authoritative.

WebSocket admission uses a pending-client barrier and reconciles the cursor after registration. Active connections retain canonical principal authority and are revalidated across authority transitions, heartbeat, and delivery; revocation uses the same idempotent eviction path as transport failure. The initial application frame is sent before the final authoritative admission step; this is a known P2 protocol note covered by the completed Task E acceptance evidence. Eviction removes clients and pong waiters, closes the socket, updates connection accounting, and releases `OnlineUsers` presence exactly once.

`LanServer.stop()` retains an explicit lifecycle state and actionable owner thread/loop references until shutdown and thread termination are confirmed. Shutdown timeout, join timeout, and failed startup cleanup remain observable as non-stopped states; a failed startup cleanup is retried on the original owner loop without overlapping pending cleanup or automatically retrying ordinary stop failures. See [`docs/compose/reports/realtime-dataflow-hardening.md`](compose/reports/realtime-dataflow-hardening.md) for the final evidence.

## Architecture Governance

- `tests/unit/test_architecture_boundaries.py` guards key dependency rules and documents the small set of transitional exceptions. Non-presentation layers are not allowed to import PySide6.
- `docs/adr/0001-architecture-governance.md` records the current DB lifecycle, EventBus, plugin trust model, and LAN exposure decisions.
- `docs/adr/0002-library-session.md` records the target opened-library session boundary and migration sequence away from implicit current-library state.
- Existing transitional exceptions should shrink over time; new exceptions require an explicit ADR update.

## Crypto Layer

All pure crypto functions (password hashing, token generation/verification) live in `AssetsManager.domain.auth`. The LAN layer (`lan/auth.py`) re-exports them. `AuthService` and `ShareService` import crypto from `domain.auth` and DB operations from `lan/auth.py`.

## Future Work

- **Type checking**: Pyright covers `application`, `domain`, `di`, `repositories`, `controllers`, `lan`, core non-UI modules. Next: tackle `dialogs/`, `panels/`, `widgets/` type noise.
- **Desktop/service unification**: `FileSystemModel` and `AssetService` now share sort/filter/category rules via `application/asset_filters.py`; next step is to unify stat/thumbnail caching.
- **Performance baselines**: Track large directory listing, search, thumbnail cache, and LAN response times with real libraries.
