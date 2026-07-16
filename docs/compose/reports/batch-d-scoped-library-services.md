# Batch D Scoped Library Services Report

## Delivery Range

- Base: `efe0c42` (`fix: repair merged webui test dependencies`)
- Requested initial implementation HEAD: `9f376fc` (`fix: drain scoped work before library teardown`)
- Verified implementation endpoint: `855700717b0246df433eeac4dd55cb92de025800` (`fix: reject closed callback sessions`)
- Implementation review range: `efe0c42..8557007`
- The final architecture/report commit is intentionally outside the implementation endpoint.
- The approved anchor documents `docs/compose/specs/2026-07-15-batch-d-scoped-library-services-design.md` and `docs/compose/plans/2026-07-15-batch-d-scoped-library-services.md` were untracked in the source worktree and are absent from this isolated branch. This report maps the approved S1-S8 contract without claiming those anchors are tracked here.

## S1-S8 Mapping

| Section | Delivered behavior | Primary evidence |
| --- | --- | --- |
| S1 | New opened-library flows use `LibrarySession`; `LibraryContext` construction remains internal to `LibraryService`. | `AssetsManager/application/context.py`, `AssetsManager/application/library_service.py`, `tests/integration/test_library_service.py` |
| S2 | `ApplicationBootstrap.for_library(session)` accepts only its exact live canonical session and binds the complete service bundle to that identity. No second session/context is created by the bundle factory. | `AssetsManager/application/bootstrap.py`, `AssetsManager/application/library_service.py`, `tests/unit/test_bootstrap.py` |
| S3 | MainWindow resolves one bundle and injects it into file-list, info, sidebar, and tag-tree panels. Presentation lookup can only reuse the already-open current session and cannot open a library as a side effect. | `AssetsManager/window.py`, `AssetsManager/panels/_service_access.py`, `AssetsManager/panels/file_list/_base.py`, `AssetsManager/panels/info.py`, `AssetsManager/panels/sidebar.py`, `tests/desktop/test_scoped_service_access.py` |
| S4 | Undo is cached per canonical session identity, shared by consumers of that bundle, and cleaned only by the bootstrap session-close listener. Closing a panel no longer destroys the bootstrap-owned Undo service. | `AssetsManager/application/bootstrap.py`, `AssetsManager/application/undo_service.py`, `AssetsManager/panels/file_list/_base.py`, `tests/integration/test_undo_service.py`, `tests/desktop/test_file_list_shim.py` |
| S5 | Session close rejects new work, drains active operations, closes only the requested library connection, is idempotent, serializes same-root reopen, and rejects same-thread close from inside an active lease instead of deadlocking. | `AssetsManager/application/context.py`, `AssetsManager/application/library_service.py`, `tests/core/test_database_metadata.py`, `tests/integration/test_library_service.py` |
| S6 | Covered file-list mutations fail closed without an injected bundle. Production presentation code contains no `FileOperationService()` or `UndoService()` constructor. The architecture test now ratchets this invariant. | `AssetsManager/panels/file_list/_actions.py`, `AssetsManager/panels/file_list/_base.py`, `tests/desktop/test_file_list_shim.py`, `tests/unit/test_architecture_boundaries.py` |
| S7 | Session-bound service operations hold leases; thumbnail generations drain before teardown; InfoPanel flushes pending notes before switch; the whole async file-info task holds its originating session lease, preventing post-close repository work. | `AssetsManager/application/context.py`, scoped application services, `AssetsManager/panels/file_list/_loader.py`, `AssetsManager/panels/info.py`, `AssetsManager/window.py`, `tests/desktop/test_thumbnail_loader.py`, `tests/unit/test_window_session_switching.py` |
| S8 | The exact range was reviewed for mutation fallbacks, `LibraryContext`/`.current` growth, stale writes, and Phase 3/6/7/8 scope creep. Focused, full Python, architecture, and retained WebUI gates passed. | This report and the evidence below |

## Changed Lifecycle And Injection Files

Application/session lifecycle:

- `AssetsManager/application/bootstrap.py`
- `AssetsManager/application/context.py`
- `AssetsManager/application/file_operation_service.py`
- `AssetsManager/application/library_service.py`
- `AssetsManager/application/metadata_service.py`
- `AssetsManager/application/project_service.py`
- `AssetsManager/application/tag_service.py`
- `AssetsManager/application/undo_service.py`

Presentation injection and stale-work lifecycle:

- `AssetsManager/panels/_service_access.py`
- `AssetsManager/panels/file_list/_actions.py`
- `AssetsManager/panels/file_list/_base.py`
- `AssetsManager/panels/file_list/_loader.py`
- `AssetsManager/panels/info.py`
- `AssetsManager/panels/sidebar.py`
- `AssetsManager/window.py`

Regression coverage:

- `tests/core/test_database_metadata.py`
- `tests/desktop/test_file_list_details.py`
- `tests/desktop/test_file_list_shim.py`
- `tests/desktop/test_scoped_service_access.py`
- `tests/desktop/test_thumbnail_loader.py`
- `tests/integration/test_library_service.py`
- `tests/integration/test_undo_service.py`
- `tests/unit/test_bootstrap.py`
- `tests/unit/test_window_session_switching.py`
- `tests/unit/test_architecture_boundaries.py` in the final architecture/report commit

## Architecture Audit

