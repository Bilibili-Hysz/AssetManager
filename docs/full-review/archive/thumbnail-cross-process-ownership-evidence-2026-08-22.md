# Thumbnail Cross-Process Ownership Evidence (2026-08-22)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `thumbnail-cross-process-ownership-evidence-2026-08-22` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; 25-C follow-up after the prior thumbnail lifecycle snapshots |
| Baseline status SHA-256 | `347bdd8a110ef00334311d9e4a2959530db1d02246f0906ce03e1cfae25e8590` |
| Baseline diff SHA-256 | `79281b6ce10a005ba13b5ca484e055ccd7cb6664f7473a8e4af06002cfdf092f` |
| Baseline tracked / untracked entries | `137 / 80` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records the 25-C ownership and SQLite busy-policy continuation. Historical reports and manifests remain unchanged. The machine-readable companion is [audit-manifest-thumbnail-cross-process-ownership-evidence-2026-08-22.json](audit-manifest-thumbnail-cross-process-ownership-evidence-2026-08-22.json).

## Implemented contracts

### `THUMBNAIL-CROSS-PROCESS-OWNER-01`

`cache_owner_lock()` now provides an OS-backed per-thumbnail-directory lease using the existing `LibraryLock`/`QLockFile` stale-owner semantics, while retaining the process-local `artifact_lock()` as the inner lock. Persistent publication and destructive cleanup paths now acquire the owner before filesystem and metadata operations (`AssetsManager/application/thumbnail_cache_lifecycle.py:28`, `AssetsManager/application/thumbnail_service.py:345`, `AssetsManager/panels/file_list/_loader.py:1230`, `AssetsManager/application/database_integrity_service.py:453`).

Video resolve, Desktop bake/video extraction, stale cache removal, clear, orphan cleanup, integrity thumbnail pruning, and file-operation projection cleanup use the owner seam. The owner file is a control marker and is excluded from artifact suffix handling. Temp names for Desktop WebP bake include PID and random entropy, preventing independent workers from cleaning each other's temporary files (`AssetsManager/panels/file_list/_loader.py:1225`).

### `THUMBNAIL-CONDITIONAL-DELETE-01`

`ThumbnailRepository.delete_if_matches()` deletes a row only when the observed source path, source timing, source size, baked/cache sizes, artifact kind, and creation timestamp still match. Eviction re-reads each candidate under the owner lease and uses this conditional delete, so a newer metadata upsert is not removed by an older eviction snapshot (`AssetsManager/repositories/thumbnail_repository.py:177`, `AssetsManager/application/thumbnail_service.py:360`).

### `SQLITE-THUMBNAIL-BUSY-01`

Managed database connections now explicitly set `PRAGMA busy_timeout` to the same 30-second policy used by `sqlite3.connect(timeout=30)`. Thumbnail repository writes use a bounded complete-operation retry for retryable `database is locked`/`database is busy` errors; caller-owned transactions are not automatically replayed or rolled back (`AssetsManager/core/database.py:68`, `AssetsManager/core/database.py:908`, `AssetsManager/repositories/thumbnail_repository.py:41`).

`touch_access`, `upsert_entry`, `delete_entries`, `delete_path`, and `clear_all` share the write boundary; `commit=False` remains caller-owned. The repository public `commit()` now observes the connection write lock.

## Executed verification

### Focused ownership/lifecycle matrix

```text
python -W error::RuntimeWarning -m pytest -n 0 --basetemp=.zcode/pytest-batch25c-focused -q tests/integration/test_thumbnail_service.py tests/desktop/test_thumbnail_loader.py tests/unit/test_thumbnail_repository.py tests/core/test_database_metadata.py tests/unit/test_database_integrity_service.py tests/integration/test_file_operation_service.py tests/core/test_db_migrations.py
```

Result: **260 passed, 0 failed**, exit code 0, 49.40 seconds. Coverage includes real subprocess owner exclusion and owner recovery, video metadata registration, conditional eviction deletes, transaction preservation, SQLite pragma contract, cleanup paths, migrations, Desktop lifecycle, and file-operation projection behavior. Raw output: `artifacts/evidence/2026-08-22/thumbnail-cross-process-ownership/focused.stdout.log`.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch25c-full -n 0 -q
```

Result: **3972 passed, 14 skipped, 17 deselected, 2 warnings**, exit code 0, 625.46 seconds. The two warnings are the pre-existing share-dialog signal disconnect and duplicate ZIP-entry validation warning. Windows-limited symlink/POSIX/process skips remain recorded. Raw output: `artifacts/evidence/2026-08-22/thumbnail-cross-process-ownership/full.stdout.log`.

### Static and governance gates

All of the following exited 0; raw output is in `artifacts/evidence/2026-08-22/thumbnail-cross-process-ownership/static.stdout.log`:

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

The post-index governance rerun validated all **28** manifests and re-ran the complete static gate chain successfully. Raw output: `artifacts/evidence/2026-08-22/thumbnail-cross-process-ownership/static-post-index.stdout.log` and `static-post-index.stderr.log`.

## Remaining limits

The findings remain **`fixed-unverified`**. The subprocess tests prove owner exclusion and recovery for the implemented QLockFile seam on Windows, but do not prove POSIX/Windows filesystem replacement races, Windows kernel-level reparse/handle atomicity, power-loss durability, network/UNC filesystem behavior, or PID-reuse-proof stale recovery. The protocol is still coarse per thumbnail directory rather than a per-key distributed lease, and does not provide a full crash-atomic transaction spanning SQLite metadata and filesystem artifacts.

Eviction, integrity, clear, file-operation cleanup, and publication remain separately recoverable operations even though they now share the owner boundary. Browser E2E, real LAN adversarial replacement, complete ffmpeg codec/container compatibility, large-scale disk/memory performance, profile/max-size/blur isolation, CVE/dependency state, package/release execution, clean-checkout reproducibility, and mutation-side copy/move/delete/restore atomicity were not run in this batch.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
