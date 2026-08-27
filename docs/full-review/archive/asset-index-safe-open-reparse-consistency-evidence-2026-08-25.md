# AssetIndex / Safe-Open Reparse Consistency Evidence (2026-08-25)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `asset-index-safe-open-reparse-consistency-evidence-2026-08-25` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded 30-C reparse detection consistency batch |
| Baseline status SHA-256 | `75ceb75f7df10da73c1702f30b15135879607d541231f8657156d86e3bfb901a` |
| Baseline diff SHA-256 | `b94164cb85ae12274cdafb8b33707d6f586905876dbb37a790dd30e7d5529c04` |
| Baseline tracked / untracked entries | `143 / 133` (counts taken before this batch's report/manifest landed) |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot aligns link/reparse admission across the asset index and the final-open snapshot path, closing the last known fail-open inspection point. The machine-readable companion is [audit-manifest-asset-index-safe-open-reparse-consistency-evidence-2026-08-25.json](audit-manifest-asset-index-safe-open-reparse-consistency-evidence-2026-08-25.json). Finding ID: `REPARSE-DETECTION-CONSISTENCY-30C-01`.

## Implemented contract

- **AssetIndexService** `_is_link_or_reparse()` gains a Windows-only attribute leg: `entry.stat(follow_symlinks=False)` carrying `FILE_ATTRIBUTE_REPARSE_POINT` classifies the entry as a link. This closes a real hole — `os.DirEntry` has no `is_junction`, so junctions previously passed single-directory scans undetected (the tree-prune path used `pathlib.Path` and was covered only on Python ≥3.12). OSError handling stays fail-closed; POSIX behavior is byte-identical (the leg is inactive).
- **core/file_snapshot** `_reject_reparse_ancestors()` Windows branch now uses non-following `os.lstat()`, converts any inspection OSError into `SnapshotPathEscapeError` (fail-closed), and probes `is_junction`/`is_mount` via getattr-callable instead of swallowing `AttributeError`. Previously a broken junction whose follow-stat failed slipped through with no test locking that behavior. Desktop/LAN final-open consumers become stricter on uninspectable components by design.
- Test-infrastructure hardening in the recovery process-termination module: child status writes retry transient `PermissionError` during the atomic replace handshake, the barrier ceiling rose to 90s for cold interpreter starts under full-suite pressure, and checkpoint timeouts now surface child liveness plus stderr tails.

## Verification

### Focused matrix

```text
python -m pytest -n 0 -q tests/lan/test_safe_open.py tests/integration/test_asset_index_service.py tests/integration/test_project_service_containment.py tests/desktop/test_thumbnail_loader.py tests/integration/test_import_manifest_recovery_claim_process.py
```

Result: **122 passed, 5 skipped**, exit code 0 (symlink privilege and platform-gated skips). Raw output: `artifacts/evidence/2026-08-25/reparse-consistency/focused.stdout.log`.

New regressions:

- Fake-entry unit tests pin the reparse-attribute leg (`nt`-gated), plain-entry acceptance, and OSError fail-closed behavior of `_is_link_or_reparse`.
- A real NTFS junction integration test (mklink /J) proves both scan paths exclude the junction and its external sentinel while regular files index normally.
- A monkeypatched ancestor-lstat failure proves `open_under_root` fails closed through the safe-open adapter (`PathEscapeError`) instead of following an uninspectable component.
- A real broken-junction smoke test (junction whose target is removed) rejects opening through it.

### Full Python suite

Two runs are recorded honestly:

1. First run failed once: `test_kill_after_claim_blocks_takeover_until_lease_expiry` hit the cold-start barrier timeout (30s insufficient under full-suite memory pressure).
2. After raising the barrier ceiling to 90s and adding stderr diagnostics, a second pre-existing flake surfaced — the dual-race child's atomic JSON replace transiently failed with WinError 5 while the parent read the file; fixed with a bounded PermissionError retry.

Final green run: **4043 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0, 614.34 seconds. Raw output: `artifacts/evidence/2026-08-25/reparse-consistency/full.stdout.log`.

### Targeted static checks

```text
python -m ruff check AssetsManager/application/asset_index_service.py AssetsManager/core/file_snapshot.py tests/integration/test_asset_index_service.py tests/lan/test_safe_open.py
python -m compileall AssetsManager/application/asset_index_service.py AssetsManager/core/file_snapshot.py tests/integration/test_asset_index_service.py tests/lan/test_safe_open.py -q
git diff --check
```

Each exited 0; digests under `artifacts/evidence/2026-08-25/reparse-consistency/`.

## Findings and boundaries

`REPARSE-DETECTION-CONSISTENCY-30C-01` is **fixed-unverified**: the tested junction exclusion, reparse-attribute classification, and fail-closed inspection behaviors pass deterministically on Windows; POSIX CI keeps prior behavior unchanged.

Explicitly remaining:

- No cross-platform race-proof claim: components replaced *between* checks remain outside this batch's scope on every platform.
- Mount-point policy beyond rejection (e.g., allowing trusted mounts) is out of scope; junction cleanup semantics unchanged.
- The extra per-entry stat on Windows scans trades one metadata read for junction coverage; not benchmarked here.
- Power-loss, exactly-once, E2E/LAN intermediary, CVE/dependency, performance, package/release, and clean-checkout claims remain out of scope.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
