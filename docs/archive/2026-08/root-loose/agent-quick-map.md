# Agent Quick Map

Default first-read map for subagents. For large or high-risk work, also read `docs/agent-architecture-map-deep.md`.

## Ground Rules

- Active project is the repository root.
- `Project/` is an ignored backup. Do not edit it unless explicitly asked.
- Prefer small, low-risk changes with regression tests.
- Current gate: `603 passed, 0 warnings`.
- Architecture guard: `tests/unit/test_architecture_boundaries.py`.

## Quality Gate

```powershell
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

Run focused checks first, then the full gate before major handoffs.

## Layer Rules

- `domain/` is pure domain. No application, LAN, presentation, `sqlite3`, or core infrastructure imports except documented exceptions.
- `application/` holds use-case services. No Qt imports.
- `repositories/` own DB table access.
- `lan/` is aiohttp presentation plus server infrastructure. No desktop imports.
- `panels/`, `widgets/`, `dialogs/` are desktop presentation. Avoid adding direct DB/store access.
- New opened-library code should prefer `LibrarySession` over `LibraryContext` or `LibraryService.current`.

## Fast Paths

| Task | Start Here | Tests |
|---|---|---|
| LAN auth/users | `AssetsManager/lan/server.py`, `AssetsManager/lan/routes/_helpers.py`, `AssetsManager/lan/routes/auth.py`, `AssetsManager/lan/routes/users.py` | `tests/lan/test_lan_api.py`, `tests/integration/test_auth_service.py` |
| LAN route/security | `AssetsManager/lan/routes/`, `AssetsManager/lan/api.py`, `AssetsManager/lan/path_guard.py`, `docs/lan-security.md` | `tests/lan/` |
| Library/session | `AssetsManager/application/context.py`, `AssetsManager/application/library_service.py`, `docs/adr/0002-library-session.md` | `tests/integration/test_library_service.py` |
| Metadata/tags | `AssetsManager/application/metadata_service.py`, `AssetsManager/application/tag_service.py`, `AssetsManager/repositories/` | `tests/integration/test_metadata_service.py`, `tests/integration/test_tag_service.py` |
| File operations/undo | `AssetsManager/application/file_operation_service.py`, `AssetsManager/application/undo_service.py` | `tests/integration/test_file_operation_service.py`, `tests/integration/test_undo_service.py` |
| Desktop panels | `AssetsManager/panels/`, `AssetsManager/controllers/`, `AssetsManager/panels/_event_bridge.py` | `tests/desktop/`, `tests/unit/test_*controller.py` |
| Plugins | `AssetsManager/application/plugin_service.py`, `AssetsManager/core/plugins/`, `Plugins/Docs/` | `tests/integration/test_plugin_service.py`, `tests/core/test_plugins.py` |
| DB/migrations | `AssetsManager/core/database.py`, `AssetsManager/core/db_migrations.py`, `AssetsManager/repositories/` | `tests/core/test_db_migrations.py` |

## High-Risk Notes

- LAN paths: use `PathGuard`, `validate_path()`, or `validated_existing_key()`. Never bypass.
- LAN auth: `_auth_middleware` in `lan/server.py` is security-sensitive.
- LAN routes: add handler, export it from `lan/routes/__init__.py`, register it in `lan/api.py`, then test it.
- DB: SQLite connections use `check_same_thread=False`; writes need `db_write_lock()` or repository APIs.
- DI: `AuthService` and `ShareService` are not normal app-container singletons; LAN creates them with `db_conn` and `token_secret`.
- Auth split: `domain/auth.py` is pure crypto; `lan/auth.py` is DB operations plus crypto re-exports.

## Common Flows

```text
Desktop open library:
StartupWindow -> LibraryService.open_session() -> LibrarySession -> ApplicationBootstrap.for_library() -> panels
```

```text
LAN request:
HTTP -> security_middleware -> _auth_middleware -> lan/api.py -> lan/routes/<domain>.py -> service/repository
```

```text
Domain event to UI:
service publishes event -> domain/event_bus.py -> panels/_event_bridge.py -> Qt signal -> panel refresh
```
