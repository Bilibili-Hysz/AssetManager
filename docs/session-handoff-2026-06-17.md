# Session Handoff - 2026-06-17

## Purpose

Use this document to migrate the current coding session to a new conversation. It summarizes the active workspace, recent changes, verification status, working rules, and recommended next task.

## Workspace

- Active repository: `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
- Active project source is at the repository root.
- `Project/` is a complete ignored backup of the old pre-flattened workspace. Do not edit it unless explicitly requested.
- Main edit targets are `AssetsManager/`, `tests/`, and `docs/`.
- Git was reinitialized at the flattened root. No initial baseline commit has been created yet.

## Current Quality Gate

Latest full gate passed:

```powershell
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

Latest result:

- Ruff: passed
- Pyright: `0 errors, 0 warnings, 0 informations`
- Compileall: passed
- Pytest: `607 passed, 1577 warnings in 17.48s`

## Current Working Rules

- Make small, low-risk fixes only after verifying the issue still exists.
- Add or update focused regression tests for behavior changes.
- Run focused tests first, then the full quality gate before handoff.
- Keep docs synchronized when test baseline or behavior changes materially.
- Do not edit `Project/`; it is a backup.
- Use `docs/agent-quick-map.md` as the first navigation doc for non-trivial work.
- Use `docs/agent-architecture-map-deep.md` for large, cross-cutting, or high-risk work.

## Subagent Strategy

- Use `explore` for codebase search, architecture mapping, and audits.
- Use `general` for contained implementation tasks after scope is clear.
- Main agent should review diffs, run quality gates, and update docs.
- Subagents should read `docs/agent-quick-map.md` first for non-trivial work.
- Subagents should also read `docs/agent-architecture-map-deep.md` for medium, large, or high-risk tasks.

## Recent Completed Work

### Architecture Refactoring (P1-P7) — 2026-06-17

Completed a 7-phase architecture refactoring focused on DI cleanup, layer boundary enforcement, and singleton deprecation:

- **P1 — SQLite Cross-Thread Safety Audit:** Audited all SQLite access patterns. Confirmed existing patterns are safe; no fixes needed.
- **P2 — Remove get_lib_db() from Services:** Removed `get_lib_db()` calls from `MetadataService`, `TagService`, and `ProjectService`. Services now receive `db_conn` through constructor injection.
- **P3 — LAN Auth Cleanup:** Cleaned `AssetsManager/lan/auth.py` from 454 lines to 81 lines by extracting registration logic into dedicated helpers.
- **P4 — DatabaseManager DI Registration:** Registered `DatabaseManager` in the DI container and deprecated the `get_manager()` singleton function with deprecation warnings.
- **P5 — Panel Fallback Removal:** Removed panel fallback paths and simplified `_service_access.py` to use direct DI resolution.
- **P6 — LibrarySession Lifecycle:** Improved `LibrarySession` with proper close cleanup and switch guard to prevent mid-switch races.
- **P7 — Architecture Boundary Tests:** Expanded `tests/unit/test_architecture_boundaries.py` to enforce all 5 layer rules: core→desktop, core→application, application→lan, desktop→lan, and presentation direct DB access.

All deprecation warnings in tests are expected and intentional — they come from legacy code paths that still call deprecated singleton functions. These will be cleaned up as downstream callers are migrated.

### Workspace And Documentation

- Flattened `Project/AssetsManager_Python_Rewrite_refactor` into the repository root.
- Preserved `Project/` as ignored backup.
- Added and maintained `docs/workspace.md`.
- Added `docs/agent-quick-map.md` as a short subagent navigation map.
- Moved the long architecture map to `docs/agent-architecture-map-deep.md`.
- Updated `.opencode/AGENTS.md`, `docs/workspace.md`, `docs/testing.md`, `docs/architecture-diagram.md`, `docs/refactor-baseline.md`, and `docs/task-handoff-2026-06-16.md` to the current baseline.

### LAN Auth Request Context

- Added typed aiohttp request keys in `AssetsManager/lan/routes/_helpers.py`:
- `AUTH_USER_REQUEST_KEY`
- `AUTH_KIND_REQUEST_KEY`
- `set_request_auth_context()`
- `get_request_user()`
- `get_request_auth_kind()`
- Replaced direct raw request dict access such as `request["user"]` and `request["auth_kind"]` in LAN auth/share/user paths.
- Added regression coverage ensuring access-key auth no longer emits `NotAppKeyWarning`.

### LAN User Cache Invalidation

