# Architecture Optimization Roadmap

Date: 2026-06-19
Scope: current root-level `AssetsManager/`, `tests/`, `docs/`, and `Plugins/` codebase.

This document records the current architecture review and an executable optimization plan. It supersedes the older archived plan in `docs/history/architecture-optimization-plan.md`, which described earlier phases that have already been partially or fully executed.

## Current Assessment

The project already has a solid migration foundation:

- `application/` contains most use-case services.
- `domain/` contains domain events, auth helpers, asset/library/share concepts, and domain errors.
- `repositories/` centralizes many SQLite table operations.
- LAN routes are split by domain under `AssetsManager/lan/routes/`.
- Desktop panels have started moving non-Qt logic into `controllers/`.
- Architecture boundary tests exist in `tests/unit/test_architecture_boundaries.py`.

The project is now in the later stage of an architectural migration. The highest-value work is not adding more layers, but closing transitional gaps and making existing boundaries consistent.

## Main Architecture Debt

### Desktop Presentation

- `AssetsManager/window.py` still coordinates library sessions, menus, LAN sharing, plugin commands, theme refresh, workspace tabs, persistence, and shutdown.
- `AssetsManager/panels/info.py` remains a large widget that includes file classification, URL discovery, directory size work, metadata display, notes/tags coordination, and background file-info tasks.
- `AssetsManager/panels/file_list/` spreads behavior across mixins and still contains operation orchestration, undo/redo wiring, context-menu handling, plugin interaction, drag rendering, keyboard handling, and background task logic.
- `AssetsManager/panels/sidebar.py` mixes tree UI, favorites/recent persistence, search, preloading, settings, keyboard shortcuts, and context menus.
- Some presentation code still depends on legacy core/store access through documented fallback allowlists.

### Application And Session Boundaries

- `LibrarySession` is the preferred opened-library boundary, but `LibraryContext`, legacy current-library state, and scoped-service fallback paths still coexist.
- `ApplicationBootstrap.for_library(session)` creates a good scoped service bundle, but panels still resolve services repeatedly through `_service_access.py` instead of receiving scoped services once on library switch.
- `UndoService` is registered as an application singleton even though undo history is library/session-specific.
- Some services are instantiated ad hoc instead of coming from DI/scoped services.

### Events

- Two event systems coexist: `domain.event_bus` for application/domain events and `core.signal_bus` for Qt signals.
- Some business events are published as domain events, while some UI refresh paths still depend on Qt signals.
- `library_opened` behavior exists in both worlds, which risks duplicate or missing notifications.

### Persistence And Repositories

- Several services still contain inline SQL that should live in repositories.
- `AuthRepository` still owns some share-link schema responsibility that belongs to `ShareRepository` or migrations.
- `DatabaseManager` manages per-library SQLite connections, but per-library teardown is not explicit.
- `check_same_thread=False` allows cross-thread SQLite use; writes are serialized, while reads rely on SQLite/WAL behavior and call-site discipline.

### LAN And Security

- Some LAN routes create services ad hoc instead of using a consistent scoped-service bundle.
- Auth and share responsibilities overlap between `AuthService` and `ShareService`.
- `/ws` is currently treated as public by the middleware pattern and needs explicit authentication if it can expose operational events.
- Download `Content-Disposition` headers should sanitize filenames.
- Query-parameter auth (`?key=`, `?token=`) leaks credentials into logs/history/referrers and should be deprecated.
- Share path checks should consistently use canonical path containment, preferably via `PathGuard`.

### Plugins

- Plugin code executes with full Python interpreter access.
- The permission model is currently advisory if permission checks only warn and do not block high-risk contributions.
- Plugin unload removes host-context contributions, but global mutations such as registered categories/theme tokens need a clear rollback strategy.

## Guiding Principles

- Prefer small verified refactors over a large rewrite.
- Shrink transitional exceptions instead of adding new compatibility paths.
- New behavior should enter through application services first, then be used by desktop and LAN callers.
- Presentation code should render UI and handle user events, not own persistence, file-system business logic, or database access.
- Domain events should represent business facts; Qt signals should be presentation transport only.
- Security fixes take priority over aesthetic cleanup.
- Each phase should include focused tests and should keep the full gate green.

## Phase 0: Baseline And Governance

