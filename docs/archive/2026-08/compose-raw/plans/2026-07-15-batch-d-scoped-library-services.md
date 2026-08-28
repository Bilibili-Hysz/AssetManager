# Batch D Scoped Library Services Implementation Plan
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the Phase 2 library/session boundary so desktop panels consume one session-bound service bundle, mutations fail closed without it, Undo remains isolated per library, and one library can be closed without closing others.

**Architecture:** Keep `LibrarySession` as the opened-library boundary and make `ApplicationBootstrap.for_library(session)` the only new scoped-service factory. Inject the resulting bundle once from MainWindow into panels; keep legacy `LibraryContext` and fallback constructors only as isolated compatibility paths. Add explicit per-library database teardown and session-closed guards without expanding Batch D into event convergence or broad UI decomposition.

**Tech Stack:** Python 3.14, PySide6, SQLite, pytest, ruff, pyright, existing React/Vite WebUI gates.

## Global Constraints

- `LibrarySession` is the only public opened-library boundary for new code.
- `ApplicationBootstrap.for_library(session)` is the single source for a complete scoped-service bundle.
- Covered desktop mutations must refuse to execute when scoped services are absent and must never instantiate an unbound `FileOperationService()` or `UndoService()` fallback.
- Closing one library must not close other opened-library connections; repeated close must be idempotent.
- Background work must not write to a closed or replaced library.
- Batch D does not include Phase 3 event-system convergence, full InfoPanel/FileList/Sidebar decomposition, plugin lifecycle hardening, or Phase 8 performance baselines.
- New behavior uses TDD: write a focused failing regression, run it RED, implement the smallest fix, then run it GREEN.
- Before delivery run Python Ruff, Pyright, compileall, full pytest, architecture-boundary tests, and the existing WebUI npm test/typecheck/build gates.

---

### Task 1: Make Session-Scoped Bundle Identity Explicit

**Covers:** [S1, S2]

**Files:**
- Modify: `AssetsManager/application/context.py`
- Modify: `AssetsManager/application/bootstrap.py`
- Modify: `AssetsManager/application/library_service.py`
- Modify: `tests/unit/test_bootstrap.py`
- Modify: `tests/integration/test_library_service.py`
- Create or modify: `tests/unit/test_architecture_boundaries.py`

**Interfaces:**
- Consumes: existing `LibrarySession`, `LibraryContext`, `ApplicationBootstrap.for_library()`, and `LibraryService.open_session()` APIs.
- Produces: a scoped bundle whose `session` is the exact input object, no second session/context creation, and no new `LibraryContext` callers in new code.

- [ ] **Step 1: Add a failing identity test** that creates a `LibrarySession`, passes it to `ApplicationBootstrap.for_library(session)`, and asserts `scoped.session is session`, every session-bound repository uses `session.db_conn`, and no global current-library lookup occurs.
- [ ] **Step 2: Run `python -m pytest tests/unit/test_bootstrap.py tests/integration/test_library_service.py -q`** and confirm the new identity/legacy-boundary assertion fails against the current implementation.
- [ ] **Step 3: Implement the smallest session-bound bundle change**. Keep `LibraryContext` compatibility wrappers intact, but make new bootstrap/library-service code pass the existing session object through without reconstructing or resolving a second context.
- [ ] **Step 4: Add an architecture assertion** that new scoped application/presentation paths do not import or call `LibraryService.current`/`LibraryContext` except the documented compatibility modules. Do not expand the allowlist; narrow it if the implementation permits.
- [ ] **Step 5: Run the focused tests GREEN** and inspect the bundle fields for session-root consistency.
- [ ] **Step 6: Commit** with `git add AssetsManager/application/context.py AssetsManager/application/bootstrap.py AssetsManager/application/library_service.py tests/unit/test_bootstrap.py tests/integration/test_library_service.py tests/unit/test_architecture_boundaries.py && git commit -m "refactor: make scoped bundles session-bound"`.

### Task 2: Inject Scoped Services Into Desktop Panels

**Covers:** [S3, S6]

**Files:**
- Modify: `AssetsManager/window.py`
- Modify: `AssetsManager/panels/_service_access.py`
- Modify: `AssetsManager/panels/info.py`
- Modify: `AssetsManager/panels/sidebar.py`
- Modify: `AssetsManager/panels/tag_tree.py`
- Modify: `AssetsManager/panels/file_list/_actions.py`
- Modify: `AssetsManager/panels/file_list/_base.py`
- Modify: `AssetsManager/panels/file_list/__init__.py`
- Test: `tests/desktop/test_file_list_shim.py`
- Test: `tests/desktop/test_file_list_model.py`
- Test or create: `tests/desktop/test_panel_scoped_services.py`

