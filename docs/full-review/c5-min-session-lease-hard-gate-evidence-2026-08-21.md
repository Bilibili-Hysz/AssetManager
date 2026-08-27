# C5-min Session lease timeout owner hard gate 证据（2026-08-21）

## 1. Scope and baseline

本报告记录 canonical `LibraryService.close_session()` 的 session lease timeout hard gate。它是 C2/C3、C4-min 与此前动态证据的新增补充，不修改既有 manifest。

| Field | Value |
|---|---|
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Worktree source | Dirty worktree |
| Status fingerprint | `cbfafdfde37e87ed3d3494c90f201b600ef384e57ea6c9ff2787ef806a023988` |
| Binary diff fingerprint | `8f1de9d4a56b77f909dd6ceac2bd2f9ebf8696017e15af25ae857d3f96783eed` |
| Tracked / untracked changes | 59 / 18 before this report and manifest were added |
| Runtime | Windows, Python 3.14 local environment |

No commit, push, reset, clean, dependency installation, browser E2E, full Python suite, release validation, or vulnerability scan was performed.

## 2. Implemented finding

### C5-01 / XOWN-01: Session lease timeout must not commit owner teardown

`LibrarySession._finish_close()` now returns a boolean drain result. A direct low-level session close retains its bounded liveness behavior, but the canonical owner teardown in `LibraryService._run_owned_teardown()` treats an explicit `False` as a hard failure:

- `progress.session_finished` is not marked complete.
- `DatabaseManager.close_library()` is not called.
- The library lock is not released.
- `_closing_sessions`, teardown progress, root ownership and generation state remain available for explicit retry.
- A `TimeoutError` is raised from `close_session()`.

After the lease is released, a second `close_session()` retries the pending teardown and only then closes the database/releases ownership. A contender cannot open the root during the failed teardown.

The owner-level test uses a real session operation lease, verifies the retained SQLite connection and closing ownership, blocks a contender, releases the lease, retries close, and then verifies the contender can open the root.

## 3. Executed validation

| Command | Result |
|---|---|
| `pytest tests/unit/test_session_context_cancellation.py tests/unit/test_library_runtime.py tests/integration/test_reconciliation_library_owner_handoff.py tests/integration/test_reconciliation_runtime_lifecycle.py -q -n 0 --basetemp=.zcode/pytest-c5-related` | 43 passed |
| `pytest tests/lan/test_server_lifecycle.py -q -n 0 --basetemp=.zcode/pytest-c5-lan` | 50 passed |
| `pytest tests/integration/test_shutdown_stress.py -q -n 0 --basetemp=.zcode/pytest-c5-stress` | 1 passed |
| C5 Python compile | passed |
| `ruff check AssetsManager tests scripts run.py` | passed |
| `python scripts/check_doc_stats.py` | README stats current |
| `python scripts/check_audit_reports.py` | 6 existing manifests valid before this report was added |
| `python scripts/check_boundaries.py` | passed |
| `python scripts/check_style_sources.py` | 0 violations across 83 files |
| `python scripts/check_route_capabilities.py` | 0 violations |
| `python scripts/check_frontend_data_fetch.py` | 0 violations across 26 pages |
| `python scripts/check_layers.py` | layer DAG passed |
| `git diff --check` | no whitespace errors; LF/CRLF conversion warnings only |

The default pytest temp root remains inaccessible in this environment (`WinError 5`), so pytest commands used repository-local `--basetemp` and `-n 0`.

The selected `test_window_lifecycle_lan_failure.py` run had two unrelated setup failures: its spawned scenario could not establish the expected WebSocket client before the assertion, and logged a missing temporary `old` path. The LAN lifecycle suite and all C5 owner/session/runtime tests passed; those two window scenarios are not counted as C5 evidence.

## 4. Explicit non-goals and remaining evidence

- Direct non-owner `LibrarySession.close()` retains historical timeout/liveness behavior; the hard gate is applied at canonical `LibraryService` ownership teardown.
- Watcher/gallery/maintenance/scanner/ZIP StopResult unification and Qt/window closeEvent policy were not changed.
- C4-B move metadata savepoint and thumbnail filesystem side-effect handling remain separate.
- No full Python suite, browser E2E, real-backend LAN acceptance, performance benchmark, dependency/CVE scan, package/release validation, or independent Windows lifecycle CI was run.
- C5-01 remains `fixed-unverified`; this report does not mark it `verified-fixed`.
