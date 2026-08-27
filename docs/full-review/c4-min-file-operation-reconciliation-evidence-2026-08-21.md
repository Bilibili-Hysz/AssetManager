# C4-min 文件操作索引修复实施证据（2026-08-21）

## 1. Scope and baseline

本报告记录 FileOperationService 的 bounded reconciliation scope、delete/trash projection failure warning、restore snapshot failure warning，以及现有 asset-index root rescan queue 的接入。它不代表完整 filesystem projection repair/outbox 实施。

| Field | Value |
|---|---|
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Worktree source | Dirty worktree |
| Status fingerprint | `d82b89d8cf2045540a030ffe8ac97b944c55b62ab7b3174e99a6933f9455ca50` |
| Binary diff fingerprint | `a9b42d2d95ad7cf3d05ee1cf0cac10bccf8d6704b8d5a9efac861e506bd9aa9e` |
| Tracked / untracked changes | 55 / 16 before this report and manifest were added |
| Runtime | Windows, Python 3.14 local environment |

No commit, push, reset, clean, dependency installation, browser E2E, full Python suite, release validation, or vulnerability scan was performed.

## 2. Implemented findings

### C4-01 / XFS-01 / XFS-02 / EVID-06: Existing reconciliation scope

`FileOperationService._reconciliation_scope()` now selects an existing target directory, its existing parent, or the bound library root. Delete/trash projection failures therefore do not enqueue a task pointing at a deleted file or directory, which would otherwise become a terminal `FileNotFoundError` in the current worker.

The existing `ASSET_INDEX_ROOT_RESCAN` queue remains unchanged and is explicitly limited to asset-index repair. This batch does not claim that the queue repairs metadata, tags, favorites, thumbnails, or complete projection state.

### C4-02 / XFS-02: Delete/trash projection cleanup observability

Permanent delete and trash delete now convert projection cleanup failures into structured `FileOperationWarning` values with `projection_cleanup_failed`, `phase=projection_cleanup`, failure type, operation id, and the original affected path. The filesystem success result remains `ok=True` with `degraded=True`; the existing `deleted` invalidation event remains unchanged. A root/parent index rescan is queued using the normalized existing scope.

The underlying `_clear_deleted_projection()` savepoint rollback behavior is unchanged, so failed cleanup still preserves database rows rather than partially deleting them.

### C4-03 / XFS-06: Restore snapshot failure observability

`_restore_projection_snapshot()` now returns a success flag for malformed/unreadable snapshots and DB restore failures. `restore_backup()` records `projection_restore_failed` with the target path and queues an existing-scope asset-index rescan while preserving filesystem restore success and the existing `restored` invalidation behavior. The snapshot contents and thumbnail semantics were not expanded.

## 3. Executed validation

| Command | Result |
|---|---|
| `pytest tests/integration/test_file_operation_service.py -k 'projection_failure or restore_projection_snapshot_failure or delete_projection' -q -n 0 --basetemp=.zcode/pytest-c4-new` | 4 passed, 43 deselected |
| `pytest tests/integration/test_file_operation_service.py tests/unit/test_reconciliation_queue.py tests/unit/test_reconciliation_queue_sqlite_store.py tests/unit/test_asset_index_reconciliation_service.py tests/integration/test_reconciliation_bootstrap_order.py tests/integration/test_reconciliation_runtime_cutover.py -q -n 0 --basetemp=.zcode/pytest-c4-related` | 101 passed |
| `pytest tests/integration/test_import_service.py tests/integration/test_library_watcher_service.py -q -n 0 --basetemp=.zcode/pytest-c4-neighbors` | 15 passed |
| Python compile for changed service/test files | passed |
| `ruff check AssetsManager tests scripts run.py` | passed |
| `python scripts/check_doc_stats.py` | README stats current |
| `python scripts/check_audit_reports.py` | 5 existing manifests valid before this report was added |
| `python scripts/check_boundaries.py` | passed |
| `python scripts/check_style_sources.py` | 0 violations across 83 files |
| `python scripts/check_route_capabilities.py` | 0 violations |
| `python scripts/check_frontend_data_fetch.py` | 0 violations across 26 pages |
| `python scripts/check_layers.py` | layer DAG passed |
| `git diff --check` | no whitespace errors; LF/CRLF conversion warnings only |

The default pytest temp root remains inaccessible in this environment (`WinError 5`), so pytest commands used repository-local `--basetemp` and `-n 0`.

## 4. Explicit non-goals and remaining evidence

- This is not a general filesystem repair envelope or durable projection outbox.
- The existing queue still repairs only asset index; metadata/tags/favorites/thumbnail repair is not guaranteed.
- Move metadata migration, import partial results, watcher repair, FileSystemChanged payload changes, queue schema changes, and global after-commit semantics remain separate work.
- No full Python suite, browser E2E, real-backend LAN acceptance, performance benchmark, dependency/CVE scan, package/release validation, or independent Windows lifecycle CI was run.
- C4 findings remain `fixed-unverified`; no finding is marked `verified-fixed`.
