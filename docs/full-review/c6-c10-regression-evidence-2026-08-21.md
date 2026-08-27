# C6-C10 并行回归与全量验证证据（2026-08-21）

## 1. Snapshot Metadata

| Field | Value |
|---|---|
| Report ID | `c6-c10-regression-evidence-2026-08-21` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; baseline captured before this report and manifest were added |
| Status fingerprint | `b6edf006c887fd3c7da05d4916ec613b024225e71d1721e458038fc20a168e22` |
| Binary diff fingerprint | `4600b5c9f3eca1b08b894cf514bb728bcdb915c8d777049cb26859fc609e34b9` |
| Tracked / untracked changes | 97 / 40 before this report and manifest were added |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This is a new dated execution snapshot. It does not rewrite earlier C6-C10 evidence. The machine-readable companion is [audit-manifest-c6-c10-regression-evidence-2026-08-21.json](audit-manifest-c6-c10-regression-evidence-2026-08-21.json).

## 2. Parallel Execution Results

Three independent execution agents were used with unique repository-local basetemp directories and `-n 0`.

### C10 durable import/recovery batch

Command:

```text
python -m pytest --basetemp=.zcode/pytest-agent-c10 -n 0 tests/unit/test_import_manifest_store.py tests/integration/test_import_service.py tests/unit/test_db_lock_low_batch.py tests/unit/test_reconciliation_queue_migration.py tests/unit/test_reconciliation_queue_sqlite_store.py tests/unit/test_reconciliation_low_batch.py
```

Result: **66 passed, 0 failed, 0 skipped**, exit code 0, 10.94 seconds.

### C6-C9 neighboring regression batch

Four focused commands completed with unique basetemp `.zcode/pytest-agent-c6c9`:

| Scope | Result |
|---|---:|
| Reconciliation service/queue unit suite | 55 passed |
| Watcher, owner handoff, cross-process queue suite | 23 passed |
| Import/session cancellation/worker suite | 36 passed |
| Desktop file-list/viewer/window switching suite | 174 passed |
| **Total** | **288 passed, 0 failed, 0 skipped** |

The four commands exited 0. Their durations were 25.82s, 87.31s, 143.20s, and 248.81s respectively.

### Full default Python suite

Command:

```text
python -m pytest --basetemp=.zcode/pytest-agent-full-fixed -n 0
```

Result: **3903 collected, 17 deselected, 3886 selected, 3879 passed, 0 failed, 7 skipped, 2 warnings**, exit code 0. Wall-clock duration was 695.826 seconds; pytest-reported duration was 688.18 seconds.

The seven skips are platform/environment-limited: six require Windows symlink privileges/support and report `WinError 1314`; one covers nondeterministic abrupt Windows process termination/queue finalization. They are not counted as failures and do not establish independent Windows lifecycle coverage.

## 3. Failure Convergence

The first full-suite run before the final fixes reported seven failures. The failures were classified and resolved as follows:

- Download quota tests expected the old raised `HTTPTooManyRequests` contract. They now assert the canonical JSON 429 response while retaining quota headers and prepared-ZIP cleanup.
- Download path-escape recorder status remained at the default 500 because `HTTPException.status` was not propagated into the performance event. The route now restores that status capture for single and batch downloads.
- The realtime close-session test asserted `_clients` immediately after `runtime_ready`; it now waits for the existing admission barrier with a bounded timeout.
- The architecture boundary test used an obsolete one-line function signature marker; it now matches the stable function prefix while preserving delegation assertions.
- The two spawned window lifecycle tests had the same admission race and missing fixture roots. They now create the roots and wait boundedly for WebSocket admission. Both passed in 99.03 seconds in a direct rerun.

The repaired failure set was directly rechecked: download/quota tests **9 passed**, architecture boundary **1 passed**, realtime close-session **1 passed**, and window lifecycle **2 passed**.

## 4. Final Static Gates

The final local gates passed after the fixes:

| Command | Result |
|---|---|
| `python scripts/check_audit_reports.py` | exit 0; 16 manifests valid |
| `python scripts/check_doc_stats.py` | exit 0; README stats current |
| `python scripts/check_boundaries.py` | exit 0 |
| `python scripts/check_style_sources.py` | exit 0; 0 violations across 83 files |
| `python scripts/check_route_capabilities.py` | exit 0; 0 violations |
| `python scripts/check_frontend_data_fetch.py` | exit 0; 0 violations across 26 pages |
| `python scripts/check_layers.py` | exit 0 |
| `python -m compileall -q AssetsManager tests scripts` | exit 0 |
| `python -m ruff check AssetsManager tests scripts run.py` | exit 0 |
| `git diff --check` | exit 0 |

Raw logs and provenance metadata are stored under `artifacts/evidence/2026-08-21/c6-c10-regression-final/`. Agent-reported test counts are recorded as execution summaries; no unavailable agent stdout is represented as a local raw log.

## 5. Remaining Boundaries

- The seven Windows-limited skips remain unresolved for a privileged/independent Windows lifecycle environment.
- Browser E2E, real-backend LAN acceptance, dependency/CVE scan, performance benchmark, package/release validation, clean-checkout reproduction, power-loss testing, and independent Windows lifecycle CI were not run.
- Full import copy replay, durable event outbox, exactly-once event dispatch, thumbnail snapshot evolution, watcher scan cursor, and cross-system SQLite/filesystem atomicity remain outside C6-C10.
- All findings remain `fixed-unverified`; this report does not promote any finding to `verified-fixed`.
