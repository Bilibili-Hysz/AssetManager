# Batch B File Operation Consistency Implementation Plan

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/batch-b-file-operation-consistency.md)

**Goal:** Unify desktop file changes with library-scoped projection and Undo/Redo behavior.

## Completed Work

- [x] Bind `FileOperationService` to `LibrarySession` and `AssetIndexService` through bootstrap.
- [x] Reconcile metadata, thumbnail cache/files, index entries, directory descendants, and events after covered mutations.
- [x] Execute Undo/Redo through the operation service and retain history on failure.
- [x] Delegate grid, paste, drop, rename, delete, undo, and redo through scoped services.
- [x] Add integration and desktop regression coverage.
- [x] Run Python and WebUI quality gates.
