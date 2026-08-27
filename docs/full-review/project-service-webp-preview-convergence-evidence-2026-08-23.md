# ProjectService WebP Preview Convergence Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `project-service-webp-preview-convergence-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; non-destructive ProjectService preview validation batch |
| Baseline status SHA-256 | `dc2ded78a38b67f1dd310e9d38483818988ca8b54214a61237e1ecc27f1ad751` |
| Baseline diff SHA-256 | `266256a671128f9e77a828713e554e7a044945ebd49988a3a7aa930a197a37f9` |
| Baseline tracked / untracked entries | `143 / 98` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records ProjectService convergence with the WebP metadata/key contract. The machine-readable companion is [audit-manifest-project-service-webp-preview-convergence-evidence-2026-08-23.json](audit-manifest-project-service-webp-preview-convergence-evidence-2026-08-23.json).

## Implemented contract

`ProjectService._attach_baked_thumbnails()` now:

- accepts only `artifact_kind == "webp"` rows and image source extensions;
- validates non-null `render_profile` against the canonical WebP profile registry and requires its `baked_size` to match the profile size;
- preserves NULL-profile v2/legacy compatibility rows without synthetic backfill, while requiring a positive baked size;
- validates source size and nanosecond mtime when present, with the existing seconds-mtime fallback for older rows;
- derives artifacts through the safe `artifact_path()` key contract, rejecting nested/invalid keys and link/reparse components;
- selects the largest valid profile deterministically, preferring known profiles and then stable profile/cache-key ordering for equal sizes;
- preserves DirectoryCache preview precedence and keeps video JPG rows out of project WebP fallback.

The output remains the existing source-relative `thumbnail_path`; no cache key or artifact path is added to API DTOs. No metadata, artifact, migration or cache row is deleted or rewritten by this batch.

## Verification

### Focused matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch25i-focused-evidence -q tests/integration/test_project_service.py tests/integration/test_project_service_containment.py tests/integration/test_thumbnail_service.py tests/desktop/test_thumbnail_loader.py
```

Result: **145 passed, 3 skipped, 0 failed**, exit code 0, 20.41 seconds. Raw output: `artifacts/evidence/2026-08-23/project-service-webp-preview-convergence/focused.stdout.log`.

Coverage includes profile mismatch and unknown-profile rejection, legacy NULL-profile compatibility, source identity checks, safe cache-key handling, JPG exclusion, ProjectService containment and adjacent WebP/loader admission regressions.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25i-full -n 0 -q
```

Result: **3993 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 649.92 seconds. Raw output: `artifacts/evidence/2026-08-23/project-service-webp-preview-convergence/full.stdout.log`.

### Static/governance gates

Pre-index governance passed: audit manifests, README stats, boundaries, style sources, route capabilities, frontend data-fetch, layer DAG, Ruff, compileall and `git diff --check`. Raw output: `artifacts/evidence/2026-08-23/project-service-webp-preview-convergence/static.stdout.log` and `static.stderr.log`; the post-index run is recorded separately in the manifest.

## Compatibility limits

This batch does not decode/validate WebP bytes inside ProjectService; malformed/undersized WebP admission remains owned by `ThumbnailService`. It does not change ThumbnailService resolution, video JPG dual-read, WebP v3 key generation, schema migrations, path migration, cleanup, browser/intermediary E2E or API DTOs.

The result remains **fixed-unverified** for cross-platform filesystem races, power-loss recovery, browser/intermediary E2E, mutation atomicity, clean checkout, package/release, CVE/dependency and performance claims. No commit, push, release, revert, reset, clean or dirty-worktree overwrite was performed.
