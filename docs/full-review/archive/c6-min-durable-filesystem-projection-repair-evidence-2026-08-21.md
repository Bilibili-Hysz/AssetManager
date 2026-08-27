# C6-min Durable filesystem projection repair 证据（2026-08-21）

## 1. Scope and baseline

本报告记录 C6-min 的 durable filesystem projection repair 第一切片：move/rename 与 delete/trash 的版本化 repair payload、SQLite durable queue、lease/CAS worker dispatch，以及失败生产者接入。

本批不覆盖 restore、import、watcher、copy/duplicate、gallery projection，也不宣称已经完成全量 filesystem projection repair。

| Field | Value |
|---|---|
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Worktree source | Dirty worktree |
| Status fingerprint | `4d58afe153da5df1c27c2c35c08b2d2382cf461847cfed458661bb9363469562` |
| Binary diff fingerprint | `96c43890bac03a8d20260caaf8485e261ad225ffa89be5f5c8314c059578de3c` |
| Tracked / untracked changes | 80 / 23 before this report and manifest were added |
| Runtime | Windows, Python 3.14 local environment |

## 2. Implemented findings

### C6-01 / XFS-01 / XFS-02 / EVID-06: Versioned durable repair envelope

`ReconciliationKind.FILESYSTEM_PROJECTION_REPAIR` now coexists with the legacy asset-index kind. Tasks carry canonical JSON payloads with operation version, operation ID, projection set, scope, expected filesystem state, and move/delete-specific intent. Paths are validated against the library root before enqueue and again when loaded from SQLite/JSON.

SQLite schema migration v30 adds the payload column and accepts the new task kind while preserving existing task rows, lease fields, attempts, unique scope/kind dedupe and queue generation semantics. Existing asset-index callers retain default behavior and use `{}` payloads.

### C6-02 / XFS-01: Move projection repair

Move metadata failures now enqueue a distinct durable repair task containing source and destination paths, directory flag, and expected `source_absent`/`destination_present` state. The shared reconciliation worker dispatches the task under the existing session operation lease and heartbeat. The executor re-runs the savepoint-protected path metadata migration and refreshes source/destination index scopes without executing another filesystem move or publishing a new `FileSystemChanged` event.

An integration test injects migration failure after the filesystem move, processes both the compatibility index task and repair task, and verifies the new path tag projection is restored while the old path is absent.

### C6-03 / XFS-02: Delete/trash projection repair

Delete and trash cleanup failures now enqueue durable intents preserving the original target path, delete mode and expected absent state even when the filesystem path no longer exists. The worker reuses the existing complete projection cleanup savepoint with event publication disabled, then refreshes the affected index scope. Repair completion therefore does not recursively publish another filesystem mutation event.

### C6-04: Shared worker lifecycle and failure classification

The existing worker lease heartbeat, stale-worker CAS protection, retryable SQLite/OSError handling, terminal invalid-payload/path handling and bounded shutdown lifecycle are reused. Unsupported repair configuration is terminal rather than crashing the supervisor. Repair tasks are acknowledged only after projection and index operations report durable success.

## 3. Executed validation

| Command | Result |
|---|---|
| Queue/schema/worker/file-operation related suite | 118 passed |
| Queue cross-process/lease/fault-injection suite | 23 passed, 1 skipped |
| Focused repair producer/worker tests | 4 passed |
| Python compileall | passed |
| `ruff check AssetsManager tests scripts run.py` | passed |
| `python scripts/check_doc_stats.py` | README stats current |
| `python scripts/check_audit_reports.py` | 8 existing manifests valid before this report was added |
| `python scripts/check_boundaries.py` | passed |
| `python scripts/check_style_sources.py` | 0 violations across 83 files |
| `python scripts/check_route_capabilities.py` | 0 violations |
| `python scripts/check_frontend_data_fetch.py` | 0 violations across 26 pages |
| `python scripts/check_layers.py` | layer DAG passed |
| `git diff --check` | no whitespace errors; LF/CRLF conversion warnings only |

The default pytest temp root remains inaccessible in this environment (`WinError 5`), so pytest commands used repository-local `--basetemp` and `-n 0`.

## 4. Explicit non-goals and remaining evidence

- The new repair task supports only move/rename and delete/trash. Restore, import, watcher, copy/duplicate and gallery projection remain separate work.
- SQLite queue persistence is durable, but filesystem mutation and queue enqueue are not one cross-system transaction; a crash can still occur between those boundaries.
- Thumbnail byte rename side effects remain outside SQLite rollback and require future compensation/oracle work.
- Queue repair currently uses the existing asset-index service for index projection; complete projection semantics beyond the declared move/delete set are not inferred.
- No full Python suite, browser E2E, real-backend LAN acceptance, performance benchmark, dependency/CVE scan, package/release validation, or independent Windows lifecycle CI was run.
- C6 findings remain `fixed-unverified`; this report does not mark them `verified-fixed`.
