# Batch B File Operation Consistency Design
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/batch-b-file-operation-consistency.md)

## [S1] Goal

Make library-scoped desktop file mutations consistent across the filesystem, metadata, thumbnail cache, asset index, events, and Undo/Redo history.

## [S2] Covered Operations

Covered operations are rename, in-library move, copy into a library, external-file copy into a library, permanent delete, trash delete, and reversible Undo/Redo for rename, move, and permanent delete.

## [S3] Command Boundary

`FileOperationService` is the only desktop mutation boundary. Bound services validate the active library root; desktop mutation entry points refuse to run without scoped services. External copy is allowed only when the destination is inside a bound library.

## [S4] Projection Order

After a filesystem mutation succeeds, the service updates metadata, thumbnails, and asset-index projections before publishing the corresponding domain event. Directory moves and copies reconcile descendants. Deletes clear path/subtree projections.

## [S5] Undo Semantics

Undo and redo execute through the operation service and only move a history entry after execution succeeds. Permanent-delete backups are committed for each actually deleted path; trash deletion is non-reversible.

## [S6] Desktop Delegation

Grid rename emits an intent handled by the panel. Paste and drop use scoped services: in-library drops move, external drops copy. Unscoped rename, delete, paste, drop, undo, and redo fail closed.

## [S7] Verification

Integration tests cover projection/event ordering, subtree indexing, external-copy destination containment, and Undo/Redo success/failure behavior. Desktop tests cover intent delegation, scoped mutation guards, clipboard paste, drop classification, and partial permanent-delete Undo bookkeeping.

## [S8] Non-Goals

This batch does not redesign `LibrarySession`, add filesystem watching, support cross-library move, restore recycle-bin items, or make create-folder and duplicate operations projection-aware.