- Fixed `AssetsManager/lan/routes/users.py` so `handle_toggle_user()` calls `get_lan(request).invalidate_user_cache()` after successful activate/deactivate.
- Added lower-level cache invalidation coverage.
- Added route-level HTTP regression coverage for `POST /api/users/{id}/toggle?key=...` proving the active-user cache is cleared through the actual route.
- Simplified the related tests to use `database._SCHEMA` and `init_users_table()` instead of duplicated SQL schema fragments.

### LAN Error Leakage Cleanup

- Audited LAN error response leakage using an `explore` subagent.
- Sanitized the legacy `AssetsManager/lan/auth.py` registration fallback error so it no longer returns raw exception strings.
- Replaced the path-containing `ValueError` in `AssetsManager/lan/server.py::connection_for()` with a generic mismatch message.
- Left global aiohttp error middleware out of scope because it is higher risk and should be planned separately.

### LAN Share Download Limit Semantics

- Fixed `AssetsManager/lan/routes/shares.py::handle_share_download()` to use `get_share_record()` so exhausted shares can return `403 Download limit reached` instead of being hidden as `404 Share not found`.
- Changed the download route to respect the boolean result from `share_svc.increment_download()`.
- If the atomic increment fails, the route now returns `403 Download limit reached` and does not serve the file.
- Added regression coverage for exhausted download limit behavior.
- Added regression coverage proving an atomic increment failure blocks file serving.

## Important Current Files

- `.opencode/AGENTS.md`: subagent delegation rules and prompt templates.
- `docs/agent-quick-map.md`: first-read navigation doc for subagents.
- `docs/agent-architecture-map-deep.md`: deeper architecture map for larger tasks.
- `docs/task-handoff-2026-06-16.md`: broad project handoff and long-term task list.
- `docs/workspace.md`: flattened workspace rules and quality gate.
- `docs/testing.md`: current test strategy and baseline.
- `docs/refactor-baseline.md`: historical progress table and current result.
- `AssetsManager/lan/routes/_helpers.py`: LAN request context helpers and shared route helpers.
- `AssetsManager/lan/server.py`: LAN server, auth middleware, active-user cache.
- `AssetsManager/lan/routes/users.py`: user toggle route and cache invalidation.
- `AssetsManager/lan/routes/shares.py`: share create/list/delete/download/preview/info routes.
- `AssetsManager/repositories/share_repository.py`: atomic `increment_download()` implementation.
- `AssetsManager/application/share_service.py`: share service wrapper over repository operations.
- `tests/lan/test_lan_api.py`: LAN route/security regression tests.
- `tests/integration/test_repositories.py`: repository tests including share download counter.
- `tests/integration/test_share_service.py`: share service validation tests.

## Known Remaining Work

### Recommended Next Task

Review LAN SQLite access across event-loop and threadpool boundaries.

Suggested approach:

1. Identify LAN routes that use shared `sqlite3.Connection` from both request handlers and `asyncio.to_thread`.
2. Verify whether the behavior is actually unsafe or only theoretically risky.
3. Make the smallest low-risk fix if a concrete issue is confirmed.
4. Add focused regression tests.
5. Run the full quality gate.

### Other Remaining Tasks

- Clean up deprecation warnings in tests by migrating callers from deprecated singletons (`get_manager()`, `get_store()`, `get_project_data()`, `get_library_service()`) to DI-resolved services.
- Review share download completion semantics. The route now uses atomic increment correctly, but file response serving can still fail after the counter increments.
- Review temp ZIP cleanup for all response paths and large download cancellation behavior.
- Review `/api/shares/{id}/download` and preview public semantics for passwordless shares.
- Continue reviewing LAN error responses for internal path or exception leakage beyond the already handled low-risk points.
- Review `FileOperationService.unique_destination()` TOCTOU behavior.
- Review permanent delete/backup race between backup creation and deletion.
- Review malformed URL JSON handling in `MetadataRepository`.
- Decide whether `UndoService` should be scoped per library/session instead of singleton-like scoped service resolution.
- Continue replacing presentation direct store/db access with scoped services where practical.

## New Session Prompt

```text
We are working in D:\~Vibe-Coding\Projects\AssetsManager_old-bak. The active project is flattened at the repository root; Project/ is an ignored backup and must not be edited unless explicitly requested.

Read docs/session-handoff-2026-06-17.md, docs/workspace.md, and docs/agent-quick-map.md first. For larger or high-risk tasks, also read docs/agent-architecture-map-deep.md.

Continue the bug-audit/fix work with small, low-risk changes. Verify issues before editing, add focused regression tests, run focused tests first, then run the full gate:

python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q

Latest full gate passed: 607 passed, 1577 warnings.

Recommended first task: review LAN SQLite access across event-loop and threadpool boundaries.
```
