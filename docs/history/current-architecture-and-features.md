# AssetManager Current Architecture And Feature Map

**Scan date:** 2026-06-14
**Codebase:** `AssetsManager_Python_Rewrite_refactor`
**Current gate:** latest reported gate is `ruff check .`, `pyright`, and `pytest`, with `536 passed`.

> Archived snapshot. The active workspace was flattened to the repository root on 2026-06-16. See `docs/workspace.md`, `docs/architecture.md`, and `docs/testing.md` for current status.

This document is a code-based snapshot of the refactored AssetManager architecture and feature surface. It complements `docs/architecture.md`, `docs/architecture-diagram.md`, and `docs/PROJECT_SUMMARY.md`, but focuses on the current module layout, service seams, and route inventory.

## 1. Product Shape

AssetManager is a PySide6 desktop asset-library manager with an optional aiohttp LAN web app. The current refactor turns the original desktop-focused tool into a layered platform:

- Desktop UI: library launcher, dockable main window, file browser, sidebar, info panel, tag tree, image viewer, tray, settings dialogs, sharing dialogs, plugin manager.
- LAN UI/API: browser interface plus JSON endpoints for browsing, metadata, thumbnails, downloads, auth, users, invites, shares, tunnel status, stats, and WebSocket events.
- Shared application layer: reusable services for library context, asset listing, metadata, tags, projects, search, thumbnails, file operations, undo, auth, shares, plugins, and indexing.
- Infrastructure: per-library SQLite, migrations, runtime data folders, settings, themes, tag store, project data, thumbnail cache, plugin loader, crash handling, i18n, and UI scaling.

## 2. High-Level Flow

```text
main.py / run.py
  -> AssetsManager.app.main()
    -> QApplication, theme, i18n, ApplicationBootstrap
    -> plugin discovery and enabled-plugin loading
    -> SystemTrayManager
    -> StartupWindow
      -> LibraryService.open_library(path)
      -> MainWindow

Desktop presentation
  -> MainWindow, dialogs, panels, widgets
  -> controllers where UI logic has been extracted
  -> application services
  -> domain models, events, repositories, core infrastructure

LAN sharing
  -> LanSharingMixin in the desktop window
  -> lan.manager / lan.server
  -> lan.api.setup_routes()
  -> lan.routes.* handlers
  -> application services
  -> repositories, domain, core
```

## 3. Layer Map

| Layer | Main Paths | Responsibility |
|---|---|---|
| Entry points | `main.py`, `run.py`, `AssetsManager/app.py` | Starts QApplication, installs crash handler, initializes theme/i18n, wires services, opens startup window. |
| Desktop presentation | `AssetsManager/window.py`, `dialogs/`, `panels/`, `widgets/`, `dock_factory.py` | Qt UI, dock layout, dialogs, browser, status bar, workspace tabs, tray, LAN controls. |
| LAN presentation | `AssetsManager/lan/`, `AssetsManager/lan/routes/`, `AssetsManager/lan/static/` | aiohttp app, HTTP API, static web UI, security middleware, WebSocket, tunnel integration. |
| Controllers | `AssetsManager/controllers/` | Testable non-Qt logic used by UI panels. Current controllers cover file list, info panel, and tag tree. |
| Application services | `AssetsManager/application/` | Use-case orchestration shared by desktop and LAN. This is the main refactor seam. |
| Domain | `AssetsManager/domain/` | Value objects, domain errors, domain events, auth helpers, share model, library/asset concepts. |
| Repositories | `AssetsManager/repositories/` | SQLite table access for tags, metadata, auth, share links, thumbnail cache, plugin metadata. |
| DI | `AssetsManager/di/` | Thread-safe `ServiceContainer` used by `ApplicationBootstrap`. |
| Core infrastructure | `AssetsManager/core/` | Database lifecycle, migrations, settings, themes, signal bus, tag store, project data, plugin internals, path resolver, scaling. |
| Tests | `tests/` | Unit, integration, desktop, LAN, core, and performance coverage. |

## 4. Startup And Bootstrap

`AssetsManager/app.py` is the main application entry. It performs these responsibilities:

- Enables Qt high-DPI behavior via `enable_high_dpi()`.
- Installs the global crash handler via `install_crash_handler()`.
- Creates `QApplication` and sets application metadata.
- Installs the app icon, theme manager, global stylesheet, translator, and application service bootstrap.
- Starts plugin discovery through `PluginService` and loads enabled plugins with a `PluginHostContext`.
- Creates `SystemTrayManager` and `StartupWindow`.

`ApplicationBootstrap` registers shared services in the DI container:

- `SettingsService`
- `LibraryService`
- `AssetService`
- `MetadataService`
- `TagService`
- `ProjectService`
- `ThumbnailService`
- `SearchService`
- `FileOperationService`
- `UndoService`
- `AssetIndexService`
- `PluginService`

