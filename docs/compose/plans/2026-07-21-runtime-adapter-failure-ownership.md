# Runtime Adapter Failure Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep `LibraryRuntime` lifecycle-adapter ownership truthful when LAN server construction or startup fails, while preserving retryable ownership for incomplete cleanup.

**Architecture:** `_LanServerImpl` registers with its Runtime only after all constructor validation and aiohttp application construction succeeds. A server worker unregisters itself only after reaching a terminal non-running state with completed cleanup; shutdown failures and timeouts retain registration so `Runtime.close()` or a later explicit `stop()` can retry. The real close-session regression executes its second `close_session()` rather than reusing a cached cleanup result.

**Tech Stack:** Python 3, threading, asyncio, aiohttp, pytest.

## Global Constraints

- Preserve unrelated working-tree changes; do not reset, checkout, clean, stage, or commit.
- Do not change Runtime-to-LAN ownership direction: server stop must not close Runtime or LibrarySession.
- Construction failures must never enter `runtime._lifecycle_adapters`.
- Terminal startup rollback with complete cleanup must unregister the server.
- Startup/shutdown failure with incomplete cleanup must retain the adapter for retry.
- Keep changes limited to `AssetsManager/lan/server.py` and focused LAN/runtime lifecycle tests.

---

### Task 1: Make the real close-session idempotency assertion genuine

**Files:**
- Modify: `tests/lan/test_runtime_realtime.py`

**Interfaces:**
- Consumes: the test-local `run_sync_cleanup(key, function, *args)` helper.
- Produces: two actual calls to `LibraryService.close_session(session)` without concurrent duplicate cleanup after timeout.

- [ ] **Step 1: Add an invocation counter around `close_session`.**

  Wrap the canonical bound method without changing its behavior:

  ```python
  close_session_calls = []
  original_close_session = bootstrap.library_service.close_session

  def observe_close_session(current_session):
      close_session_calls.append(current_session)
      return original_close_session(current_session)
  ```

  Use `observe_close_session` for the primary and idempotency calls and assert `close_session_calls == [session, session]` after the second call.

- [ ] **Step 2: Run RED.**

  ```powershell
  python -m pytest tests/lan/test_runtime_realtime.py::test_real_library_close_session_stops_lan_server_and_websocket -q
  ```

  Expected: FAIL because completed pending key `"session"` prevents the second invocation.

- [ ] **Step 3: Retire completed pending workers before starting a later invocation.**

  In `run_sync_cleanup`, reuse an existing key only while its worker is unfinished. Once complete and its error has been observed, remove that key from `pending_sync_cleanups`; a later call with the same key starts a new daemon worker. A timed-out unfinished worker remains cached so fallback cleanup cannot start a concurrent duplicate.

- [ ] **Step 4: Run GREEN and the full realtime test file.**

  ```powershell
  python -m pytest tests/lan/test_runtime_realtime.py::test_real_library_close_session_stops_lan_server_and_websocket -q
  python -m pytest tests/lan/test_runtime_realtime.py -q
  ```

  Expected: both actual close calls complete, server stop remains exactly once, and all realtime tests pass.

### Task 2: Register only fully constructed LAN adapters

**Files:**
- Modify: `AssetsManager/lan/server.py`
- Modify: `tests/lan/test_lan_api.py`

**Interfaces:**
- Consumes: `LibraryRuntime.register_lifecycle_adapter(self)`.
- Produces: construction-time all-or-nothing adapter registration.

- [ ] **Step 1: Add a failing constructor-validation regression.**

  Build a canonical Runtime, replace one runtime service provider with a foreign provider, construct `_LanServerImpl(runtime=runtime)`, expect `ValueError`, then assert `runtime._lifecycle_adapters == []`.

- [ ] **Step 2: Run RED.**

  ```powershell
  python -m pytest tests/lan/test_lan_api.py::<constructor_failure_test> -q
  ```

  Expected: FAIL because the current constructor registers before provider validation.

