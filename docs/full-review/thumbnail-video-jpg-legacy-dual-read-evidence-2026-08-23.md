# Video JPG Legacy Dual-Read Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `thumbnail-video-jpg-legacy-dual-read-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; non-destructive video JPG compatibility batch |
| Baseline status SHA-256 | `70993d10e7d326434b8f124d3076e00111fbfea0672e452fd8928436ed903f61` |
| Baseline diff SHA-256 | `a9d1ac90db3f493eff699b7f894643c925c8b28f2f3e11cb48044e6e677bcedb` |
| Baseline tracked / untracked entries | `142 / 96` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot closes the Shared/LAN video JPG compatibility gap without changing the existing key contract. The machine-readable companion is [audit-manifest-thumbnail-video-jpg-legacy-dual-read-evidence-2026-08-23.json](audit-manifest-thumbnail-video-jpg-legacy-dual-read-evidence-2026-08-23.json).

## Implemented contract

`ThumbnailService.resolve()` now checks video frame artifacts in this order under the existing cache-owner lock:

1. current identity-aware v2 `{cache_key}.jpg`;
2. pre-v2 legacy `{legacy_thumbnail_cache_key}.jpg`;
3. source snapshot and ffmpeg extraction into the v2 path.

A legacy hit is registered with its actual legacy cache key and frame path. New extraction still writes only the v2 key. Existing owner locking, bounded source snapshot, expected-identity verification, atomic ffmpeg publish, metadata registration and fixed 512px extraction remain unchanged.

The WebP cache admission path was not broadened to JPG: WebP format/dimension validation remains WebP-specific. No JPG v3/profile key, v34 migration, profile-aware path migration or destructive artifact migration was introduced. Existing lifecycle, eviction, integrity and file-operation cleanup behavior for `.jpg` remains unchanged.

## Verification

### Focused matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch25h-focused-evidence -q tests/integration/test_thumbnail_service.py tests/desktop/test_thumbnail_loader.py
```

Result: **101 passed, 0 failed**, exit code 0, 13.44 seconds. Raw output: `artifacts/evidence/2026-08-23/thumbnail-video-jpg-legacy-dual-read/focused.stdout.log`.

The focused tests include service-level legacy JPG reuse, v2-over-legacy precedence, extraction/reuse, managed JPG metadata registration and Desktop v2/legacy JPG regressions.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25h-full -n 0 -q
```

Result: **3989 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 608.06 seconds. Raw output: `artifacts/evidence/2026-08-23/thumbnail-video-jpg-legacy-dual-read/full.stdout.log`.

### Static/governance gates

The pre-report and post-report governance chains passed: audit-manifest validation, README stats, boundaries, style sources, route capabilities, frontend data-fetch, layer DAG, Ruff, compileall and `git diff --check`. Raw output: `artifacts/evidence/2026-08-23/thumbnail-video-jpg-legacy-dual-read/static.stdout.log` and `static.stderr.log`; the post-index run is recorded separately in the manifest.

## Compatibility limits

This batch does not define JPG render profiles or a v3 JPG key because both current producers use one fixed 512px first-frame contract and existing JPG metadata has nullable `render_profile`. It does not strengthen JPG artifact admission to the WebP format/dimension validator, prove stale-frame race behavior, add browser/intermediary E2E, or alter path-migration collision semantics.

The result remains **fixed-unverified** for cross-platform filesystem races, power-loss recovery, browser/intermediary E2E, mutation atomicity, clean checkout, package/release, CVE/dependency and performance claims. No commit, push, release, revert, reset, clean or dirty-worktree overwrite was performed.
