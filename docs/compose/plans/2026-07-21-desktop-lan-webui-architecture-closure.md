# Desktop–LAN–WebUI Architecture Closure Implementation Plan

> [!WARNING]
> **Historical plan:** superseded by
> [`2026-07-21-desktop-lan-webui-architecture-recalibration.md`](2026-07-21-desktop-lan-webui-architecture-recalibration.md),
> which is the current authoritative task chain after re-auditing the code and
> separating delivered realtime hardening from remaining architecture work.
> Keep this file for traceability; do not execute it in parallel with the
> recalibrated plan.

> [!NOTE]
> This plan contains the remaining implementation chain; it is not evidence
> that the closure tasks have been executed. See the current-state report:
> [Desktop–LAN–WebUI Architecture Migration — Current-State Report](../reports/desktop-lan-webui-architecture-migration.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the verified Runtime lifecycle, realtime admission/recovery, cookie-only identity and projection-producer gaps that prevent the Desktop–LAN–WebUI migration from being release-ready.

**Architecture:** Keep `ApplicationBootstrap` and `LibraryRuntime` as the sole library-scoped ownership boundary. First make session close a truthful barrier for every LAN adapter; then make WebSocket admission and first-cursor recovery authoritative; then align browser identity teardown and all advertised projection domains with canonical HTTP refetches; finally remove compatibility paths and run the complete acceptance matrix.

**Tech Stack:** Python 3, threading, asyncio, aiohttp, SQLite, pytest, React 18, TypeScript, Vitest, Chromium acceptance harness.

## Global Constraints

- SQLite and the filesystem remain authoritative; WebSocket messages remain invalidation hints only.
- `LibraryService.close_session()` must not release session/DB resources while a registered LAN adapter can still use them.
- Business transactions must not depend on WebSocket delivery success.
- Browser authentication is HttpOnly-cookie based; credentials must not be returned to or stored by JavaScript.
- Do not add a second service assembly path, persistent revision store, microservice, Redis, Kafka or React Query migration.
- Every task must add or strengthen a focused regression before changing production behavior.
- Preserve unrelated working-tree changes and do not commit without explicit authorization.

## File Responsibility Map

- `AssetsManager/application/library_service.py`, `context.py`: session closing barrier and DB release order.
- `AssetsManager/application/bootstrap.py`, `runtime.py`: Runtime adapter cleanup, retry state and exact ownership.
- `AssetsManager/lan/server.py`, `lan/__init__.py`, `lan/manager.py`: server generation registration and truthful failed-stop state.
- `AssetsManager/lan/routes/websocket.py`, `lan/ws.py`: baseline/admission ordering and no-frame rejection.
- `webui/src/stores/AuthContext.tsx`, `webui/src/pages/LoginPage.tsx`, `webui/src/App.tsx`: cookie-only identity and route teardown.
- `webui/src/stores/RealtimeContext.tsx`, `hooks/useInvalidation.ts`, `hooks/useSearch.ts`: first-ready recovery and projection invalidation.
- `AssetsManager/domain/events.py`, event producers, `runtime_events.py`, LAN/admin React consumers: shares/users/stats producer alignment.
- `tests/unit/test_library_runtime.py`, `tests/integration/test_library_service.py`, `tests/lan/test_server_lifecycle.py`, `tests/lan/test_runtime_realtime.py`, `webui/src/**/*.test.tsx`: focused closure gates. Create a missing focused test file only where the existing suite has no route/provider boundary fixture; do not cite a non-existent test file as an existing gate.

## Dependency Order

`Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7`.

Tasks 1–3 are the P1 lifecycle/realtime foundation. Task 4 depends on stable
identity transitions. Task 5 depends on the provider and event router being
able to describe every advertised domain. Tasks 6–7 are cleanup and release
evidence, not substitutes for the earlier behavioral fixes.

---

### Task 1: Make session close a truthful Runtime barrier

**Covers:** [C1]

**Files:**
- Modify: `AssetsManager/application/library_service.py`
- Modify: `AssetsManager/application/bootstrap.py`
- Modify: `AssetsManager/application/runtime.py`
- Modify: `AssetsManager/application/context.py` only if the close barrier needs a narrow internal hook
- Test: `tests/unit/test_library_runtime.py`
- Test: `tests/integration/test_library_service.py`
- Test: `tests/integration/test_window_lifecycle_lan_failure.py`

**Interfaces:**
- Consumes: `LibraryService._notify_session_closing`, `LibraryRuntime.register_lifecycle_adapter`, `LibraryRuntime.close`.
- Produces: a pre-close adapter-stop barrier; `session_closed` and `DatabaseManager.close_library()` occur only after adapter cleanup succeeds or the session remains explicitly failed/retryable.

  Required state transition:

  ```text
  open session
    → _begin_close()                 # reject new operation leases
    → session_closing                # stop registered Runtime adapters
    → _finish_close()                # drain existing leases and clear caches
    → session_closed                 # remove Runtime ownership
    → close_library()                # release DB resource last
  ```

- [ ] **Step 1: Add the failing ordering test.**

  Register a fake adapter whose `stop()` records the session state and blocks once. Start one leased session operation, call `close_session()` from another thread, and assert: new leases fail after `_begin_close()`, the adapter is stopped before DB close, the existing lease drains before `session_closed`, and the DB close callback is last.

- [ ] **Step 2: Add failure-retention tests.**

  Make the adapter fail once, call `close_session()`, and assert the server/adapter remains registered and the session is not reported as cleanly closed. Call the close operation again after allowing the adapter to stop and assert cleanup completes without a second DB close.

- [ ] **Step 3: Implement the smallest lifecycle split.**

  Keep `_begin_close()` as the new-operation rejection point. Make the
  `session_closing` listener perform the Runtime adapter cleanup while the
  session resources are still live. Do not call the post-close
  `runtime.close()` as the first adapter-stop boundary. Drain existing leases;
  only then notify `session_closed` and release the per-library DB. Preserve
  the original exception and retain retry ownership when adapter cleanup is
  incomplete. If cleanup fails, expose the failed state and do not claim that
  `close_session()` completed cleanly.

- [ ] **Step 4: Verify the focused gate.**

  Run: `python -m pytest tests/unit/test_library_runtime.py tests/integration/test_library_service.py tests/integration/test_window_lifecycle_lan_failure.py -q`

  Expected: all focused tests pass, including failure retry and adapter-before-DB ordering.

---

### Task 2: Reconcile LAN server generation ownership

**Covers:** [C1]

**Files:**
- Modify: `AssetsManager/lan/server.py`
- Modify: `AssetsManager/lan/manager.py`
- Modify: `AssetsManager/application/runtime.py` only if registration state needs an explicit generation
- Test: `tests/lan/test_server_lifecycle.py`
- Test: `tests/unit/test_lan_sharing.py`
- Test: `tests/unit/test_library_runtime.py`

**Interfaces:**
- Consumes: `runtime.register_lifecycle_adapter()` and `unregister_lifecycle_adapter()`.
- Produces: exactly one Runtime registration for each successful server generation; failed stop retains the handle and failed state for retry.

- [ ] **Step 1: Add the restart-ownership regression.**

  Construct one live Runtime and server, execute `start → stop → start`, then close the canonical session without manually stopping the server. Assert the second generation is stopped by Runtime cleanup and no duplicate registration exists.

- [ ] **Step 2: Add the ShareManager failure regression.**

  Use a fake server whose first `stop()` raises and whose second call succeeds. Assert after the first `ShareManager.stop()` the server handle is retained, `status()['running']` is false or failed-but-actionable rather than falsely clean, and the second call retries the same handle.

- [ ] **Step 3: Re-register only after successful start.**

  Keep construction-time validation all-or-nothing. A successful `start()`
  must register the server if the prior generation unregistered it; a failed or
  incomplete generation must retain ownership. Make
  `register_lifecycle_adapter()`/`unregister_lifecycle_adapter()` idempotent
  under concurrent stop/start rejection. The generation invariant is:

  ```text
  constructed + validated → no registration yet
  start succeeds          → exactly one registration
  confirmed stop          → unregister that generation
  next start succeeds     → exactly one new registration
  ```

- [ ] **Step 4: Preserve failed cleanup state.**

  Change `ShareManager.stop()` so it does not set `_server = None` or publish a clean stopped state after an exception. The retry path must not create a second server or overlap cleanup.

- [ ] **Step 5: Verify the lifecycle gate.**

  Run: `python -m pytest tests/lan/test_server_lifecycle.py tests/unit/test_lan_sharing.py tests/unit/test_library_runtime.py -q`

  Expected: restart, concurrent stop, startup failure, failed stop retry and session-owned teardown all pass.

---

### Task 3: Close WebSocket admission and first-cursor recovery races

**Covers:** [C2]

**Files:**
- Modify: `AssetsManager/lan/routes/websocket.py`
- Modify: `AssetsManager/lan/ws.py`
- Modify: `webui/src/stores/RealtimeContext.tsx`
- Test: `tests/lan/test_runtime_realtime.py`
- Test: `webui/src/stores/RealtimeContext.test.tsx`
- Test: `webui/src/hooks/useWebSocket.test.tsx`

**Interfaces:**
- Consumes: `WebSocketManager.add(..., admission_pending=True)`, `finish_admission()`, Runtime `epoch/revision`, and `/api/revision`.
- Produces: no invalidation before baseline; first browser baseline causes one authoritative recovery; failed admission leaves no client or presence residue.

- [ ] **Step 1: Add the deterministic server admission race test.**

  Pause baseline delivery, emit an invalidation, and assert the socket receives no `projection_invalidated` before `runtime_ready`. Force baseline failure and assert the socket is evicted and absent from clients, pong waiters and presence.

- [ ] **Step 2: Add the first-ready React regression.**

  Start the provider with cursor `{ epoch: '', revision: 0 }`, emit the first `runtime_ready`, and assert `/api/revision` is called once and every registered projection receives one recovery notification even when the ready revision is zero.

- [ ] **Step 3: Implement one authoritative admission sequence.**

  Authenticate and check `principal.capabilities.realtime` before sending any
  application frame. Prepare the socket, add it as a pending lease, send the
  baseline, re-read the cursor, and call `finish_admission()` only after the
  baseline/reconciliation sequence succeeds. On any send/authorization error,
  call the single eviction path. Do not send a baseline frame to a rejected
  connection after admission has failed.

- [ ] **Step 4: Trigger initial recovery explicitly.**

  In `RealtimeContext`, treat an empty cursor as uncertain state. On the first valid `runtime_ready`, update the cursor and run the same deduplicated recovery/fan-out path used for epoch changes; do not make later duplicate ready frames refetch.

- [ ] **Step 5: Verify the realtime gate.**

  Run: `python -m pytest tests/lan/test_runtime_realtime.py -q`; then `npm --prefix webui test -- --run src/stores/RealtimeContext.test.tsx src/hooks/useWebSocket.test.tsx`; then `npm --prefix webui run typecheck`.

  Expected: ordered admission, cleanup, first-ready recovery, gap recovery and epoch recovery all pass.

---

### Task 4: Make browser identity transitions clear protected projections

**Covers:** [C3]

**Files:**
- Modify: `AssetsManager/lan/routes/auth.py`
- Modify: `AssetsManager/lan/dto.py`
- Modify: `webui/src/types/api.ts`
- Modify: `webui/src/stores/AuthContext.tsx`
- Modify: `webui/src/pages/LoginPage.tsx`
- Modify: `webui/src/App.tsx`
- Modify: `webui/src/pages/BrowsePage.tsx`
- Modify: `webui/src/pages/DetailPage.tsx`
- Create or modify: `webui/src/components/auth/ProtectedRoute.tsx`
- Test: `tests/lan/test_lan_api.py`
- Test: `webui/src/pages/LoginPage.test.tsx`
- Test: `webui/src/stores/AuthContext.test.tsx`
- Create: `webui/src/App.test.tsx`

**Interfaces:**
- Consumes: `SessionPrincipal`, `Capabilities`, same-origin `credentials: 'same-origin'` API calls.
- Produces: token-free login/register/key DTOs, cookie-only AuthContext, shared protected route guard and identity-scoped data reset.

- [ ] **Step 1: Add token-free contract tests.**

  Assert successful password, user, registration and key responses contain no `token`; assert the HttpOnly cookie is still set and `/auth/me` remains authoritative. Update TypeScript fixtures to omit bearer-token fields.

- [ ] **Step 2: Add identity teardown tests.**

  Render an authenticated protected route, trigger logout and a 401, and
  assert the route redirects, principal becomes guest, RealtimeProvider
  remounts, cursor resets and protected list/detail/search state is cleared.
  Add the guard in the new route-level test harness; assert a stale response
  from the previous identity cannot repopulate the page.

- [ ] **Step 3: Implement cookie-only auth.**

  Return only a normalized principal snapshot or a minimal success marker from login/register/key routes; keep the actual credential in the HttpOnly cookie. Remove token state and `setToken` compatibility from production consumers. Login must call `refreshMe()` before navigating.

- [ ] **Step 4: Add one protected route boundary.**

  Guard `/browse` and `/detail` using the server capability/principal state. Public landing and share receive routes remain outside this guard. On identity generation change, cancel/ignore all protected projection requests and clear selection/cursor state.

- [ ] **Step 5: Verify the identity gate.**

  Run: `python -m pytest tests/lan/test_lan_api.py::test_task4_auth_me_exposes_unified_principal_for_all_kinds tests/lan/test_lan_api.py::test_auth_register_route_returns_user_token tests/lan/test_t2_t4_contracts.py::test_auth_cookie_is_httponly -q`; then the existing LoginPage/AuthContext/Browse/Detail tests plus the new route-guard test; then `npm --prefix webui run typecheck`.

  Expected: no JavaScript-visible bearer token and no protected projection survives identity loss.

---

### Task 5: Complete invalidation producers and canonical projection refresh

**Covers:** [C4]

**Files:**
- Modify: `AssetsManager/domain/events.py`
- Modify: `AssetsManager/application/runtime_events.py`
- Modify: `AssetsManager/application/share_service.py`
- Modify: `AssetsManager/application/auth_service.py`
- Modify: `AssetsManager/lan/routes/shares.py`
- Modify: `AssetsManager/lan/routes/users.py`
- Modify: `AssetsManager/lan/routes/system.py`
- Modify: `webui/src/hooks/useSearch.ts`
- Modify: `webui/src/components/admin/InviteManagement.tsx`
- Modify: `webui/src/components/admin/ActivityLog.tsx`
- Modify: `webui/src/components/admin/OnlineUsers.tsx`
- Modify: `webui/src/components/layout/StatusBar.tsx`
- Test: `tests/integration/test_runtime_events.py`
- Test: `tests/lan/test_runtime_realtime.py`
- Test: `webui/src/hooks/useSearch.test.tsx`
- Test: `webui/src/components/admin/AdminManagement.test.tsx`
- Test: `webui/src/components/admin/ActivityLog.test.tsx`
- Test: `webui/src/components/admin/OnlineUsers.test.tsx`

**Interfaces:**
- Consumes: `InvalidationEvent` domain literals and existing HTTP list/stats APIs.
- Produces: producer-backed `shares/users/stats` invalidation or explicitly unavailable UI; active search/admin projections refetch canonical server data.

- [ ] **Step 1: Add failing producer mapping tests.**

  Publish share create/revoke/delete and user/invite mutation facts with the current session token, assert the router emits the corresponding domain, and assert unrelated Runtime sessions receive nothing. Add a stats test that distinguishes a measured value from unavailable bytes/activity.

- [ ] **Step 2: Add consumer refresh tests.**

  With an active search query, dispatch a `files`/`metadata` invalidation and assert the query refetches. After invite create/revoke, assert the component refetches the invite list and never uses browser `Date.now()` as `created_at`. Assert admin activity/online/stats consumers refresh only for their registered domains.

- [ ] **Step 3: Add session-scoped events and mappings.**

  Define immutable events carrying `library_root` and `session_token`; publish them only after the underlying transaction succeeds. Extend `ProjectionDomain` and `EVENT_DOMAINS` only for domains with a real producer and HTTP projection.

- [ ] **Step 4: Replace local synthesis with authoritative refetch.**

  Keep request-generation guards, but after mutation success reload the canonical list/detail response. If a metric cannot be measured, return/render `null` or unavailable rather than zero.

- [ ] **Step 5: Verify the producer/projection gate.**

  Run: `python -m pytest tests/integration/test_runtime_events.py tests/lan/test_runtime_realtime.py -q`; then `npm --prefix webui test -- --run src/hooks/useSearch.test.tsx src/components/admin/AdminManagement.test.tsx src/components/admin/ActivityLog.test.tsx src/components/admin/OnlineUsers.test.tsx`; then `npm --prefix webui run typecheck`.

  Expected: every advertised domain has an evidence-backed producer and canonical consumer refresh.

---

### Task 6: Remove migration fallbacks and ratchet architecture gates

**Covers:** [C5]

**Files:**
- Modify: `AssetsManager/application/bootstrap.py`
- Modify: `AssetsManager/application/library_service.py`
- Modify: `AssetsManager/window.py`
- Modify: `AssetsManager/lan/manager.py`
- Modify: `AssetsManager/lan/routes/_helpers.py`
- Modify: `webui/src/hooks/useWebSocket.ts`
- Modify: `webui/src/stores/AuthContext.tsx`
- Modify: `webui/src/types/api.ts`
- Modify: `tests/unit/test_architecture_boundaries.py`
- Modify: `tests/core/test_package_contents.py`
- Modify: `scripts/check_package_contents.py`

**Interfaces:**
- Consumes: completed Runtime, principal, provider and producer contracts.
- Produces: one production assembly path, one identity contract, no direct page event parser, and no dead compatibility fallback.

- [ ] **Step 1: Add forbidden-pattern gates.**

  Assert production code has no raw-connection LAN service assembly, no `cleanup_library()` call, no `LibraryService.current` production read, no browser token state/response field, and no direct page-level WebSocket event interpretation.

- [ ] **Step 2: Migrate remaining callers.**

  Change each caller found by `rg -n "for_library\\(|cleanup_library\\(|get_library_service\\(|\\.current\\b" AssetsManager tests` to consume an explicit canonical Runtime or an explicitly scoped service passed by its owner. Keep compatibility only in tests that characterize a documented external boundary.

- [ ] **Step 3: Delete only proven fallbacks.**

  Remove the compatibility facade, legacy auth fields and transport bridge only after the focused consumer tests pass. Do not delete domain events still used by Desktop panels without migrating those producers/consumers first.

- [ ] **Step 4: Verify the boundary gate.**

  Run: `python -m pytest tests/unit/test_architecture_boundaries.py tests/core/test_package_contents.py -q`; then `npm --prefix webui test -- --run`; then `npm --prefix webui run typecheck`; then `npm --prefix webui run build`.

  Expected: forbidden-pattern scans return no unapproved production matches and packaging includes only the canonical modules.

---

### Task 7: Execute final cross-surface closure and publish evidence

**Covers:** [C1, C2, C3, C4, C5]

**Files:**
- Update: `docs/architecture.md`
- Update: `docs/architecture-diagram.md`
- Update: `docs/adr/0003-library-runtime.md`
- Update: `docs/compose/reports/desktop-lan-webui-architecture-migration.md`
- Update: this plan and the closure design with exact evidence
- Create: `docs/compose/reports/desktop-lan-webui-architecture-closure.md`

**Interfaces:**
- Consumes: Tasks 1–6 and their focused evidence.
- Produces: a release decision based on actual cross-surface behavior, not aggregate test counts.

- [ ] **Step 1: Run all automated gates.**

  Run:

  ```powershell
  python -m pytest -q
  npm --prefix webui test -- --run
  npm --prefix webui run typecheck
  npm --prefix webui run build
  python -m pytest tests/core/test_packaging_entrypoints.py tests/core/test_package_contents.py -q
  ```

  Record exact pass/skip counts and the Windows symlink limitation.

- [ ] **Step 2: Run the real acceptance matrix.**

  Verify Desktop mutation → LAN → Browser, LAN mutation → Desktop, first
  runtime baseline, disconnect with missed revisions, LAN restart, same-root
  reopen, password/key/user/guest/share authorization, logout/401 identity
  teardown, preview/download/path guards, and session close with a connected
  WebSocket.

- [ ] **Step 3: Verify ownership and residue.**

  After each journey assert no old Runtime subscription, no active WebSocket,
  no lifecycle adapter, no live server thread, no operation on a closed
  session, no stale projection response and no wrong-library response.

- [ ] **Step 4: Write the closure report.**

  The report must state one of `delivered`, `conditionally ready` or `not
  ready`, list every unexecuted/manual gate, link the exact task evidence and
  update the historical migration report without overwriting the fact that
  earlier evidence was captured at a different HEAD.

- [ ] **Step 5: Run documentation verification.**

  Run `git diff --check` and verify every link/file cited by the updated
  reports, plans, ADR and architecture indexes exists. Do not create a commit
  unless the user separately authorizes it.

## Release Decision Rules

- `delivered`: all C1–C5 contracts and the full matrix have fresh evidence;
  no P0/P1 or security finding remains.
- `conditionally ready`: no P0/P1 remains, but a documented platform/manual
  gate is still unavailable and the release owner accepts that limitation.
- `not ready`: any P0/P1, security concern, incomplete lifecycle contract,
  stale identity projection, missing producer or unexecuted critical journey.
