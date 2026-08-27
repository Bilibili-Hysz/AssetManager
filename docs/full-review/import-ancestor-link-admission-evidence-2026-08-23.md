# Import Ancestor Link Admission Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `import-ancestor-link-admission-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded 28-B ImportService ancestor-link admission batch |
| Baseline status SHA-256 | `5d488534b53b073845ffe0679456881a1b0557c18779e41fcd174252dc3bac00` |
| Baseline diff SHA-256 | `3ee219723f69c50d954e9897a56f6b771b355c673def690160e1d1c1229ff796` |
| Baseline tracked / untracked entries | `143 / 121` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records the bounded ImportService destination ancestor-link/reparse admission hardening and dynamic verification. The machine-readable companion is [audit-manifest-import-ancestor-link-admission-evidence-2026-08-23.json](audit-manifest-import-ancestor-link-admission-evidence-2026-08-23.json). Finding ID: `IMPORT-ANCESTOR-LINK-ADMISSION-28B-01`.

## Implemented contract

- Added application-layer `_reject_link_or_reparse_ancestors()` without introducing an application-to-LAN dependency.
- The helper uses the canonicalized session root as its trust anchor, checks only components below that root, rejects symlinks, junctions, mounts, Windows reparse attributes, non-directory components, and inspection failures, and allows missing trailing directories.
- `import_sources()` performs lexical destination admission before canonical planning/manifest creation, so an existing destination symlink or junction is rejected before it can be erased by `Path.resolve()`.
- `_copy_one()` revalidates the destination and relative target parent before and after directory creation, and revalidates explicit target parents before exclusive file creation.
- Existing `_plan_targets()` `candidate.exists()` and automatic `_1` rename semantics remain unchanged. The 28-A exclusive-create, leaf no-overwrite, metadata, identity-aware cleanup, manifest, cancellation, and subprocess positional signature contracts remain intact.

## Verification

### Focused matrix

```text
python -m pytest -n 0 -q tests/integration/test_import_service.py tests/integration/test_import_subprocess_termination.py tests/unit/test_import_manifest_store.py tests/integration/test_file_operation_service.py
```

Result: **95 passed, 2 skipped**, exit code 0, 40.56 seconds. The skipped cases are the nested POSIX symlink and dangling symlink tests because this Windows worker lacks symlink privilege (WinError 1314). Raw output: `artifacts/evidence/2026-08-23/import-ancestor-link-admission/focused.stdout.log`.

Coverage includes pre-existing nested destination symlink rejection, Windows junction admission when available, fail-closed inspection errors, deterministic post-plan parent revalidation, existing 28-A leaf races and cleanup, manifest recovery, subprocess compatibility, file-operation regressions, and auto-renaming.

### Full Python suite

```text
python -m pytest -n 0 -q
```

Result: **4021 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0, 553.57 seconds. Raw output: `artifacts/evidence/2026-08-23/import-ancestor-link-admission/full.stdout.log`.

The serial `-n 0` lane is used because this Windows environment previously failed xdist worker setup with a temporary-directory `PermissionError: [WinError 5]`. Skips remain platform-limited symlink/junction/POSIX flock cases and the existing nondeterministic multiprocessing Queue termination fixture. Warnings are the existing Qt signal disconnect warning and duplicate ZIP entry warning.

### Targeted static checks

The following commands each exited 0:

```text
python -m ruff check AssetsManager/application/import_service.py tests/integration/test_import_service.py
python -m compileall AssetsManager/application/import_service.py tests/integration/test_import_service.py -q
git diff --check
```

Raw outputs and SHA-256 digests are under `artifacts/evidence/2026-08-23/import-ancestor-link-admission/`.

## Findings and boundaries

`IMPORT-ANCESTOR-LINK-ADMISSION-28B-01` is **fixed-unverified** for the bounded admission contract: existing destination/relative-parent links are rejected, inspection failures fail closed, and deterministic revalidation prevents the tested unsafe parent path from being used. POSIX and Windows capability-gated tests were not both executable on this worker.

The following remain explicitly unverified or out of scope:

- This is not a POSIX `openat`/directory-fd proof and does not establish cross-platform race-proof behavior.
- Windows reparse-point replacement between checks, root-directory replacement, and native no-follow directory-handle semantics remain unverified.
- The session root itself and its parents remain the existing trust anchor contract; this batch does not change root identity or root alias behavior.
- Source directory symlink-following policy is unchanged and separate.
- Power-loss durability, copy replay/idempotency, filesystem+SQLite+queue atomicity, restore admission, package/release, dependency/CVE, performance, and clean-checkout claims are not made.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
