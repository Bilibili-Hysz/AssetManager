# C4-B Move metadata migration savepoint 证据（2026-08-21）

## 1. Scope and baseline

本报告记录 move/rename 的 metadata projection migration 原子边界、thumbnail rename 失败传播，以及单文件/批量移动的 `metadata_migration_failed` 降级契约。它是 C4-min 文件操作证据的独立补充，不修改既有快照。

本批针对证据收敛中的 `XFS-01` / `EVID-06`：文件系统 move 成功后，tags、metadata、favorites、thumbnail cache 的迁移可能部分写入，且原有 `ASSET_INDEX_ROOT_RESCAN` 不能修复完整 projection。

| Field | Value |
|---|---|
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Worktree source | Dirty worktree |
| Status fingerprint | `8ac218ac21adecf0b3423e3c0b860a53b26686967467825095fbb191db5418b1` |
| Binary diff fingerprint | `4450a0efbceaa260a4a751a8c46ddfa239d46fca018035d3844e5daca26117d3` |
| Tracked / untracked changes | 61 / 20 before this report and manifest were added |
| Runtime | Windows, Python 3.14 local environment |

## 2. Implemented findings

### C4-B-01 / XFS-01 / EVID-06: Migration savepoint and transaction ownership

`AssetsManager/core/database.py` now wraps the complete path projection migration in a SQLite savepoint. Tags, metadata, favorites and thumbnail-cache SQL mutations release the savepoint together; a mid-operation exception rolls back to the savepoint and re-raises the original failure. A caller-owned outer transaction remains active and is not committed or rolled back by the helper. On a helper-owned transaction, failure cleanup also clears the transaction boundary.

This prevents a later unrelated commit from committing a partial path migration. Existing successful migration behavior and caller-owned transaction preservation remain covered.

### C4-B-02 / XFS-01: Thumbnail rename failure is no longer silently accepted

When an old thumbnail byte file must be moved and `Path.replace()` raises `OSError`, migration now propagates the failure. The database savepoint therefore rolls back the cache-row update and other projection writes. Existing destination-thumbnail collision behavior remains unchanged.

SQLite cannot roll back a filesystem rename that already succeeded. The implementation and evidence do not claim cross-system atomicity; a complete durable metadata/tag/favorite/thumbnail repair envelope remains future work.

### C4-B-03 / XFS-01: Move failure observability and existing-directory reconciliation scope

Single-file and batch move paths now record `metadata_migration_failed` in the existing `FileOperationWarning` channel and enqueue an existing directory scope (destination directory, its parent, or the bound library root). Batch results expose the warning as `degraded=True`; the single-file `Path` return remains backward compatible and exposes the warning through its existing diagnostics channel.

The filesystem move and `FileSystemChanged("moved")` event still describe a completed filesystem operation. They do not assert that all database projections succeeded. The current queue remains `ASSET_INDEX_ROOT_RESCAN`, so it repairs asset index only and does not repair tags, metadata, favorites, thumbnail rows, or thumbnail bytes.

Batch move now rejects a caller-owned outer SQLite transaction before filesystem I/O, matching the single-file clean-boundary contract.

## 3. Executed validation

| Command | Result |
|---|---|
| `pytest tests/core/test_database_metadata.py tests/integration/test_file_operation_service.py -q -n 0 --basetemp=.zcode/c4b-basetemp-3` | 67 passed |
| `pytest tests/integration/test_favorite_file_operations.py tests/integration/test_event_publishing.py tests/unit/test_core_db_low_batch.py tests/unit/test_reconciliation_queue_sqlite_store.py -q -n 0 --basetemp=.zcode/c4b-neighbor-basetemp` | 50 passed |
| Python compile for changed implementation/tests | passed |
| Scoped Ruff for changed implementation/tests | passed |
| `python scripts/check_doc_stats.py` | README stats current |
| `python scripts/check_boundaries.py` | passed |
| `python scripts/check_style_sources.py` | 0 violations across 83 files |
| `python scripts/check_route_capabilities.py` | 0 violations |
| `python scripts/check_frontend_data_fetch.py` | 0 violations across 26 pages |
| `python scripts/check_layers.py` | layer DAG passed |
| `git diff --check` | no whitespace errors; LF/CRLF conversion warnings only |

The default pytest temp root remains inaccessible in this environment (`WinError 5`), so pytest commands used repository-local `--basetemp` and `-n 0`.

## 4. Explicit non-goals and remaining evidence

- The existing reconciliation queue remains asset-index-only; no complete filesystem projection repair worker or durable outbox was implemented.
- SQLite savepoints cannot undo a thumbnail filesystem rename that already succeeded; crash/retry compensation remains a separate design.
- Import partial/degraded results, watcher repair production, global after-commit semantics, and lifecycle drain unification were not changed.
- No full Python suite, browser E2E, real-backend LAN acceptance, performance benchmark, dependency/CVE scan, package/release validation, or independent Windows lifecycle CI was run.
- C4-B findings remain `fixed-unverified`; this report does not mark them `verified-fixed`.
