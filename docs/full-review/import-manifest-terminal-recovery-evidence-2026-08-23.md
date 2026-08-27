# Import Manifest Terminal / Recovery Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `import-manifest-terminal-recovery-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded import manifest recovery correctness batch |
| Baseline status SHA-256 | `3b10d6255ecaa5a8088de57711fceddb74594290292730290e4242af3d72aac5` |
| Baseline diff SHA-256 | `61a6946dcf12864a8abe17ba9c49737e0d208c032cd99cd75e05c603252a0ea8` |
| Baseline tracked / untracked entries | `143 / 107` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records import manifest terminal/recovery correctness. The machine-readable companion is [audit-manifest-import-manifest-terminal-recovery-evidence-2026-08-23.json](audit-manifest-import-manifest-terminal-recovery-evidence-2026-08-23.json).

## Implemented contract

- Successful restart-time recovery now enqueues the root rescan once and transitions the manifest to the existing terminal `completed` state; `completed` is excluded from recovery scans, so reopen is idempotent without adding a schema migration.
- Manifest transitions now have explicit guards. `completed` and `cancelled` rows cannot be reactivated; CAS updates also match the expected state as well as generation, preventing stale writers from overwriting a newer state.
- Import filesystem copy and manifest item persistence are handled separately. A copied file remains counted as copied if manifest update fails; the import continues with later files and returns degraded/recovery information rather than aborting with a misleading copy failure.
- Cancellation keeps its existing no-refresh/no-import-event behavior, but copied partial output now requests an index rescan through the reconciliation queue. A cancellation before any copy does not create an unnecessary rescan.

This batch does not replay missing copies, add import idempotency keys, or claim cross-system filesystem/SQLite/queue atomicity.

## Verification

### Focused matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch26a-focused-evidence -q tests/unit/test_import_manifest_store.py tests/integration/test_import_service.py tests/integration/test_reconciliation_queue_fault_injection.py tests/integration/test_reconciliation_queue_process_matrix.py
```

Result: **25 passed, 0 failed**, exit code 0, 11.97 seconds. Raw output: `artifacts/evidence/2026-08-23/import-manifest-terminal-recovery/focused.stdout.log`.

Coverage includes recovery idempotence, terminal transition protection, manifest update failure continuation, partial cancellation rescan, and reconciliation CAS/lease recovery.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch26a-full -n 0 -q
```

Result: **3998 passed, 14 skipped, 20 deselected, 2 warnings**, exit code 0, 557.78 seconds. Raw output: `artifacts/evidence/2026-08-23/import-manifest-terminal-recovery/full.stdout.log`.

### Static/governance gates

Pre-index governance passed: audit manifests, README stats, boundaries, style sources, route capabilities, frontend data-fetch, layer DAG, Ruff, compileall and `git diff --check`. Raw output: `static.stdout.log` and `static.stderr.log`; post-index validation is recorded separately in the manifest.

## Compatibility limits

The recovery terminal uses existing `completed` schema state rather than introducing a new migration. Existing `recovery_pending` records are processed once and then become terminal. Queue enqueue success followed by database finish failure remains a retryable boundary; duplicate queue requests rely on the queue’s existing operation-id merge semantics.

Power-loss, subprocess termination at every import filesystem boundary, copy replay/idempotency, durable event outbox, cross-system atomicity, POSIX/Windows filesystem proof, browser/intermediary E2E, package/release, CVE/dependency, performance and clean-checkout remain **fixed-unverified**. No commit, push, release, revert, reset, clean or dirty-worktree overwrite was performed.
