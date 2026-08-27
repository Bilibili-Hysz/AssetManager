# Thumbnail Path Migration / Cleanup Consistency Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `thumbnail-path-migration-concurrency-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded application-layer cache-owner lock convergence |
| Baseline status SHA-256 | `560db764521c9d3078ca1984b79241a19c58675a63027f745fcdc4a1919df5db` |
| Baseline diff SHA-256 | `1ee32773da473ecb7aec6460aed54438a56a9e8c5a17472241fd24b7dc011ace` |
| Baseline tracked / untracked entries | `143 / 102` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records the production caller lock-order convergence. The machine-readable companion is [audit-manifest-thumbnail-path-migration-concurrency-evidence-2026-08-23.json](audit-manifest-thumbnail-path-migration-concurrency-evidence-2026-08-23.json).

## Implemented contract

Production application callers now acquire `cache_owner_lock(session.thumb_dir)` before calling the core-only `migrate_path_metadata()` helper:

- `FileOperationService._migrate_metadata()` covers single and batch moves;
- `FilesystemProjectionRepairService._repair_move()` covers durable filesystem projection repair.

The resulting cooperating-runtime order is:

```text
LibraryLock -> path locks (move) -> cache owner -> artifact lock -> SQLite write lock -> SAVEPOINT
```

The core database module remains application-independent; it does not import the application lifecycle lock, preserving the layer DAG. Direct low-level core test callers remain valid and are intentionally outside the application runtime lock wrapper.

Existing collision semantics remain non-destructive: destination artifacts are not overwritten, destination rows are not replaced, and old bytes may remain for later integrity handling. SQLite savepoints still cannot undo a filesystem rename that already completed; this batch does not claim filesystem or power-loss atomicity.

## Verification

### Focused matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch25k-focused-evidence -q tests/core/test_database_metadata.py tests/unit/test_core_db_low_batch.py tests/integration/test_file_operation_service.py tests/integration/test_thumbnail_service.py tests/unit/test_database_integrity_service.py tests/unit/test_integrity_low_batch.py tests/unit/test_thumbnail_repository.py tests/unit/test_architecture_boundaries.py
```

Result: **260 passed, 0 failed**, exit code 0, 68.38 seconds. Raw output: `artifacts/evidence/2026-08-23/thumbnail-path-migration-concurrency/focused.stdout.log`.

Coverage includes path migration savepoint/collision/rename failure, file-operation and repair projections, eviction, integrity, repository conditional deletion and architecture layer/order assertions.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25k-full -n 0 -q
```

Result: **3996 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 615.83 seconds. Raw output: `artifacts/evidence/2026-08-23/thumbnail-path-migration-concurrency/full.stdout.log`.

### Static/governance gates

Pre-index governance passed: audit manifests, README stats, boundaries, style sources, route capabilities, frontend data-fetch, layer DAG, Ruff, compileall and `git diff --check`. Raw output: `artifacts/evidence/2026-08-23/thumbnail-path-migration-concurrency/static.stdout.log` and `static.stderr.log`; post-index validation is recorded separately in the manifest.

## Compatibility limits

This batch does not move existing v2/legacy artifacts in bulk, add JPG v3/profile semantics, alter schema history, redesign eviction or cleanup, or prove independent processes running migration/eviction/integrity simultaneously. The core helper’s SQLite savepoint remains non-atomic with external filesystem rename. POSIX/Windows race proof, power-loss recovery, browser/intermediary E2E, mutation atomicity, package/release, CVE/dependency, performance and clean-checkout remain **fixed-unverified**.

No commit, push, release, revert, reset, clean or dirty-worktree overwrite was performed.
