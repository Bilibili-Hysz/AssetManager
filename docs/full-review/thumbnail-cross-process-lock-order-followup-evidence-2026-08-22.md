# Thumbnail Cross-Process Lock-Order Follow-up Evidence (2026-08-22)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `thumbnail-cross-process-lock-order-followup-evidence-2026-08-22` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; final 25-C lock-order follow-up |
| Baseline status SHA-256 | `07a50d0707adbf58bb20580c7a0e610e52356250c062114dd3f26f4fcfcd755d` |
| Baseline diff SHA-256 | `c9496d2276397835fc949fcb5fcf9e4452ba97d1ac685210ebfb4e19a47275a9` |
| Baseline tracked / untracked entries | `137 / 82` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only follow-up records the final lock-order correction after the initial 25-C evidence snapshot. Earlier reports and manifests remain unchanged. The machine-readable companion is [audit-manifest-thumbnail-cross-process-lock-order-followup-evidence-2026-08-22.json](audit-manifest-thumbnail-cross-process-lock-order-followup-evidence-2026-08-22.json).

## Correction

File-operation projection cleanup now acquires the thumbnail cache owner before entering the SQLite write lock and retains that ownership through thumbnail row deletion and artifact removal. This enforces the documented order `cache owner -> process artifact lock -> SQLite write lock` rather than acquiring SQLite first and the cache owner afterward (`AssetsManager/application/file_operation_service.py:1148`).

The correction preserves the existing savepoint and event ordering contracts. Non-thumbnail projections remain in the existing transaction, while thumbnail artifact cleanup occurs under the same cache owner lease. This reduces the cross-resource race window but does not make SQLite and filesystem operations one crash-atomic transaction.

## Verification

### Lock-order focused matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch25c-lockorder-focused -q tests/integration/test_file_operation_service.py tests/unit/test_database_integrity_service.py tests/integration/test_thumbnail_service.py tests/desktop/test_thumbnail_loader.py tests/unit/test_thumbnail_repository.py tests/core/test_database_metadata.py
```

Result: **200 passed, 0 failed**, exit code 0, 46.76 seconds. Raw output: `artifacts/evidence/2026-08-22/thumbnail-cross-process-lock-order-followup/focused.stdout.log`.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25c-lockorder-full -n 0 -q
```

Result: **3972 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 579.26 seconds. Raw output: `artifacts/evidence/2026-08-22/thumbnail-cross-process-lock-order-followup/full.stdout.log`.

### Static and governance gates

The complete audit validator, README/doc stats, boundaries, style sources, route capabilities, frontend data-fetch, layer DAG, Ruff, compileall, and `git diff --check` chain exited 0. Raw output: `artifacts/evidence/2026-08-22/thumbnail-cross-process-lock-order-followup/static.stdout.log` and `static.stderr.log`.

## Remaining limits

This correction remains **fixed-unverified**. It does not prove a crash-atomic DB/filesystem transaction, per-key distributed leases, POSIX/Windows replacement-race proof, Windows kernel reparse/handle atomicity, power-loss durability, network/UNC behavior, or PID-reuse-proof stale-owner recovery. Browser E2E, real LAN adversarial replacement, full ffmpeg/profile matrix, large-scale performance, CVE/dependency, package/release, clean-checkout, and mutation-side atomicity remain outside this follow-up.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
