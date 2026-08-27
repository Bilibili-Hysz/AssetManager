# Import Copy Replay / Idempotency Evidence (2026-08-25)

## Snapshot metadata

| Field | Value |
|---|---|
|---|---|
| Report ID | `import-copy-replay-idempotency-evidence-2026-08-25` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded 28-C explicit import replay batch |
| Baseline status SHA-256 | `9148ab00c233432ad1d2b2d979aaeea8ccce7ea9b924ce16d0272fa0c5594456` |
| Baseline diff SHA-256 | `49f4c7d8a2be6225091d432827ce338562d8049c402443bde97853891ca8f586` |
| Baseline tracked / untracked entries | `143 / 123` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records explicit replay support for one durable import operation and its dynamic verification. The machine-readable companion is [audit-manifest-import-copy-replay-idempotency-evidence-2026-08-25.json](audit-manifest-import-copy-replay-idempotency-evidence-2026-08-25.json). Finding ID: `IMPORT-COPY-REPLAY-IDEMPOTENCY-28C-01`.

## Implemented contract

- New manifests use payload v2 when stable source fingerprints can be captured. Each item contains a stable `copy_id` derived from operation ID and item index, plus source `size`, `mtime_ns`, and SHA-256.
- Legacy payload v1 remains readable, but lacks replay identity and is conservatively not auto-replayed.
- `ImportService.replay_import(operation_id)` is an explicit, narrow operation-level replay path. It does not alter ordinary repeated `import_sources()` behavior, which continues to use automatic `_1/_2` conflict renaming.
- Replay re-fingerprints the source and refuses replay when the source changed. A missing manifest target is recreated at the original target using the existing exclusive-create/no-overwrite and ancestor-admission path.
- An existing target is adopted only when it is a regular, contained, non-link file whose size and SHA-256 match the durable source fingerprint. Mismatched targets are reported as `replay_conflict` and preserved.
- Manifest item and aggregate state changes still use the existing CAS store. Filesystem effects and SQLite updates remain separate; this batch does not claim exactly-once execution or cross-system atomicity.

## Verification

### Focused matrix

```text
python -m pytest -n 0 -q tests/integration/test_import_service.py tests/integration/test_import_subprocess_termination.py tests/unit/test_import_manifest_store.py tests/integration/test_import_manifest_recovery_claim_process.py tests/integration/test_reconciliation_queue_sqlite_runtime.py
```

Result: **49 passed, 2 skipped**, exit code 0, 14.31 seconds. Skips are the existing Windows symlink privilege cases (WinError 1314). Raw output: `artifacts/evidence/2026-08-25/import-copy-replay-idempotency/focused.stdout.log`.

Coverage includes v2 payload identity, matching-target adoption without physical copy, missing-target replay at the original path, source-change rejection, target conflict preservation, legacy v1 no-op behavior, ordinary repeated-import `_1` semantics, subprocess recovery, manifest CAS/lease, and queue runtime behavior.

### Full Python suite

```text
python -m pytest -n 0 -q
```

Result: **4027 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0, 591.00 seconds. Raw output: `artifacts/evidence/2026-08-25/import-copy-replay-idempotency/full.stdout.log`.

The serial `-n 0` lane remains necessary because this Windows environment previously failed xdist worker setup with a temporary-directory `PermissionError: [WinError 5]`. Skips remain platform-limited symlink/junction/POSIX flock cases and the existing nondeterministic multiprocessing Queue termination fixture. Warnings are the existing Qt signal disconnect warning and duplicate ZIP entry warning.

### Targeted static checks

The following commands each exited 0:

```text
python -m ruff check AssetsManager/application/import_service.py AssetsManager/application/import_manifest_store.py tests/integration/test_import_service.py tests/unit/test_import_manifest_store.py
python -m compileall AssetsManager/application/import_service.py AssetsManager/application/import_manifest_store.py tests/integration/test_import_service.py tests/unit/test_import_manifest_store.py -q
git diff --check
```

Raw outputs and SHA-256 digests are under `artifacts/evidence/2026-08-25/import-copy-replay-idempotency/`.

## Findings and boundaries

`IMPORT-COPY-REPLAY-IDEMPOTENCY-28C-01` is **fixed-unverified** for the explicit same-operation/item replay contract. Matching targets are safely adopted, missing targets use the original exclusive target, changed sources and conflicting targets fail closed, and legacy v1 manifests do not receive unsafe automatic reuse.

The following remain explicitly unverified or out of scope:

- This is not exactly-once worker execution. Recovery leases and queue dedupe remain ownership/compensation mechanisms, not filesystem side-effect transactions.
- Copy and manifest CAS are not one atomic transaction; power-loss between physical copy and manifest update remains a separate failure window.
- Cross-platform mutation races between source fingerprinting, target adoption, and copy are not proven race-free.
- No global same-content deduplication was added; ordinary repeated imports may intentionally create renamed copies.
- No item-level SQLite copy ledger or transactional outbox was added in this bounded batch.
- No clean-checkout, package/release, dependency/CVE, performance, or production deployment claim is made.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
