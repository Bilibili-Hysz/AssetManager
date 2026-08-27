# Restore Residue Sweep Evidence (2026-08-27)

## Scope
Finding `RESTORE-RESIDUE-SWEEP-50-01`: hard crashes between restore steps left `.library-data_*.restore-<hex>` staging dirs and `.restore-intent-*.tmp` files in the RuntimeData root forever, while failed-staging quarantine entries accumulated with no retirement path.

## Change
`LibraryService._sweep_orphan_restore_residue(identity)` runs inside `_open()` after interrupted-restore recovery and while this slot's cross-process library lock is held. Within THIS slot's namespace only it archives week-old orphan staging directories into the restore quarantine (`create_missing=True`; safe under the held lock), unlinks week-old intent `.tmp` residue, and folds week-old quarantine entries under `_expired/` rather than deleting them. The live intent marker and every path its payload references are explicitly out of bounds; link/junction/reparse candidates are refused; any OSError logs and preserves the entry. Other libraries' namespaces are never scanned (their own locks protect their state).

## Verification
Finding ID for this batch: `RESTORE-RESIDUE-SWEEP-50-01`.
library_service focused suite: **26 passed** covering archival-with-fold end-state, fresh entries untouched, marker preservation, foreign-slot immunity, link-flagged preservation, open-trigger integration, and expired-quarantine folding. Final serial suite: **4112 passed, 16 skipped, 20 deselected, 2 warnings**, exit 0.

## Boundaries
Status is `fixed-unverified`. Sweep is best-effort inside open (not a scheduler); nothing is permanently deleted by design; multi-process behavior beyond the slot lock and real crash timing remain unexercised.
