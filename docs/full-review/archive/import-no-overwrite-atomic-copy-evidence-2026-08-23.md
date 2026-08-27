# ImportService Atomic No-Overwrite Copy Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `import-no-overwrite-atomic-copy-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded 28-A ImportService copy batch |
| Baseline status SHA-256 | `b8bbfbed95e54810fb1859d8eee5ac99a9b88cee96098dbf12280b9e3fb2f381` |
| Baseline diff SHA-256 | `0114659989f9fa6b2b8126773535d062a1745f51b018f55b4ba2389cb587a9d4` |
| Baseline tracked / untracked entries | `143 / 117` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records the bounded ImportService no-overwrite copy hardening and its dynamic verification. The machine-readable companion is [audit-manifest-import-no-overwrite-atomic-copy-evidence-2026-08-23.json](audit-manifest-import-no-overwrite-atomic-copy-evidence-2026-08-23.json). Finding ID: `IMPORT-COPY-NO-OVERWRITE-28A-01`.

## Implemented contract

- `_copy_one()` now opens the source through an injectable read seam, rejects any existing directory entry with `os.path.lexists()`, and materializes the destination with `O_CREAT|O_EXCL` (plus Windows `O_BINARY` and POSIX `O_NOFOLLOW` when available).
- The created descriptor is checked with `fstat()` for a regular file. The resolved target parent is compared with the planned destination parent before bytes are written.
- Bytes are streamed with `shutil.copyfileobj()` and metadata is copied with `shutil.copystat(..., follow_symlinks=False)`.
- Cleanup records the created file identity (`st_dev`, `st_ino`) and removes a failed target only when the path still identifies that created file and the path was not marked escaped. A replacement/rival target is left untouched.
- The positional `_copy_one(src, rel, destination_dir, target=None)` contract remains compatible with existing subprocess test wrappers. Existing planner auto-renaming semantics remain unchanged.

## Verification

### Focused matrix

```text
python -m pytest -n 0 -q tests/integration/test_import_service.py tests/integration/test_import_subprocess_termination.py
```

Result: **26 passed, 1 skipped**, exit code 0, 11.98 seconds. The skipped test is the dangling-symlink case because this Windows worker lacks the privilege required to create symlinks (WinError 1314). Raw output: `artifacts/evidence/2026-08-23/import-no-overwrite-atomic-copy/focused.stdout.log`.

Coverage includes normal single-file and recursive imports, auto-renaming, source/read and stream failures, planning-time rival insertion, explicit pre-existing and repeated targets, owned partial cleanup, post-create target replacement during cleanup, session lease retention, subprocess-compatible invocation, and the platform-gated dangling-symlink rejection path.

### Targeted static checks

The following commands each exited 0:

```text
python -m ruff check AssetsManager/application/import_service.py tests/integration/test_import_service.py
python -m compileall AssetsManager/application/import_service.py tests/integration/test_import_service.py -q
git diff --check
```

Raw outputs and SHA-256 digests are under `artifacts/evidence/2026-08-23/import-no-overwrite-atomic-copy/`.

### Full Python suite

```text
python -m pytest -n 0 -q
```

The default xdist invocation was not usable in this Windows environment: worker setup failed before collection with `PermissionError: [WinError 5]` while creating `pytest-of-86177`. The equivalent serial run executed the suite and returned **4014 passed, 15 skipped, 20 deselected, 1 failed, 2 warnings**, exit code 1. The single failure was `tests/integration/test_file_operation_service.py::test_batch_move_rejects_caller_outer_transaction_before_filesystem_io`, which is outside the 28-A ImportService surface and was not changed in this batch. Raw output: `artifacts/evidence/2026-08-23/import-no-overwrite-atomic-copy/full.stdout.log`.

This full-suite result is recorded as a failed gate; it is not represented as a passing regression result.

## Findings and boundaries

`IMPORT-COPY-NO-OVERWRITE-28A-01` is **fixed-unverified** for the bounded contract: the local ordinary-file rival, exclusive-create rejection, owned partial cleanup, and post-create path-replacement cleanup tests passed on Windows. The implementation prevents the tested rival from being overwritten or deleted.

The following remain explicitly unverified or out of scope:

- Windows reparse-point/junction and ancestor-directory replacement races; Windows has no POSIX `O_NOFOLLOW` equivalent in this path.
- Full cross-platform race-proof claims, power-loss durability, copy replay/idempotency, and filesystem+SQLite+queue atomicity.
- Source filesystem metadata/xattr equivalence with the old `copy2()` behavior; this batch preserves basic stat metadata through `copystat` but does not claim xattr parity.
- The POSIX dangling-symlink branch was not executable on this Windows worker; its test is present and skipped with the privilege limitation.
- The unrelated full-suite transaction-boundary failure remains open and is not attributed to this batch.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