`ApplicationBootstrap.for_library(context_or_session)` returns a `LibraryScopedServices` bundle. This is the current factory entry for per-library service instances that need the library-scoped SQLite connection provider, especially `MetadataService`, `TagService`, and `ProjectService`. Desktop panels resolve this bundle through presentation-layer bootstrap accessors; the shared scoped-service lookup opens a `LibrarySession` before creating scoped services. Library-opened paths in `InfoPanel` and `TagTreePanel` now require scoped services, and `FileListPanel` requires scoped runtime when a QApplication bootstrap is present.

The startup window owns the first user decision: create a library, open a folder, open a recent library, or open settings/about/help. Opening a library calls `LibraryService.open_library()` and then creates `MainWindow`.

## 5. Desktop Shell

`AssetsManager/window.py` is the main desktop shell. It combines multiple mixins and widgets:

- `LibraryContextMixin` maintains the active library root, database connection, tag store, thumbnail cache directory, current path, project data, and service references.
- `FileActionsMixin` handles create, rename, duplicate, copy, move, paste, delete, reveal, and selection-driven operations through `FileOperationService` and undo commands.
- `LanSharingMixin` starts/stops LAN sharing and coordinates the LAN server manager.
- `DockLayoutPersistenceMixin` saves/restores dock layout and workspace state.
- `TitleBar`, `WorkspaceBar`, `StatusBar`, `Sidebar`, `FileListPanel`, `InfoPanel`, `TagTreePanel`, `PreviewDock`, and `ImageViewer` make up the visible workspace.

Important desktop behaviors:

- Dockable panels are created by `dock_factory.py` and persisted by the layout mixin.
- Workspace tabs allow multiple folder contexts in the same main window.
- The file list is backed by `FileListController` plus application services.
- The info panel is backed by `InfoPanelController` and `MetadataService`.
- The tag tree is backed by `TagTreeController` and tag services.
- Library-scoped desktop runtime is resolved from `ApplicationBootstrap.for_library(context)`; fallback to global stores is limited to bootstrap-free isolated panel scenarios.
- File operations publish domain events such as `FileCreated`, `FileDeleted`, `FileCopied`, and `FileRenamed`.

## 6. Application Services

### `LibraryService`

Owns library lifecycle and context creation. It resolves runtime paths, initializes/open databases, runs migrations, creates tag stores, and returns `LibraryContext` for legacy callers or `LibrarySession` through `open_session()` for migrated opened-library paths.

### `AssetService`

Lists directories and returns `DirectoryListing` plus `AssetListItem` objects. It handles hidden files, category filters, search matching, include/exclude rules, max depth, sorting, directory preview image selection, and directory item counts.

### `MetadataService`

Coordinates metadata access through repository/core functions. It is used by desktop info panels and LAN endpoints for descriptions, metadata fields, and file tags.

### `TagService`

Wraps tag operations and keeps tag-related use cases out of Qt panels. It works with `TagStore` and repository helpers.

### `ProjectService`

Wraps project data operations for listing projects, recent projects, project details, and project-related settings.

### `SearchService`

Provides shared search behavior for indexed and metadata-aware searches.

### `ThumbnailService`

Resolves thumbnails from cache or source files, applies optional blur by tags, processes images through Pillow, and produces WebP bytes for LAN serving.

### `FileOperationService`

Performs create, rename, move, copy, duplicate, permanent delete, and trash delete operations. It also migrates metadata after moves and publishes file operation domain events.

### `UndoService`

Maintains undo/redo command history for desktop file operations.

### `AuthService`

Handles LAN user authentication, password/key hashing, token generation, user lifecycle, invite codes, and a compatibility set of share-link methods.

### `ShareService`

Encapsulates share-link creation, retrieval, listing, deletion, password checks, share token generation/verification, download counting, and path-scope validation.

### `PluginService`

Is the application-facing facade over `PluginManagerService`. It discovers, enables, disables, loads, unloads, lists plugins, and exposes command/menu contributions from the host context.

### `AssetIndexService`

Owns asset indexing workflows used by search and asset discovery scenarios.

## 7. Domain And Events

Domain modules provide shared primitives rather than UI code:

- `asset.py`: asset categories and extension sets.
- `library.py`: library context/value objects.
- `share.py`: `ShareLink` and share access rules.
- `auth.py`: password, key, user token, and share token helpers.
- `events.py`: domain events for file, tag, metadata, library, plugin, and LAN activity.
- `event_bus.py`: process-local event bus used by services and UI integration.
- `errors.py`: domain-level exceptions.

The event bus currently supports decoupling file operations and metadata/tag/library changes from listeners. This is useful for refreshing UI, invalidating caches, and plugin or future automation hooks.

## 8. Persistence

SQLite is the core persistence mechanism. The database layer lives primarily in `AssetsManager/core/database.py` plus repositories.

Current repository responsibilities:

- `AuthRepository`: users and invite codes.
- `ShareRepository`: share links and download counters.
- `MetadataRepository`: file descriptions and structured metadata.
- `TagRepository`: tag mappings and tag queries.
- `ThumbnailRepository`: thumbnail cache metadata.
- `PluginRepository`: plugin enablement/metadata state.

Runtime and library data are resolved through `runtime_paths.py`, `settings_paths.py`, and `LibraryService`. Migration logic is centralized in core database helpers and covered by tests.