Goal: lock the current baseline and make the migration rules explicit before changing architecture.

Tasks:

1. Run and record the full quality gate:
   `python -m ruff check .`
   `python -m pyright`
   `python -m compileall AssetsManager -q`
   `python -m pytest -q`
2. Treat `tests/unit/test_architecture_boundaries.py` as a migration ratchet. Remove allowlist entries as code is cleaned up; do not expand them without an ADR update.
3. Document target boundaries:
   `LibrarySession` is the opened-library boundary.
   `ApplicationBootstrap.for_library(session)` is the desktop scoped-service source.
   LAN handlers use `LanScopedServices` or application services.
   Repositories own SQL.
4. Add or update ADR notes when changing lifecycle, event, plugin, or LAN exposure rules.

Acceptance criteria:

- Full gate passes before refactoring starts.
- No new architecture-boundary exceptions are introduced.
- Each future phase has focused tests identified before implementation.

## Phase 1: LAN And Plugin Security

Goal: reduce externally exploitable risk before broad structural cleanup.

Tasks:

1. Authenticate WebSocket connections.
   Files: `AssetsManager/lan/server.py`, `AssetsManager/lan/routes/websocket.py`, `AssetsManager/lan/ws.py`.
   Remove `/ws` from unauthenticated behavior or validate token/cookie/header in the WebSocket handler before accepting.
2. Add WebSocket connection management.
   Add a max connection limit, heartbeat/ping behavior, and cleanup for dead clients even when no broadcasts occur.
3. Sanitize download filenames.
   Files: `AssetsManager/lan/routes/downloads.py`, `AssetsManager/lan/routes/shares.py`.
   Add a shared helper that strips control characters, quotes, and backslashes, and uses RFC 5987-style `filename*=` for non-ASCII names where appropriate.
4. Deprecate query-parameter auth.
   File: `AssetsManager/lan/routes/_helpers.py`.
   First log warnings for `?key=` and `?token=`, then remove them in a later compatibility-breaking pass.
5. Normalize share path validation.
   Files: `AssetsManager/lan/path_guard.py`, `AssetsManager/lan/routes/shares.py`, `AssetsManager/domain/share.py`.
   Use canonical path containment checks consistently. Avoid relying on string prefix checks for access decisions.
6. Decide plugin trust model.
   Files: `AssetsManager/core/plugins/host_context.py`, `AssetsManager/core/plugins/loader.py`, `AssetsManager/core/plugins/manager.py`, `Plugins/Docs/`.
   Either document plugins as fully trusted local code, or make high-risk permissions block actions instead of only logging warnings.

Acceptance criteria:

- LAN tests cover WebSocket auth, share scope traversal, download header safety, and query-auth deprecation behavior.
- Plugin tests cover denied high-risk contributions if enforcement is chosen.
- User-facing plugin docs no longer imply stronger isolation than the code provides.

## Phase 2: Library Session And Scoped Services

Goal: make opened-library state and services explicit and per-session.

Tasks:

1. Make `LibrarySession` the only public opened-library boundary.
   Files: `AssetsManager/application/context.py`, `AssetsManager/application/library_service.py`.
   Keep `LibraryContext` internal or legacy-only. Remove direct context passing from new code.
2. Replace repeated panel service lookup with library-switch injection.
   Files: `AssetsManager/window.py`, `AssetsManager/panels/_service_access.py`, `AssetsManager/panels/info.py`, `AssetsManager/panels/tag_tree.py`, `AssetsManager/panels/file_list/`.
   On library switch, resolve `LibraryScopedServices` once and pass it to panels with methods such as `set_scoped_services(services)`.
3. Scope `UndoService` per library.
   Files: `AssetsManager/application/undo_service.py`, `AssetsManager/application/bootstrap.py`, `AssetsManager/panels/file_list/_actions.py`.
   Either create one undo service per `LibraryScopedServices` bundle or key undo stacks by library root.
4. Remove ad-hoc service instantiation in presentation code.
   Files: `AssetsManager/panels/file_list/_actions.py` and other panel files.
   Use injected scoped services instead of `FileOperationService()`, `UndoService()`, or fallback service constructors.
5. Add explicit per-library database teardown.
   Files: `AssetsManager/core/database.py`, `AssetsManager/application/library_service.py`.
   Add `DatabaseManager.close_library(root)` and call it from session/library-close paths when appropriate.

