---
feature: batch-b-file-operation-consistency
status: delivered
specs:
  - docs/compose/specs/2026-07-15-batch-b-file-operation-consistency-design.md
plans:
  - docs/compose/plans/2026-07-15-batch-b-file-operation-consistency.md
branch: batch-b-file-operation-consistency
commits: a893537..6ff0754
---

# Batch B File Operation Consistency - Final Report

## What Was Built

Batch B makes covered desktop file operations library-scoped and projection-consistent. Rename, move, copy, external import, permanent delete, trash delete, restore, and Undo/Redo now preserve filesystem, metadata, thumbnail, asset-index, and event state as one command flow.

## Architecture

`ApplicationBootstrap.for_library()` creates a `FileOperationService` bound to the active session and `AssetIndexService`. File changes complete their filesystem mutation, then reconcile projections, then publish their existing domain event. `UndoService.perform_undo()` and `perform_redo()` delegate to that service and transfer history only after success.

Grid inline rename emits an intent to the panel. Paste, drag/drop, rename, delete, Undo, and Redo require scoped services. In-library drag/drop moves files; external paths copy into the active library. Trash remains non-reversible, while permanent deletion records per-path backups only for paths actually deleted.

## Usage

Desktop users retain existing keyboard, context-menu, clipboard, and drag/drop flows. System clipboard local-file URLs can be pasted into an opened library. A file drag from another directory inside the same library is moved; a drag from outside the library is copied.

## Verification

- `python -m ruff check . --exclude ".Cython&Noikta"`: passed.
- `python -m pyright`: `0 errors, 0 warnings`.
- `python -m compileall AssetsManager -q`: passed.
- `python -m pytest -q`: `811 passed`.
- `npm ci && npm run typecheck && npm run build` in `webui/`: passed.

## Journey Log

> Brief notes on what informed the final design. Not required reading.

- [lesson] Projection consistency requires event observers to run only after index, thumbnail, and metadata reconciliation.
- [lesson] Batch results need per-path Undo commits; a whole-batch success flag loses Undo history after partial success.
- [lesson] Mutation entry points must fail closed without scoped services; an unbound fallback bypasses both library containment and projections.

## Source Materials

| File | Role | Notes |
|---|---|---|
| `docs/compose/specs/2026-07-15-batch-b-file-operation-consistency-design.md` | Design | Final scope and invariants. |
| `docs/compose/plans/2026-07-15-batch-b-file-operation-consistency.md` | Plan | Completed implementation tasks. |
