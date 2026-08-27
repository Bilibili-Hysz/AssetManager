# Import Source Consistency TOCTOU Evidence (2026-08-25)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `import-source-consistency-toctou-evidence-2026-08-25` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded 28-E source-drift guard batch |
| Baseline status SHA-256 | `e0b807ba9cf8e78952cb4cf7bed8251eaca991cc99c3e211aab4c8bf24452e34` |
| Baseline diff SHA-256 | `f9139203d489a582e9fb1cf64e5d3655126412eaa3b3ef38aa0dcaabcb984873` |
| Baseline tracked / untracked entries | `143 / 129` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records the bounded source-consistency guard between manifest fingerprinting and streaming copy, and its dynamic verification. The machine-readable companion is [audit-manifest-import-source-consistency-toctou-evidence-2026-08-25.json](audit-manifest-import-source-consistency-toctou-evidence-2026-08-25.json). Finding ID: `IMPORT-SOURCE-CONSISTENCY-28E-01`.

## Implemented contract

- `_copy_one()` accepts a keyword-only `expected_fingerprint` (after `target`; positional callers and existing subprocess wrappers stay compatible).
- When a v2 fingerprint is supplied, the freshly opened source handle is fstat-checked before any bytes are written: size or mtime mismatch raises `OSError("{src}: source changed since manifest fingerprint")` before target creation proceeds.
- After streaming, the same handle is re-fstat-checked against its opened state (detects mid-copy replacement/truncation) and the consumed byte count (`tell()`) must equal the fingerprinted size (detects truncation/append divergence); mismatches raise deterministic OSErrors.
- Failures flow through the existing OSError cleanup path: only the exclusively created partial target is removed.
- `import_sources()` now hoists per-source fingerprints to the copy loop scope: v2 imports pass each item's durable fingerprint as the expectation; if any fingerprint capture fails the whole manifest falls back to v1 exactly as before (no expected values passed). `replay_import()`'s missing-target branch passes the durable fingerprint it has just verified against the current source.
- Payload structure is unchanged; content-level end-to-end proof remains owned by replay-time full SHA-256 adoption.

## Verification

### Focused matrix

```text
python -m pytest -n 0 -q tests/integration/test_import_service.py tests/integration/test_import_subprocess_termination.py tests/unit/test_import_manifest_store.py tests/integration/test_import_manifest_recovery_claim_process.py
```

Result: **56 passed, 2 skipped**, exit code 0, 16.46 seconds. Skips are the pre-existing Windows symlink privilege cases (WinError 1314). Raw output: `artifacts/evidence/2026-08-25/import-source-consistency-toctou/focused.stdout.log`.

New deterministic regressions:

- Calling `_copy_one` with a stale fingerprint after the source changed raises "changed since manifest fingerprint" and leaves no partial target.
- A `shutil.copyfileobj` wrapper that appends to the source after streaming completes triggers "source changed while copying"; the partial target is cleaned up.
- Both instance-level test wrappers (`_copy_one` rival injection and subprocess checkpoint) were widened with `**kwargs` and all previously pinned contracts — including the three subprocess termination checkpoints and both double-fault recovery paths — remain green.

### Full Python suite

```text
python -m pytest -n 0 -q
```

Result: **4035 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0, 608.39 seconds. Raw output: `artifacts/evidence/2026-08-25/import-source-consistency-toctou/full.stdout.log`. The serial `-n 0` lane remains required on this host (xdist worker temp-directory `PermissionError`); skips and warnings are the established platform-limited set.

### Targeted static checks

The following commands each exited 0:

```text
python -m ruff check AssetsManager/application/import_service.py tests/integration/test_import_service.py tests/integration/test_import_subprocess_termination.py
python -m compileall AssetsManager/application/import_service.py tests/integration/test_import_service.py tests/integration/test_import_subprocess_termination.py -q
git diff --check
```

Raw outputs and SHA-256 digests are under `artifacts/evidence/2026-08-25/import-source-consistency-toctou/`.

## Findings and boundaries

`IMPORT-SOURCE-CONSISTENCY-28E-01` is **fixed-unverified** for the bounded guard contract: stale-fingerprint rejection and mid-stream mutation detection are deterministically proven; normal v2 imports and replay now bind the streamed bytes to the durable fingerprint at handle level.

Remaining boundaries, explicitly unverified:

- Handle-level only: an in-place rewrite that preserves size and lands within filesystem mtime granularity is not detectable during copy; byte-exact proof still happens only at replay-time target adoption (full SHA-256).
- No cross-platform zero-race claim: POSIX has no dirfd/openat traversal here and Windows replacement races (reparse/junction swap between checks) remain open from earlier batches.
- No incremental hashing during streaming; `shutil.copyfileobj` stays the injection seam used by fault-injection tests.
- Power-loss windows, cross-system atomicity, exactly-once semantics, restore_backup admission, E2E/LAN/CVE/performance/release claims remain out of scope.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
