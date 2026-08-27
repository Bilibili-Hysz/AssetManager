# Thumbnail Blur Cache Privacy Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `thumbnail-blur-cache-privacy-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; focused LAN blurred-preview privacy batch |
| Baseline status SHA-256 | `32b13375ed0d5862d1e700863ac220f1d6300ba12f3b20d119590449f0d3d08f` |
| Baseline diff SHA-256 | `9558a1b5b6dd98fb67cce5329f48a03a05e6f04b10262870988539be80674314` |
| Baseline tracked / untracked entries | `137 / 88` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records the narrow LAN HTTP cache-header privacy fix. It does not modify prior reports or manifests. The machine-readable companion is [audit-manifest-thumbnail-blur-cache-privacy-evidence-2026-08-23.json](audit-manifest-thumbnail-blur-cache-privacy-evidence-2026-08-23.json).

## Finding and implementation

LAN thumbnail resolution already evaluates blur policy on cache hits: `ThumbnailService.resolve()` sets `should_blur`, and `lan/routes/thumbnails.py` processes cache hits rather than taking the unblurred-original fast path. The remaining issue was response caching: processed output always used `Cache-Control: public, max-age=3600`, including blurred output.

The single-thumbnail route now selects the existing shared header constants:

- `PRIVATE_PREVIEW_HEADERS` (`private, no-store`) when `result.should_blur` is true;
- `PUBLIC_PREVIEW_HEADERS` (`public, max-age=3600`) for unblurred processed output.

This keeps the existing content-security header and public caching behavior for non-sensitive previews while preventing browser/shared-cache retention of blurred sensitive previews. No cache key, metadata schema, WebUI namespace, route URL, batch response shape, or persistent blurred artifact producer was changed.

## Verification

### Focused LAN privacy matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch25e-privacy-focused-evidence -q tests/lan/test_thumbnail_admission.py tests/lan/test_image_routes.py tests/lan/test_lan_api.py
```

Result: **255 passed, 0 failed**, exit code 0. Raw output: `artifacts/evidence/2026-08-23/thumbnail-blur-cache-privacy/focused.stdout.log`.

Added regression coverage confirms blurred output is `private, no-store` and unblurred processed output remains `public, max-age=3600`. Existing malformed/undersized cache, image-route blur, batch, permission, and LAN security tests also pass.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25e-privacy-full -n 0 -q
```

Result: **3985 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 582.60 seconds. Raw output: `artifacts/evidence/2026-08-23/thumbnail-blur-cache-privacy/full.stdout.log`.

The skips are platform-limited symlink/POSIX-lock or Windows process cases. The two warnings are recorded in the raw output and were not reclassified as failures.

### Static/governance gates

The initial static chain passed: audit manifests, README stats, boundaries, style sources, route capabilities, frontend data-fetch, layer DAG, Ruff, compileall, and `git diff --check`. Raw output: `artifacts/evidence/2026-08-23/thumbnail-blur-cache-privacy/static.stdout.log` and `static.stderr.log`.

## Remaining limits

This batch does not claim complete blur/profile isolation. It does not add blur provenance to persistent artifacts, introduce v3/profile-aware keys, isolate WebUI/sessionStorage thumbnail namespaces, change Desktop policy scope, migrate metadata schema, or modify batch response cache headers. It also does not prove filesystem race behavior, power-loss recovery, mutation atomicity, browser E2E, performance, CVE/dependency, package/release, or clean-checkout behavior.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
