# ADR 0002: Library Session Boundary

Date: 2026-06-15

## Status

Accepted.

## Context

AssetManager now has explicit per-library `LibraryContext` objects and library-scoped application services, but the runtime model is still transitional:

- `DatabaseManager` still owns shared SQLite connections and mutable current-library state.
- `LibraryContext` exposes raw infrastructure objects such as `db_conn`, `tag_store`, and `project_data`.
- Some application services can still be constructed without a scoped provider and fall back to global DB lookup.
- Desktop panels now prefer scoped bootstrap services, but a small bootstrap-free fallback allowlist remains for isolated panel use.

The next architecture step is to introduce a stable session boundary that represents an opened library and owns all scoped runtime resources for that library.

## Decision

Introduce `LibrarySession` as the target public boundary for opened-library runtime state.

`LibrarySession` should become the object passed to desktop, LAN, and service-bootstrap entry points when code needs to operate on an opened library. It should wrap, rather than immediately replace, the existing `LibraryContext` during migration.

The target session responsibilities are:

- Identify the opened library root and runtime directories.
- Provide a scoped `ConnectionProvider` that rejects mismatched roots.
- Expose library-scoped application services or a service bundle, not raw DB ownership.
- Own close/shutdown semantics for per-library subscriptions, caches, and scoped resources added later.
- Keep presentation code independent from `DatabaseManager.current` and raw SQLite connection lookup.

The target non-responsibilities are:

- It must not become a second service locator for application-wide singletons.
- It must not expose mutable global current-library state.
- It must not own desktop widgets, Qt objects, or LAN request objects.
- It must not bypass repositories or application services for new feature code.

## Migration Plan

1. Add `LibrarySession` as a thin wrapper around `LibraryContext` and existing scoped service creation. Done: `LibrarySession` currently delegates to `LibraryContext` without changing ownership semantics.
2. Change `ApplicationBootstrap.for_library(...)` to accept `LibrarySession` once call sites can be migrated without churn. Done: it now accepts only `LibrarySession`; callers must open a session before requesting scoped services.
3. Move desktop `library_opened` paths from raw `LibraryContext` access to session-scoped APIs. In progress: the shared presentation scoped-service lookup, `MainWindow` open/switch flows, app startup library-open flow, scoped-service consumers, and application-layer tests now open or use a `LibrarySession` before accessing active library resources. `LibraryService.open_session` now has explicit cache reuse, multi-library isolation, mismatched-root rejection, and `current_session` lifecycle coverage.
4. Move LAN per-library setup to session-scoped services where request handlers need shared scoped runtime. In progress: the desktop LAN sharing toggle now opens a `LibrarySession` before constructing `LanServer`.
5. Remove no-provider service fallbacks after tests and direct legacy callers use explicit sessions/providers. In progress: `LibrarySession.close()` and `LibraryService.close_session()` now provide explicit session lifecycle management; presentation fallback allowlist is guarded by architecture tests.
6. Reduce `LibraryContext` to an internal construction detail, then remove direct raw DB exposure from presentation paths.

Each step must keep the full quality gate passing and should be guarded by architecture tests where practical.

## Rules For New Work

- New opened-library code should accept a `LibrarySession` unless it is still directly constructing or adapting legacy `LibraryContext` resources.
- Do not add new `DatabaseManager.current`, `get_lib_db(...)`, `get_store(...)`, or `get_project_data(...)` access from presentation code.
- Application-layer tests that only need an initialized library should use `LibraryService.open_session(...)`; direct `open_library(...)` calls are reserved for `LibraryService`, core database, and compatibility tests that specifically cover that API.
- Architecture boundary tests now enforce that `open_library(...)` stays inside the documented boundaries.
- `LibraryService.current` is documented as legacy-only in code; new callers should use `LibraryService.current_session` and the boundary tests enforce this.
- Do not add new application service constructors that silently fall back to global current-library state.
- New per-library subscriptions and caches must have an explicit close path owned by the session or by a shorter-lived presentation object.
- Existing bootstrap-free test compatibility is allowed only in documented fallback paths and should not expand.
- Domain layer must not import `sqlite3` or core infrastructure modules (`database`, `tag_store`, `project_data`, `settings`, `singleton`). Architecture boundary tests enforce this.
- `LibraryService.open_library()` must not have TOCTOU races — the entire cache-check + context-creation must be atomic under the lock.

## Consequences

- The current `LibraryContext` remains valid during migration, but it is no longer the long-term public boundary.
- The session boundary gives desktop and LAN a common vocabulary for opened-library lifecycle.
- The migration can proceed incrementally without changing persisted data or user-visible behavior.
- Some constructors and tests still expose context-shaped resources while legacy internals converge, but bootstrap scoped-service entry points now require sessions and `LibraryService.current_session` is the preferred current-library read API for new callers.

## Open Questions

- ~~Whether `LibrarySession.close()` should close the shared SQLite connection or only session-owned resources while `DatabaseManager` still owns connection pooling.~~ Resolved: `close()` marks the session as closed and `LibraryService.close_session()` removes the cached context. The shared `db_conn` is **not** closed here because connection lifetime is still managed by `DatabaseManager`. Closing is idempotent.
- Whether the session should expose a service bundle directly or expose a method that asks `ApplicationBootstrap` to build scoped services.
- How multi-library desktop workflows should represent multiple simultaneous sessions if that feature is added later.
