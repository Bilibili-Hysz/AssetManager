# Batch B Task 2 Library-Bound Undo Plan: Task 3 Amendment

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/implement-approved-batch-b-task-3-only-in-d-vibe-coding-proj.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the approved Task 3 desktop paste integration by importing operating-system clipboard files through an explicit, library-destination-bound service API while retaining the existing internal-copy containment boundary.

**Architecture:** `FileOperationService` gains `copy_external_to_directory(...)`, separate from the containment-safe internal `copy_to_directory(...)`. It validates the bound library destination and owns copying, collision naming, projection refresh, and `FileCopied` publication. `ActionsMixin` only reads local system clipboard URLs when no internal clipboard state exists, partitions copy sources by library containment, invokes the scoped service paths asynchronously, aggregates errors, and refreshes once.

**Tech Stack:** Python 3, PySide6 clipboard APIs, pytest integration and desktop tests, SQLite-backed `AssetIndexService`, ruff, pyright.

## Global Constraints

- Implement approved Batch B Task 3 only; Task 2 undo/redo and backup contracts are reused as-is.
- Keep `copy_to_directory(...)` as the library-contained source API; do not add an allow-external boolean or relax its source validation.
- `copy_external_to_directory(...)` may accept external sources, but must validate the destination against the active bound/session root.
- All copying, collision resolution, projection refresh, and `FileCopied` publication remain in `FileOperationService`.
- The desktop panel must use `_get_file_operation_service()` and must not make direct filesystem mutations.
- System clipboard paste uses local URLs only when internal clipboard state is absent; external move/cut is not supported.
- Mixed copy sources are partitioned into internal and external service calls, errors are aggregated, and the panel refreshes once.
- Use focused failing-first integration tests before implementation changes.
- Run focused tests, ruff, and pyright; do not commit.

---

## Task Manifest

| id | description | acceptance | files | dependsOn |
| --- | --- | --- | --- | --- |
| T1 | Add external-copy service support and scoped desktop paste dispatch with focused TDD coverage. | External imports preserve destination containment and service-owned projections/events; internal copies retain source containment; desktop dispatch uses scoped services and system local-file URLs. | `AssetsManager/application/file_operation_service.py`, `AssetsManager/panels/file_list/_actions.py`, `tests/integration/test_file_operation_service.py`, `tests/desktop/test_file_list_shim.py` | [] |

### Task 1: Implement External Copy and Scoped Desktop Paste

**Covers:** [S8, S9, S10, S11]

**Files:**
- Modify: `AssetsManager/application/file_operation_service.py`
- Modify: `AssetsManager/panels/file_list/_actions.py`
- Modify: `tests/integration/test_file_operation_service.py`
- Modify: `tests/desktop/test_file_list_shim.py`

**Interfaces:**
- Consumes: `FileOperationResult`, `_root_for`, `_refresh_parents`, `_refresh_directory_tree`, `unique_destination`, `QApplication.clipboard()`, and `_get_file_operation_service()`.
- Produces: `FileOperationService.copy_external_to_directory(sources, destination_dir, library_root=None) -> FileOperationResult` and a service-only `ActionsMixin._paste` dispatch path for internal and external clipboard sources.

- [ ] **Step 1: Add failing focused tests for the external-copy service contract**

Cover a bound external file and directory import into a library destination,
including a same-name collision. Subscribe to `FileCopied` and assert that the
corresponding file and directory-tree index entries exist when it is observed.
Also assert that an external destination is rejected and that the existing
`copy_to_directory(...)` still rejects external sources.

Run: `pytest tests/integration/test_file_operation_service.py -k "external or copy_to_directory" -v`

Expected: FAIL because the explicit external-copy operation does not exist.

- [ ] **Step 2: Implement the narrow service operation**

Add `copy_external_to_directory(...)` beside `copy_to_directory(...)`. Reuse
the existing copy materialization, unique-destination, parent/tree refresh,
error collection, and `FileCopied` ordering, but apply root validation only to
the resolved destination. Keep `copy_to_directory(...)` unchanged so it
continues to validate every source under the library root.

Run the focused integration test from Step 1.

Expected: PASS.

- [ ] **Step 3: Add failing desktop dispatch tests**

Using the existing offscreen Qt fixture style, seed `QMimeData` with local-file
URLs and a non-local URL. With no `_clipboard_source`, assert `_paste` passes
library-contained URLs to `copy_to_directory(...)` and external URLs to
`copy_external_to_directory(...)`; verify non-local URLs are ignored. Add a
separate test that a non-empty internal clipboard state takes precedence and
does not consult external clipboard URLs. Stub the background runner and scoped
service so the test remains service-dispatch focused.

Run: `pytest tests/desktop/test_file_list_shim.py -k "paste or clipboard" -v`

Expected: FAIL because `_paste` returns before reading system clipboard URLs
and has no external-copy dispatch.

- [ ] **Step 4: Make ActionsMixin a thin asynchronous dispatcher**

When the internal clipboard is empty, extract only local file paths from
`QApplication.clipboard().mimeData().urls()`. Preserve internal cut behavior.
For copy operations, resolve paths against the active library root, partition
internal from external sources, invoke the appropriate scoped service method,
combine their `changed_paths` and errors into one result, and retain one
post-operation refresh/error presentation. Do not add direct filesystem calls
to the panel.

Run the focused desktop test from Step 3, then:

`pytest tests/integration/test_file_operation_service.py tests/desktop/test_file_list_shim.py -v`

Expected: PASS.

- [ ] **Step 5: Run static verification and inspect scope without committing**

Run: `ruff check AssetsManager/application/file_operation_service.py AssetsManager/panels/file_list/_actions.py tests/integration/test_file_operation_service.py tests/desktop/test_file_list_shim.py`

Expected: `All checks passed!`

Run: `pyright`

Expected: exit status 0 with no new errors in the changed production files.

Run: `git status --short`

Expected: Task 3 changes are limited to the scoped service, desktop action
mixin, and their focused tests, alongside pre-existing dirty worktree changes;
no `git add` or `git commit` command is run.

## Self-Review

- Spec coverage: Task 1 implements amendment requirements S8 through S11; Task 2 undo/redo requirements S1 through S7 are reused without changes.
- Scope: one cohesive task matches the medium change surface and avoids splitting service and panel behavior that must be verified together.
- Boundary consistency: the new API alone permits external sources, while `copy_to_directory(...)` remains library-source-contained and all desktop filesystem behavior remains service-backed.
