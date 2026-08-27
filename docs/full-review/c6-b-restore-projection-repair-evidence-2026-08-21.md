# C6-B Restore projection durable repair 证据（2026-08-21）

## 1. Scope and baseline

本报告记录 undo/file-operation restore projection failure 的 durable repair 补齐：合法 projection snapshot 被内嵌到 reconciliation payload，由现有 lease/CAS worker 重放 tags、metadata、favorites 和 asset index。

本批明确不覆盖 thumbnail rows/bytes；当前 undo snapshot 不包含 thumbnail 数据，因此没有将 thumbnail restore 写入已完成能力。

| Field | Value |
|---|---|
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Worktree source | Dirty worktree |
| Status fingerprint | `d7e469cc2e1747ade01a0bc5f9cdf27f926adc22db65883442b4ea75f4206a05` |
| Binary diff fingerprint | `e86ef516f673a4c1f02850d8a26d715593e5fe8ebe0c1c6667b77d8ebf8f47fd` |
| Tracked / untracked changes | 81 / 25 before this report and manifest were added |
| Runtime | Windows, Python 3.14 local environment |

## 2. Implemented findings

### C6-B-01 / XFS-01 / EVID-06: Validated restore payload

`FILESYSTEM_PROJECTION_REPAIR` now accepts `operation_kind="restore"` with a truthful projection set of `asset_index`, `tags`, `metadata`, and `favorites`. The payload includes target path, directory flag, expected target-present state, and an embedded validated undo projection snapshot.

Snapshot validation enforces format/version, root-contained base path, row arity/scalar shape, row-count bound and serialized-size bound. The durable payload never references the temporary undo backup or sidecar path.

### C6-B-02 / XFS-01: Durable restore replay executor

When filesystem restore succeeds but snapshot database restoration fails, a valid snapshot is embedded into a durable repair task while the existing generic asset-index rescan remains available as compatibility behavior. The repair worker remaps snapshot paths from the original base to the restored target and applies tags, metadata, and favorites under one SQLite savepoint, then refreshes the target index.

The executor is projection-only: it does not copy files, publish `restored` events, or publish tag catalog events. Replayed tasks therefore do not create recursive filesystem events. Malformed or out-of-contract snapshots remain warning-only and do not create an unreplayable repair task.

### C6-B-03 / XFS-01: Worker age-budget and marker equivalence safety

Projection repair tasks have no `AssetIndexPublishResult`; the worker age-budget path no longer asserts a non-null index result before stale completion handling. Legacy marker task equivalence now includes the durable payload, preventing two different restore intents from being treated as identical merely because task metadata matches.

Repair enqueue errors are separated from generic asset-index rescan enqueue so invalid restore payloads do not suppress the compatibility fallback.

## 3. Executed validation

| Command | Result |
|---|---|
| C6-B queue/worker/file-operation/undo related suite | 152 passed |
| Restore payload unit tests | 2 passed |
| Restore failure replay integration test | 1 passed |
| Python compileall | passed |
| `ruff check AssetsManager tests scripts run.py` | passed |
| `python scripts/check_doc_stats.py` | README stats current |
| `python scripts/check_audit_reports.py` | 9 existing manifests valid before this report was added |
| `python scripts/check_boundaries.py` | passed |
| `python scripts/check_style_sources.py` | 0 violations across 83 files |
| `python scripts/check_route_capabilities.py` | 0 violations |
| `python scripts/check_frontend_data_fetch.py` | 0 violations across 26 pages |
| `python scripts/check_layers.py` | layer DAG passed |
| `git diff --check` | no whitespace errors; LF/CRLF conversion warnings only |

The default pytest temp root remains inaccessible in this environment (`WinError 5`), so pytest commands used repository-local `--basetemp` and `-n 0`.

## 4. Explicit non-goals and remaining evidence

- Thumbnail rows/bytes are not restored because the existing undo snapshot format does not contain them; thumbnail restore requires a separate snapshot/schema design.
- Full-library RuntimeData archive restore is unrelated and unchanged.
- Restore payloads embedded in old binaries may be rejected by versions that only understand move/delete; rolling-version downgrade compatibility remains a deployment concern.
- Filesystem restore and queue enqueue are not one cross-system transaction; a crash between them remains possible.
- No full Python suite, browser E2E, real-backend LAN acceptance, performance benchmark, dependency/CVE scan, package/release validation, or independent Windows lifecycle CI was run.
- C6-B findings remain `fixed-unverified`; this report does not mark them `verified-fixed`.
