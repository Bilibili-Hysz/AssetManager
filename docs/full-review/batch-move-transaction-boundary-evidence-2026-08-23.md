# Batch Move Transaction Boundary Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `batch-move-transaction-boundary-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded batch move transaction-admission batch |
| Baseline status SHA-256 | `98b1c13d9da1879ba2754361652c80308eb5571fb8511247c0af9552c515457b` |
| Baseline diff SHA-256 | `b66e7fd5c19a76b33162587d611fd26dfb295abba70130c2353747ad4c5a4600` |
| Baseline tracked / untracked entries | `143 / 119` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records the bounded batch move clean-transaction admission hardening and dynamic verification. The machine-readable companion is [audit-manifest-batch-move-transaction-boundary-evidence-2026-08-23.json](audit-manifest-batch-move-transaction-boundary-evidence-2026-08-23.json). Finding ID: `BATCH-MOVE-TRANSACTION-BOUNDARY-29-01`.

## Implemented contract

- `FileOperationService.move_to_directory()` now performs a connection-owned clean-transaction preflight before entering the source loop or performing filesystem mutation.
- The existing per-source check remains in place as race observability and fail-closed protection if the connection becomes transactional during the batch.
- A caller-owned outer SQLite transaction is rejected with `RuntimeError("FileOperationService move requires a clean transaction boundary")` before the first filesystem operation.
- The batch test stops the reconciliation worker before opening the caller transaction, matching the established single-move and delete transaction-boundary fixtures and removing shared-connection timing interference.
- The regression covers two source files and verifies both remain in place, neither destination is created, and the caller sentinel remains visible while the caller retains transaction ownership.
- A clean multi-source batch happy-path test verifies that preflight does not change normal `moved_pairs` or file-content behavior.

## Verification

### Focused matrix

```text
python -m pytest -n 0 -q tests/integration/test_file_operation_service.py tests/integration/test_event_publishing.py tests/core/test_database_metadata.py tests/integration/test_import_service.py
```

Result: **112 passed, 1 skipped**, exit code 0, 40.79 seconds. The skipped case is the existing Windows symlink-privilege-limited ImportService test (WinError 1314). Raw output: `artifacts/evidence/2026-08-23/batch-move-transaction-boundary/focused.stdout.log`.

The narrower transaction-boundary selection also passed **8 tests**, with 46 deselected. It initially had one malformed `-k` expression that collected no tests; that command is not treated as evidence and was immediately corrected.

### Full Python suite

```text
python -m pytest -n 0 -q
```

Result: **4018 passed, 15 skipped, 20 deselected, 2 warnings**, exit code 0, 569.75 seconds. Raw output: `artifacts/evidence/2026-08-23/batch-move-transaction-boundary/full.stdout.log`.

The xdist default remains unsuitable on this Windows worker because worker setup previously failed with a temporary-directory `PermissionError: [WinError 5]`; this batch uses the serial `-n 0` lane. Skips are platform-limited symlink/junction/POSIX flock cases and the existing nondeterministic multiprocessing Queue termination fixture. Warnings are the existing Qt signal disconnect warning and duplicate ZIP entry warning.

### Targeted static checks

The following commands each exited 0:

```text
python -m ruff check AssetsManager/application/file_operation_service.py tests/integration/test_file_operation_service.py
python -m compileall AssetsManager/application/file_operation_service.py tests/integration/test_file_operation_service.py -q
git diff --check
```

Raw outputs and SHA-256 digests are under `artifacts/evidence/2026-08-23/batch-move-transaction-boundary/`.

## Findings and boundaries

`BATCH-MOVE-TRANSACTION-BOUNDARY-29-01` is **verified-fixed** for the bounded contract: an already-open caller transaction is rejected before the first batch filesystem mutation, the test fixture is stable against the shared reconciliation worker, and clean multi-source operation remains green.

The following remain explicitly unverified or out of scope:

- This does not prove a cross-thread or cross-process race-proof boundary between the preflight check and filesystem I/O; the per-item check improves fail-closed observability but does not make SQLite and filesystem mutation one atomic transaction.
- A transaction opened after a source has already moved may still leave a partial batch; filesystem moves are not rolled back by SQLite savepoints or caller rollback.
- `restore_backup`, copy/duplicate, delete whole-batch admission, power-loss recovery, and filesystem+SQLite+queue atomicity are separate work.
- No clean-checkout, package/release, CVE/dependency, performance, or production deployment claim is made.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
