# Import Manifest Recovery Claim / Lease Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `import-manifest-recovery-claim-lease-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded v34 import recovery claim/lease batch |
| Baseline status SHA-256 | `c9e21e0370a135e9afa3d978e003eb92886bdd7d2889a0d45ad31a645eb44629` |
| Baseline diff SHA-256 | `ac68b6038e01e9f2060eb4913944c74c1a8067f15e9e5a01e8381e177b63558c` |
| Baseline tracked / untracked entries | `143 / 115` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records v34 additive migration and durable import manifest recovery ownership. The machine-readable companion is [audit-manifest-import-manifest-recovery-claim-lease-evidence-2026-08-23.json](audit-manifest-import-manifest-recovery-claim-lease-evidence-2026-08-23.json). Finding ID: `IMPORT-MANIFEST-RECOVERY-CLAIM-LEASE-01`.

## Implemented contract

- v31 import-manifest DDL remains frozen as `IMPORT_MANIFESTS_SCHEMA_V31`; v34 adds nullable `recovery_claim_token` and `recovery_lease_expires_at` columns plus `idx_import_manifests_recovery_lease` through an additive migration.
- Recovery uses an atomic `BEGIN IMMEDIATE`/SAVEPOINT claim update with operation ID, library root, generation, state, and expired-or-empty lease predicate. A successful claim advances generation and returns a random owner token and bounded wall-clock expiry.
- Recovery completion, failure recording, and lease renewal use token-bound generation/state CAS. Terminal or failed paths clear the claim fields. An expired claim can be taken over; the old token cannot finish the manifest.
- `ImportManifestRecoveryService` claims before queue enqueue. A losing runtime does not enqueue. Queue path/kind dedupe remains a compensating mechanism for the enqueue/manifest boundary; this batch does not claim exactly-once execution or cross-system atomicity.
- A Windows-safe dual-process test uses independent SQLite connections and atomic JSON status files. Both children observe generation 0, but only one claim/finish path reports recovery; the final manifest is completed once and the queue retains one operation ID.

## Verification

### Focused matrix

```text
python -m pytest -n 0 -q tests/core/test_db_migrations.py tests/unit/test_db_lock_low_batch.py tests/unit/test_import_manifest_store.py tests/integration/test_import_service.py tests/integration/test_import_subprocess_termination.py tests/integration/test_import_manifest_recovery_claim_process.py tests/integration/test_reconciliation_queue_sqlite_runtime.py tests/integration/test_reconciliation_queue_fault_injection.py tests/integration/test_reconciliation_queue_external_lock.py
```

Result: **113 passed, 0 failed**, exit code 0, 11.99 seconds. Raw output: `artifacts/evidence/2026-08-23/import-manifest-recovery-claim-lease/focused.stdout.log`.

Coverage includes v33-to-v34 migration, idempotent upgrade, claim winner/loser, expired-lease takeover, stale-token rejection, malformed recovery, token-bound finish/failure, dual-process race, existing import subprocess recovery, and reconciliation CAS/lock fixtures.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch27b-full -n 0 -q
```

Result: **4012 passed, 14 skipped, 20 deselected, 2 warnings**, exit code 0, 550.01 seconds. Raw output: `artifacts/evidence/2026-08-23/import-manifest-recovery-claim-lease/full.stdout.log`.

The skipped cases remain platform-limited POSIX flock and symlink/junction fixtures plus the pre-existing nondeterministic multiprocessing Queue termination module. The new Popen-based manifest claim race passed on Windows.

### Targeted static checks

Targeted Ruff, compileall, and `git diff --check` passed. Full governance is recorded by the post-index static artifact and the independent audit validator.

## Evidence boundaries

This batch proves a local durable claim/lease CAS contract and a two-process manifest claim winner under controlled SQLite conditions. It does not prove strict exactly-once queue execution, filesystem/SQLite/queue cross-system atomicity, power-loss safety, ImportService atomic no-overwrite, symlink/junction filesystem race resistance, copy replay/idempotency, restore crash windows, production intermediary behavior, package/release integrity, CVE/dependency status, performance, or clean-checkout behavior. Those remain **fixed-unverified**. The JSON handshake uses temporary-file replacement only to avoid partial test-control reads; it is not fsync or hardware-failure evidence. No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
