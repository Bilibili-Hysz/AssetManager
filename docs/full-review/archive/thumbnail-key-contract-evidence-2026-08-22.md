# Thumbnail Identity-Aware Key Contract Evidence (2026-08-22)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `thumbnail-key-contract-evidence-2026-08-22` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; baseline captured before this report and manifest were added |
| Baseline status SHA-256 | `2f0ef2f5571556d171ccc96c3d555bb405d46edcf2f9450d2ebbb42b3cd05843` |
| Baseline diff SHA-256 | `35da1c5998c52c8d15c3a0d60d1cd430fe6464390ca972cb8e04c2a12ffa8b63` |
| Baseline tracked / untracked entries | `132 / 73` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only dated snapshot records the 25-A identity-aware thumbnail key contract. Historical 24 reports/manifests remain unchanged. The machine-readable companion is [audit-manifest-thumbnail-key-contract-evidence-2026-08-22.json](audit-manifest-thumbnail-key-contract-evidence-2026-08-22.json).

## Implemented contracts

### `THUMBNAIL-KEY-CONTRACT-01` - shared versioned fingerprint key

`AssetsManager/core/thumbnail_key.py` is now the low-level owner of thumbnail key construction. `ThumbnailSourceFingerprint` contains the canonical resolved path plus device, inode, size, and `mtime_ns`; the v2 key includes an explicit version marker and preserves the existing 16-character lowercase hexadecimal artifact name (`AssetsManager/core/thumbnail_key.py:14`, `AssetsManager/core/thumbnail_key.py:45`, `AssetsManager/core/thumbnail_key.py:63`).

The helper accepts a previously observed identity/fingerprint. When supplied, it reuses that identity rather than statting the source again. This allows final-open snapshot callers to share the same source identity with key generation. The application service module cache now stores the complete fingerprint instead of only a second-resolution mtime (`AssetsManager/application/thumbnail_service.py:31`, `AssetsManager/application/thumbnail_service.py:108`).

### `THUMBNAIL-KEY-COMPAT-01` - legacy artifact reads

The pre-v2 path/second-mtime algorithm remains available as `legacy_thumbnail_cache_key()`. `ThumbnailService.resolve()` tries the new v2 `.webp` key first and then the legacy key; the Desktop loader does the same for `.webp` and video `.jpg` artifacts (`AssetsManager/core/thumbnail_key.py:84`, `AssetsManager/application/thumbnail_service.py:287`, `AssetsManager/panels/file_list/_loader.py:914`, `AssetsManager/panels/file_list/_loader.py:956`). New writes use the v2 key; this batch does not perform a destructive cache migration.

The external `ThumbnailResult.cache_hit` meaning is unchanged: an eligible cache artifact exists and is selected. This batch does not turn it into strict source metadata validation, and it does not change the existing behavior that a cache can be served without consuming the source.

### `THUMBNAIL-KEY-CALLERS-01` - shared database and desktop callers

The database path-migration compatibility wrapper now delegates to the shared v2 helper rather than maintaining a second path/mtime implementation (`AssetsManager/core/database.py:25`, `AssetsManager/core/database.py:1478`). Desktop `_disk_key()` accepts the snapshot identity and uses the same application/shared helper; snapshot-derived identities are propagated into image bake and video frame key selection (`AssetsManager/panels/file_list/_loader.py:927`, `AssetsManager/panels/file_list/_loader.py:1040`, `AssetsManager/panels/file_list/_loader.py:1198`).

No `thumbnail_cache` schema columns or migrations were added in this batch. Existing metadata fields and repository contracts remain unchanged; metadata/profile validation and persistent eviction are deferred to 25-B/25-D.

## Executed verification

### Key/storage/consumer focused matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch25-focused-final -q tests/unit/test_thumbnail_key.py tests/unit/test_thumbnail_repository.py tests/unit/test_core_db_low_batch.py tests/core/test_database_metadata.py tests/integration/test_thumbnail_service.py tests/integration/test_project_service.py tests/lan/test_thumbnail_admission.py tests/lan/test_image_routes.py tests/desktop/test_thumbnail_loader.py tests/desktop/test_file_list_view.py
```

Result: **316 passed, 1 skipped, 0 failed**, exit code 0, 78.03 seconds. The skip is a Windows directory-symlink privilege limitation. Raw output: `artifacts/evidence/2026-08-22/thumbnail-key-contract/focused.stdout.log`.

The matrix covers v2 key determinism, same-path identity replacement, nanosecond mtime changes, supplied-identity no-stat behavior, legacy `.webp` compatibility, database path migration, repository metadata CRUD, ProjectService baked-thumbnail containment, LAN admission/image routes, Desktop disk/memory cache behavior, snapshot identity propagation, and FileList runtime lifecycle.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25-full -n 0 -q
```

Result: **3959 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 577.30 seconds. Existing warnings are the share-dialog signal disconnect and duplicate ZIP-entry validation warning. Windows-limited skips include symlink privileges, POSIX flock recovery, and nondeterministic process termination. Raw output: `artifacts/evidence/2026-08-22/thumbnail-key-contract/full.stdout.log`.

### Static and governance gates

The following exited 0; raw output is in `artifacts/evidence/2026-08-22/thumbnail-key-contract/static.stdout.log`:

- `python scripts/check_audit_reports.py`
- `python scripts/check_doc_stats.py`
- `python scripts/check_boundaries.py`
- `python scripts/check_style_sources.py`
- `python scripts/check_route_capabilities.py`
- `python scripts/check_frontend_data_fetch.py`
- `python scripts/check_layers.py`
- `python -m ruff check AssetsManager tests scripts run.py`
- `python -m compileall AssetsManager -q`
- `git diff --check`

README structure statistics were updated by the managed `check_doc_stats.py --fix` command because this batch adds one core module and one Python test file (`core=34`, `python_test_files=274`).

## Status and remaining limits

The key contract findings remain **`fixed-unverified`**. This Windows evidence does not prove independent POSIX replacement-race behavior, Windows kernel-level reparse/handle atomicity, complete ffmpeg codec/container compatibility, browser E2E, real LAN adversarial replacement, large-file memory/performance limits, persistent cache eviction, cross-process single-flight generation, CVE/dependency state, package/release execution, clean-checkout reproducibility, or power-loss recovery.

This batch deliberately does not modify `thumbnail_cache` schema/metadata fields, strictify `cache_hit`, isolate every max-size/blur/bake profile in the persistent key, implement disk eviction, coordinate cross-process writers, or change WebUI sessionStorage semantics. The module key cache, disk baked cache, Desktop memory cache, grid texture cache, and WebUI sessionStorage cache remain distinct layers.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
