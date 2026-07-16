# Batch D Scoped Library Services Report

## Delivery Range

- Base: `efe0c42` (`fix: repair merged webui test dependencies`)
- Requested initial implementation HEAD: `9f376fc` (`fix: drain scoped work before library teardown`)
- Final implementation endpoint: `e8d0a60a1c364f21e7af76450c0809d46bc23ec7` (`fix: reject stale scoped UI completions`)
- Implementation review range: `efe0c42..e8d0a60`. This commit span contains the intervening architecture/report commit `2091669`, so it is a delivery-review range rather than an implementation-only diff.
- Exact topology is linear: implementation fixes through `8557007`, then the architecture/report commit `2091669`, then lifecycle atomicity fixes `9d5c8e4`, then async identity/single-injection fixes `e8d0a60` at `HEAD`.
- Complete delivery range: `efe0c42..e8d0a60`, including the prior architecture/report commit and all later implementation fixes.
- The approved anchor documents `docs/compose/specs/2026-07-15-batch-d-scoped-library-services-design.md` and `docs/compose/plans/2026-07-15-batch-d-scoped-library-services.md` were untracked in the source worktree and are absent from this isolated branch. This report maps the approved S1-S8 contract without claiming those anchors are tracked here.

## S1-S8 Mapping

| Section | Delivered behavior | Primary evidence |
| --- | --- | --- |
| S1 | New opened-library flows use `LibrarySession`; `LibraryContext` construction remains internal to `LibraryService`. | `AssetsManager/application/context.py`, `AssetsManager/application/library_service.py`, `tests/integration/test_library_service.py` |
| S2 | `ApplicationBootstrap.for_library(session)` accepts only its exact live canonical session and binds the complete service bundle to that identity. No second session/context is created by the bundle factory. | `AssetsManager/application/bootstrap.py`, `AssetsManager/application/library_service.py`, `tests/unit/test_bootstrap.py` |
| S3 | MainWindow resolves one bundle and injects it into file-list, info, sidebar, and tag-tree panels. File-list accepts an already-injected matching bundle without reinjecting it, while presentation lookup can only reuse the already-open current session and cannot open a library as a side effect. | `AssetsManager/window.py`, `AssetsManager/panels/_service_access.py`, `AssetsManager/panels/file_list/_base.py`, `AssetsManager/panels/info.py`, `AssetsManager/panels/sidebar.py`, `tests/desktop/test_scoped_service_access.py` |
| S4 | Undo is cached per canonical session identity, shared by consumers of that bundle, and cleaned only by the bootstrap session-close listener. Closing a panel no longer destroys the bootstrap-owned Undo service. | `AssetsManager/application/bootstrap.py`, `AssetsManager/application/undo_service.py`, `AssetsManager/panels/file_list/_base.py`, `tests/integration/test_undo_service.py`, `tests/desktop/test_file_list_shim.py` |
| S5 | Session close rejects new work, drains active operations, closes only the requested library connection, is idempotent, serializes same-root reopen, and rejects same-thread close from inside an active lease instead of deadlocking. `9d5c8e4` also serializes whole-service teardown with per-session teardown, including sessions already removed from the active map. | `AssetsManager/application/context.py`, `AssetsManager/application/library_service.py`, `tests/unit/test_bootstrap.py`, `tests/core/test_database_metadata.py`, `tests/integration/test_library_service.py` |
| S6 | Covered file-list mutations fail closed without an injected bundle. Production presentation code contains no `FileOperationService()` or `UndoService()` constructor. The architecture test now ratchets this invariant. | `AssetsManager/panels/file_list/_actions.py`, `AssetsManager/panels/file_list/_base.py`, `tests/desktop/test_file_list_shim.py`, `tests/unit/test_architecture_boundaries.py` |
| S7 | Session-bound service operations hold leases; thumbnail generations drain before teardown; InfoPanel flushes pending notes before switch; the whole async file-info task holds its originating session lease, preventing post-close repository work. `e8d0a60` tags file-info, preview, and directory-size completions with a generation, session identity, and path so stale work cannot render after navigation or same-root reopen. | `AssetsManager/application/context.py`, scoped application services, `AssetsManager/panels/file_list/_loader.py`, `AssetsManager/panels/info.py`, `AssetsManager/window.py`, `tests/desktop/test_thumbnail_loader.py`, `tests/desktop/test_info_async_identity.py`, `tests/unit/test_window_session_switching.py` |
| S8 | The complete delivery range was reviewed for mutation fallbacks, `LibraryContext`/`.current` growth, stale writes, and Phase 3/6/7/8 scope creep. Final controller gates passed for Python quality, compilation, the full suite, architecture boundaries, and the retained WebUI checks. | This report and the evidence below |

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
- `tests/desktop/test_info_async_identity.py`
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

Final controller verification completed against the delivery endpoint `e8d0a60a1c364f21e7af76450c0809d46bc23ec7` before this report-only commit.

Python gates:

```text
python -m ruff check . --exclude ".Cython&Noikta"
All checks passed!

python -m pyright
0 errors, 0 warnings, 0 informations

python -m compileall AssetsManager -q
(no output, exit 0)

python -m pytest -q
885 passed in 66.19s

python -m pytest tests/unit/test_architecture_boundaries.py -q
16 passed in 10.10s
```

WebUI gates:

```text
npm test -- --run
17 passed test files; 57 passed tests

npm run typecheck
tsc --noEmit (exit 0)

npm run build
1621 modules transformed; built in 16.46s
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
- Serialized service-wide teardown against individual-session close/reopen work, including an in-flight removed session (`9d5c8e4`).
- Bound asynchronous InfoPanel completions to a generation, exact session object, and path; retained a single matching FileList injection during normal switching (`e8d0a60`).
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
