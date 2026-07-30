# Window Exit Stop Failure Teardown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure a real application exit still shuts down every window resource and closes all canonical library runtimes when the first explicit LAN server stop fails.

**Architecture:** `WindowLifecycleCoordinator.shutdown_resources()` owns best-effort window-resource teardown and rethrows its first ordinary failure after trying every step. `MainWindow.closeEvent()` owns final application teardown through nested `finally` blocks so the base Qt close handler and `LibraryService.close()` are attempted regardless of a coordinator failure. A spawned offscreen-Qt integration test uses the real Runtime, LAN server, TCP/WebSocket, session, and database.

**Tech Stack:** Python 3, pytest, PySide6 offscreen Qt, multiprocessing spawn, aiohttp, threaded asyncio LAN server.

## Global Constraints

- Preserve all dirty-worktree changes; do not stage, commit, reset, checkout, clean, or rewrite unrelated files.
- Follow strict RED → GREEN for each task; no production edit before the focused test fails for the intended lifecycle omission.
- Catch ordinary `Exception` only in best-effort window resource cleanup; do not intercept `BaseException`.
- `LibraryService.close()` failure takes precedence over an earlier window-resource error because canonical session/Runtime cleanup did not complete.
- Do not modify LAN server or Runtime behavior in this task.

---

### Task 1: Best-effort window resource teardown

**Files:**
- Modify: `AssetsManager/window_lifecycle_coordinator.py:72-88`
- Test: `tests/unit/test_window_session_switching.py`

**Interfaces:**
- Consumes: `WindowLifecycleCoordinator.shutdown_resources() -> None` and existing panel/layout methods.
- Produces: every shutdown step is attempted in the existing order even when an earlier ordinary step fails; the first error is re-raised afterward.

- [ ] Add a failing test whose running server appends `lan.stop` then raises `RuntimeError("lan stop failed")`; each panel, dock save, workspace save, and file-list shutdown appends its event. Assert all events occur in the existing order and the final raised error is the original LAN error.
- [ ] Add a second focused assertion that a failed intermediate panel does not prevent later panels/layout/file-list cleanup and does not replace the first LAN error. Do not add a generic aggregation abstraction.
- [ ] Run `python -m pytest tests/unit/test_window_session_switching.py -q` and confirm RED because current `shutdown_resources()` exits at the first failed stop.
- [ ] Implement a local `first_error: Exception | None` and a small nested callable runner that catches `Exception`, stores only the first error, and continues. Invoke it for LAN stop, each live panel shutdown, both layout saves, and file-list shutdown in the current order. Raise `first_error` after all attempts.
- [ ] Re-run the focused unit suite; then run Ruff, compileall, and diff check on the coordinator and test.

### Task 2: Real closeEvent Runtime retry and canonical teardown

**Files:**
- Modify: `AssetsManager/window.py:647-661`
- Extend: `tests/integration/test_window_lifecycle_lan_failure.py`

**Interfaces:**
- Consumes: Task 1 best-effort `shutdown_resources()`, `MainWindow.closeEvent(event)`, `LibraryService.close()`, Runtime lifecycle adapter retry.
- Produces: application exit attempts base Qt close and canonical service close even when the first explicit LAN stop fails.

- [ ] Extend the existing spawned-process real lifecycle test with a separate exit scenario. In the child process set `QT_QPA_PLATFORM=offscreen`, create/reuse `QApplication`, construct a minimal `MainWindow` shell without its full UI setup, inject the real bootstrap/session/server and no-op panels/layout methods, and connect a real authenticated WebSocket.
- [ ] Inject a one-shot `_shutdown()` `RuntimeError("explicit exit stop failed")`, then directly invoke real `MainWindow.closeEvent()` with a `QCloseEvent`. Assert RED on current code: `library_service.close()` is skipped, shutdown attempt count is one, session/DB/WS/Runtime adapter remain live.
- [ ] Modify `closeEvent()` using nested `try/finally`: `_shutdown_resources()` is attempted first; `super().closeEvent(event)` is attempted regardless; `self._library_service().close()` is attempted in the innermost `finally`. Do not catch and replace exceptions—the innermost canonical close failure naturally takes precedence; otherwise the original coordinator error propagates.
- [ ] Assert GREEN: two shutdown attempts against the same real server adapter, real WebSocket close, all sessions closed, bootstrap Runtime cache empty, server stopped/thread cleared, realtime subscription removed, Runtime adapter list empty, DB closed, panel/layout events completed, and the original exit stop error remains observable when final close succeeds.
- [ ] Keep the scenario inside the existing disposable Windows spawn boundary. The parent must continue draining Pipe while joining, terminate/kill on deadline, and close both Pipe endpoints in every success/failure/start-error path.
- [ ] Run the exit scenario and switch scenario; run window unit, Runtime, server lifecycle/realtime, and Chromium realtime acceptance gates; run Ruff, compileall, and diff check.