Acceptance criteria:

- Panels no longer open sessions just to resolve services during normal UI actions.
- `UndoService` behavior is covered for switching between two libraries.
- Architecture-boundary fallback allowlists shrink.
- Closing one library does not require closing all library database connections.

## Phase 3: Event System Convergence

Goal: eliminate split-brain behavior between domain events and Qt signals.

Tasks:

1. Treat `domain.event_bus` as the source of business events.
   Mutating application services publish file, tag, metadata, share, plugin, and library events there.
2. Treat `core.signal_bus` as presentation transport only.
   It may continue handling UI-local signals such as current selection, theme refresh, language refresh, and navigation while migration continues.
3. Expand `panels/_event_bridge.py` into the single bridge from domain events to Qt-thread UI notifications.
4. Remove duplicate `library_opened` emission paths.
   Prefer publishing from `LibraryService` and bridging to UI.
5. Add tests for event bridge behavior.

Acceptance criteria:

- A business mutation is published once as a domain event.
- Desktop UI refresh paths receive domain events through one bridge.
- Tests cover file operation events, metadata/tag events, and library-opened events.

## Phase 4: Repository And Database Boundary Cleanup

Goal: move table logic behind repositories and reduce direct database access outside infrastructure.

Tasks:

1. Move inline SQL out of services.
   Files: `AssetsManager/application/tag_service.py`, `AssetsManager/application/search_service.py`, `AssetsManager/application/project_service.py`.
   Candidate repository methods include tag counts, files by tag, cached file counts, and file-meta cache writes.
2. Move share schema responsibility out of `AuthRepository`.
   Files: `AssetsManager/repositories/auth_repository.py`, `AssetsManager/repositories/share_repository.py`, migrations.
   `ShareRepository` or migrations should own `share_links` schema.
3. Clarify database locking policy.
   File: `AssetsManager/core/database.py`.
   Short term: document which operations must hold `db_write_lock()` and ensure all writes comply.
   Medium term: consider per-library locks or read/write lock semantics for worker/LAN-heavy paths.
4. Retire legacy singleton access paths gradually.
   Files: `AssetsManager/core/database.py`, `AssetsManager/core/tag_store.py`, `AssetsManager/core/project_data.py`.
   Remove usage of `get_lib_db()`, `get_manager()`, `get_store()`, and `get_project_data()` from presentation as scoped services replace them.

Acceptance criteria:

- Application services do not gain new raw SQL.
- Repository tests cover moved queries.
- Architecture tests prevent direct presentation DB/store access outside the shrinking transitional allowlist.

## Phase 5: LAN Service Organization

Goal: make LAN route handlers thin, consistent, and testable.

Tasks:

1. Extend `LanScopedServices`.
   File: `AssetsManager/lan/routes/_helpers.py`.
   Add typed fields for `share_service`, `search_service`, `thumbnail_service`, and `asset_service` where appropriate.
2. Remove per-request ad-hoc service creation.
   Files: `AssetsManager/lan/routes/shares.py`, `AssetsManager/lan/routes/system.py`, `AssetsManager/lan/routes/files.py`, `AssetsManager/lan/routes/metadata.py`, `AssetsManager/lan/routes/thumbnails.py`.
3. Consolidate share-link management into `ShareService`.
   Files: `AssetsManager/application/auth_service.py`, `AssetsManager/application/share_service.py`.
   Keep `AuthService` focused on users, auth tokens, login, invites, and access validation.
4. Replace middleware skip-list with a less fragile public-endpoint declaration.
   File: `AssetsManager/lan/server.py`.
   Avoid complex path/method boolean expressions for auth bypass decisions.
5. Add total-size limits for batch ZIP downloads.
   File: `AssetsManager/lan/routes/downloads.py`.

Acceptance criteria:

- LAN routes primarily validate requests, call services, and format responses.
- Share/auth responsibilities no longer overlap in new code.
- Public endpoint behavior is covered by regression tests.

## Phase 6: Desktop UI Decomposition

Goal: make large widgets thin and move reusable behavior into testable controllers/services.

Tasks:

1. Split `InfoPanel`.
   Files: `AssetsManager/panels/info.py`, `AssetsManager/controllers/info_controller.py`.
   Move URL discovery, directory classification, directory size work, plugin metadata parsing, and file-info loading into controller/service helpers.