**Interfaces:**
- Consumes: the session-bound scoped bundle from Task 1.
- Produces: explicit `set_scoped_services(services)` injection on mutation-capable panels; normal actions use the stored bundle; absent bundle returns the existing refusal path without constructing unbound mutation services.

- [ ] **Step 1: Add failing tests** for MainWindow/panel injection on library open or switch and for rename, paste, drop, delete, Undo, and Redo refusing to execute when the bundle is absent. Assert no `FileOperationService()` or `UndoService()` constructor is reached in those paths.
- [ ] **Step 2: Run focused desktop tests** with `python -m pytest tests/desktop/test_file_list_shim.py tests/desktop/test_file_list_model.py tests/desktop/test_panel_scoped_services.py -q` and confirm RED.
- [ ] **Step 3: Add one explicit panel injection entry point per panel** and have MainWindow call those methods exactly once per active library bundle. Store the bundle rather than resolving through `_service_access.py` on every action.
- [ ] **Step 4: Replace mutation fallback resolution** in file-list actions/base with a scoped-service check that returns the existing failure/refusal result. Leave read-only compatibility helpers untouched unless they are required to avoid constructing mutation services.
- [ ] **Step 5: Run focused desktop tests GREEN**, then run the full desktop suite to catch Qt signal/lifecycle regressions.
- [ ] **Step 6: Commit** with `git add AssetsManager/window.py AssetsManager/panels tests/desktop && git commit -m "refactor: inject library services into panels"`.

### Task 3: Enforce Per-Library Undo Isolation

**Covers:** [S4, S6, S7]

**Files:**
- Modify: `AssetsManager/application/undo_service.py`
- Modify: `AssetsManager/application/bootstrap.py`
- Modify: `AssetsManager/panels/file_list/_actions.py`
- Modify: `AssetsManager/application/library_service.py`
- Test: `tests/integration/test_undo_service.py`
- Test: `tests/unit/test_bootstrap.py`
- Test: `tests/desktop/test_file_list_shim.py`

**Interfaces:**
- Consumes: Task 1 session-bound scoped bundle and Task 2 injected panel services.
- Produces: one Undo service per open library/session, independent stacks across two libraries, and invalidation/discard of a closed library's stack without affecting another library.

- [ ] **Step 1: Add failing two-library tests**: perform a file mutation in library A and B, assert each Undo service sees only its own history, switch active library, and assert Undo/Redo uses the active session's service.
- [ ] **Step 2: Add a failing close test** that closes A, verifies A's Undo service rejects further operations, and verifies B's mutation can still Undo/Redo.
- [ ] **Step 3: Run `python -m pytest tests/integration/test_undo_service.py tests/unit/test_bootstrap.py tests/desktop/test_file_list_shim.py -q`** and confirm RED.
- [ ] **Step 4: Key Undo service lifecycle to the session identity/root** and make `LibraryService.close_session()` invalidate and detach only that service. Keep Batch B success-first execution and session-bound FileOperationService delegation unchanged.
- [ ] **Step 5: Run focused tests GREEN**, then run the complete integration/desktop Undo tests.
- [ ] **Step 6: Commit** with `git add AssetsManager/application/undo_service.py AssetsManager/application/bootstrap.py AssetsManager/application/library_service.py AssetsManager/panels/file_list/_actions.py tests/integration/test_undo_service.py tests/unit/test_bootstrap.py tests/desktop/test_file_list_shim.py && git commit -m "fix: isolate undo history per library session"`.

### Task 4: Add Explicit Per-Library Database Teardown

**Covers:** [S5, S6, S7]

**Files:**
- Modify: `AssetsManager/core/database.py`
- Modify: `AssetsManager/application/context.py`
- Modify: `AssetsManager/application/library_service.py`
- Modify: `AssetsManager/window.py`
- Test: `tests/core/test_database.py` or existing database test module
- Test: `tests/integration/test_library_service.py`
- Test: `tests/unit/test_window_session_switching.py`

**Interfaces:**
- Consumes: Task 1 session identity, Task 3 per-library Undo lifecycle, and existing Batch A LAN/thumbnail switch ordering.
- Produces: `DatabaseManager.close_library(root)`, idempotent session close, selective connection teardown, and deterministic closed-session rejection.

