# Batch D Scoped Library Services Design
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

**Status:** Approved for specification review

## [S1] Problem and Scope

Batch B made covered file mutations library-scoped, but desktop presentation code still resolves services repeatedly and retains unbound fallback constructors. `LibraryService` exposes both legacy `LibraryContext` and preferred `LibrarySession` paths, while per-library database teardown is not an explicit lifecycle contract.

Batch D completes the Phase 2 scoped-services boundary:

- `LibrarySession` is the only public opened-library boundary for new code.
- `ApplicationBootstrap.for_library(session)` is the single source for a complete scoped-service bundle.
- MainWindow injects that bundle into panels on library open/switch instead of panels repeatedly resolving services.
- Covered desktop mutations fail closed without scoped services; no unbound `FileOperationService()` or `UndoService()` fallback is reachable from mutation actions.
- Undo history remains isolated per library and is tested across two simultaneously opened libraries.
- Closing one library tears down only that library's database/session resources, is idempotent, and leaves other libraries usable.

Out of scope: Phase 3 event-system convergence, full InfoPanel/FileList/Sidebar decomposition, plugin lifecycle hardening, and Phase 8 performance baselines.

## [S2] Session Boundary

`LibrarySession` remains the opened-library value passed to `ApplicationBootstrap.for_library(session)`. New application, window, panel, and test code must not depend on `LibraryContext`, `LibraryService.current`, or direct context passing. Existing legacy entry points may remain as compatibility wrappers, but they must be clearly isolated and must not be used by the new injection path.

The scoped bundle must retain the session identity and expose the services required by the desktop panels, including file operations, Undo, assets/index, metadata, tags, search, thumbnails, and project data where currently needed. The bundle must not create a second session or silently fall back to global mutable state.

## [S3] Injection and Mutation Rules

On library open or switch, MainWindow resolves the scoped bundle once and calls explicit panel injection methods such as `set_scoped_services(services)`. File-list, info, sidebar, and tag-tree panels must use the injected bundle during normal UI actions.

Mutation actions including rename, paste, drop, delete, Undo, and Redo must refuse to execute when scoped services are absent. They must never instantiate an unbound `FileOperationService()` or `UndoService()` to continue. Read-only legacy fallback behavior may remain only where it does not mutate files, metadata, thumbnails, indexes, or Undo history.

## [S4] Undo and Cross-Library Isolation

Each opened library has an independent Undo stack. An operation committed in library A must not appear in library B, and switching back to A must preserve only A's history while A remains open. Closing A discards or invalidates A's Undo service and cannot affect B's stack.

Undo and Redo must continue using the session-bound `FileOperationService` so filesystem, metadata, thumbnail, index, and event projection behavior remains consistent with Batch B.

## [S5] Database and Session Teardown

`DatabaseManager.close_library(root)` is the explicit per-library teardown operation. `LibraryService.close_session()` must first stop or detach session-bound service consumers and then close only the requested library's database connection and session resources.

Teardown requirements:

- Closing one library does not close other opened-library connections.
- Repeated close is idempotent.
- New operations against a closed session fail deterministically rather than writing through a closed connection.
- Background work captures session/runtime identity and cannot write to a closed or replaced library.
- Shutdown and library switching preserve the existing Batch A LAN/thumbnail stop-and-invalidate ordering.

## [S6] Error and Compatibility Behavior

If a panel has no scoped bundle, mutation commands return a failure result or show the existing user-facing refusal path; they must not silently mutate through global services. If teardown encounters an already-closed connection, it remains idempotent; unexpected teardown errors are surfaced through existing logging/error mechanisms without closing unrelated libraries.

Legacy `LibraryContext` APIs remain only where existing callers require them. Batch D must not add new callers or expand compatibility allowlists. Any retained fallback must be covered by an architecture-boundary test or explicitly documented as legacy-only.

## [S7] Tests and Acceptance Gates

Focused tests must cover:

- `LibrarySession`-based scoped bundle identity and one-time panel injection on library switch.
- Two-library Undo isolation, switching, closing one library, and preserving the other library's operations.
- Mutation refusal when scoped services are absent, including rename/delete/paste/drop/Undo/Redo.
- `DatabaseManager.close_library(root)` closing only the requested library and tolerating repeated close.
- Closed-session operations failing without writes, plus background work refusing stale session writes.
- Existing LAN/thumbnail shutdown ordering where lifecycle code is touched.

Before delivery, run:

```text
python -m ruff check . --exclude ".Cython&Noikta"
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
python -m pytest tests/unit/test_architecture_boundaries.py -q
```

From `webui/`, retain the Batch C gates:

```text
npm ci
npm test -- --run
npm run typecheck
npm run build
```

## [S8] Delivery Boundary

The delivery report must enumerate the exact base-to-implementation commit range, list changed lifecycle/injection files, record focused and full gate output, and disclose any remaining legacy compatibility paths. Batch D is not complete until the final implementation is reviewed against S1-S7 and the merged result passes the same gates.
