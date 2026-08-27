# Development Rules

These rules are mandatory for new refactor work.

- UI code must not write SQLite directly unless it is legacy code waiting for migration.
- UI code must not construct `RuntimeData` paths directly; use path resolver or `LibraryContext`.
- New database access should prefer `LibrarySession` once available, or `LibraryContext` plus explicit per-root APIs (`connection_for`, `data_dir_for`, `thumb_dir_for`) during migration, over mutable current-library state.
- LAN routes must validate every user-supplied path through a central path guard before touching the file system.
- Database schema changes must use a migration and include tests.
- Cross-thread SQLite writes must use the shared database write lock or repository APIs.
- New features should have an application service entry point before desktop or LAN presentation code calls them.
- Do not add new cross-module access to private `MainWindow`, panel, or widget attributes.
- Background workers must have a shutdown or cancellation path.
- Preserve existing user-visible behavior unless a migration or behavior change is explicitly documented.
- Prefer small, reversible changes over broad rewrites.

## Naming

- Application services use `*Service` names.
- Long-lived per-library state is currently represented by `LibraryContext`; the target public boundary is `LibrarySession` per ADR 0002.
- Presentation code may depend on application services; application services must not depend on PySide6 widgets.
- LAN routes should parse HTTP inputs, call application services, and shape HTTP responses. They should not own reusable browsing or metadata logic.
- File mutations should go through `FileOperationService` or a repository/service wrapper so metadata migration, conflict naming, and undo integration remain consistent.
- New LAN route handlers go in the appropriate `AssetsManager/lan/routes/` module. Shared helpers (path validation, auth token extraction, ZIP building) go in `routes/_helpers.py`. The parent `api.py` only imports handlers and registers them in `setup_routes()`.
- `format_size` and other cross-layer formatting utilities live in `AssetsManager/core/format_utils.py`, not in `lan/utils.py`.

### Path Naming Convention

| Name | Meaning | Example |
|------|---------|---------|
| `library_root` | Root directory of the opened asset library | `/assets/lib1` |
| `current_path` | Currently browsed directory or file | `/assets/lib1/characters/hero` |
| `selected_path` | Currently selected item in UI | `/assets/lib1/hero.png` |
| `target_path` | Operation target (rename, move, delete) | `/assets/lib1/hero_v2.png` |
| `rel_path` | Relative path from library root (LAN/API) | `characters/hero.png` |

### Event Naming Convention

| Signal/Event | Payload | Source |
|-------------|---------|--------|
| `library_opened(root)` | Library root path | `window.py`, `startup.py` |
| `directory_changed(current_path)` | Current browsing directory | `file_list/_navigation.py`, `sidebar.py` |
| `file_focused(file_info)` | Selected file info | `file_list` |
| `FileSystemChanged` | Session-bound file projection change | `FileOperationService` |
| `AssetTagsChanged` / `TagCatalogChanged` | Session-bound asset or tag catalog change | `TagService` |
| `AssetNotesChanged` / `AssetUrlsChanged` | Session-bound asset metadata change | `MetadataService` |

**Rule**: `library_opened` carries library roots; `directory_changed` carries browsing paths. Never conflate the two.

### Domain Events And Qt Signals

- Application services publish immutable domain events through `EventBus`; desktop panels consume them only through `panels/_event_bridge.py`, which forwards them to the Qt thread.
- New panel refresh logic must use session-scoped events (`FileSystemChanged`, `AssetTagsChanged`, `TagCatalogChanged`, `AssetNotesChanged`, `AssetUrlsChanged`) and must filter on the active `session_token` before mutating UI state.
- Legacy unscoped events (`FileCreated`, `FileRenamed`, `FileDeleted`, `FileCopied`, `TagsChanged`, `NotesChanged`, `UrlsChanged`) remain a plugin and compatibility API. Do not add panel subscriptions to them.
- `core.signal_bus` is for Qt-only presentation coordination such as navigation, focus, theme, language, and UI scale. It is not a replacement for application mutation events.

## New Feature Entry Rules

New features should follow this path:
- Desktop UI → controller/service → application service → repository/core
- LAN route → route helper/service → application service → repository/core

Prohibited:
- UI must not access DB directly
- LAN must not import desktop modules
- Application layer must not import Qt
- Library-rooted operations must use `LibrarySession` / `ConnectionProvider`

## Documentation Structure

| Document | Purpose |
|----------|---------|
| `docs/full-review/` | 带日期、commit 和 manifest 的审计快照；不是当前工作区权威。当前事实以代码、测试和 CI 配置为准。 |
| `docs/architecture.md` | Current architecture facts |
| `docs/architecture-diagram.md` | Architecture diagrams |
| `docs/workspace.md` | Current flattened workspace layout and backup policy |
| `docs/development.md` | Development rules (this file) |
| `docs/testing.md` | Testing strategy |
| `docs/lan-security.md` | LAN security model |
| `docs/migrations.md` | DB migration notes |
| `docs/adr/*.md` | Architecture Decision Records |
| `docs/history/` | Historical snapshots (refactor plans, summaries) |