2. Move file operation orchestration from file-list UI into controller code.
   Files: `AssetsManager/panels/file_list/_actions.py`, `AssetsManager/controllers/file_list_controller.py`.
   Inject `FileOperationService` and scoped `UndoService`.
3. Extract file-list UI helpers.
   Files: `AssetsManager/panels/file_list/_base.py`, `AssetsManager/panels/file_list/__init__.py`.
   Candidates: drag preview renderer, shortcut dispatcher, background task runner, breadcrumb builder.
4. Add a `SidebarController`.
   File: `AssetsManager/panels/sidebar.py`.
   Move favorites/recent operations, search filtering, preloading coordination, and settings persistence out of the widget.
5. Reduce `MainWindow` by coordinators.
   File: `AssetsManager/window.py`.
   Extract low-risk areas first: plugin menu, sharing, workspace switching, theme refresh.
6. Remove module-level UI side effects.
   File: `AssetsManager/dock_factory.py`.
   Replace import-time signal connections and global dock state with explicit lifecycle management.

Acceptance criteria:

- New behavior in panels is covered through controller/service tests when possible.
- UI widgets do not gain new direct file-system/database business logic.
- File-list, info, and sidebar classes shrink through behavior extraction, not by hiding complexity in untested helpers.

## Phase 7: Plugin Lifecycle Hardening

Goal: prevent stale plugin state and make plugin behavior predictable.

Tasks:

1. Enforce or honestly document plugin permissions.
2. Track global mutations caused by plugin category/theme-token registration.
3. Restore or remove plugin-owned global contributions on unload.
4. Wrap plugin command/menu/file-handler execution in consistent error handling with plugin IDs in logs.
5. Add tests for enable, disable, unload, contribution cleanup, and permission denial/warning behavior.

Acceptance criteria:

- Disabling or unloading a plugin does not leave stale commands, menu items, categories, or theme tokens.
- Plugin failures do not crash the host unless explicitly configured.
- Documentation matches actual isolation guarantees.

## Phase 8: Performance Baselines

Goal: protect the core user experience for large asset libraries.

Focus areas:

1. Directory listing.
   `AssetService._scan_dir_summary()` can produce N+1 directory scans. Consider lazy summaries, cached directory stats, or index-backed counts/previews.
2. Thumbnail resolution.
   Audit global thumbnail caches and multi-library behavior. Record cold and warm cache timings.
3. Search.
   Prefer indexed search through `AssetIndexService` where possible, with clear fallback behavior.
4. LAN endpoints.
   Track `/api/files`, `/api/search`, and `/api/thumbnails/batch` latency.
5. Batch downloads.
   Track memory and temp-disk usage, not only request count.

Suggested metrics:

- 1k and 10k file directory listing time.
- First-screen thumbnail cold-load time.
- Thumbnail hot-cache response time.
- LAN `/api/files` P50/P95.
- Search P50/P95.
- Batch ZIP size and creation-time limits.

Acceptance criteria:

- Performance tests have thresholds or recorded baselines.
- Optimizations include before/after numbers.
- Large-library regressions are visible before release.

## Recommended Execution Order

1. Phase 1: LAN/WebSocket/download/plugin security.
2. Phase 2: `LibrarySession`, scoped services, and scoped undo.
3. Phase 3: event system convergence.
4. Phase 5: LAN scoped-service organization and auth/share cleanup.
5. Phase 4: repository/database boundary cleanup.
6. Phase 6: desktop UI decomposition.
7. Phase 7: plugin lifecycle hardening.
8. Phase 8: performance baselines and optimization.

## First Five Implementation Tasks

1. Authenticate `/ws`, add connection limits, and add heartbeat cleanup.
2. Add a safe download filename helper and apply it to all download responses.
3. Make `UndoService` library/session-scoped.
4. Resolve `LibraryScopedServices` once on library switch and inject them into panels.
5. Add `ShareService` to LAN scoped services and stop using `AuthService` for share-link management in new code.

## Quality Gate

Run focused checks first for each change set. Before treating a phase as complete, run:

```powershell
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

Always include:

```powershell
python -m pytest tests/unit/test_architecture_boundaries.py -q
```

for architecture-facing changes.
