# Batch B Task 2: Library-Bound Undo Service Specification

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/implement-approved-batch-b-task-3-only-in-d-vibe-coding-proj.md)

## Context

`FileOperationService` is now library-session aware. Its `move(...)` operation
migrates path metadata, refreshes asset-index projections, and emits
`FileRenamed`; its `delete_permanent(...)` operation clears metadata,
thumbnail, and index projections before emitting `FileDeleted`. `UndoService`
still reverses operations with direct `os`, `shutil`, and raw stack mutation,
so undo/redo bypasses those projections and can lose an entry when execution
fails.

Batch B Task 2 changed application services only. This amendment assigns the
remaining desktop panel integration and its narrowly required external-import
service operation to Batch B Task 3. The completed Task 2 undo/redo routing,
backup handling, and history contracts are reused without modification.

## File Map

| File | Responsibility |
| --- | --- |
| `AssetsManager/application/file_operation_service.py` | Provide a bound restore API that materializes a permanent-delete backup and reconciles the resulting index/event projection. |
| `AssetsManager/application/undo_service.py` | Delegate committed undo/redo execution to `FileOperationService` and mutate history only after a successful operation. |
| `tests/integration/test_undo_service.py` | Exercise application-service undo/redo behavior against a real library session and its database/index projections. |
| `tests/integration/test_file_operation_service.py` | Cover the restore API's filesystem, projection, and event contract if focused coverage is clearer there. |
| `AssetsManager/panels/file_list/_actions.py` | Dispatch clipboard paste through scoped file-operation services and read external local-file URLs only when the panel has no internal clipboard state. |
| `tests/desktop/test_file_list_shim.py` | Prove clipboard URL extraction and internal/external service dispatch without direct panel filesystem mutation. |

## Requirements

### S1. Bound execution interface

`UndoService` must expose these application-facing methods:

```python
def perform_undo(
    self,
    file_operations: FileOperationService,
    library_root: str | Path | None = None,
) -> bool: ...

def perform_redo(
    self,
    file_operations: FileOperationService,
    library_root: str | Path | None = None,
) -> bool: ...
```

The caller passes the library-bound `FileOperationService` created by
`ApplicationBootstrap.for_library(...)`. The optional root is forwarded for
unbound callers and must remain compatible with `FileOperationService` root
validation. The methods return `False` for an empty source stack or a failed
operation and `True` only after both filesystem/projection execution and the
corresponding stack transition succeed.

### S2. Rename and move reversal

Undoing a `rename` record must call
`file_operations.move(entry.new, entry.old, library_root=library_root)`.
Redoing it must call
`file_operations.move(entry.old, entry.new, library_root=library_root)`.
`UndoService` must not call `os.rename` for these committed flows. This makes
metadata migration, index refresh, root enforcement, and `FileRenamed` event
publishing identical to normal file operations.

### S3. Failure-safe history transitions

`perform_undo` must inspect the most recent undo entry, execute its reversal,
then move that same entry from undo to redo only on success. On failure, the
undo entry remains available, the redo stack is unchanged, and the target path
is not changed by `UndoService`.

`perform_redo` follows the mirror rule: execute from the top redo entry first,
then move it to undo only on success. On failure, redo remains available and
undo remains unchanged. Catch expected filesystem/service operation failures
and return `False`; do not silently report success.

### S4. Permanent-delete backup reconciliation

Add the smallest `FileOperationService` API needed to materialize an
`UndoEntry` backup at its original destination. Its proposed shape is:

```python
def restore_permanent(
    self,
    backup: str | Path,
    destination: str | Path,
    is_dir: bool,
    library_root: str | Path | None = None,
) -> FileOperationResult: ...
```

The method must validate the destination against the bound/session root,
restore a file via `shutil.copy2` or a directory via `shutil.copytree`, refresh
the destination parent and restored directory tree in the asset index, and
publish `FileCreated(path=..., is_dir=...)` only after reconciliation. Existing
metadata and thumbnail projections were intentionally removed by the original
permanent delete and must remain absent rather than becoming stale references.

Undo of a `delete` entry calls `restore_permanent(...)`; redo calls
`delete_permanent([entry.path], library_root=library_root)`. A result with any
errors is a failed undo/redo operation. `UndoService` must not use raw
`shutil.copy*`, `os.remove`, or `shutil.rmtree` for these committed flows.

### S5. Compatibility and ownership boundaries

Keep `UndoEntry`, `record_rename`, `record_delete`, `can_undo`, `can_redo`,
`peek_undo`, `peek_redo`, `clear`, `clear_redo`, and `cleanup` behavior and
signatures compatible. Continue cleaning backup artifacts when history is
evicted or cleared. Do not edit desktop UI, panels, or Task 3-owned action
wiring.

