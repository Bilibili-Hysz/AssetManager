# Import Manifest Recovery Robustness / Dual-Connection CAS Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `import-manifest-recovery-robustness-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded import manifest recovery robustness batch |
| Baseline status SHA-256 | `c43833e72f912a3b6febfd82924d608ce82969a900a2d24c501c10703dd2eff8` |
| Baseline diff SHA-256 | `a8553ef001fee2a781d3c1817fd84bfcc34ec2e793df945835ee40eed0f5b5bd` |
| Baseline tracked / untracked entries | `143 / 112` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records manifest parsing isolation, connection-owned reads, item-level transition guards, dual-connection stale CAS protection, external-lock fail-closed behavior, and recovery finish-failure retry semantics. The machine-readable companion is [audit-manifest-import-manifest-recovery-robustness-evidence-2026-08-23.json](audit-manifest-import-manifest-recovery-robustness-evidence-2026-08-23.json). Finding ID: `IMPORT-MANIFEST-RECOVERY-ROBUSTNESS-01`.

## Implemented contract

- `ImportManifestStore.get()` and `list_recovery()` now use the connection-owned database lock before reading shared SQLite connections.
- Persisted rows are decoded and structurally validated on read. A malformed JSON or malformed payload row is isolated as a diagnostic record instead of aborting recovery for valid rows. Recovery keeps the row unresolved as `recovery_pending`, increments attempts through generation/state CAS, and records the error type/message. Failure to record the fallback is logged and does not block other manifests.
- Item transitions are monotonic: `pending` may become `copied`, `failed`, or `skipped`; terminal item states cannot be rewritten to another terminal state without a future explicit retry contract.
- Recovery finish failures are not reported as successful recovery. Queue enqueue remains durable/deduplicated by the existing queue scope, while a later recovery can retry the manifest. Exceptions from the fallback diagnostic update are captured and logged.
- File-backed dual-connection tests prove stale generation/state writers cannot overwrite a newer payload, and an external SQLite `BEGIN IMMEDIATE` lock makes finish fail closed until the lock is released.

This batch does not add a recovery lease or strict single-consumer claim, does not add a new aggregate schema state, and does not replay missing copies.

## Verification

### Focused matrix

```text
python -m pytest -n 0 -q tests/unit/test_import_manifest_store.py tests/integration/test_import_service.py tests/integration/test_import_subprocess_termination.py tests/integration/test_reconciliation_queue_sqlite_runtime.py tests/integration/test_reconciliation_queue_fault_injection.py tests/integration/test_reconciliation_queue_external_lock.py
```

Result: **36 passed, 0 failed**, exit code 0, 10.75 seconds. Raw output: `artifacts/evidence/2026-08-23/import-manifest-recovery-robustness/focused.stdout.log`.

Coverage includes malformed-row isolation, item transition guards, finish false/exception retry, file-backed stale CAS, external SQLite lock fail-closed behavior, previous subprocess checkpoints, and reconciliation recovery fixtures.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch27a-full -n 0 -q
```

Result: **4008 passed, 14 skipped, 20 deselected, 2 warnings**, exit code 0, 565.89 seconds. Raw output: `artifacts/evidence/2026-08-23/import-manifest-recovery-robustness/full.stdout.log`.

The skipped cases are platform-limited POSIX flock and symlink/junction fixtures plus the pre-existing nondeterministic multiprocessing Queue termination module. No new 27-A test was skipped.

### Targeted static checks

Ruff, compileall, and `git diff --check` passed for the changed store/tests. Raw outputs are archived as `targeted-ruff.*`, `targeted-compile.*`, and `targeted-diffcheck.*` in the evidence directory.

## Evidence boundaries

This batch verifies local SQLite read locking, generation/state CAS, malformed-row isolation, and recovery retry semantics. It does not prove strict single-consumer recovery across two independent runtimes/processes, filesystem/SQLite/queue cross-system atomicity, power-loss safety, atomic no-overwrite under concurrent target creation, symlink/junction race resistance, copy replay/idempotency, package/release integrity, CVE/dependency status, performance, production intermediary behavior, or clean-checkout behavior. Those remain **fixed-unverified**. No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
