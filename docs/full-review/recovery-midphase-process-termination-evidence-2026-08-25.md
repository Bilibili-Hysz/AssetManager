# Recovery Mid-Phase Process Termination Evidence (2026-08-25)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `recovery-midphase-process-termination-evidence-2026-08-25` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded 29-C recovery mid-phase kill verification batch |
| Baseline status SHA-256 | `cb69a3077cac6965709d98b617d08a54a707bbcb551f42df54294bba5e8e15c5` |
| Baseline diff SHA-256 | `d70a0792415850d84744c7ac9e27fe7caec5cb6bbe8a1b887c7a9557b98590da` |
| Baseline tracked / untracked entries | `143 / 131` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot elevates the two mid-phase recovery windows from monkeypatch-level fault injection to real subprocess termination evidence. The machine-readable companion is [audit-manifest-recovery-midphase-process-termination-evidence-2026-08-25.json](audit-manifest-recovery-midphase-process-termination-evidence-2026-08-25.json). Finding ID: `RECOVERY-MIDPHASE-KILL-29C-01`.

## Implemented contract (tests only; no production changes)

New checkpoint infrastructure in `tests/integration/test_import_manifest_recovery_claim_process.py`:

- `_CHECKPOINT_CHILD_SCRIPT` spawns a real recovery worker process over a file-backed SQLite database using the proven unmanaged-store construction (`ShortLeaseStore` subclass forces a 3-second claim lease so takeover polls stay fast).
- mode `after_claim`: blocks inside a wrapped `enqueue_or_merge` after the claim transaction committed but before any queue row exists.
- mode `after_enqueue`: blocks inside a wrapped `finish_recovery` after the enqueue committed but before the manifest finish CAS.

Two new termination tests:

1. **Kill after claim**: the killed child leaves a live claim (state unchanged, generation+1, token set, future expiry) and an empty queue. An immediate parent `recover()` is rejected by the live-lease predicate and enqueues nothing. After lease expiry a polled takeover converges to `completed`, `attempts==1`, token cleared, `generation==3`, with exactly one queue row whose `operation_ids == [op]`.
2. **Kill after enqueue**: the queue row survives the kill with its pre-kill `task_id`. The live lease again blocks immediate takeover without duplicating tasks. Takeover merges into the same task — `task_id` stable across pre-kill/immediate/post-takeover observations and `operation_ids.count(op)==1` throughout. Manifest finishes as `completed`; a further restart-time pass finds nothing left to do and the queue stays at one row.

The child-startup barrier timeout was raised from 15s to 30s: Windows children pay a full interpreter + package import, and a cold first start could otherwise flake the wait.

## Verification

### Focused matrix

```text
python -m pytest -n 0 -q tests/integration/test_import_manifest_recovery_claim_process.py tests/integration/test_import_subprocess_termination.py tests/unit/test_import_manifest_store.py tests/integration/test_import_service.py
```

Result: **58 passed, 2 skipped**, exit code 0, 27.57 seconds (symlink privilege skips). Raw output: `artifacts/evidence/2026-08-25/recovery-midphase-process-termination/focused.stdout.log`.

One flake was observed and fixed during development: the first full-file run timed out waiting for the cold child process; standalone rerun passed and the barrier timeout increase removed the fragile window. This ordering diagnostic is recorded honestly rather than hidden.

### Full Python suite

```text
python -m pytest -n 0 -q
```

Result: **4037 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0, 610.30 seconds. Raw output: `artifacts/evidence/2026-08-25/recovery-midphase-process-termination/full.stdout.log`. The two new termination tests add roughly 8–14 seconds of deliberate lease-expiry polling to the suite. Serial `-n 0` remains required on this host (xdist worker temp-directory `PermissionError`); skips/warnings are the established platform-limited set.

### Targeted static checks

```text
python -m ruff check AssetsManager tests/integration/test_import_manifest_recovery_claim_process.py
python -m compileall tests/integration/test_import_manifest_recovery_claim_process.py -q
git diff --check
```

Each exited 0; digests under `artifacts/evidence/2026-08-25/recovery-midphase-process-termination/`.

## Findings and boundaries

`RECOVERY-MIDPHASE-KILL-29C-01` is **fixed-unverified** → verified for the bounded kill-window contract on this Windows host: both mid-phase terminations leave intents recoverable, leases gate premature takeover, and queue identity stays single-row stable across restarts. Status recorded as `fixed-unverified` because the evidence covers one platform and controlled checkpoints, not an exhaustive distributed proof.

Explicitly remaining:

- Wall-clock leases remain a compensation mechanism, not exactly-once execution; a crash between physical side effects and their bookkeeping still relies on later reconciliation.
- No power-loss durability claim; SQLite commits are durable but the filesystem/index effects of rescans are separate systems.
- Cross-platform process semantics (POSIX SIGKILL timing, NFS/other filesystems) untested.
- The 3-second forced lease is a test-only injection; production default remains 30 seconds.
- completed-with-pending-items bookkeeping semantics and all previously recorded import boundaries are unchanged.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
