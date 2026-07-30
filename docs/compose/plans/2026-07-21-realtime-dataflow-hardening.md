# Desktop–WebUI Realtime Dataflow Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the audited realtime correctness, authorization, shutdown, and failed-socket lifecycle gaps before continuing unrelated implementation-plan work.

**Architecture:** Preserve `LibraryRuntime` as the sole event/revision owner and keep SQLite/filesystem authoritative. Harden the LAN adapter at connection admission, authorization revocation, server shutdown, and socket eviction boundaries; React continues to consume invalidation hints and refetch authoritative HTTP projections.

**Tech Stack:** Python 3, aiohttp, pytest/anyio, React 18, TypeScript, Vitest, Chromium acceptance harness.

## Global Constraints

- SQLite and the filesystem remain authoritative; WebSocket messages remain invalidation hints containing `epoch`, `revision`, domains, and relative paths only.
- Desktop continues to call application services directly rather than using local HTTP.
- Preserve session/root isolation, HttpOnly-cookie authentication, query-credential rejection for WebSockets, explicit principal capabilities, and the existing `epoch + revision` recovery protocol.
- Each task must use TDD and pass its focused tests before the next task begins.
- Do not modify unrelated user changes, create commits, or create branches without explicit authorization.

---

### Task 1: Atomic WebSocket Admission Baseline

**Covers:** [S2] Atomic WebSocket admission

**Files:**
- Modify: `AssetsManager/lan/routes/websocket.py`
- Modify: `AssetsManager/lan/ws.py` only if a manager admission primitive is required
- Test: `tests/lan/test_runtime_realtime.py`
- Test: `tests/e2e/test_webui_realtime_acceptance.py` if a real-browser ordering assertion is required

**Interfaces:**
- Consumes: `lan.runtime.epoch/revision`, `WebSocketManager`, authenticated `SessionPrincipal`.
- Produces: a socket admission path that sends a successful `runtime_ready` baseline before the socket can receive runtime broadcasts; failed baseline delivery leaves no active client.

- [ ] **Step 1: Write a deterministic failing admission-race test**

Add a test that pauses the baseline send, emits a runtime invalidation, and asserts the new socket does not receive `projection_invalidated` before `runtime_ready`. Also assert a failed baseline send does not leave the socket in `WebSocketManager.connections`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/lan/test_runtime_realtime.py -k "admission or ready or baseline" -q`

Expected: the new race test fails against the current `add()`-then-`send_json(runtime_ready)` ordering.

- [ ] **Step 3: Implement the smallest atomic admission change**

Use one of these concrete implementations, selected by the existing manager API: send `runtime_ready` before adding the socket to the broadcast set, or add a manager-level pending client state that excludes the socket until the baseline send succeeds. On send failure, close the socket and remove all associated bookkeeping before returning.

- [ ] **Step 4: Run focused Python and browser realtime tests**

Run: `python -m pytest tests/lan/test_runtime_realtime.py -q` and `python -m pytest tests/e2e/test_webui_realtime_acceptance.py -q`.

Expected: all focused tests pass, including the forced admission race, without weakening query-credential or capability checks.

- [ ] **Step 5: Review the diff and boundary assertions**

Run: `rg -n "ws_manager\.add|runtime_ready|projection_invalidated" AssetsManager/lan/routes/websocket.py AssetsManager/lan/ws.py tests/lan/test_runtime_realtime.py` and `git diff --check -- AssetsManager/lan tests/lan tests/e2e`.

Expected: there is one ordered admission path, no duplicate broadcast registration, and no whitespace errors.

### Task 2: Live WebSocket Authorization Revocation

**Covers:** [S3] Live authorization revocation

**Files:**
- Modify: `AssetsManager/lan/routes/websocket.py`
- Modify: `AssetsManager/lan/ws.py` if connection metadata/revocation support belongs there
- Modify: `AssetsManager/lan/server.py` or auth/user-management integration only where the canonical revoke signal is already owned
- Test: `tests/lan/test_runtime_realtime.py`
- Test: `tests/lan/test_t2_t4_contracts.py` for query/capability regressions
- Test: `tests/e2e/test_webui_realtime_acceptance.py` for ordinary user-cookie behavior if harness support exists

**Interfaces:**
- Consumes: authenticated principal identity and the existing auth/token verification source of truth.
- Produces: a live connection that is closed or denied further broadcasts when its user/token/realtime authority is revoked.

- [ ] **Step 1: Write failing live-revocation tests**

Add tests for a connected user socket whose active status or token authority is revoked, then emit a runtime invalidation and assert no further projection event is delivered and the socket is closed/removed. Keep the existing handshake tests for guests, query credentials, and missing realtime capability.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/lan/test_runtime_realtime.py tests/lan/test_t2_t4_contracts.py -k "revoke or disable or delete or token or websocket" -q`.

Expected: the new live-revocation test fails because current authorization is handshake-only.

- [ ] **Step 3: Implement canonical revalidation/revocation**

Bind each authenticated socket to a revocable identity record or token/session identifier. Revalidate at the existing heartbeat/connection lifecycle boundary or consume the existing canonical auth revocation signal. Route revocation through the same close/removal path as ordinary disconnect, and never accept query-string credentials as a substitute.

- [ ] **Step 4: Verify auth and realtime behavior**

Run: `python -m pytest tests/lan/test_runtime_realtime.py tests/lan/test_t2_t4_contracts.py tests/lan/test_role_permissions.py -q`.

Expected: live revocation passes and all existing capability/query-credential tests remain green.

- [ ] **Step 5: Run ordinary user-cookie browser coverage or document the environment gate**

Run the available authenticated Chromium acceptance for user-cookie revocation. If the harness cannot create this scenario, add a focused server-level test and document the missing browser gate rather than claiming it was covered.

