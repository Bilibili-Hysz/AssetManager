# Desktop Final-Open Migration Evidence (2026-08-22)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `desktop-final-open-migration-evidence-2026-08-22` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; baseline captured before this report and manifest were added |
| Baseline status SHA-256 | `fc3411f07c64443b1399a0a790cb63eaaa022bc0ad7d90f77eaf69364f512c59` |
| Baseline diff SHA-256 | `57608486d948422b06828ef005212d3089054ae5625a889f67cf8fed0f7d8265` |
| Baseline tracked / untracked entries | `132 / 69` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only dated snapshot records the desktop final-open continuation. It does not modify the prior 23 audit manifests. The machine-readable companion is [audit-manifest-desktop-final-open-migration-evidence-2026-08-22.json](audit-manifest-desktop-final-open-migration-evidence-2026-08-22.json).

## Implemented contracts

### `DESKTOP-FINAL-OPEN-01` - FileList image and video snapshot inputs

`ThumbnailLoader` now captures bounded source bytes through the shared `AssetsManager.core.file_snapshot.read_snapshot()` path before desktop image decode. `QImageReader` receives a `QBuffer` backed by the captured bytes rather than the admitted source path. Native bake tasks consume the same captured body and identity, and metadata uses the captured identity instead of reopening the source for size/mtime after decode (`AssetsManager/panels/file_list/_loader.py:107`, `AssetsManager/panels/file_list/_loader.py:886`, `AssetsManager/panels/file_list/_loader.py:1012`, `AssetsManager/panels/file_list/_loader.py:1132`).

Desktop video extraction now snapshots the source before dispatching to the dedicated ffmpeg pool. The pool task calls `ThumbnailService._extract_video_frame_from_bytes()` and therefore gives ffmpeg a controlled temporary input, not the user source path (`AssetsManager/panels/file_list/_loader.py:180`). Existing cached frame files remain cache-only reads.

The loader keeps its existing signal, generation, deferred-load, memory-budget, bake, cancellation, and ffmpeg-pool contracts. The memory cache records the captured `FileIdentity` when available and invalidates a hit when the current source identity differs.

### `DESKTOP-FINAL-OPEN-02` - ImageViewer snapshot decoding and EXIF isolation

The full-image and strip workers capture bounded source bytes and decode through `QBuffer`; they retain generation and cooperative cancellation checks. The viewer’s compatibility `_decode_image(path, max_dim)` helper remains available for explicit legacy callers and test doubles, while production worker tasks use `_decode_captured_image()` (`AssetsManager/panels/image_viewer.py:77`, `AssetsManager/panels/image_viewer.py:140`).

EXIF reads are now worker-side reads from captured bytes. The queued EXIF signal is rejected when generation or current path is stale, so metadata from a previous image cannot overwrite the current viewer (`AssetsManager/panels/image_viewer.py:168`, `AssetsManager/panels/image_viewer.py:623`). The public `_read_exif(path)` compatibility helper remains for direct callers/tests.

`MainWindow` passes the active library session root to `open_image_viewer()` while preserving the old call shape. Library-root confinement therefore applies to normal in-library viewer navigation (`AssetsManager/window.py:778`, `AssetsManager/window.py:791`).

### `DESKTOP-PREVIEW-FINAL-OPEN-01` - InfoPanel preview snapshot

The asynchronous InfoPanel preview path now uses the shared bounded snapshot primitive and `QBuffer`-backed `QImageReader`, including directory previews. The UI signal and fallback behavior are unchanged (`AssetsManager/panels/info.py:1059`, `AssetsManager/panels/_info_parts.py:184`).

## Executed verification

### Focused desktop/worker regression

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch24-focused -q tests/desktop/test_file_list_view.py tests/desktop/test_image_viewer.py tests/desktop/test_thumbnail_loader.py tests/desktop/test_info_async_identity.py tests/unit/test_workers.py tests/unit/test_low_batch_panels.py
```

Result: **236 passed, 0 failed**, exit code 0, 74.58 seconds. Raw output: `artifacts/evidence/2026-08-22/desktop-final-open/focused.stdout.log`.

Additional explicit snapshot regressions were included in the captured focused run, including decoding a captured body after source removal, identity-bound memory-cache completion, bytes-based video extraction, viewer stale-generation handling, and InfoPanel preview identity behavior.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch24-full-final -n 0 -q
```

Result: **3952 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 646.21 seconds. The warnings are the existing share-dialog signal disconnect and duplicate ZIP-entry validation warning. Windows-limited skips include symlink privilege limitations, POSIX flock recovery, and nondeterministic abrupt process termination. Raw output: `artifacts/evidence/2026-08-22/desktop-final-open/full.stdout.log`.

### Static and governance gates

The following exited 0; raw output is in `artifacts/evidence/2026-08-22/desktop-final-open/static.stdout.log`:

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

At the time of the static run, the validator reported the pre-index state of 23 manifests; this new report and manifest are intentionally appended afterward and must be validated again after indexing.

## Status and remaining limits

The desktop final-open findings remain **`fixed-unverified`**. The executed evidence is Windows-only and does not prove independent POSIX race behavior, fully atomic Windows reparse/handle semantics, browser E2E/range behavior, real LAN backend behavior, complete ffmpeg codec/container compatibility, large-file memory/performance limits, CVE/dependency state, package/release execution, clean-checkout reproducibility, or power-loss recovery.

The desktop loader’s legacy `_extract_video_frame(Path, Path)` compatibility method remains in `ThumbnailService` for external/older callers; the migrated FileList path does not use it. Thumbnail cache key redesign, persistent eviction, cross-process single-flight generation, mutation-side atomicity, and archive restore/quarantine recovery remain separate batches.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
