# LAN Final-Open / TOCTOU Hardening Evidence (2026-08-22)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `final-open-toctou-hardening-evidence-2026-08-22` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; baseline captured before this report and manifest were added |
| Baseline status SHA-256 | `3510e80ac9b1ec89370c3716dc0da1fcebed680ae1a3fa0e843021abf8cfd597` |
| Baseline diff SHA-256 | `224e06640613fe5d2c1ef03dc8f419ee0b11c6e3e644ec7358b6732b8b651e61` |
| Baseline tracked / untracked entries | `128 / 64` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only dated snapshot records final byte-acquisition hardening for LAN delivery. Earlier audit snapshots remain unchanged. Its machine-readable companion is [audit-manifest-final-open-toctou-hardening-evidence-2026-08-22.json](audit-manifest-final-open-toctou-hardening-evidence-2026-08-22.json).

## Implemented contracts

### `LAN-FINAL-OPEN-01` - bind delivery bytes to an opened handle

`safe_open_under_root()` now validates final containment, rejects link/reparse ancestors, requires a regular file, records descriptor identity, and returns an owned binary handle. POSIX uses descriptor-relative directory traversal with `O_DIRECTORY | O_NOFOLLOW` for ancestors and `O_NOFOLLOW` for the leaf (`AssetsManager/lan/safe_open.py:66-92`, `AssetsManager/lan/safe_open.py:95-149`). Windows retains ADS rejection plus reparse/path/identity rechecks, but this snapshot does not claim a fully atomic Windows no-follow primitive.

`read_safe_file()` reads only through that handle and verifies descriptor identity after the read (`AssetsManager/lan/safe_open.py:152-166`). Direct LAN delivery no longer gives a source path to delayed `aiohttp.FileResponse` opening in downloads, shares, raster image delivery, thumbnail originals/fallbacks, and shop file delivery (`AssetsManager/lan/routes/downloads.py:136-151`, `AssetsManager/lan/routes/shares.py:305-320`, `AssetsManager/lan/routes/_helpers.py:509-543`, `AssetsManager/lan/routes/image.py:103-116`, `AssetsManager/lan/routes/thumbnails.py:74-121`, `AssetsManager/lan/routes/shop/delivery.py:216-236`).

### `LAN-ZIP-FINAL-OPEN-01` - ZIP sources are read through safe handles

`build_zip_sync()` no longer calls `ZipFile.write(path)`. It skips link entries, safe-opens each top-level or recursive source, then uses `writestr()` with bytes read from the owned handle (`AssetsManager/lan/routes/_helpers.py:556-598`). This applies to download directory/batch ZIPs and shop delivery directory ZIPs without changing their existing temporary-file cleanup or quota order.

## Executed verification

### Focused final-open regression

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-final-open-evidence-final -q tests/lan/test_safe_open.py tests/lan/test_helpers.py tests/lan/test_path_guard.py tests/lan/test_image_routes.py tests/lan/test_thumbnail_admission.py tests/lan/test_free_download_quota.py tests/lan/test_commerce_routes.py tests/lan/test_share_claim_routes.py tests/lan/test_lan_api.py::TestThumbnailSecurity::test_thumbnail_route_serves_nested_image_for_browser_preview tests/lan/test_order_receipt_routes.py::test_receipt_delivery_uses_cookie_only_and_consumes_once tests/integration/test_thumbnail_service.py tests/integration/test_share_service.py
```

Result: **183 passed, 2 skipped, 0 failed**, exit code 0, 14.28 seconds. The skips are Windows symlink privilege limitations. Coverage includes safe handle identity, containment, replacement rejection, regular-file rejection, original thumbnail MIME contract, download quota preparation, share/shop delivery compatibility, and ZIP source bytes. Raw output is stored at `artifacts/evidence/2026-08-22/final-open-toctou-final/focused.stdout.log`.

### Full Python suite

```text
python -m pytest --basetemp=.zcode/pytest-final-open-full-posix -n 0 -q
```

Result: **3947 passed, 14 skipped, 17 deselected, 0 failed, 2 warnings**, exit code 0, 637.35 seconds. Windows-limited skips include unavailable symlink privileges, POSIX flock recovery, and nondeterministic abrupt process termination. The two warnings are the existing share-dialog signal disconnect and duplicate ZIP-entry validation warning. Raw output is stored at `artifacts/evidence/2026-08-22/final-open-toctou-final/full.stdout.log`.

### Static and governance gates

The following all exited 0 and their raw output is stored at `artifacts/evidence/2026-08-22/final-open-toctou-final/static.stdout.log`:

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

The final-open findings remain **`fixed-unverified`**. This local evidence does not prove independent POSIX deployment behavior, a fully atomic Windows handle traversal, browser E2E/range-response performance, real LAN backend behavior under adversarial replacement, large-file memory behavior, dependency/CVE state, package/release execution, clean-checkout reproducibility, or power-loss recovery.

This batch deliberately excludes mutation-side atomicity for copy/move/delete/restore, library export semantic refactoring, full thumbnail cache eviction/performance work, archive restore/quarantine writes, and the broader category generation architecture.

No commit, push, release, revert, reset, clean, or overwrite of existing dirty-worktree changes was performed.