### Task 3: Correct LAN Server Shutdown State

**Covers:** [S4] Shutdown state correctness

**Files:**
- Modify: `AssetsManager/lan/server.py`
- Test: `tests/lan/test_lan_api.py` or the existing server lifecycle test module
- Test: `tests/e2e/test_webui_realtime_acceptance.py` only if teardown assertions are corrected there

**Interfaces:**
- Consumes: existing `_shutdown()` future, server loop/thread references, `LanServer.start/stop/is_running`.
- Produces: explicit confirmed-stop behavior; timeout/failure retains actionable state and prevents unsafe restart.

- [ ] **Step 1: Write failing shutdown-timeout tests**

Add tests that force `_shutdown()` timeout and thread-join timeout. Save the pre-stop thread reference and assert current code does not incorrectly report a stopped/restartable server while that thread remains alive.

- [ ] **Step 2: Run focused lifecycle tests and verify RED**

Run: `python -m pytest tests/lan -k "stop or shutdown or restart or thread" -q`.

Expected: the new timeout test fails because current `stop()` clears `_running`, `_loop`, and `_thread` unconditionally.

- [ ] **Step 3: Implement explicit stopping/failed handling**

Only clear `_loop` and `_thread` after confirmed thread termination. If shutdown or join times out, preserve the references, retain a non-stopped state, and reject `start()` while the old thread is alive. Keep successful stop idempotent and preserve normal same-port restart after confirmed termination.

- [ ] **Step 4: Run lifecycle and browser teardown verification**

Run: `python -m pytest tests/lan -k "stop or shutdown or restart or thread" -q` and `python -m pytest tests/e2e/test_webui_realtime_acceptance.py -q`.

Expected: timeout state is truthful, confirmed restart works, and browser teardown observes the actual pre-stop thread termination.

### Task 4: Unified Failed-Socket Eviction and Presence Cleanup

**Covers:** [S5] Failed-socket lifecycle cleanup

**Files:**
- Modify: `AssetsManager/lan/ws.py`
- Modify: `AssetsManager/lan/routes/websocket.py` only if route cleanup needs an explicit idempotent hook
- Modify: `AssetsManager/lan/server.py` only if connection accounting callback ownership requires it
- Test: `tests/lan/test_lan_api.py`
- Test: `tests/lan/test_runtime_realtime.py`

**Interfaces:**
- Consumes: `WebSocketManager` clients/pong waiters, `on_connection_change`, route `finally`, and `online_users` presence.
- Produces: one idempotent failed-client eviction path that removes, closes, accounts, and releases presence without affecting healthy clients.

- [ ] **Step 1: Write failing eviction tests**

Add one broadcast-send failure test and one heartbeat failure test. Assert the dead socket is closed, removed from clients and pong waiters, connection count is decremented, and associated `OnlineUsers` presence is disconnected; assert a healthy peer still receives the event.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest tests/lan/test_lan_api.py tests/lan/test_runtime_realtime.py -k "broadcast or heartbeat or dead or connection or presence" -q`.

Expected: current direct set removal fails one or more accounting/presence assertions.

- [ ] **Step 3: Implement one idempotent eviction helper**

Centralize failed-client handling so both broadcast and heartbeat call the same async cleanup operation. It must coordinate manager bookkeeping and socket close without double-calling normal route cleanup or double-decrementing connection counts.

- [ ] **Step 4: Verify healthy-peer isolation and full LAN realtime tests**

Run: `python -m pytest tests/lan/test_lan_api.py tests/lan/test_runtime_realtime.py tests/lan/test_public_contracts.py tests/lan/test_t2_t4_contracts.py -q`.

Expected: all tests pass, including failure eviction, healthy-peer delivery, auth, path, DTO, and runtime isolation coverage.

### Task 5: Cross-Surface Hardening Gate

**Covers:** [S1] Scope and invariants, [S6] Verification gates

**Files:**
- Modify: only earlier task files if a gate exposes a directly related regression.
- Update: `docs/architecture.md`, `docs/compose/reports/desktop-lan-webui-architecture-migration.md`, and this plan/spec with final hardening evidence.

- [ ] **Step 1: Run Python dataflow and security gates**

Run: `python -m pytest tests/lan/test_runtime_realtime.py tests/lan/test_public_contracts.py tests/lan/test_t2_t4_contracts.py tests/lan/test_role_permissions.py tests/unit/test_architecture_boundaries.py -q`.

- [ ] **Step 2: Run React realtime and WebUI gates**

Run: `npm --prefix webui test -- --run src/stores/RealtimeContext.test.tsx src/hooks/useWebSocket.test.tsx src/pages/BrowsePage.test.tsx src/pages/DetailPage.test.tsx` and `npm --prefix webui run typecheck` and `npm --prefix webui run build`.

- [ ] **Step 3: Run real browser acceptance**

Run: `python -m pytest tests/e2e/test_webui_realtime_acceptance.py -q`.

Expected: Desktop mutation, disconnect/reconnect gap recovery, epoch replacement, auth boundary, and teardown assertions pass.

- [ ] **Step 4: Update evidence and residual risks**

Record exact pass counts, documented Windows symlink skips, any React Router warnings, and any unavailable ordinary-user browser gate. Do not mark the hardening complete if a P1 scenario lacks a passing deterministic test.

- [ ] **Step 5: Run final diff and architecture scan**

Run: `git diff --check`, `rg -n "DatabaseManager\.current|new WebSocket|ws_manager\.add|runtime_ready|projection_invalidated|_thread = None|_running = False" AssetsManager/application AssetsManager/lan webui/src tests`, and inspect all changed files for unrelated modifications.

Expected: no forbidden production dataflow fallback, no unsafe admission ordering, no unconditional timeout cleanup, and no unverified P1 claim.