- Production `FileOperationService()` and `UndoService()` construction occurs only in `ApplicationBootstrap.for_library()`.
- Production `LibraryContext()` construction occurs only inside `LibraryService`; no presentation code consumes `LibraryContext`.
- No production code reads deprecated `LibraryService.current`; the only allowed reads are its two compatibility tests.
- Presentation scoped lookup no longer calls `open_session()` and therefore cannot create a context, change current-library state, or publish `LibraryOpened`.
- File-list read paths no longer construct `DatabaseManager` or `TagStore` when injection is absent.
- The presentation DB/store call allowlist was narrowed from seven entries to two. The import allowlist was narrowed from seven entries to three.
- Retained call exceptions are `sidebar_favorites.set_library_root -> get_library_dir` and `sidebar_recent.set_library_root -> get_library_dir`.
- Retained import exceptions are the two sidebar dialog database imports and `InfoPanel`'s existing read-only `ProjectData.compute_dir_size` fallback.
- No allowlist was broadened to hide a Batch D violation.

## Verification Evidence

Focused Batch D regressions after final fixes:

```text
python -m pytest tests/unit/test_architecture_boundaries.py tests/unit/test_bootstrap.py tests/integration/test_library_service.py tests/integration/test_undo_service.py tests/desktop/test_file_list_shim.py tests/desktop/test_scoped_service_access.py tests/desktop/test_thumbnail_loader.py tests/unit/test_window_session_switching.py tests/core/test_database_metadata.py -q
150 passed in 16.13s
```

Additional explicit-injection regression after the full-suite finding:

```text
python -m pytest tests/desktop/test_file_list_details.py -q
18 passed in 1.92s
```

Python gates:

```text
python -m ruff check . --exclude ".Cython&Noikta"
All checks passed!

python -m pyright
0 errors, 0 warnings, 0 informations
Pyright also printed a non-failing update notice: v1.1.410 -> v1.1.411.

python -m compileall AssetsManager -q
(no output, exit 0)

python -m pytest -q
876 passed in 63.02s (0:01:03)

python -m pytest tests/unit/test_architecture_boundaries.py -q
16 passed in 5.22s
```

WebUI gates, run before the final full Python suite so `webui/dist` was present:

```text
npm ci
added 237 packages, and audited 238 packages in 22s
5 vulnerabilities (3 moderate, 1 high, 1 critical)

npm test -- --run
17 passed test files; 57 passed tests; duration 17.28s

npm run typecheck
tsc --noEmit (exit 0)

npm run build
1621 modules transformed; built in 9.40s
dist/index.html 0.81 kB (gzip 0.44 kB)
dist/assets/index-C07LYIce.css 24.04 kB (gzip 5.24 kB)
dist/assets/index-COj95Eix.js 262.61 kB (gzip 79.57 kB)
```

Diff hygiene:

```text
git diff --check efe0c42..8557007
(no errors, exit 0)
```

## Review Findings Resolved

- Removed panel ownership of the bootstrap-owned Undo service.
- Flushed and stopped pending note saves before old-session teardown.
- Removed session-opening side effects from presentation service lookup.
- Removed the file-list database/store constructor fallback.
- Bound the complete async file-info task to its originating session lease.
- Bound async directory-size cache work to its originating session lease.
- Guarded synchronous `LibraryOpened` callbacks from accessing a closed or root-mismatched stale bundle before replacement injection, including same-root reopen.
- Rejected reentrant same-thread session close rather than waiting on itself.
- Updated desktop tests to explicitly open and inject scoped bundles.
- Added a constructor ratchet for presentation mutation services and removed stale architecture exceptions.

## Residual Legacy Compatibility

- `LibraryService.open_library()` and `LibraryService.current` remain deprecated compatibility APIs returning/exposing `LibraryContext`; architecture tests prevent new use.
- `get_library_service()` remains a deprecated singleton helper for legacy/test callers.
- `MainWindow._library_service()` and `LanSharingMixin._library_service()` retain pre-existing singleton fallback behavior when QApplication bootstrap wiring is absent. Normal scoped injection does not use those fallbacks.
- `InfoController` and `TagTreeController` retain pre-existing optional service constructors for isolated legacy/controller call sites; the normal panel injection path supplies scoped services.
- The two sidebar dialog database helpers and InfoPanel's read-only `ProjectData.compute_dir_size` fallback remain documented architecture exceptions.
- These residuals are not used to continue covered file-list mutations without scoped services.

## Scope Review And Nonclaims

- Phase 3: no event-system convergence was implemented. Existing `LibraryOpened` publication remains.
- Phase 6: no broad desktop decomposition was implemented. Panel edits are limited to scoped injection, lifecycle ownership, and stale-work safety.
- Phase 7: no plugin lifecycle hardening was implemented. Plugin repository work was only enclosed in the existing InfoPanel task's session lease.
- Phase 8: no performance baseline or optimization claim is made. Thumbnail task tracking exists solely to prevent stale-session work during teardown.
- No claim is made that all legacy singleton/service-locator APIs were removed.
- No claim is made that all read-only presentation infrastructure fallbacks were removed.
- No manual GUI exploratory test, installer/package test, deployment test, or multi-process stress test was performed.
- `npm ci` reported five dependency vulnerabilities; this Batch D work did not change dependencies or claim to remediate them.
- The WebUI build emitted hashed assets as recorded above; generated `webui/dist` files are ignored and are not part of the commit.
