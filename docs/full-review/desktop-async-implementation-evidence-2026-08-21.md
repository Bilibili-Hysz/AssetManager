# Desktop Async Lifecycle 实施证据（2026-08-21）

## 1. Scope

本报告记录 `PC-1`、`PC-2`、`PC-3` 的实际实施和验证结果。它是对 [evidence-convergence-2026-08-20.md](evidence-convergence-2026-08-20.md) 的动态实施补充，不重写其静态输入摘要或原始 finding IDs。

| Field | Value |
|---|---|
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Worktree source | Dirty worktree |
| Status fingerprint | `393427a92137101d6e7a8c2e9727c9af02290193fd1e8a7ce40a66ac0eab568e` |
| Binary diff fingerprint | `7a4dc78e699c68994a12338321190007a98fa3d3a12dbafa97bac7b6bbccd04b` |
| Tracked / untracked changes | 17 / 7 at capture time |
| Runtime | Windows offscreen Qt test environment, Python 3.14 local environment |

The status contains pre-existing worktree changes plus this implementation batch and dated evidence documents. No commit, push, release, dependency install, browser test, package build, or full Python suite was performed.

## 2. Implemented Findings

### PC-1 / EVID-09: Cover-scan GUI delivery

`_CoverScanSignals.done` now carries result identity at `AssetsManager/panels/file_list/_base_logic.py:55`, and `_CoverScanTask` emits `dir_path`, result, generation, and task at `:81`. `_request_cover_scan` connects the signal directly to the panel-bound slot with `Qt.ConnectionType.QueuedConnection` at `:538`; the nested Python closure and its missing Qt receiver affinity were removed.

The regression `test_folder_cover_result_is_delivered_on_the_gui_thread` at `tests/desktop/test_file_list_view.py:3318` blocks the worker, records both thread identities, releases the worker, pumps Qt events, and proves that completion runs on the GUI thread.

**Result:** EVID-09 is implemented and verified in the local offscreen Qt environment. Windows lifecycle CI remains the required independent validation lane.

### PC-2 / EVID-08: Drag-drop worker truthfulness

`_on_drop` now guarantees one `FileOperationResult` payload for every accepted worker at `AssetsManager/panels/file_list/_base_logic.py:663-717`. Session admission and all service execution are inside the error boundary. Unexpected exceptions become an explicit zero-change failure result; an absent payload is also a failure. Completion requests selection only for nonempty changed paths.

Regression coverage:

- `test_drop_unexpected_service_error_reports_failed_feedback` at `tests/desktop/test_file_list_view.py:2958`.
- `test_drop_closed_session_before_worker_start_is_not_zero_success` at `tests/desktop/test_file_list_view.py:3006`.

**Result:** EVID-08 is implemented and verified in focused Desktop tests.

### PC-3 / EVID-10: Timed private-pool teardown

An isolated probe first established the actual failure mode: a valid image decode was blocked for 30 seconds, Viewer drain timeout was set to 100ms, and `close + final wrapper destruction` returned after approximately 30.005 seconds. The measured teardown followed the blocked worker rather than the configured timeout.

`BoundedPool.close()` at `AssetsManager/core/workers.py:136` now cancels tokens, attempts a timed drain, and, on timeout, transfers the native `QThreadPool` to a daemon reaper. The reaper retains no QWidget, session, task callback, or UI bridge and removes its registry entry after the worker exits. `retained_pool_count()` at `:34` is a read-only lifecycle diagnostic used by tests.

Terminal owners migrated in this batch:

- FileList terminal shutdown calls `_close_cover_scan_pool` at `AssetsManager/panels/file_list/_base_logic.py:516` through `AssetsManager/panels/file_list/_base.py:136`.
- ImageViewer terminal close calls `BoundedPool.close` at `AssetsManager/panels/image_viewer.py:886`.

Nonterminal library-switch paths retain the existing `drain()` behavior and may reuse the owner pool. Other private pool owners are intentionally out of scope for this batch.

Regression coverage:

- `test_bounded_pool_close_reaps_a_timed_out_pool_without_blocking` at `tests/unit/test_workers.py:88`.
- `test_folder_cover_shutdown_reaps_a_timed_out_pool` at `tests/desktop/test_file_list_view.py:3543`.
- Updated `test_close_cancels_inflight_decode_and_drains_bounded` at `tests/desktop/test_image_viewer.py:324`.

**Result:** EVID-10 is implemented and verified with blocked worker lifecycle tests in the local Qt environment. The reaper behavior still requires Windows lifecycle CI coverage before being considered release-verified.

## 3. Executed Validation

| Command | Result |
|---|---|
| `pytest tests/unit/test_workers.py -q -n 0 --basetemp=.zcode/pytest-workers-full` | 7 passed |
| `pytest tests/desktop/test_file_list_view.py -q -n 0 --basetemp=.zcode/pytest-filelist-full` | 136 passed |
| `pytest tests/desktop/test_image_viewer.py -q -n 0 --basetemp=.zcode/pytest-viewer-full` | 17 passed |
| `pytest tests/desktop/test_file_list_view.py tests/desktop/test_image_viewer.py tests/unit/test_workers.py tests/unit/test_low_batch_panels.py -q -n 0 --basetemp=.zcode/pytest-desktop-pc` | 171 passed |
| `ruff check AssetsManager tests scripts run.py` | passed |
| `python scripts/check_audit_reports.py` | 1 manifest valid |
| `python scripts/check_doc_stats.py` | README structural stats current |
| Existing generated-contract, boundary, style, route-capability, frontend-data-fetch, web-token, and layer-DAG gates | passed |
| `git diff --check` | no whitespace errors; existing LF/CRLF conversion warnings remain |

The default pytest temp root was inaccessible (`WinError 5` at `%TEMP%/pytest-of-86177`), so all executed pytest commands used an explicit repository-local `--basetemp` and `-n 0`. This is an environment workaround, not a product test result.

## 4. Remaining Evidence and Scope

- No complete Python suite, browser, LAN, performance, package, release, or dependency validation was run.
- The retained-pool mechanism has only migrated FileList cover and ImageViewer decode terminal owners. FileSystemModel, Sidebar, InfoPanel, and import pool migration require a separate lifecycle batch.
- The static manifest `audit-manifest-2026-08-20.json` remains immutable. A later manifest should record the implementation diff and Windows CI result before changing EVID-08/09/10 to `verified-fixed`.
