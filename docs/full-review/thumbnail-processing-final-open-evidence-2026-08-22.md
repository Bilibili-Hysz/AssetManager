# Thumbnail Processing Final-Open Evidence (2026-08-22)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `thumbnail-processing-final-open-evidence-2026-08-22` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; baseline captured before this report and manifest were added |
| Baseline status SHA-256 | `5a6d40770c998185caa469896b34e97c434683b5ad4e778c8cd87ef7b8a3f9e0` |
| Baseline diff SHA-256 | `f9cd92893cec5add6a98a097c71d486c4fac5ffe4065b921687816e55bd01172` |
| Baseline tracked / untracked entries | `128 / 67` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records the thumbnail/Pillow/ffmpeg continuation of final-open hardening. Historical snapshots remain unchanged. The machine-readable companion is [audit-manifest-thumbnail-processing-final-open-evidence-2026-08-22.json](audit-manifest-thumbnail-processing-final-open-evidence-2026-08-22.json).

## Implemented contracts

### `THUMBNAIL-SNAPSHOT-01` - application-safe source snapshots

The shared final-open implementation now lives in `AssetsManager/core/file_snapshot.py`, with no LAN or Qt dependency. It provides identity-bound root-confined handles, POSIX descriptor-relative no-follow traversal, Windows reparse/ADS mitigation, and bounded byte snapshots. `AssetsManager/lan/safe_open.py` remains a compatibility adapter for existing LAN names and error types.

`ThumbnailService.process_image()` now snapshots the source before decoding and delegates to `process_image_bytes()`. Pillow operates within a `BytesIO` lifetime, explicitly loads the image, applies EXIF orientation/resize/blur/mode conversion, and emits WEBP without reopening the user path (`AssetsManager/application/thumbnail_service.py:375-450`).

### `THUMBNAIL-ROUTE-01` - one snapshot through route processing

Single and batch thumbnail routes now safe-read resolved sources once and pass the captured bytes through the bytes processing seam. `/api/image` and the shared blur-gated helper verify and process the same captured bytes instead of separately verifying and reopening the source path (`AssetsManager/lan/routes/thumbnails.py:74-132`, `AssetsManager/lan/routes/image.py:91-137`, `AssetsManager/lan/routes/_helpers.py:510-551`). Legacy test/service doubles retain the old `process_image` seam through `process_image_snapshot()` without changing the real service path.

### `THUMBNAIL-VIDEO-01` - ffmpeg consumes a controlled snapshot

When a new video frame is needed, the source is safely snapshotted first. ffmpeg receives a closed, named temporary input with the original suffix; its output is written to a random temporary path and atomically replaced into the thumbnail cache only after success. Temporary input/output files are cleaned on failure. The existing path-based `_extract_video_frame(Path, Path)` remains for desktop loader compatibility (`AssetsManager/application/thumbnail_service.py:322-426`).

## Executed verification

### Focused thumbnail/media regression

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-thumbnail-evidence-final -q tests/integration/test_thumbnail_service.py tests/integration/test_share_service.py tests/lan/test_image_routes.py tests/lan/test_thumbnail_admission.py tests/lan/test_share_preview_policy.py tests/lan/test_lan_api.py::TestThumbnailSecurity::test_thumbnail_route_serves_nested_image_for_browser_preview tests/lan/test_safe_open.py tests/lan/test_helpers.py tests/desktop/test_thumbnail_loader.py
```

Result: **412 passed, 2 skipped, 0 failed**, exit code 0, 33.56 seconds. Skips are Windows symlink privilege limitations. Coverage includes bytes/Pillow processing, source identity, video snapshot extraction, thumbnail/image/blur/share routes, ZIP helper compatibility, and desktop loader compatibility. Raw output: `artifacts/evidence/2026-08-22/thumbnail-processing-final/focused.stdout.log`.

### Full Python suite

```text
python -m pytest --basetemp=.zcode/pytest-thumbnail-full-final -n 0 -q
```

Result: **3950 passed, 14 skipped, 17 deselected, 0 failed, 2 warnings**, exit code 0, 636.85 seconds. Windows-limited skips include symlink privileges, POSIX flock recovery, and nondeterministic process termination. Existing warnings are the share-dialog signal disconnect and duplicate ZIP-entry validation warning. Raw output: `artifacts/evidence/2026-08-22/thumbnail-processing-final/full.stdout.log`.

### Static and governance gates

The following exited 0; raw output is in `artifacts/evidence/2026-08-22/thumbnail-processing-final/static.stdout.log`:

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

## Status and remaining limits

The thumbnail processing findings remain **`fixed-unverified`**. This Windows evidence does not prove independent POSIX race behavior, fully atomic Windows reparse handling, ffmpeg container compatibility across the full media matrix, browser E2E/range behavior, large-file memory/performance limits, real LAN adversarial replacement, CVE/dependency state, package/release execution, clean-checkout reproducibility, or power-loss recovery.

Desktop `QImageReader(path)` and desktop ffmpeg compatibility remain separate path-based consumers outside this batch. Thumbnail cache key redesign/eviction/performance, mutation-side atomicity, and archive restore/quarantine remain deferred.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
