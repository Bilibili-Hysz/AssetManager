# Thumbnail Cache Metadata and Eviction Evidence (2026-08-22)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `thumbnail-cache-metadata-eviction-evidence-2026-08-22` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; baseline captured before this report and manifest were added |
| Baseline status SHA-256 | `041eac729fafdda5fa499cfd4cc6e1dbb26f0578921f6fdc079a066550471f19` |
| Baseline diff SHA-256 | `0fa5ef6aab11e860bfd1bf892baa82931ac2ac054fce154bbd5be8fff8502256` |
| Baseline tracked / untracked entries | `137 / 76` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only dated snapshot records the 25-B thumbnail metadata and persistent eviction continuation. Historical 25 reports/manifests remain unchanged. The machine-readable companion is [audit-manifest-thumbnail-cache-metadata-eviction-evidence-2026-08-22.json](audit-manifest-thumbnail-cache-metadata-eviction-evidence-2026-08-22.json).

## Implemented contracts

### `THUMBNAIL-METADATA-PERSISTENCE-01` - v32 metadata lifecycle

`thumbnail_cache` now has an append-only schema v32 migration with nullable `source_mtime_ns`, `artifact_kind` (`webp`/`jpg`), and a stable `last_access` eviction index. Fresh schema and existing v31 databases converge through the new migration without changing the historical v1-v31 migration names or baseline contract (`AssetsManager/core/database.py:397`, `AssetsManager/core/db_migrations.py:47`, `AssetsManager/core/db_migrations.py:1021`). Legacy rows retain `NULL`/default semantics and no synthetic identity is backfilled.

`ThumbnailRepository` now exposes a complete immutable `ThumbnailMetadata` DTO, `get_entry()`, stable eviction candidates, batch deletion, and an upsert using `ON CONFLICT DO UPDATE`. Existing three-column metadata and positional upsert adapters remain available. Explicit `commit=False` preserves caller-owned savepoints, while the historical default commit behavior remains unchanged (`AssetsManager/repositories/thumbnail_repository.py:13`, `AssetsManager/repositories/thumbnail_repository.py:53`, `AssetsManager/repositories/thumbnail_repository.py:79`, `AssetsManager/repositories/thumbnail_repository.py:144`).

### `THUMBNAIL-ARTIFACT-LIFECYCLE-01` - unified derived artifact handling

`thumbnail_cache_lifecycle.py` derives artifact paths only from a validated cache key, cache directory, and known artifact kind. The process-local per-directory lock coordinates artifact removal and eviction for the participating writers (`AssetsManager/application/thumbnail_cache_lifecycle.py:35`). Desktop clear/orphan cleanup and file-operation projection cleanup now cover `.webp`, `.jpg`, and controlled `.tmp` artifacts. Integrity orphan repair recognizes both `.webp` and `.jpg` and uses the safe derived path (`AssetsManager/panels/file_list/_loader.py:1207`, `AssetsManager/panels/file_list/_loader.py:1225`, `AssetsManager/application/database_integrity_service.py:468`, `AssetsManager/application/file_operation_service.py:1209`).

Video frames produced by the Desktop loader are registered as `artifact_kind='jpg'` with source `mtime_ns` and cache size metadata. Image bake metadata records the same precise source timing (`AssetsManager/panels/file_list/_loader.py:991`, `AssetsManager/panels/file_list/_loader.py:1183`).

### `THUMBNAIL-STALE-EVICTION-01` - bounded single-process persistent eviction

`ThumbnailService.evict_cache()` reads candidates in `last_access`, `created_at`, `cache_key` order, accounts for entry bytes/count, removes only derived artifacts under the thumbnail directory lock, and deletes metadata only after successful or already-absent artifact removal (`AssetsManager/application/thumbnail_service.py:295`). This is intentionally a single-process coordinator; cross-process ownership and single-flight remain 25-C work.

The existing `cache_hit` meaning and 25-A legacy key fallback remain unchanged. This batch does not silently convert cache hits into strict source/profile validation.

## Executed verification

### Metadata, cleanup, and consumer focused matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch25b-focused-final -q tests/unit/test_thumbnail_repository.py tests/unit/test_database_integrity_service.py tests/core/test_db_migrations.py tests/core/test_database_metadata.py tests/unit/test_core_db_low_batch.py tests/integration/test_thumbnail_service.py tests/integration/test_project_service.py tests/integration/test_file_operation_service.py tests/lan/test_thumbnail_admission.py tests/lan/test_image_routes.py tests/desktop/test_thumbnail_loader.py tests/desktop/test_file_list_view.py
```

Result: **450 passed, 1 skipped, 0 failed**, exit code 0, 109.85 seconds. The skip is a Windows directory-symlink privilege limitation. Coverage includes v32 migration, complete metadata DTO/upsert/candidate/delete semantics, `.webp/.jpg/.tmp` cleanup, integrity orphan repair, file-operation projection cleanup, single-process byte eviction, ProjectService preview filtering, LAN thumbnail/image routes, and Desktop loader lifecycle. Raw output: `artifacts/evidence/2026-08-22/thumbnail-cache-metadata-eviction/focused.stdout.log`.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25b-full -n 0 -q
```

Result: **3965 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 598.13 seconds. Existing warnings are the share-dialog signal disconnect and duplicate ZIP-entry validation warning. Windows-limited skips include symlink privileges, POSIX flock recovery, and nondeterministic process termination. Raw output: `artifacts/evidence/2026-08-22/thumbnail-cache-metadata-eviction/full.stdout.log`.

### Static and governance gates

The following exited 0; raw output is in `artifacts/evidence/2026-08-22/thumbnail-cache-metadata-eviction/static.stdout.log`:

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

README structure statistics are current at `app_services=51`, `schema_version=32`, and `python_test_files=274`.

A post-index governance rerun was completed after this report and manifest were linked from `00-INDEX.md`. It validated all **26** manifests and re-ran the complete static gate chain successfully. Raw output: `artifacts/evidence/2026-08-22/thumbnail-cache-metadata-eviction/static-post-index.stdout.log` and `static-post-index.stderr.log`.

## Status and remaining limits

The metadata, artifact lifecycle, and eviction findings remain **`fixed-unverified`**. This evidence is Windows-only and does not prove independent POSIX replacement-race behavior, Windows kernel-level reparse/handle atomicity, browser E2E, real LAN adversarial replacement, complete ffmpeg codec/container compatibility, large-scale disk/memory performance, CVE/dependency state, package/release execution, clean-checkout reproducibility, or power-loss recovery.

The eviction coordinator is process-local. Cross-process eviction ownership, single-flight generation, and writer coordination remain deferred to 25-C. Complete max-size/blur/bake profile isolation remains deferred to 25-D. Mutation-side copy/move/delete/restore atomicity, archive restore/quarantine recovery, and all power-loss semantics remain outside this batch. The module key cache, persistent disk cache, Desktop memory cache, grid texture cache, and WebUI sessionStorage cache remain separate layers.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