## 9. LAN Web App

The LAN subsystem is organized around `lan.api.setup_routes()` and route modules in `AssetsManager/lan/routes/`.

Major route groups:

- Static UI: serves the browser app and static assets.
- Assets: directory listing, metadata, thumbnails, image serving, and downloads.
- Auth: login, logout, token checks, registration, users, invites, password/key validation.
- Shares: create/list/delete share links, verify passwords, validate tokens, enforce share scope.
- Projects: project listing, recent projects, project details, and project thumbnails.
- Search: LAN-facing search endpoints.
- Settings: share/LAN settings exposure and updates.
- Tunnel: tunnel status and control endpoints.
- Stats: server/library stats.
- WebSocket: live event channel.

The LAN app uses middleware for security headers, error handling, body limits, CORS/origin rules, and rate limiting. Route handlers should depend on application services rather than direct database/core calls when a matching service exists.

## 10. Desktop Dialogs And Panels

Important desktop modules include:

- `dialogs/startup.py`: startup/library launcher.
- `dialogs/settings.py`: settings UI.
- `dialogs/sharing_settings_dialog.py`: LAN/share configuration and status.
- `dialogs/plugin_manager_dialog.py`: plugin discovery and management.
- `dialogs/edit_metadata.py`: metadata editing.
- `dialogs/tag_editor_dialog.py`: file tag management.
- `dialogs/batch_rename.py`: batch renaming.
- `panels/file_list.py`: main asset browser panel.
- `panels/info.py`: selected asset information and metadata.
- `panels/sidebar.py`: navigation/sidebar.
- `panels/tag_tree.py`: tag tree and filtering.
- `widgets/image_viewer.py`: image preview/viewing.
- `widgets/title_bar.py`, `workspace_bar.py`, `status_bar.py`: shell chrome.

The codebase has already started extracting panel logic into controllers. Continuing that pattern is the clearest route for shrinking UI classes without changing behavior.

## 11. Plugins

Plugins are managed through `core/plugins.py` and surfaced through `PluginService`.

Current plugin architecture:

- Plugin descriptors are discovered from configured plugin paths.
- Enablement state is persisted.
- Enabled plugins are loaded during app startup.
- Plugins receive a host context and may contribute commands or menu entries.
- The desktop app registers core APIs, services, menus, and hooks before loading enabled plugins.

Runtime plugin storage is under the shared runtime plugin path. The app also includes a top-level `Plugins/` area for plugin-related assets or examples.

## 12. Internationalization And Scaling

The desktop app uses an i18n layer around Qt translation helpers and `.ts` translation files. New user-visible strings in Qt UI should be routed through the existing translation helpers.

UI scaling is centralized in `core/ui_scale.py`. Fixed dimensions should use scaled helpers such as `scaled_px()` or existing scaling abstractions. A grep still shows fixed-size APIs in several desktop files, but many already wrap dimensions with scaling.

## 13. Quality Gate And Test Shape

The reported current quality gate is clean:

```text
ruff check .
pyright
pytest
536 passed
```

The test suite spans:

- Unit tests for services, repositories, domain helpers, controllers, plugins, UI utilities, and path/database logic.
- Integration tests for metadata migrations, LAN auth/shares, file operations, plugin integration, and startup flows.
- Desktop-focused tests using Qt-friendly test helpers.
- LAN route and middleware tests.
- Performance-oriented tests for search, thumbnails, and large-library paths.

## 14. Refactor Progress Snapshot

Already improved:

- Service layer exists and is wired through `ApplicationBootstrap`.
- Several desktop panels have extracted controllers.
- LAN routes are split into modules.
- Auth/share logic has service/repository/domain separation.
- Plugin management has a service facade and startup integration.
- File operations are centralized and emit domain events.
- Thumbnail cache key generation and processing are isolated.
- Tests and static checks are currently clean.

Remaining useful directions:

- Continue moving route logic from direct core/repository calls into application services where service coverage exists.
- Continue extracting desktop panel logic into controllers for large UI classes.
- Reduce user-visible hard-coded strings by routing them through i18n helpers.
- Audit remaining fixed dimensions and ensure all are scaling-aware.
- Remove duplicate compatibility surfaces once callers are consolidated, especially overlapping auth/share methods.
- Avoid expanding abstractions unless a route, desktop panel, or test demonstrates a concrete need.

## 15. Practical Maintenance Rules

- Prefer adding behavior in application services first, then use the service from desktop and LAN callers.
- Keep Qt widgets responsible for presentation and event wiring, not business rules.
- Keep repositories limited to persistence concerns.
- Preserve per-library data isolation through `LibraryContext` and runtime path helpers.
- Publish domain events from mutating services when UI/cache/plugin listeners may care.
- For UI strings, use translation helpers from the same module pattern already present nearby.
- For fixed pixel values, use `core.ui_scale` helpers unless the value is deliberately device-independent or supplied by Qt style metrics.
- Run `ruff check .`, `pyright`, and `pytest` before treating a refactor batch as complete.