- [ ] **Step 3: Move registration to the constructor commit point.**

  Remove registration before service-provider validation. After `self.services`, `self._services`, and `_build_app()` succeed, register the server:

  ```python
  self._services = self.services
  self._build_app()
  register_adapter = getattr(self.runtime, "register_lifecycle_adapter", None)
  if callable(register_adapter):
      register_adapter(self)
  ```

- [ ] **Step 4: Run GREEN and constructor contract tests.**

  ```powershell
  python -m pytest tests/lan/test_lan_api.py::<constructor_failure_test> tests/lan/test_lan_api.py::test_runtime_injection_uses_canonical_session_resources_and_services -q
  ```

  Expected: failed construction leaves no adapter; successful construction registers exactly once.

### Task 3: Unregister after terminal startup rollback

**Files:**
- Modify: `AssetsManager/lan/server.py`
- Modify: `tests/lan/test_server_lifecycle.py`

**Interfaces:**
- Consumes: `_cleanup_complete`, `_running`, `_unregister_runtime_adapter()` and worker-thread termination.
- Produces: registry truth after bind/startup failure without weakening retry ownership after incomplete cleanup.

- [ ] **Step 1: Add a failing terminal startup regression.**

  Extend the controlled bind-failure server with a Runtime mock exposing `unregister_lifecycle_adapter`. After `start()` raises and the worker terminates with `_cleanup_complete is True`, assert `unregister_lifecycle_adapter(server)` was called once.

- [ ] **Step 2: Run RED.**

  ```powershell
  python -m pytest tests/lan/test_server_lifecycle.py::test_bind_failure_returns_without_waiting_for_rollback_timeout -q
  ```

  Expected: FAIL because terminal worker exit does not currently unregister.

- [ ] **Step 3: Unregister only at terminal worker completion.**

  In `_run()` finalization, close the event loop, then unregister only when cleanup is complete and the server is not running:

  ```python
  finally:
      self._loop.close()
      if self._cleanup_complete and not self._running:
          self._unregister_runtime_adapter()
  ```

  Keep the existing successful `stop()` unregister calls idempotent. Do not unregister when `_cleanup_complete` is false.

- [ ] **Step 4: Run lifecycle GREEN and retry regressions.**

  ```powershell
  python -m pytest tests/lan/test_server_lifecycle.py -q
  python -m pytest tests/unit/test_library_runtime.py tests/unit/test_lan_sharing.py -q
  ```

  Expected: bind/startup terminal failures unregister; stop timeout/failure retry tests continue passing.

- [ ] **Step 5: Run integrated verification and review.**

  ```powershell
  python -m pytest tests/integration/test_runtime_events.py tests/lan/test_runtime_realtime.py tests/lan/test_server_lifecycle.py tests/lan/test_lan_api.py tests/unit/test_lan_sharing.py tests/unit/test_library_runtime.py tests/integration/test_library_service.py -q
  python -m ruff check AssetsManager/lan/server.py tests/lan/test_runtime_realtime.py tests/lan/test_server_lifecycle.py tests/lan/test_lan_api.py
  python -m compileall -q AssetsManager/application AssetsManager/lan
  git diff --check -- AssetsManager/lan/server.py tests/lan/test_runtime_realtime.py tests/lan/test_server_lifecycle.py tests/lan/test_lan_api.py
  ```

  Expected: all lifecycle and LAN gates pass; independent review finds no registry, lock-order, or retry regression.

## Plan self-review

- Constructor failure, terminal startup rollback, and incomplete-cleanup retry are separate ownership states and have separate assertions.
- The test-helper fix proves actual idempotency without permitting concurrent duplicate cleanup after timeout.
- Registration is moved only to the constructor commit point; no new adapter abstraction or reverse ownership is introduced.
- No commit, worktree migration, UI change, or unrelated cleanup is included.
