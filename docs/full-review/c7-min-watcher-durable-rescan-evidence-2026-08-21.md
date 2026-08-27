# C7-min LibraryWatcher durable rescan 与 stop/join 证据（2026-08-21）

## 1. Scope and baseline

本报告记录 LibraryWatcherService 的 durable asset-index rescan producer、root-scope queue 接入，以及 watcher stop/join/restart 生命周期修复。

本批不改变 watcher 的 mtime-only 检测模型，不处理原地文件覆盖漏检、durable scan cursor、ImportService partial contract 或其他 projection repair 类型。

| Field | Value |
|---|---|
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Worktree source | Dirty worktree |
| Status fingerprint | `598e75570bbf9d06b10d473600b8a9bcf6abe63fcf6629da1078b0ef5c2c2698` |
| Binary diff fingerprint | `d6a8f25d04568da781fe762e5e47ef977fee1243467d16c9856230a0512443b7` |
| Tracked / untracked changes | 83 / 27 before this report and manifest were added |
| Runtime | Windows, Python 3.14 local environment |

## 2. Implemented findings

### C7-01 / XFS-03 / EVID-06: Durable external-watch rescan

`LibraryWatcherService` now accepts the session-scoped `ReconciliationQueue`. After a non-baseline scan detects changes, it enqueues one root-scoped `ASSET_INDEX_ROOT_RESCAN` task with reason `external_watch` and a stable operation ID for that round before publishing the existing in-process `external_watch` event.

The queue write is wrapped in `session.operation()` when available. Queue persistence failure is logged and does not suppress the current event or terminate the watcher loop. Root scope avoids enqueueing removed directories and lets the existing durable worker rebuild the full index tree.

### C7-02 / XOWN-06: Watcher stop/join and restart hardening

Watcher runs now use per-run stop/wakeup events. `start()` refuses overlap with a still-live prior thread; `stop()` sets the run events and performs a bounded join. A live thread raises `LibraryWatcherStopTimeout` and remains retained for an explicit retry rather than being reported as stopped. A stopped thread is cleared before restart, preventing old/new watcher overlap and stale wakeup spin.

Runtime already propagates lifecycle adapter stop exceptions through its existing teardown state machine, so a watcher timeout participates in the same retryable owner teardown semantics.

## 3. Executed validation

| Command | Result |
|---|---|
| `pytest tests/integration/test_library_watcher_service.py` | 9 passed |
| watcher/reconciliation/runtime/owner/shutdown related suite | 47 passed |
| Python compileall | passed |
| `ruff check AssetsManager tests scripts run.py` | passed |
| `python scripts/check_doc_stats.py` | README stats current |
| `python scripts/check_audit_reports.py` | 10 existing manifests valid before this report was added |
| `python scripts/check_boundaries.py` | passed |
| `python scripts/check_style_sources.py` | 0 violations across 83 files |
| `python scripts/check_route_capabilities.py` | 0 violations |
| `python scripts/check_frontend_data_fetch.py` | 0 violations across 26 pages |
| `python scripts/check_layers.py` | layer DAG passed |
| `git diff --check` | no whitespace errors; LF/CRLF conversion warnings only |

The default pytest temp root remains inaccessible in this environment (`WinError 5`), so pytest commands used repository-local `--basetemp` and `-n 0`.

## 4. Explicit non-goals and remaining evidence

- Directory mtime polling can still miss in-place file overwrites whose parent directory mtime does not change.
- Partial-scan `_pending` cursor remains process-local and is not durable across crash/restart.
- Queue enqueue and external filesystem mutation are not one cross-system transaction; a crash window remains between observation and durable enqueue.
- Import partial/degraded result, thumbnail restore, gallery repair, full Python/browser/real-LAN/release/CVE and independent Windows lifecycle validation were not run.
- C7 findings remain `fixed-unverified`; this report does not mark them `verified-fixed`.
