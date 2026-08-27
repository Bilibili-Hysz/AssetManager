# Thumbnail Shared/LAN Cache Admission Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `thumbnail-shared-lan-profile-admission-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; focused 25-D-B shared/LAN WebP cache admission batch |
| Baseline status SHA-256 | `a6576113796309e4cc203025b681186eff0d6aa9302dfabe97ceee682ead021b` |
| Baseline diff SHA-256 | `6002d7c8b41e029b04d94db6d7488b9c400c76a502ff2a60d40b0ff07e6581d7` |
| Baseline tracked / untracked entries | `137 / 86` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records the narrow shared/LAN persistent WebP cache admission fix. It does not modify prior reports or manifests. The machine-readable companion is [audit-manifest-thumbnail-shared-lan-profile-admission-evidence-2026-08-23.json](audit-manifest-thumbnail-shared-lan-profile-admission-evidence-2026-08-23.json).

## Implemented contract

`ThumbnailService.resolve()` now validates each v2/legacy WebP candidate from a bounded, root-confined `read_snapshot()` before selecting it (`AssetsManager/application/thumbnail_service.py:111`, `AssetsManager/application/thumbnail_service.py:461`). The validator consumes only the captured bytes and requires:

- a stable regular-file snapshot within the thumbnail directory;
- a structurally valid WebP that can be loaded by Pillow;
- positive dimensions whose maximum edge meets the requested `max_size`.

Malformed, truncated, empty, non-WebP, undersized, replaced, or unreadable artifacts are treated as cache misses. They are retained for existing cleanup/eviction flows; no metadata row or artifact is deleted or rewritten. v2 is still attempted before legacy, and a valid cache still returns `cache_hit=True` with source-admission bypass semantics. The identity returned in the result is the identity captured by the same snapshot used for admission, so the existing LAN final-open check can detect later replacement.

The change is application-layer only. It does not alter `/api/image`, video JPG generation, database schema, thumbnail metadata, key versioning, WebUI cache namespaces, mutation/recovery, or route-local validation.

## Verification

### Focused shared/LAN matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch25d-b-focused-evidence -q tests/integration/test_thumbnail_service.py tests/lan/test_thumbnail_admission.py tests/lan/test_lan_api.py
```

Result: **294 passed, 0 failed**, exit code 0. Raw output: `artifacts/evidence/2026-08-23/thumbnail-shared-lan-profile-admission/focused.stdout.log`.

Coverage includes valid v2 and legacy WebP hits, maximum-edge admission for non-square artifacts, malformed and undersized cache fallback, invalid v2 to valid legacy fallback, oversized-source bypass for a valid cache, and LAN route responses that do not serve injected malformed/undersized bytes.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25d-b-full -n 0 -q
```

Result: **3983 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 613.94 seconds. Raw output: `artifacts/evidence/2026-08-23/thumbnail-shared-lan-profile-admission/full.stdout.log`.

The skips are platform-limited symlink/POSIX-lock or Windows process cases; the two warnings are recorded in the raw output and were not reclassified as failures.

### Static/governance gates

The initial static chain passed: audit manifests, README stats, boundaries, style sources, route capabilities, frontend data-fetch, layer DAG, Ruff, compileall, and `git diff --check`. Raw output: `artifacts/evidence/2026-08-23/thumbnail-shared-lan-profile-admission/static.stdout.log` and `static.stderr.log`.

A post-index governance rerun is recorded in `static-post-index.stdout.log` and `static-post-index.stderr.log`; it must be interpreted together with the companion manifest after indexing this report.

## Remaining limits

This finding remains **fixed-unverified**. This batch does not provide profile-aware key isolation, WebUI cache namespace isolation, v3 profile-aware persistent key migration, blurred-artifact isolation, generic video JPG convergence, ProjectService artifact-kind/profile convergence, or mutation/recovery atomicity. It does not prove POSIX/Windows filesystem race behavior, power-loss recovery, browser E2E, performance, CVE/dependency, package/release, or clean-checkout behavior.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