- [ ] **Step 1: Add failing database tests** that open libraries A and B, call `close_library(A)`, assert A's connection is closed/unavailable, B's connection remains usable, and repeated `close_library(A)` does not raise.
- [ ] **Step 2: Add failing session tests** that call `LibraryService.close_session(A)` twice and assert session-bound operations fail without touching B or writing A after close.
- [ ] **Step 3: Add a failing background-work test** using the existing thumbnail or file-index task boundary: capture A's session identity, close A, run the completion path, and assert no repository/index write occurs after closure.
- [ ] **Step 4: Run focused tests RED** with `python -m pytest tests/core/test_database.py tests/integration/test_library_service.py tests/unit/test_window_session_switching.py -q`.
- [ ] **Step 5: Implement `close_library(root)`** under the existing database lock/connection registry. Mark the session closed before cleanup, close only the requested connection, make repeated close a no-op, and expose a deterministic closed-state check to session-bound services.
- [ ] **Step 6: Wire close ordering** so LAN/thumbnail invalidation and scoped-service detachment occur before database/session close, preserving Batch A behavior and avoiding unrelated-library shutdown.
- [ ] **Step 7: Run focused tests GREEN**, then run all lifecycle, thumbnail, file-operation, and database tests.
- [ ] **Step 8: Commit** with `git add AssetsManager/core/database.py AssetsManager/application/context.py AssetsManager/application/library_service.py AssetsManager/window.py tests/core tests/integration/test_library_service.py tests/unit/test_window_session_switching.py && git commit -m "feat: close individual library database sessions"`.

### Task 5: Final Boundary Ratchet, Report, and Delivery Verification

**Covers:** [S1, S2, S3, S4, S5, S6, S7, S8]

**Files:**
- Modify: `tests/unit/test_architecture_boundaries.py`
- Create: `docs/compose/reports/batch-d-scoped-library-services.md`
- Modify only if required by focused verification: relevant implementation/test files from Tasks 1-4

**Interfaces:**
- Consumes: all prior scoped bundle, panel injection, Undo, and teardown contracts.
- Produces: final architecture ratchet, complete evidence report, and verified Batch D implementation endpoint.

- [ ] **Step 1: Run the architecture boundary test** and identify every remaining panel mutation fallback or new `LibraryContext`/global-service access. Remove only Batch D-scoped exceptions; do not hide violations by broadening allowlists.
- [ ] **Step 2: Run focused regression groups**:
  `python -m pytest tests/unit/test_bootstrap.py tests/integration/test_library_service.py tests/integration/test_undo_service.py tests/desktop/test_file_list_shim.py tests/unit/test_window_session_switching.py -q`.
- [ ] **Step 3: Run the full Python gate**:
  `python -m ruff check . --exclude ".Cython&Noikta"`;
  `python -m pyright`;
  `python -m compileall AssetsManager -q`;
  `python -m pytest -q`;
  `python -m pytest tests/unit/test_architecture_boundaries.py -q`.
- [ ] **Step 4: Run retained WebUI gates** from `webui/`: `npm ci`, `npm test -- --run`, `npm run typecheck`, `npm run build`.
- [ ] **Step 5: Write `docs/compose/reports/batch-d-scoped-library-services.md`** with exact base-to-implementation range, changed lifecycle/injection files, S1-S8 mapping, focused/full command output, residual legacy paths, and explicit non-claims for manual/package/deployment tests.
- [ ] **Step 6: Review the full diff** for scope creep into Phase 3/6/7/8, stale-session writes, fallback constructors, and incorrect report endpoints.
- [ ] **Step 7: Commit** with `git add tests/unit/test_architecture_boundaries.py docs/compose/reports/batch-d-scoped-library-services.md && git commit -m "docs: finalize Batch D scoped services report"`.

## Self-Review

- Spec coverage: [S1] Tasks 1 and 5; [S2] Tasks 1 and 5; [S3] Task 2 and 5; [S4] Task 3 and 5; [S5] Task 4 and 5; [S6] Tasks 2-4 and 5; [S7] Tasks 3-5; [S8] Task 5.
- No `TBD`, `TODO`, or unassigned spec sections are present.
- Interfaces are consistent: Task 1 defines session-bound bundle identity; Task 2 injects it; Task 3 scopes Undo to it; Task 4 closes it selectively; Task 5 ratchets and reports the complete range.
- Explicitly excluded: event convergence, full widget decomposition, plugin lifecycle, and performance baselines.
