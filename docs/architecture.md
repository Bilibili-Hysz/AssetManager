# AssetManager Next Architecture

This refactor treats AssetManager as a platform with two first-class presentations: the PySide6 desktop app and the LAN web app. Both presentations should share application services instead of duplicating business logic.

## Layers

- `presentation`: PySide6 windows, panels, widgets, dialogs, LAN HTTP routes, and static web UI.
- `application`: use-case services such as opening libraries, browsing assets, editing metadata, generating thumbnails, sharing libraries, and searching.
- `domain`: stable concepts such as libraries, assets, projects, tags, metadata, shares, users, and domain errors.
- `infrastructure`: SQLite, file-system access, settings storage, thumbnail cache, aiohttp, tunnel processes, and path resolution.

The current codebase is being migrated gradually. Existing `core`, `panels`, `widgets`, and `lan` modules remain valid until their responsibilities are moved behind application services.

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

`LibraryContext` (`context.py`) is a frozen dataclass bundling root, data_dir, thumb_dir, db_conn, tag_store, and project_data for an opened library. It also exposes `connection_for()` so services can receive a scoped `ConnectionProvider` without falling back to mutable current-library state. ADR 0002 defines `LibrarySession` as the target public opened-library boundary; it currently exists as a thin wrapper around `LibraryContext` while call sites migrate. Desktop presentation code obtains per-library services through the QApplication bootstrap and `ApplicationBootstrap.for_library(session)`, which now requires a `LibrarySession`. `InfoPanel` and `TagTreePanel` require scoped services after `library_opened`, while `FileListPanel` requires scoped runtime when bootstrap is present and only keeps fallback for isolated bootstrap-free panel tests.

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

Application services publish domain events via `AssetsManager.domain.event_bus.get_event_bus()`:

| Service | Method | Event |
|---------|--------|-------|
| `LibraryService` | `open_library()` | `LibraryOpened` |
| `TagService` | `add_tag()`, `remove_tag()`, `rename_tag()`, `delete_tag()` | `TagsChanged` |
| `MetadataService` | `set_notes()` | `NotesChanged` |
| `MetadataService` | `add_url()`, `remove_url()` | `UrlsChanged` |
| `FileOperationService` | `create_folder()` | `FileCreated` |
| `FileOperationService` | `move()`, `move_to_directory()` | `FileRenamed` |
| `FileOperationService` | `copy_to_directory()` | `FileCopied` |
| `FileOperationService` | `duplicate()` | `FileCreated` |
| `FileOperationService` | `delete_permanent()`, `delete_to_trash()` | `FileDeleted` |

Desktop panels subscribe to domain events through `panels/_event_bridge.py`, which forwards domain events via Qt signals before invoking UI handlers. This keeps UI mutation on the Qt thread when events are published by worker or LAN threads. `EventBus.subscribe()` returns a subscription token, `subscribe_weak()` avoids keeping bound-method owners alive, and the Qt bridge closes its token during panel shutdown.

## Application Bootstrap

`ApplicationBootstrap` (`application/bootstrap.py`) wires long-lived application services into a `ServiceContainer`. `AuthService` and `ShareService` are excluded because they require `db_conn` + `token_secret` from the LAN server at runtime. `ApplicationBootstrap.for_library(session)` returns a `LibraryScopedServices` bundle that binds `MetadataService`, `TagService`, and `ProjectService` to the target scoped `connection_for()` provider.

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
