# Window Stop Failure Close-Session Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that a library switch still performs canonical session teardown when the window's first explicit LAN `stop()` fails, while preserving the original error and refusing to open the replacement library.

**Architecture:** Add one real integration regression using `ApplicationBootstrap`, `_LanServerImpl`, localhost TCP, and an aiohttp WebSocket. Inject a one-shot failure at the real server's `_shutdown()` seam. Update only `WindowLifecycleCoordinator.switch_library()` so it records an ordinary explicit-stop exception, drains panels, closes and cleans the old canonical session, then re-raises that exception before opening a new session.

**Tech Stack:** Python 3, pytest/AnyIO, aiohttp, threaded asyncio LAN server, PySide-independent window shell.

## Global Constraints

- Preserve the dirty worktree; do not stage, commit, reset, checkout, clean, or overwrite unrelated changes.
- Follow strict RED → GREEN: production code may change only after the new real regression fails for the expected missing `close_session()` behavior.
- Keep scope limited to library switching; do not change application-exit teardown in this task.
- A later canonical cleanup failure takes precedence over the saved explicit-stop error because the old session was not safely closed.
- After successful old-session cleanup, re-raise the original explicit-stop error and do not open the replacement library.

---

### Task 1: Real window-switch failure regression and minimal coordinator repair

**Files:**
- Create: `tests/integration/test_window_lifecycle_lan_failure.py`
- Modify: `AssetsManager/window_lifecycle_coordinator.py:16-55`

**Interfaces:**
- Consumes: `WindowLifecycleCoordinator.switch_library(path: str) -> None`, `ApplicationBootstrap.library_service.close_session(session)`, `_LanServerImpl.start()`, `_LanServerImpl.stop()`.
- Produces: the window-switch contract that an initial ordinary `server.stop()` failure cannot bypass canonical old-session cleanup, and the original error is propagated before any replacement session is opened.

- [ ] **Step 1: Write the failing real integration test**

Create an AnyIO test that:

```python
bootstrap = ApplicationBootstrap()
session = bootstrap.library_service.open_session(tmp_path / "library")
runtime = bootstrap.runtime_for(session)
server = _LanServerImpl(runtime=runtime, password="test-password")
server.start(port=0, bind="127.0.0.1")
ws = await client.ws_connect(real_loopback_url, headers=auth_headers)

original_shutdown = server._shutdown
shutdown_attempts = 0

async def fail_once_then_shutdown():
    nonlocal shutdown_attempts
    shutdown_attempts += 1
    if shutdown_attempts == 1:
        raise RuntimeError("explicit window stop failed")
    await original_shutdown()

server._shutdown = fail_once_then_shutdown
```

Use a minimal window shell with the real `bootstrap`, `session`, and `server`; panels may be `None`, `_open_library_session()` must raise `AssertionError`, and `_apply_scoped_services()` must never run. Execute `coordinator.switch_library(new_root)` in a bounded worker thread, await the real WebSocket close frame, then assert:

```python
assert isinstance(switch_error, RuntimeError)
assert str(switch_error) == "explicit window stop failed"
assert shutdown_attempts == 2
assert session.is_closed
assert not bootstrap.library_service.owns_live_session(session)
assert id(session) not in bootstrap._runtimes
assert server._lifecycle_state == "stopped"
assert not server.is_running()
assert server._thread is None
assert server._runtime_subscription is None
assert not runtime._lifecycle_adapters
assert not server._ws_manager._clients
assert replacement_open_calls == []
```

The test cleanup must be bounded and idempotent, closing the WebSocket/client and calling canonical session/service cleanup only when still needed.

- [ ] **Step 2: Run RED and confirm the root cause**

Run:

```powershell
python -m pytest tests/integration/test_window_lifecycle_lan_failure.py -q
```

Expected: FAIL because the current coordinator propagates `explicit window stop failed` immediately; `session.is_closed` remains false, shutdown has only one attempt, the WebSocket remains open, and no canonical Runtime retry occurred. Test setup or timeout errors do not count as RED.

- [ ] **Step 3: Implement the minimal delayed-error coordinator behavior**

In `switch_library()`:

```python
stop_error: Exception | None = None
if lan_server and lan_server.is_running():
    try:
        lan_server.stop()
    except Exception as exc:
        stop_error = exc
    else:
        # Preserve the existing immediate status/tray update on normal success.
        ...

# Preserve existing panel preparation and canonical old-session cleanup.
...

if stop_error is not None:
    # Canonical close succeeded, so the server is now stopped. Reflect that
    # state, then preserve the original explicit-stop failure for the caller.
    ...
    raise stop_error

# Only a fully successful old-library teardown may open the replacement.
session = window._open_library_session(path)
```

Catch only `Exception`, not `BaseException`; process-control and caller-cancellation exceptions must not be converted into a deferred window error. Do not catch `close_session()` or `cleanup_library()` failures—the later cleanup error must propagate directly.

- [ ] **Step 4: Run GREEN and focused regressions**

Run:

```powershell
python -m pytest tests/integration/test_window_lifecycle_lan_failure.py -q
python -m pytest tests/unit/test_window_session_switching.py tests/unit/test_library_runtime.py tests/lan/test_server_lifecycle.py tests/lan/test_runtime_realtime.py -q
```

Expected: the new real regression passes; existing successful switch ordering, Runtime retry, server lifecycle, and real realtime teardown tests all pass.

- [ ] **Step 5: Run static and final integration gates**

Run:

```powershell
python -m ruff check AssetsManager/window_lifecycle_coordinator.py tests/integration/test_window_lifecycle_lan_failure.py
python -m compileall -q AssetsManager/window_lifecycle_coordinator.py tests/integration/test_window_lifecycle_lan_failure.py
git diff --check -- AssetsManager/window_lifecycle_coordinator.py tests/integration/test_window_lifecycle_lan_failure.py
python -m pytest tests/integration/test_window_lifecycle_lan_failure.py tests/e2e/test_webui_realtime_acceptance.py -q
```

Expected: all commands exit zero. Independently review the diff for exception priority, replacement-open prevention, real WebSocket closure, Runtime adapter release, and preservation of the normal successful-switch order.
