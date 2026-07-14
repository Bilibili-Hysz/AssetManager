# Architecture Refactoring Plan

Date: 2026-06-17

## [S1] Goal and Constraints

**End state:** Every layer depends on the layer below only through well-defined interfaces. No legacy global-function fallbacks, no duplicate code, no implicit cross-thread access.

**Quality gate (must pass after every step):**
```
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q  # 603 passed, 0 warnings
```

**Strategy:** Bottom-up, 7 phases. Each phase is independently committable and can be paused/resumed at any time.

## [S2] Phase Overview

| Phase | Topic | Core Change | Risk |
|-------|-------|-------------|------|
| P1 | SQLite cross-thread safety | Audit + fix LAN thread boundaries | High |
| P2 | Application layer cleanup | Services use ConnectionProvider uniformly | Low |
| P3 | lan/auth.py cleanup | Merge duplicate DB operations | Medium |
| P4 | Singleton global function removal | Replace get_manager/get_store with DI | Medium |
| P5 | Panel layer decoupling | Remove fallback paths | Medium |
| P6 | Session lifecycle | LibraryContext/LibrarySession clarification | Low |
| P7 | Architecture boundary tests | Enforce layer rules | Low |

**Dependencies:** P1 standalone, P2 depends on P1, P3 standalone, P4 depends on P2, P5 depends on P4, P6 depends on P5, P7 validates all.

## [S3] P1 — SQLite Cross-Thread Safety

**Problem:** `_LanServerImpl` creates `sqlite3.Connection(check_same_thread=False)` shared across three contexts:
1. Qt main thread (via `LibrarySession.db_conn`)
2. LAN aiohttp event loop thread (`_startup()` calls `init_users_table()`)
3. `asyncio.to_thread()` thread pool (`handle_files` → `_list()`)

WAL mode allows concurrent reads, `db_write_lock()` protects writes, but we must confirm:
- Connection is not closed by Qt main thread while server is running
- `handle_files` → `AssetService().list_directory()` does not write via the connection
- `_has_active_users()` cache query is safe from the event loop thread

**Scope:**
- Audit all LAN route DB access paths
- Confirm `connection_for()` always returns the same connection in LAN context
- Add regression tests verifying concurrent read safety
- If concrete issues found, apply minimal fixes

## [S4] P2 — Application Layer Cleanup

**Problem:** `MetadataService`, `TagService`, `ProjectService` constructors accept optional `ConnectionProvider` but fall back to `get_lib_db()`:

```python
# MetadataService._connection()
if self._connection_provider is not None:
    return self._connection_provider(root)
return get_lib_db(root)  # ← fallback path
```

This masks missing dependency injection.

**Scope:**
- Remove `get_lib_db()` fallback from the three services
- Require callers to provide `ConnectionProvider` (via `ApplicationBootstrap.for_library()` or LAN's `_build_lan_services()`)
- Update all call sites that instantiate these services directly (tests, LAN routes, etc.)

## [S5] P3 — lan/auth.py Cleanup

**Problem:** `lan/auth.py` contains ~200 lines of DB operations (`register_user`, `authenticate_user`, `list_users`, `create_share_link`, `get_share_link`, etc.) that duplicate `AuthRepository` + `ShareRepository`.

**Scope:**
- `lan/auth.py` retains only re-exports (`from AssetsManager.domain.auth import ...`) and `init_users_table()`
- Migrate `register_user()`, `authenticate_user()`, `list_users()` etc. to `AuthRepository` (partially exists)
- Migrate `create_share_link()`, `get_share_link()` etc. to `ShareRepository` / `ShareService`
- `lan/server.py` `_startup()` uses `AuthRepository.init_tables()` instead
- Ensure all LAN routes access data through `AuthService` / `ShareService`

## [S6] P4 — Singleton Global Function Removal

**Problem:** These global functions are still called by panels and some services:
- `get_manager()` → `DatabaseManager` singleton
- `get_store(root)` → `TagStore` singleton
- `get_project_data(root)` → `ProjectData` singleton
- `get_library_service()` → `LibraryService` singleton

Panels bridge through `_service_access.py` but fallback paths indicate incomplete DI migration.

**Scope:**
- Panels access services exclusively through `get_scoped_services()` / `require_scoped_services()`
- `ApplicationBootstrap` registers all needed services
- Remove `ThreadSafeSingleton` usage from `DatabaseManager`, `LibraryService` (managed by DI container)
- Keep `get_manager()` etc. as deprecated wrappers until all call sites migrate
- Final removal of deprecated wrappers

## [S7] P5 — Panel Layer Decoupling

**Problem:** Panels have fallback paths:

```python
# _base.py
if self._lib_root and has_bootstrap():
    raise RuntimeError(...)
# fallback: uses get_store(root)
```

```python
# info.py
scoped = warn_scoped_services(...)
if scoped is not None:
    return scoped.session.tag_store
if has_bootstrap():
    raise RuntimeError(...)
# fallback: get_store(self._library_root)
```

These are migration intermediates — when bootstrap exists, scoped services should be mandatory; when absent (tests), explicit test doubles should be used.

**Scope:**
- Remove all `has_bootstrap()` + fallback paths from panels
- With bootstrap: enforce `require_scoped_services()`
- Without bootstrap (tests): inject mock/test doubles via constructor
- Simplify `_service_access.py` to only provide `get_scoped_services()` and `require_scoped_services()`

## [S8] P6 — Session Lifecycle

**Problem:** `LibraryContext` and `LibrarySession` relationship is unclear:
- `LibrarySession.close()` only sets `_closed = True`, does not close resources
- `LibraryService.close_session()` removes from cache but does not close connection
- Connection lifecycle managed by `DatabaseManager.close()`
- Library switch (`_on_switch_library`) does not close old session

**Scope:**
- `LibrarySession.close()` closes session-owned resources (e.g., TagStore cache)
- `MainWindow._on_switch_library()` closes old session before opening new one
- `LibraryService.close_session()` triggers session close and cache cleanup
- Add `LibrarySession.is_closed` guard preventing use of closed session

## [S9] P7 — Architecture Boundary Tests

**Problem:** Existing `tests/unit/test_architecture_boundaries.py` may not cover all boundary rules.

**Scope:**
- Expand architecture tests covering every layer rule:
  - `domain/` does not import `application/`, `lan/`, `panels/`, `sqlite3`, `core/` infrastructure
  - `application/` does not import `PySide6`, `lan/`, `panels/`
  - `repositories/` depends only on `core/database.py` and `domain/`
  - `lan/` does not import `PySide6`, `panels/`, `controllers/`
  - `panels/` does not directly import `sqlite3` or call `get_lib_db()`
- Tests serve as regression guards preventing future violations