### S6. Focused integration coverage

Add failing-first then passing integration tests that prove:

1. A library-bound undo rename returns the file to its old path, migrates its
   tag/metadata path back, removes the new index entry, and recreates the old
   index entry.
2. A forced undo move failure retains the undo entry and leaves redo empty; a
   forced redo permanent-delete failure retains the redo entry and leaves undo
   unchanged. The affected filesystem target remains unchanged in each case.
3. Undoing a recorded permanent delete materializes the backup, has no stale
   metadata or thumbnail row/file, restores index entries, and publishes
   `FileCreated` after those projections are coherent. Redoing it removes the
   data and reconciles metadata, thumbnails, index, and `FileDeleted` exactly
   like a normal permanent delete.

### S7. Verification

Run the focused integration tests, then run:

```powershell
ruff check AssetsManager/application/undo_service.py AssetsManager/application/file_operation_service.py tests/integration/test_undo_service.py tests/integration/test_file_operation_service.py
pyright
```

Do not commit this task's changes.

## Amendment: Batch B Task 3 Desktop Paste Integration

### S8. Explicit external-copy service boundary

Add a separately named `FileOperationService` operation for importing external
filesystem sources into a library directory. Its proposed shape is:

```python
def copy_external_to_directory(
    self,
    sources: list[str | Path],
    destination_dir: str | Path,
    library_root: str | Path | None = None,
) -> FileOperationResult: ...
```

The method validates `destination_dir` against the bound/session library root,
but deliberately does not validate each source against that root. For every
successful file or directory copy, it must use the established unique-name
behavior, refresh the destination parent and copied directory tree as needed,
and publish `FileCopied` only after the projection is coherent. It returns
changed paths and per-source errors using `FileOperationResult`.

`copy_to_directory(...)` remains the internal-library copy API and must retain
its source containment check. Do not introduce an `allow_external_sources`
flag or otherwise relax that contract.

### S9. Scoped desktop clipboard dispatch

`ActionsMixin._paste` remains a thin asynchronous caller. When
`_clipboard_source` is non-empty, it retains the existing internal copy/cut
behavior. When it is empty, it reads local-file URLs from
`QApplication.clipboard().mimeData().urls()` and ignores non-local URLs.

For copy paste, partition sources relative to the active library root: call
`copy_to_directory(...)` for library-contained sources and
`copy_external_to_directory(...)` for external sources. Aggregate all returned
errors and refresh the panel once when the background work completes. Cut
operations must continue to use only the internal clipboard state and
`move_to_directory(...)`; operating-system clipboard URLs do not authorize an
external move.

The panel must not import `shutil` or perform direct filesystem copies. It
obtains the library-scoped service through `_get_file_operation_service()` and
passes the active root where required by the existing service boundary.

### S10. Focused Task 3 coverage

Add failing-first then passing tests that prove:

1. `copy_external_to_directory(...)` imports an external file and a directory
   below a bound library destination, resolves a collision with the same
   unique-name rule as internal copies, reindexes the imported paths, and
   publishes `FileCopied` after reconciliation.
2. The same external-copy API rejects a destination outside the active library
   while the existing `copy_to_directory(...)` continues rejecting an external
   source.
3. Desktop paste extracts local file URLs from the system clipboard only when
   there is no internal clipboard state, dispatches library-contained and
   external sources to their distinct scoped service operations, and does not
   use direct `os` or `shutil` file operations.

### S11. Task 3 verification

Run focused service and desktop tests first, then:

```powershell
ruff check AssetsManager/application/file_operation_service.py AssetsManager/panels/file_list/_actions.py tests/integration/test_file_operation_service.py tests/desktop/test_file_list_shim.py
pyright
```

Do not commit.

## Non-Goals

- Outside the narrowly scoped clipboard-paste dispatch in
  `AssetsManager/panels/file_list/_actions.py`, do not modify desktop UI.
- Do not alter undo stack depth, library isolation, backup cleanup, or record
  APIs beyond what is required for failure-safe execution.
- Do not recreate deleted tag metadata or thumbnails from a filesystem-only
  backup; the durable contract is projection reconciliation, not preservation
  of data deliberately removed at permanent delete time.
- Do not alter Task 2 undo/redo APIs, backup behavior, or history semantics.
- Do not support external cut/move operations or non-local clipboard URLs.
- Do not broaden the existing internal `copy_to_directory(...)` source-root
  contract.
