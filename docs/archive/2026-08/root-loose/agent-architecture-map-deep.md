# Agent Architecture Map

First-read map for subagents. Use this before medium, large, or high-risk tasks.

Active project: repository root. `Project/` is an ignored backup of the pre-flattened workspace. Do not edit `Project/` unless the user explicitly asks.

## Current Baseline

- Full gate: `python -m ruff check .`, `python -m pyright`, `python -m compileall AssetsManager -q`, `python -m pytest -q`
- Last documented result: `603 passed, 0 warnings`
- Boundary guard: `tests/unit/test_architecture_boundaries.py`

Run focused checks first, then the full gate before substantial handoffs or baseline commits.

## Root Layout

| Path | Purpose | Notes |
|---|---|---|
| `AssetsManager/` | Main application package | Active source |
| `tests/` | Unit, integration, desktop, LAN, core, perf tests | Start here for regression targets |
| `docs/` | Current architecture, ADRs, testing, handoff | Read relevant docs before large/high-risk work |
| `Plugins/` | Bundled plugin examples and plugin docs | Plugin API docs live in `Plugins/Docs/` |
| `assets/` | Packaged static assets | Icons/backgrounds |
| `main.py`, `run.py` | Desktop entry points | Launch app |
| `build.py`, `AssetManager.spec` | Build/package scripts | PyInstaller path |
| `RuntimeData/` | Runtime data when app runs | Gitignored/runtime-created; do not treat as source |
| `Project/` | Backup of old workspace | Ignored; do not edit |

## Hard Dependency Rules

These are enforced by architecture tests. Do not weaken them without ADR updates.

- `domain/` must not import application, controllers, LAN, repositories, presentation, `sqlite3`, or core infrastructure modules. Current documented exception: `domain.asset` may import `core.format_utils` temporarily.
- `core/` must not grow upper-layer dependencies. Current documented exception: `core.plugins.manager` may import `application.asset_filters` temporarily.
- Non-presentation layers must not import `PySide6`.
- `lan/` must not import desktop presentation modules.
- Presentation code should use controllers or application services, not new direct DB/store access.
- `LibraryService.current` is legacy-only; new opened-library code should use `LibrarySession`.

## High-Risk Safety Annotations

| File / Area | Risk | Rule |
|---|---|---|
| `AssetsManager/lan/server.py` `_auth_middleware` | Auth bypass | Public paths and auth order are security-sensitive. Changes require LAN tests. |
| `AssetsManager/lan/security.py` | Rate/auth limiting | Keep endpoint lists consistent with auth middleware semantics. |
| `AssetsManager/lan/path_guard.py` | Path traversal | Every user-supplied LAN path must pass through `PathGuard`, `validate_path()`, or `validated_existing_key()`. Never bypass. |
| `AssetsManager/core/database.py` | Threading/SQLite | Connections use `check_same_thread=False`; writes require `db_write_lock()` or repository APIs. Reads may cross event-loop/threadpool boundaries. |
| `AssetsManager/application/bootstrap.py` | DI trap | `AuthService` and `ShareService` are not application-container singletons; LAN creates them with `db_conn` + `token_secret`. |
| `AssetsManager/application/context.py` | Session migration | `LibraryContext` is legacy-shaped runtime state; `LibrarySession` is the preferred boundary. |
| `AssetsManager/domain/auth.py` vs `AssetsManager/lan/auth.py` | Auth split | `domain/auth.py` is pure crypto. `lan/auth.py` is DB operations plus crypto re-exports. |
| `AssetsManager/application/file_operation_service.py` | Data loss / TOCTOU | Copy/move/delete changes affect real files. Add filesystem regression tests. |
| `AssetsManager/application/undo_service.py` | Cross-library lifecycle | Currently resolved as a singleton; be careful with session scoping changes. |

## Layer Map

```text
Entry: main.py / run.py -> AssetsManager/app.py -> AssetsManager/window.py
Desktop presentation: dialogs/ panels/ widgets/ dock_factory.py
LAN presentation: lan/api.py -> lan/routes/* and lan/static/
Application: application/ services, controllers/, repositories/
Domain: domain/ models, events, pure auth crypto
Infrastructure: core/ database/settings/cache/plugins, di/, lan/server.py/security/path_guard
```

## Fast Navigation

