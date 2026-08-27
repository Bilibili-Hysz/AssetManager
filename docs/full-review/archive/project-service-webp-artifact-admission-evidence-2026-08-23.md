# ProjectService WebP Artifact Admission Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `project-service-webp-artifact-admission-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; non-destructive shared WebP admission batch |
| Baseline status SHA-256 | `4ca65709ba82d4ee97641e940008d6a7bff1e5248f457d02a35da64f2f5498fb` |
| Baseline diff SHA-256 | `7f3fb67d3b14b8a13fa07f3b41a61fa4f21db18b4e7a96f5181dcec5dd859c42` |
| Baseline tracked / untracked entries | `143 / 100` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot makes ProjectService reuse the existing read-only WebP bytes admission owner. The machine-readable companion is [audit-manifest-project-service-webp-artifact-admission-evidence-2026-08-23.json](audit-manifest-project-service-webp-artifact-admission-evidence-2026-08-23.json).

## Implemented contract

After metadata, source identity, safe key/path and containment checks pass, `ProjectService._attach_baked_thumbnails()` now calls the existing `admit_thumbnail_cache_artifact()` helper with the validated profile size.

The shared helper performs bounded stable snapshot admission, WebP format verification, Pillow `verify()` and `load()`, positive dimensions and minimum max-edge validation. It returns cache-miss semantics for malformed, non-WebP, undersized, oversized or changed-during-read artifacts. ProjectService does not acquire `cache_owner_lock()`, duplicate Pillow logic, delete metadata or delete artifacts.

DirectoryCache preview precedence, NULL-profile v2/legacy compatibility, JPG exclusion, deterministic profile selection and source-relative `thumbnail_path` output remain unchanged.

Existing ProjectService tests that used `b"webp"` as a fake valid artifact were converted to real Pillow WebP fixtures; deliberately malformed tests remain malformed. This preserves the new shared admission contract without weakening tests.

## Verification

### Focused matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch25j-focused-evidence -q tests/integration/test_project_service.py tests/integration/test_project_service_containment.py tests/integration/test_thumbnail_service.py tests/desktop/test_thumbnail_loader.py
```

Result: **148 passed, 3 skipped, 0 failed**, exit code 0, 19.45 seconds. Raw output: `artifacts/evidence/2026-08-23/project-service-webp-artifact-admission/focused.stdout.log`.

Coverage includes valid WebP admission, malformed and undersized artifacts, invalid higher-profile fallback, shared-helper rejection behavior, source/key/containment checks, JPG exclusion and existing resolver/loader regressions.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25j-full -n 0 -q
```

Result: **3996 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 595.60 seconds. Raw output: `artifacts/evidence/2026-08-23/project-service-webp-artifact-admission/full.stdout.log`.

### Static/governance gates

Pre-index governance passed: audit manifests, README stats, boundaries, style sources, route capabilities, frontend data-fetch, layer DAG, Ruff, compileall and `git diff --check`. Raw output: `artifacts/evidence/2026-08-23/project-service-webp-artifact-admission/static.stdout.log` and `static.stderr.log`; post-index validation is recorded separately in the manifest.

## Compatibility limits

This batch does not add JPG v3/profile semantics, schema migrations, path migration changes, cache cleanup, browser/intermediary E2E, or mutation/recovery behavior. It does not claim ProjectService alone proves browser delivery; LAN routes and ThumbnailService still perform their own consumption-time checks.

The result remains **fixed-unverified** for cross-platform filesystem races, power-loss recovery, browser/intermediary E2E, mutation atomicity, clean checkout, package/release, CVE/dependency and performance claims. No commit, push, release, revert, reset, clean or dirty-worktree overwrite was performed.
