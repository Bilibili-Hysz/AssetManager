# Restore Intent Recovery and Acknowledgement Evidence (2026-08-26)

## Scope
Finding `RESTORE-INTENT-UNRECOVERABLE-41-01` covered an interrupted restore marker that could fail before a library session existed, leaving no reachable recovery action.

## Changes
- `LibraryService.restore_intent_status()` reports marker state without opening SQLite.
- `retry_interrupted_restore()` acquires a fresh library lock and reuses protected marker rollback logic.
- `acknowledge_restore_intent()` requires the marker token, an unambiguous live RuntimeData directory, and the same protected lock before clearing the marker.
- Startup open failure now presents retry/manual-remediation acknowledgement actions when a marker exists.

## Verification
- Restore marker/recovery focused matrix: **7 passed**, with existing restore tests included in the final suite.
- Final serial Python suite: **4089 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0.
- Full Ruff, compileall, diff-check, and repository governance gates passed.

## Boundaries
Status is `fixed-unverified`: no subprocess kill, power-loss, cross-system atomicity, or browser/UI E2E proof was performed. Manual acknowledgement intentionally clears evidence only after explicit token confirmation and verified live data; it does not recover missing quarantine data.
