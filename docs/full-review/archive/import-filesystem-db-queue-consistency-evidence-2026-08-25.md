# Import Filesystem/DB/Queue Consistency Evidence (2026-08-25)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `import-filesystem-db-queue-consistency-evidence-2026-08-25` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded 28-D compensation consistency batch |
| Baseline status SHA-256 | `9f6a8e730d60de9d30da80cde07185ec40086db32de41c4a8726f05d6cba636f` |
| Baseline diff SHA-256 | `bf9d3d133bf1f2c78930f8a592a3851ca8d0037e2fb15482316f1bea01ab39fa` |
| Baseline tracked / untracked entries | `143 / 125` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records bounded compensation fixes at the filesystem/SQLite/queue boundary of ImportService and their dynamic verification. The machine-readable companion is [audit-manifest-import-filesystem-db-queue-consistency-evidence-2026-08-25.json](audit-manifest-import-filesystem-db-queue-consistency-evidence-2026-08-25.json). Finding ID: `IMPORT-FSQ-COMPENSATION-28D-01`.

## Implemented contract

- **Cancellation intent preservation (F2)**: both cancellation paths now attempt the durable `import_partial` rescan enqueue before reaching the terminal `cancelled` state when files have been copied. If the enqueue fails, the manifest falls back to `recovery_pending` (or stays in a non-terminal recovery state) so restart-time `recover()` compensates with a root rescan instead of leaving copied files invisible to the index forever.
- **Replay robustness (F4a)**: `replay_import` wraps per-item `update_item` calls; an exception becomes that item's failure entry and the loop continues instead of crashing mid-replay.
- **Replay index synchronization (F4b)**: after replay processing, the destination tree and parents are refreshed through the same direct-refresh path used by imports, degraded outcomes enqueue a rescan (`import_partial` / `import_refresh_degraded`), and exactly one `FileSystemChanged(kind="import")` event is published on completion.
- **Replay finish/claim handling (F4c)**: `finish()` failures (False or exception) trigger a compensating `import_manifest_recovery` enqueue and are reported as failed entries. An eligibility pre-check distinguishes "nothing to do" from "claim lost to a concurrent writer"; the latter returns a deterministic degraded result.

## Verification

### Focused matrix

```text
python -m pytest -n 0 -q tests/integration/test_import_service.py tests/integration/test_import_subprocess_termination.py tests/unit/test_import_manifest_store.py tests/integration/test_import_manifest_recovery_claim_process.py tests/integration/test_reconciliation_queue_sqlite_runtime.py
```

Result: **55 passed, 2 skipped**, exit code 0, 18.97 seconds. Skips are the existing Windows symlink privilege cases (WinError 1314). Raw output: `artifacts/evidence/2026-08-25/import-filesystem-db-queue-consistency/focused.stdout.log`.

New deterministic fault-injection coverage includes:

- Cancel with broken queue and copied>0: `ImportCancelled` still raised, manifest lands in a recoverable state, reopen recovers to `completed` with exactly one root-rescan task, target content intact without duplicate copies.
- `update_item` exception plus broken queue during a normal import: manifest ends `recovery_pending`, physical copy preserved, restart converges to `completed` with a single recovery task and no duplicate file.
- Clean import whose `store.finish` raises: manifest stays `running`, compensating `import_manifest_recovery` is enqueued, restart recovery completes it.
- Replay continues after a `manifest replay update` exception; claim race returns the deterministic "replay claim lost" degraded result; replay `finish()` failure triggers the compensating enqueue.

### Full Python suite

```text
python -m pytest -n 0 -q
```

Result: **4033 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0, 597.50 seconds. Raw output: `artifacts/evidence/2026-08-25/import-filesystem-db-queue-consistency/full.stdout.log`.

The serial `-n 0` lane remains required because xdist worker setup previously failed on this Windows host with a temporary-directory `PermissionError: [WinError 5]`. Skips are platform-limited symlink/junction/POSIX flock cases plus the known nondeterministic multiprocessing Queue termination fixture; warnings are the pre-existing Qt signal disconnect and duplicate ZIP entry warnings.

### Targeted static checks

The following commands each exited 0:

```text
python -m ruff check AssetsManager/application/import_service.py AssetsManager/application/import_manifest_store.py tests/integration/test_import_service.py
python -m compileall AssetsManager/application/import_service.py AssetsManager/application/import_manifest_store.py tests/integration/test_import_service.py -q
git diff --check
```

Raw outputs and SHA-256 digests are under `artifacts/evidence/2026-08-25/import-filesystem-db-queue-consistency/`.

## Findings and boundaries

`IMPORT-FSQ-COMPENSATION-28D-01` is **fixed-unverified** for the bounded compensation contract: the tested double-fault combinations now keep intents recoverable and converge on restart without duplicate copies or hidden files.

Known boundaries that remain explicitly unverified or intentionally unchanged:

- Restart-time recovery still marks manifests containing pending items as `completed` after the root rescan; this is a bookkeeping semantics choice (disk truth drives the index, manual `replay_import` remains the item-level exit). Changing it would break pinned subprocess-recovery contracts and cause repeated-recovery churn. Recorded as fixed-unverified bookkeeping behavior.
- Filesystem copy, SQLite CAS, and queue enqueue remain separate non-atomic systems; no cross-system transaction, power-loss safety, or exactly-once execution is claimed.
- The fingerprint-to-copy TOCTOU inside `_copy_one` (source mutated between fingerprinting and streaming) is unchanged and remains unverified.
- Process-kill windows inside `recover()` between claim/enqueue/finish were not exercised with real subprocess kills in this batch; only monkeypatch-level fault injection was used.
- No clean-checkout, package/release, dependency/CVE, performance, or production deployment claim is made.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
