# Thumbnail Video Lifecycle Hardening Evidence (2026-08-22)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `thumbnail-video-lifecycle-hardening-evidence-2026-08-22` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; follow-up after the 25-B evidence snapshot |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only follow-up records fixes found during post-25-B review. It does not modify the historical 25-B report or manifest. The machine-readable companion is [audit-manifest-thumbnail-video-lifecycle-hardening-evidence-2026-08-22.json](audit-manifest-thumbnail-video-lifecycle-hardening-evidence-2026-08-22.json).

## Implemented hardening

### `THUMBNAIL-VIDEO-METADATA-01`

`ThumbnailService.resolve()` now registers successful and reused video `.jpg` artifacts when a managed library connection is available. Registration records the identity-aware key, source size and `source_mtime_ns`, artifact size, and `artifact_kind='jpg'`. Standalone services without a provider remain usable and retain best-effort failure semantics (`AssetsManager/application/thumbnail_service.py:229`, `AssetsManager/application/thumbnail_service.py:391`).

Desktop existing-frame and asynchronous extraction paths use the same registration seam. This closes the previous LAN/Desktop lifecycle divergence, while registration failure remains non-fatal to image delivery (`AssetsManager/panels/file_list/_loader.py:961`, `AssetsManager/panels/file_list/_loader.py:1007`).

### `THUMBNAIL-VIDEO-CLEAR-01`

Dedicated ffmpeg extraction now checks the runtime cache epoch before and during publication, uses the per-directory artifact lock, and discards a frame published after `clear_thumb_cache()` invalidates the epoch. Clear also recognizes `.jpg.tmp` artifacts (`AssetsManager/panels/file_list/_loader.py:182`, `AssetsManager/panels/file_list/_loader.py:1294`).

### `THUMBNAIL-TRANSACTION-01`

`ThumbnailRepository.touch_access()` now supports `commit=False` and preserves caller-owned transactions instead of unconditionally committing a shared connection (`AssetsManager/repositories/thumbnail_repository.py:68`). A regression test covers rollback preservation.

The artifact coordinator now validates cache keys before temporary-file globbing, preventing malformed metadata keys from broadening cleanup matches (`AssetsManager/application/thumbnail_cache_lifecycle.py:50`).

## Executed verification

### Focused lifecycle matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch25b-video-final -q tests/integration/test_thumbnail_service.py tests/desktop/test_thumbnail_loader.py tests/unit/test_thumbnail_repository.py tests/unit/test_database_integrity_service.py tests/integration/test_file_operation_service.py tests/core/test_db_migrations.py
```

Result: **238 passed, 0 failed**, exit code 0. Raw output: `artifacts/evidence/2026-08-22/thumbnail-video-lifecycle-hardening/focused.stdout.log`.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25b-video-full -n 0 -q
```

Result: **3967 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 575.74 seconds. Raw output: `artifacts/evidence/2026-08-22/thumbnail-video-lifecycle-hardening/full.stdout.log`. Windows-limited symlink/POSIX/process skips and the two pre-existing warnings remain recorded; no independent POSIX race proof was run.

The post-index governance rerun validated all **27** manifests and re-ran the complete static gate chain successfully. Raw output: `artifacts/evidence/2026-08-22/thumbnail-video-lifecycle-hardening/static-post-index.stdout.log` and `static-post-index.stderr.log`.

## Remaining limits

The findings remain **`fixed-unverified`**. This follow-up does not prove cross-process ownership, DB/artifact atomicity across eviction/integrity/file-operation cleanup, power-loss recovery, Windows kernel-level reparse/handle atomicity, browser E2E, real LAN adversarial replacement, complete ffmpeg codec/container compatibility, profile-aware cache isolation, disk-pressure performance, CVE/dependency state, package/release execution, or clean-checkout reproducibility. Mutation-side copy/move/delete/restore atomicity remains outside this thumbnail follow-up.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