| Task Area | Start Here | Tests |
|---|---|---|
| Startup/app wiring | `AssetsManager/app.py`, `AssetsManager/window.py`, `AssetsManager/dialogs/startup.py` | `tests/desktop/`, `tests/integration/test_library_service.py` |
| DI/bootstrap | `AssetsManager/application/bootstrap.py`, `AssetsManager/di/__init__.py` | `tests/unit/test_bootstrap.py`, `tests/unit/test_container.py` |
| Library/session | `AssetsManager/application/context.py`, `AssetsManager/application/library_service.py`, `docs/adr/0002-library-session.md` | `tests/integration/test_library_service.py` |
| LAN auth/server | `AssetsManager/lan/server.py`, `AssetsManager/lan/routes/_helpers.py`, `AssetsManager/lan/routes/auth.py`, `AssetsManager/lan/routes/users.py` | `tests/lan/test_lan_api.py`, `tests/integration/test_auth_service.py` |
| LAN route add/change | `AssetsManager/lan/routes/<domain>.py`, `AssetsManager/lan/routes/__init__.py`, `AssetsManager/lan/api.py` | `tests/lan/` |
| LAN security/path | `AssetsManager/lan/path_guard.py`, `AssetsManager/lan/security.py`, `docs/lan-security.md` | `tests/lan/test_path_guard.py`, `tests/lan/test_lan_api.py` |
| Metadata/tags | `AssetsManager/application/metadata_service.py`, `AssetsManager/application/tag_service.py`, `AssetsManager/repositories/metadata_repository.py`, `AssetsManager/repositories/tag_repository.py` | `tests/integration/test_metadata_service.py`, `tests/integration/test_tag_service.py`, `tests/integration/test_repositories.py` |
| File operations/undo | `AssetsManager/application/file_operation_service.py`, `AssetsManager/application/undo_service.py`, `AssetsManager/panels/file_list/_actions.py` | `tests/integration/test_file_operation_service.py`, `tests/integration/test_undo_service.py` |
| Desktop panels | `AssetsManager/panels/`, `AssetsManager/controllers/`, `AssetsManager/panels/_event_bridge.py`, `AssetsManager/panels/_service_access.py` | `tests/desktop/`, `tests/unit/test_*controller.py` |
| Plugins | `AssetsManager/application/plugin_service.py`, `AssetsManager/core/plugins/`, `Plugins/Docs/` | `tests/integration/test_plugin_service.py`, `tests/core/test_plugins.py` |
| DB/migrations | `AssetsManager/core/database.py`, `AssetsManager/core/db_migrations.py`, `AssetsManager/repositories/` | `tests/core/test_db_migrations.py`, `tests/core/test_database_metadata.py` |
| Themes/i18n/UI scale | `AssetsManager/core/themes.py`, `AssetsManager/themes/`, `AssetsManager/i18n/`, `AssetsManager/core/ui_scale.py` | `tests/core/test_themes.py`, `tests/unit/test_ui_scale.py` |

## Common Flows

### Desktop Library Open

```text
StartupWindow.library_opened
  -> LibraryService.open_session(path)
  -> DatabaseManager.connection_for(path)
  -> LibraryContext -> LibrarySession
  -> ApplicationBootstrap.for_library(session)
  -> MainWindow and panels receive scoped services
```

New opened-library code should prefer `LibrarySession` over raw `LibraryContext`, `LibraryService.current`, or direct DB lookup.

### LAN Request

```text
HTTP request
  -> security_middleware
  -> _LanServerImpl._auth_middleware
  -> lan/api.py setup_routes()
  -> lan/routes/<domain>.py handler
  -> routes/_helpers.py accessors and PathGuard validation
  -> application service / repository
  -> response
```

LAN helpers: `get_lan()`, `get_auth_service()`, `get_request_user()`, `set_request_auth_context()`, `validate_path()`, `validated_existing_key()`.

### Domain Events

```text
Application service publishes domain event
  -> domain/event_bus.py
  -> panels/_event_bridge.py
  -> Qt signal on UI thread
  -> panel refresh handler
```

Use weak subscriptions or explicit tokens for UI owners.

## Checklists

### Add Or Change A LAN Route

1. Put handler in `AssetsManager/lan/routes/<domain>.py`.
2. Re-export handler in `AssetsManager/lan/routes/__init__.py`.
3. Register route in `AssetsManager/lan/api.py`.
4. Use `_helpers.py` for LAN accessors and auth context.
5. Validate all user paths with `validate_path()` or `validated_existing_key()`.
6. Add tests in `tests/lan/` and service/repository tests if logic belongs below the route.
7. If public/auth behavior changes, inspect `_auth_middleware` and `lan/security.py` rate-limit endpoint lists.

### Add Or Change A Service

1. Put reusable behavior in `AssetsManager/application/<name>_service.py`.
2. Put DB table access in `AssetsManager/repositories/` when practical.
3. Register long-lived app services in `ApplicationBootstrap` only when they do not require per-request runtime state.
4. Use `ConnectionProvider` or `LibrarySession` for per-library DB access.
5. Add unit/integration tests before wiring presentation or LAN code.

### Add Or Change Desktop UI Behavior

1. Keep reusable logic in controllers or application services.
2. Avoid adding direct DB/store access from `panels/`, `widgets/`, or `dialogs/`.
3. Use `panels/_service_access.py` for scoped service access.
4. Route domain events through `panels/_event_bridge.py` for Qt-thread safety.
5. Add desktop tests only when behavior cannot be tested without Qt.

## Quality Gate

Focused checks first; full gate before major handoff:

```powershell
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

Useful focused commands:

```powershell
python -m pytest tests/lan/test_lan_api.py -q
python -m pytest tests/unit/test_architecture_boundaries.py -q
python -m pytest tests/integration/test_library_service.py -q
python -m ruff check <changed paths>
```

## Open Questions / Future Work

Treat these as review items, not automatic fix instructions:

- Continue reviewing LAN error responses for internal path/exception leakage.
- Review share download counting semantics when file response serving fails after incrementing.
- Review LAN SQLite access across event loop and `asyncio.to_thread` boundaries.
- Review `FileOperationService.unique_destination()` TOCTOU behavior.
- Decide whether `UndoService` should be scoped per library/session.
- Continue shrinking presentation direct DB/store fallback allowlists.
