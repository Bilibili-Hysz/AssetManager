# C10-min Import durable intent/manifest 与重启恢复证据（2026-08-21）

## 1. Scope and baseline

本报告记录 ImportService 崩溃窗口收敛：在第一份文件写入前持久化 library-scoped import manifest，记录稳定的 source/target mapping 和逐项状态；在 runtime/session 建立时扫描 unresolved manifest，并以原 operation ID 合并 root-scoped asset-index rescan。

本批不声称 SQLite 与文件系统形成跨系统原子事务，不实现完整 copy replay、通用 event outbox、exactly-once `FileSystemChanged` 重放，也不扩展 move/delete/restore intent。

| Field | Value |
|---|---|
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Worktree source | Dirty worktree |
| Status fingerprint | `3dbd7d467e41013cedc8dc96de382a0c214a3a4e643e3ee6e8da0055e2c8498c` |
| Binary diff fingerprint | `dd7faf9465848c12d9f723bd6dbd16ac511d0460b3cde89345e156b88ec91cb8` |
| Tracked / untracked changes | 89 / 35 before this report and manifest were added |
| Runtime | Windows, Python 3.14 local environment |

## 2. Implemented findings

### C10-01 / XFS-10 / EVID-06: Durable pre-mutation import manifest

Schema migration v31 adds `import_manifests`, keyed by operation ID and scoped by canonical library root. It records destination, state, JSON payload, generation, attempts, errors and timestamps, with a recovery index. The store uses the existing managed SQLite connection, `db_write_lock`, `BEGIN IMMEDIATE` for independent writes and SAVEPOINT when a caller transaction already exists.

Manifest payload validation is fail-closed: version, destination, item count, serialized size, source/target presence, target root containment and item state are checked before persistence. ImportService plans conflict-renamed targets before copying, persists the `running` intent, and only then creates the destination directory or begins filesystem writes.

### C10-02 / XFS-10: Per-item state and generation-CAS updates

Each external source item is recorded as `pending`, then updated to `copied` or `failed` after its copy attempt. Successful completion marks the aggregate manifest `completed`; copy or refresh degradation marks it `degraded`, and a queue persistence failure leaves it `recovery_pending`. Cancellation records `cancelled` without rolling back copied files and preserves the existing no-refresh/no-import-event contract.

The aggregate generation increments on every state/payload update. Updates include the expected generation in their predicate, so a stale process cannot overwrite a newer runtime's manifest state. Target paths are passed into the copy operation and an existing target is rejected rather than silently overwritten.

### C10-03 / XFS-10 / EVID-06: Runtime restart recovery

`ImportManifestRecoveryService` scans `prepared`, `running`, `degraded` and `recovery_pending` manifests when the per-library runtime services are built. Recovery does not copy files and does not publish an import event. It enqueues/merges one root-scoped `ASSET_INDEX_ROOT_RESCAN` with reason `import_manifest_recovery` and the original operation ID, then records a recovery attempt. Queue failures keep the manifest unresolved for the next session startup.

The recovery service is wired into `LibraryScopedServices` and bootstrap before the reconciliation worker starts, so unresolved manifests are registered before normal durable index processing begins. Existing queue dedupe and lease/CAS semantics remain unchanged.

## 3. Executed validation

| Command / scope | Result |
|---|---|
| Import manifest store unit suite | 4 passed |
| ImportService + runtime recovery integration suite | 19 passed in final focused import run |
| C10 core regression suite | 130 passed |
| C9 neighboring desktop regression suite | 190 passed |
| Python compileall | passed |
| `ruff check AssetsManager tests scripts run.py` | passed |
| `git diff --check` | no whitespace errors; LF/CRLF conversion warnings only |
| `python scripts/check_doc_stats.py` | README stats current; schema version 31, application services 50, Python test files 263 |
| `python scripts/check_boundaries.py` | passed |
| `python scripts/check_style_sources.py` | 0 violations across 83 scoped files |
| `python scripts/check_route_capabilities.py` | 0 violations |
| `python scripts/check_frontend_data_fetch.py` | 0 violations across 26 page files |
| `python scripts/check_layers.py` | layer DAG passed |
| `python scripts/check_audit_reports.py` | audit evidence manifests are valid (14) after this report and manifest were added |

Focused pytest commands used repository-local `--basetemp` and `-n 0` because the default Windows pytest temp root is inaccessible in this environment (`WinError 5`).

## 4. Explicit non-goals and remaining evidence

- Filesystem effects and SQLite manifest state are not one atomic transaction. The manifest provides durable intent-before-side-effect and projection recovery, not rollback or power-loss atomicity.
- Recovery only enqueues an asset-index root rescan; it does not replay missing copies, infer uncertain source availability, restore tags/metadata/favorites, or repair thumbnails.
- The manifest does not provide a durable event outbox. Recovery never replays `FileSystemChanged(import)`, so exactly-once event delivery remains a separate architectural batch.
- The current focused tests cover store validation/round-trip, per-item state, queue-failure recovery state and runtime restart enqueue. They do not constitute a subprocess power-loss test at every filesystem boundary.
- No full Python suite, browser E2E, real-backend LAN acceptance, dependency/CVE scan, package/release validation, performance benchmark, hardware power-loss test, independent Windows lifecycle CI, or full import copy replay was run.
- C10 findings remain `fixed-unverified`; this report does not mark them `verified-fixed`.
