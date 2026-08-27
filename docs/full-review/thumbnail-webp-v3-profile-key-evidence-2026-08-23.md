# Persistent WebP v3 Profile Key Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `thumbnail-webp-v3-profile-key-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; non-destructive WebP v3/profile batch |
| Baseline status SHA-256 | `93fbc0da61b5b2ca5864d58db896536bfbf49d20da5417b0df02cd4979069651` |
| Baseline diff SHA-256 | `386b3a7d3cec8de89a71e12a0b21d5a3c6427892e072ef108118b6721c59bfd9` |
| Baseline tracked / untracked entries | `142 / 94` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records the first persistent WebP profile-aware key rollout. It does not modify earlier reports or manifests. The machine-readable companion is [audit-manifest-thumbnail-webp-v3-profile-key-evidence-2026-08-23.json](audit-manifest-thumbnail-webp-v3-profile-key-evidence-2026-08-23.json).

## Implemented contract

The persistent WebP path now supports three canonical non-blurred profiles:

- `desktop-webp-256-v1`;
- `desktop-webp-512-v1`;
- `desktop-webp-1024-v1`.

`profiled_thumbnail_cache_key_v3()` includes the source fingerprint and canonical profile while preserving the 16-character lowercase artifact-key contract. Existing v2 and legacy key helpers remain unchanged and readable.

Schema migration 33 adds nullable `thumbnail_cache.render_profile`. Existing rows remain NULL; no synthetic backfill, rename, delete or bulk migration is performed. Repository metadata selection/upsert/conditional-delete now carries the profile while retaining the three-column legacy adapter.

Desktop WebP bakes use v3 keys and profile metadata. Reads try compatible v3 profiles first, then v2 and legacy WebP. Profile-insufficient artifacts are retained. Video JPG remains on its existing v2/legacy lifecycle and was not migrated.

`ThumbnailService.resolve()` tries compatible v3 WebP candidates before v2 and legacy, preserving bounded artifact admission, `cache_hit` semantics and source-admission bypass for valid cache hits. ProjectService now consumes complete metadata, rejects non-WebP rows and deterministically prefers the largest available baked profile. Path metadata migration handles profile-aware WebP keys, JPG extensions and key collisions without silently deleting destination artifacts.

README schema statistics and migration prose were updated from v32 to v33 after the static documentation gate detected the drift.

## Verification

### Focused matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch25g-focused-evidence -q tests/unit/test_thumbnail_key.py tests/unit/test_thumbnail_repository.py tests/core/test_db_migrations.py tests/unit/test_db_lock_low_batch.py tests/desktop/test_thumbnail_loader.py tests/integration/test_thumbnail_service.py tests/lan/test_thumbnail_admission.py tests/integration/test_project_service.py tests/core/test_database_metadata.py tests/unit/test_core_db_low_batch.py tests/unit/test_database_integrity_service.py tests/integration/test_file_operation_service.py
```

Result: **344 passed, 1 skipped, 0 failed**, exit code 0, 46.35 seconds. Raw output: `artifacts/evidence/2026-08-23/thumbnail-webp-v3-profile-key/focused.stdout.log`.

Coverage includes v3 key determinism/profile separation, v33 migration/repository contracts, Desktop and shared resolver fallback, ProjectService WebP filtering/profile selection, path collision preservation, integrity repair, file-operation cleanup, and existing video JPG non-regression.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25g-full -n 0 -q
```

Result: **3987 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 535.65 seconds. Raw output: `artifacts/evidence/2026-08-23/thumbnail-webp-v3-profile-key/full.stdout.log`.

### Static/governance gates

After updating the measured schema version and README migration anchors to v33, audit manifests, README stats, boundaries, style sources, route capabilities, frontend data-fetch, layer DAG, Ruff, compileall and `git diff --check` passed. Raw output: `artifacts/evidence/2026-08-23/thumbnail-webp-v3-profile-key/static.stdout.log` and `static.stderr.log`.

## Non-destructive rollout limits

This batch does not migrate, rename, delete or backfill existing v2/legacy artifacts. It does not migrate video JPG keys, persist blurred artifacts, add blur provenance, change WebUI namespace logic, rewrite all ProjectService historical semantics, redesign eviction/single-flight, or implement mutation/recovery atomicity.

The migration/path and profile behavior remains **fixed-unverified** for cross-platform filesystem races, power-loss recovery, browser/intermediary E2E, clean checkout, package/release, CVE/dependency and performance claims. Legacy backends and old readers that do not expose/consume the new profile metadata require separate compatibility testing.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
