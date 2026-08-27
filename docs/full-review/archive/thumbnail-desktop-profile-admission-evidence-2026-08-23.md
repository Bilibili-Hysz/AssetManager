# Thumbnail Desktop Profile Admission Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `thumbnail-desktop-profile-admission-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; focused 25-D-A Desktop admission batch |
| Baseline status SHA-256 | `fed668d20759d29e0f84a2be3421df972a3139b9533f95d65ca5ff773bffed2b` |
| Baseline diff SHA-256 | `862ead7ffd1f468243ae6d80c21018c927e705b5cefbcb84e3ed5a98d876d245` |
| Baseline tracked / untracked entries | `137 / 84` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records the narrow Desktop persistent WebP profile-admission fix. It does not modify prior reports or manifests. The machine-readable companion is [audit-manifest-thumbnail-desktop-profile-admission-evidence-2026-08-23.json](audit-manifest-thumbnail-desktop-profile-admission-evidence-2026-08-23.json).

## Implemented contract

`ThumbnailLoader._load_image()` now captures one `get_bake_size()` value per request and passes it consistently through v2 and legacy disk-cache lookup. `_try_load_cached()` consumes the existing complete metadata DTO when available and computes `required_size = max(loader_size, bake_size)`.

The Desktop loader now:

- rejects a `.webp` row whose `artifact_kind` is not `webp`;
- rejects a positive `baked_size` below the current profile/loader requirement;
- preserves profile-insufficient artifacts and metadata for lower-profile use;
- uses actual WebP header dimensions as a conservative fallback when metadata is absent or `baked_size` is unknown;
- preserves legacy metadata rows with `source_mtime_ns=NULL` when their profile is sufficient;
- continues source-mtime stale invalidation behavior;
- uses the maximum decoded dimension for downscaling instead of width alone;
- leaves v2/legacy keys, LAN `cache_hit`, database schema, ProjectService, WebUI, and mutation services unchanged (`AssetsManager/panels/file_list/_loader.py:936`, `AssetsManager/panels/file_list/_loader.py:1149`).

## Verification

### Focused matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch25d-a-focused-final -q tests/desktop/test_thumbnail_loader.py tests/desktop/test_file_list_view.py tests/integration/test_thumbnail_service.py tests/unit/test_low_batch_loader.py
```

Result: **235 passed, 0 failed**, exit code 0, 77.79 seconds. Raw output: `artifacts/evidence/2026-08-23/thumbnail-desktop-profile-admission/focused.stdout.log`.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25d-a-full -n 0 -q
```

Result: **3977 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 624.31 seconds. Existing warnings and Windows-limited skips remain recorded. Raw output: `artifacts/evidence/2026-08-23/thumbnail-desktop-profile-admission/full.stdout.log`.

### Static/governance gates

The audit validator, README/doc stats, boundaries, style sources, route capabilities, frontend data-fetch, layer DAG, Ruff, compileall, and `git diff --check` chain exited 0. Raw output: `artifacts/evidence/2026-08-23/thumbnail-desktop-profile-admission/static.stdout.log` and `static.stderr.log`.

The post-index governance rerun validated all **30** manifests and re-ran the complete static gate chain successfully. Raw output: `artifacts/evidence/2026-08-23/thumbnail-desktop-profile-admission/static-post-index.stdout.log` and `static-post-index.stderr.log`.

## Remaining limits

This finding remains **fixed-unverified**. The batch does not provide profile-aware admission for LAN `ThumbnailService.resolve()`, WebUI namespace/profile isolation, v3 profile-aware persistent keys, ProjectService artifact-kind/profile convergence, blurred-artifact isolation, or video JPG admission changes. It also does not prove POSIX/Windows filesystem races, power-loss recovery, mutation atomicity, browser E2E, complete ffmpeg/profile matrices, performance, CVE/dependency, package/release, or clean-checkout behavior.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
