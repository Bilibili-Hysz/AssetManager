# C8-min ImportService partial/degraded contract 证据（2026-08-21）

## 1. Scope and baseline

本报告记录 ImportService 的 partial/degraded 结果契约、session operation lease、取消进度保留、refresh diagnostics 和 asset-index durable fallback 实施。

本批保持既有 `FileSystemChanged(kind="import")` 字段与成功事件语义，不新增 import-specific projection repair kind。降级补偿继续使用现有 `ASSET_INDEX_ROOT_RESCAN`；本批不声称已经具备完整 import manifest、跨系统 outbox 或任意 projection repair。

| Field | Value |
|---|---|
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Worktree source | Dirty worktree |
| Status fingerprint | `51351bc55e32bd300b74a7c43f534e3759a7460feddf8ee3724574e3dceedd4f` |
| Binary diff fingerprint | `e61d217cc9e15d7172adbe9af45942b49307890341083a79c166fc93756a3c01` |
| Tracked / untracked changes | 86 / 29 before this report and manifest were added |
| Runtime | Windows, Python 3.14 local environment |

## 2. Implemented findings

### C8-01 / XFS-10 / EVID-06: Import operation lifetime is session-bound

`ImportService.import_sources()` is wrapped by the existing `session_operation` decorator. The lease covers source collection, copy attempts, refresh, durable rescan enqueue and the single completion event, so owner teardown cannot close the session connection while the import is still executing. Each call receives an `operation_id` that is propagated to fallback queue work and returned in `ImportResult`.

The result dataclass keeps the original positional fields (`copied`, `skipped`, `failed`) and appends defaulted diagnostics fields: `processed`, `total`, `degraded`, `cancelled`, `operation_id` and `refresh_warnings`.

### C8-02 / XFS-10: Cancellation and partial/degraded outcomes remain observable

Cancellation now raises `ImportCancelled` with an optional partial `ImportResult`. The partial result records copied/skipped/failed counts, processed/total progress, cancellation state and operation ID; already copied files are retained and no import event or refresh is published on cancellation.

Per-file copy failures are accumulated rather than converted into a false all-success result. Completed imports with copy failures are returned with `degraded=True` and still publish exactly one compatible `FileSystemChanged(kind="import")` event. Source enumeration and destination setup failures return structured degraded results where no filesystem completion event is appropriate.

Refresh execution is enclosed in the import result boundary. Refresh exceptions and `last_refresh_warnings` are included in `failed`/`refresh_warnings`, and the result is marked degraded without hiding the number of files already copied.

### C8-03 / XFS-10 / EVID-06: Degraded import queues asset-index compensation

When copy or refresh work is degraded, ImportService enqueues a root-scoped existing `ASSET_INDEX_ROOT_RESCAN` task using reason `import_partial` or `import_refresh_degraded` and the import operation ID. Queue failure is best-effort and does not rewrite a truthful filesystem result into a command failure. The fallback is intentionally asset-index-only; failed source paths are not represented as metadata or filesystem projection repair payloads.

The desktop adapter preserves the two-element worker payload shape. Cancellation is delivered as `("cancelled", partial_result)`, errors as `("error", exception)`, and completed results as `("ok", result)`. The UI distinguishes cancelled and degraded completion and adds `import.partial` / `import.cancelled` translations in English, Simplified Chinese and Japanese.

## 3. Executed validation

| Command / scope | Result |
|---|---|
| `tests/integration/test_import_service.py` | 12 passed |
| Import/runtime/reconciliation/owner-handoff/watcher related combined suite | 53 passed |
| Python compileall | passed |
| `ruff check AssetsManager tests scripts run.py` | passed |
| `python scripts/check_doc_stats.py` | README stats current; all three locale counts are 839 |
| `python scripts/check_audit_reports.py` | audit evidence manifests are valid (12) |
| `python scripts/check_boundaries.py` | passed |
| `python scripts/check_style_sources.py` | 0 violations across 83 files |
| `python scripts/check_route_capabilities.py` | 0 violations |
| `python scripts/check_frontend_data_fetch.py` | 0 violations across 26 pages |
| `python scripts/check_layers.py` | layer DAG passed |
| `git diff --check` | no whitespace errors; LF/CRLF conversion warnings only |

The focused pytest command used repository-local `--basetemp` and `-n 0` because the default Windows pytest temp root is inaccessible in this environment (`WinError 5`).

## 4. Explicit non-goals and remaining evidence

- Import cancellation is cooperative; an individual `shutil.copy2` call is not interruptible, and the current desktop progress dialog still has no active cancel button.
- Copy/refresh filesystem effects and durable queue enqueue are not one cross-system transaction; a crash window remains between the side effect and queue persistence.
- The fallback repairs the asset-index projection only. It does not persist a complete import manifest, restore tags/metadata/favorites, restore thumbnail rows/bytes, or repair arbitrary runtime projections.
- No full Python suite, browser E2E, real-backend LAN acceptance, dependency/CVE scan, package/release validation, performance benchmark, or independent Windows lifecycle CI was run for this batch.
- C8 findings remain `fixed-unverified`; this report does not mark them `verified-fixed`.
