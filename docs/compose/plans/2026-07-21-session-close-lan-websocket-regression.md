# Session Close LAN WebSocket Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that closing a canonical `LibrarySession` through `LibraryService.close_session()` shuts down a real LAN server and its connected WebSocket clients through the Runtime lifecycle adapter.

**Architecture:** Add one integration regression beside the existing realtime lifecycle tests. The test uses `ApplicationBootstrap`, a real `LibraryRuntime`, `_LanServerImpl.start()` on an ephemeral localhost TCP port, and an actual aiohttp WebSocket client. Session closure remains the trigger; the test must not call `server.stop()` before the close notification. Production code changes are allowed only if this real path reproduces a failure.

**Tech Stack:** Python 3, pytest/anyio, aiohttp, asyncio, threaded LAN server, `ApplicationBootstrap` and `LibraryService`.

## Global Constraints

- Preserve unrelated working-tree changes; do not reset, checkout, clean, stage, or commit.
- Keep the test focused on `LibraryService.close_session()` driving the canonical Runtime and LAN adapter lifecycle.
- Use an ephemeral loopback TCP port and do not expose credentials, tokens, or private paths in test output.
- Keep the existing Runtime adapter ownership model: explicit `server.stop()` unregisters the adapter; Runtime cleanup stops it when session closure owns the lifecycle.
- If the regression passes without production changes, add only the test and report that no implementation change was required.

---

### Task 1: Real session-close WebSocket teardown regression

**Files:**
- Modify: `tests/lan/test_runtime_realtime.py`
- Modify only if the regression fails: the smallest production file named by the failure traceback, most likely `AssetsManager/application/runtime.py` or `AssetsManager/lan/server.py`

**Interfaces:**
- Consumes: `ApplicationBootstrap.runtime_for(session)`, `_LanServerImpl.start(port=0, bind="127.0.0.1")`, aiohttp `TestClient.ws_connect()`, and `bootstrap.library_service.close_session(session)`.
- Produces: one regression test proving server, WebSocket, realtime subscription, and Runtime adapter ownership are all torn down by canonical session closure.

- [ ] **Step 1: Add the focused integration test.**

  Add an async test in `tests/lan/test_runtime_realtime.py` that:

  1. Creates an `ApplicationBootstrap`, opens a temporary library session, and obtains its canonical Runtime.
  2. Constructs `_LanServerImpl(runtime=runtime)` and starts it on `127.0.0.1` with `port=0`.
  3. Connects an actual aiohttp client to `http://127.0.0.1:{server._port}/ws` and asserts the first message is `runtime_ready`.
  4. Asserts the server is running, the WebSocket manager contains one client, the Runtime has one lifecycle adapter, and the LAN realtime subscription exists.
  5. Calls `bootstrap.library_service.close_session(session)` without calling `server.stop()` first.
  6. Asserts the WebSocket receives a close message or reaches a closed state, the server is no longer running, the WebSocket manager has no clients, the Runtime realtime subscription is `None`, and the Runtime lifecycle adapter collection is empty.
  7. Calls `bootstrap.library_service.close_session(session)` again and performs idempotent client/server cleanup in `finally`.

  Use the existing test helpers where compatible, but keep the production server and TCP transport real. The close assertion must use a bounded `asyncio.wait_for` so a leaked WebSocket cannot hang the suite.

- [ ] **Step 2: Run the new test and inspect the result.**

  ```powershell
  python -m pytest tests/lan/test_runtime_realtime.py::<new_test_name> -q
  ```

  Expected: the test either passes against the existing Runtime adapter implementation, or fails with a concrete lifecycle traceback. Do not change production code for a speculative failure.

- [ ] **Step 3: If the test fails, write the smallest production regression fix.**

  Preserve the failure as the regression proof, then modify only the failing lifecycle boundary. The fix must maintain these invariants:

  ```text
  LibraryService.close_session()
    -> session closing notification
    -> Runtime.mark_closing()
    -> Runtime.close()
    -> registered LAN server.stop()
    -> realtime subscription and WebSocket clients close
    -> session/database close continues
  ```

  Do not make `LanServer.stop()` close the Runtime, do not call `server.stop()` from the test before `close_session()`, and do not add a second cleanup path that can double-close the session.

- [ ] **Step 4: Re-run the regression and focused lifecycle suites.**

  ```powershell
  python -m pytest tests/lan/test_runtime_realtime.py::<new_test_name> -q
  python -m pytest tests/lan/test_runtime_realtime.py tests/lan/test_server_lifecycle.py tests/unit/test_library_runtime.py tests/integration/test_library_service.py -q
  ```

  Expected: the new real TCP test and all existing lifecycle/runtime/session tests pass; no server thread or WebSocket remains after the test.

- [ ] **Step 5: Run scoped static verification and review the exact diff.**

  ```powershell
  python -m ruff check AssetsManager/application/runtime.py AssetsManager/lan/server.py tests/lan/test_runtime_realtime.py tests/lan/test_server_lifecycle.py tests/unit/test_library_runtime.py tests/integration/test_library_service.py
  python -m compileall -q AssetsManager/application AssetsManager/lan
  git diff --check -- AssetsManager/application/runtime.py AssetsManager/lan/server.py tests/lan/test_runtime_realtime.py tests/lan/test_server_lifecycle.py tests/unit/test_library_runtime.py tests/integration/test_library_service.py
  ```

  Expected: all commands exit successfully, and the diff contains only the real session-close regression plus any directly required lifecycle fix.

## Plan self-review

- Scope is one independently testable subsystem: canonical session close to real LAN/WebSocket teardown.
- No production change is assumed; the existing adapter fix is tested rather than expanded speculatively.
- The test uses the actual threaded TCP server and actual WebSocket handshake, while bounded waits prevent leaked resources from hanging pytest.
- No commit or workspace cleanup is included because the current worktree contains user-owned cross-task changes.
