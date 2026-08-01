# Desktop–LAN–WebUI Architecture Recalibration Implementation Plan

> [!NOTE]
> This document may not reflect the current implementation.
> See the [recalibration final report](../reports/desktop-lan-webui-architecture-recalibration.md)
> for the Task E evidence and current release decision. Tasks A–E have been
> executed; the decision is `delivered` after the Linux directory-symlink
> platform gate passed in Ubuntu WSL.

> [!NOTE]
> Task A is delivered. See the [Task A report](../reports/desktop-lan-webui-architecture-task-a.md)
> for the implemented lifecycle state and verification evidence. Tasks B and C
> are delivered. Task E has now been executed; see the recalibration final
> report for the delivered release decision and platform evidence.

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish only the architecture-closure work that remains after the original Desktop–LAN–WebUI migration and its realtime hardening have been re-audited against the current code.

**Architecture:** Preserve one canonical `LibrarySession → LibraryRuntime → LAN/React adapters` spine. The new chain first fixes truthful Runtime/session teardown and LAN server-generation ownership, then removes browser bearer-token state and clears identity-scoped projections, then makes every advertised invalidation domain producer-backed, and finally removes compatibility paths and runs the complete acceptance matrix.

**Tech Stack:** Python 3, threading, asyncio, aiohttp, SQLite, pytest, React 18, TypeScript, Vitest, Chromium acceptance harness.

## Global Constraints

- SQLite and the filesystem remain authoritative; WebSocket messages remain invalidation hints only.
- Business transactions must not depend on WebSocket delivery success.
- `ApplicationBootstrap.runtime_for(session)` remains the only production Runtime composition boundary.
- Browser authentication uses same-origin HttpOnly cookies; JavaScript must not receive or store bearer tokens.
- Do not repeat already-delivered realtime hardening for admission, authority revocation, failed-socket eviction, server shutdown state, or constructor/startup rollback except where a new cross-surface regression requires it.
- Do not introduce a second service assembly path, persistent revision store, microservice, Redis, Kafka, React Query migration or WebSocket business-object transport.
- UI product gaps unrelated to architecture closure stay out of this plan.
- Every implementation task starts with a focused failing regression and ends with a focused gate.
- Preserve unrelated working-tree changes; do not commit without explicit authorization.

## Current baseline and historical mapping

The final Windows baseline after Task E is `1568 passed, 1 skipped` for Python,
`37 files / 286 tests passed` for WebUI, and `210 passed` in the final Task A
Runtime/LAN lifecycle focus. One earlier combined invocation exposed a flaky
startup rollback thread assertion; run lifecycle gates serially and retain the
regression until it is deterministic. The Task E cross-surface focused slice is
`186 passed`; the one Python skip is the Windows directory-symlink case, and
the corresponding Ubuntu WSL Linux gate passed with `1 passed, 23 deselected`.

The original migration Task 1–4 foundations and most of Tasks 9–14 are
evidence-only prerequisites. Original Tasks 5, 6, 7, 8, 12, 13, 15 and 17
have remaining evidence or acceptance represented by the tasks below. Original
Task 16 is delivered for the current Task D scope: its bootstrap compatibility
removal and architecture gates are complete. The previous closure plan
`2026-07-21-desktop-lan-webui-architecture-closure.md` is historical and must
not be executed in parallel with this plan.

## File responsibility map

- `AssetsManager/application/library_service.py`, `context.py`: pre-close session barrier, lease drain and DB release order.
- `AssetsManager/application/bootstrap.py`, `runtime.py`: Runtime adapter cleanup, cache removal and failure retry ownership.
- `AssetsManager/lan/server.py`, `lan/manager.py`: successful server-generation registration and failed-stop retention.
- `AssetsManager/lan/routes/auth.py`, `lan/dto.py`: token-free authentication response contract.
- `webui/src/stores/AuthContext.tsx`, `pages/LoginPage.tsx`, `App.tsx`: cookie-only identity and protected route lifecycle.
- `webui/src/stores/RealtimeContext.tsx`, `hooks/useSearch.ts`: cursor reset and active-search invalidation.
- `AssetsManager/domain/events.py`, `application/runtime_events.py`, share/auth services and LAN routes: producer-backed invalidation domains.
- `webui/src/components/admin/InviteManagement.tsx`, `ShareManagement.tsx`, `UserManagement.tsx`, `ActivityLog.tsx`, `OnlineUsers.tsx`, `StatusBar.tsx`: canonical projection consumers.
- `tests/unit/test_library_runtime.py`, `tests/integration/test_library_service.py`, `tests/lan/test_server_lifecycle.py`, `tests/lan/test_runtime_realtime.py`: lifecycle and protocol evidence.
- `webui/src/stores/AuthContext.test.tsx`, `RealtimeContext.test.tsx`, `pages/LoginPage.test.tsx`, `pages/BrowsePage.test.tsx`, `pages/DetailPage.test.tsx`, admin/search tests: browser identity and projection evidence.

## Execution order

`Task A → Task B → Task C → Task D → Task E`.

Task A owns all Python lifecycle changes. Task B consumes stable Runtime/server
identity and owns browser credential/route teardown. Task C consumes the
identity and invalidation contracts and owns producer/projection consistency.
Task D removes compatibility paths only after A–C are green. Task E is the
release evidence gate and may not be used to paper over an open P1.

---

### Task A: Close the canonical session and LAN generation boundary

**Covers:** [S3] Target ownership and state contracts; original Tasks 6–8 and 11.

**Files:**
- Modify: `AssetsManager/application/library_service.py`
- Modify: `AssetsManager/application/bootstrap.py`
- Modify: `AssetsManager/application/runtime.py`
- Modify: `AssetsManager/application/context.py` only when the internal close barrier needs a narrow hook
- Modify: `AssetsManager/lan/server.py`
- Modify: `AssetsManager/lan/manager.py`
- Test: `tests/unit/test_library_runtime.py`
- Test: `tests/integration/test_library_service.py`
- Test: `tests/integration/test_window_lifecycle_lan_failure.py`
- Test: `tests/lan/test_server_lifecycle.py`
- Test: `tests/unit/test_lan_sharing.py`

**Interfaces:**
- Consumes: `LibraryService.add_session_closing_listener()`, `LibraryRuntime.register_lifecycle_adapter()`, `LibraryRuntime.unregister_lifecycle_adapter()`, `LanServer.start()`, `LanServer.stop()`.
- Produces: `LibraryService.close_session()` with adapter-before-session/DB ordering; one Runtime registration per successful server generation; retryable failed stop state.

  - [x] **Step 1: Add a deterministic pre-close ordering regression.**

  Register a fake Runtime adapter and a fake DB close callback. Hold one
  `LibrarySession.operation()` lease, begin `close_session()` on another
  thread, and record events. Assert this exact order:

  ```text
  session._begin_close
  adapter.stop
  existing lease release
  session._finish_close/cache clear
  session_closed listener
  db.close_library
  ```

  Also assert a new operation fails after `_begin_close()` and no adapter can
  call `session.connection_for()` after DB close.

  - [x] **Step 2: Add cleanup-failure retention and retry tests.**

  Make `adapter.stop()` fail once. Assert `close_session()` raises, the
  Runtime remains associated with the session, the adapter/server handle is
  still actionable, and `close_library()` has not been called. Make the second
  stop succeed, call close again, and assert DB close happens exactly once.

  - [x] **Step 3: Implement an explicit Runtime pre-close operation.**

  Add the smallest internal method needed to distinguish “reject new Runtime
  work” from “stop external adapters”, for example:

  ```python
  def close_adapters(self) -> None:
      self.event_router.close()
      self._cleanup_adapters()
  ```

  Call it from the session-closing path while the session is still live; do
  not rely on the post-close listener as the first adapter-stop boundary.
  Preserve the original exception and keep Runtime ownership when cleanup is
  incomplete. The post-close listener may only finalize cache removal after
  successful pre-close cleanup.

  - [x] **Step 4: Add server-generation ownership tests.**

  On one live Runtime execute `construct → start → stop → start`, assert one
  registration after each successful start and zero after confirmed stop. Then
  close the canonical session without manually stopping the server and assert
  the second generation is stopped. Add a failed `ShareManager.stop()` fake:
  first stop raises, the same `_server` handle remains available, second stop
  succeeds, and no overlapping server is created.

  - [x] **Step 5: Implement generation re-registration and failed-stop retention.**

  Register a server generation only after `start()` publishes success. On
  confirmed stop unregister exactly that generation. In `ShareManager.stop()`
  retain `_server` and an actionable failed state when stop raises; do not
  publish a clean stopped state or discard the retry handle.

  - [x] **Step 6: Run the serial lifecycle gate.**

  Run:

  ```powershell
  python -m pytest tests/unit/test_library_runtime.py tests/integration/test_library_service.py tests/integration/test_window_lifecycle_lan_failure.py -q
  python -m pytest tests/lan/test_server_lifecycle.py tests/unit/test_lan_sharing.py -q
  ```

  Expected: zero failures in both serial invocations; the startup rollback
  thread regression is deterministic and no live server/adapter survives a
  successful session close.

---

### Task B: Enforce cookie-only identity and protected projection teardown

**Covers:** [S4] Identity and projection contracts; original Task 5 and Task 12.

**Files:**
- Modify: `AssetsManager/lan/routes/auth.py`
- Modify: `AssetsManager/lan/dto.py`
- Modify: `webui/src/types/api.ts`
- Modify: `webui/src/stores/AuthContext.tsx`
- Modify: `webui/src/pages/LoginPage.tsx`
- Modify: `webui/src/App.tsx`
- Modify: `webui/src/stores/RealtimeContext.tsx`
- Modify: `webui/src/pages/BrowsePage.tsx`
- Modify: `webui/src/pages/DetailPage.tsx`
- Create: `webui/src/components/auth/ProtectedRoute.tsx`
- Test: `tests/lan/test_lan_api.py`
- Test: `tests/lan/test_t2_t4_contracts.py`
- Modify: `webui/src/stores/AuthContext.test.tsx`
- Modify: `webui/src/pages/LoginPage.test.tsx`
- Modify: `webui/src/pages/BrowsePage.test.tsx`
- Modify: `webui/src/pages/DetailPage.test.tsx`
- Create: `webui/src/components/auth/ProtectedRoute.test.tsx`

**Interfaces:**
- Consumes: `SessionPrincipal`, `Capabilities`, `fetch(..., { credentials: 'same-origin' })`.
- Produces: `LoginResponse` and `RegisterResponse` without `token`; `AuthContext` without token state; one capability-aware `/browse`/`/detail` guard; identity generation reset for RealtimeProvider and protected projections.

- [x] **Step 1: Write red token-free contract tests.**

  Assert user login, password login, registration and key verification
  responses contain no `token` field, while `Set-Cookie` still contains the
  HttpOnly `lan_token`. Assert `/auth/me` returns the principal used by the
  client. Update the TypeScript response types and fixtures in the test first
  so existing `setToken` calls fail.

- [x] **Step 2: Write red route/identity teardown tests.**

  Add `ProtectedRoute.test.tsx` covering guest redirect, missing `browse`
  capability, and authenticated access. Extend AuthContext tests so logout and
  `onUnauthorized` increment an identity generation, clear principal data and
  remount transport. Extend Browse/Detail tests so a stale response from the
  previous generation cannot restore list, detail or selection state.

- [x] **Step 3: Implement cookie-only auth.**

  Change login/register/key routes to set the cookie and return only a minimal
  success/principal response. Remove `token` from `LoginResponse`/
  `RegisterResponse`, remove `token` state and `setToken()` from production
  AuthContext, and make LoginPage call `refreshMe()` before navigation.
  Preserve share tokens and server-side cookie verification; this task only
  removes browser-visible server-auth bearer fields.

- [x] **Step 4: Implement one protected route and identity reset boundary.**

  Mount `ProtectedRoute` around `/browse` and `/detail`. Keep `/`, `/login`
  and `/s/:shareId` outside it. On identity generation change, clear route
  projection state and make `RealtimeProvider` start with `{ epoch: '',
  revision: 0 }`; the first valid `runtime_ready` must invoke exactly one
  authoritative `/api/revision` recovery/fan-out cycle.

- [x] **Step 5: Run the identity gate.**

  Run:

  ```powershell
  python -m pytest tests/lan/test_lan_api.py::test_task4_auth_me_exposes_unified_principal_for_all_kinds tests/lan/test_lan_api.py::test_auth_register_route_returns_user_token tests/lan/test_t2_t4_contracts.py::test_auth_cookie_is_httponly -q
  npm --prefix webui test -- --run src/stores/AuthContext.test.tsx src/pages/LoginPage.test.tsx src/components/auth/ProtectedRoute.test.tsx src/pages/BrowsePage.test.tsx src/pages/DetailPage.test.tsx src/stores/RealtimeContext.test.tsx
  npm --prefix webui run typecheck
  ```

  Actual: no JavaScript-visible server bearer token; protected projections
  disappear on logout/401 and stale refresh responses; first empty-cursor ready
  performs one recovery. The focused gate passed with `74 passed`, and the
  full WebUI suite passed with `35 files / 267 tests passed`.

---

### Task C: Make invalidation domains producer-backed and projections canonical

**Covers:** [S4] Identity and projection contracts; original Tasks 9, 13 and 15.

**Files:**
- Modify: `AssetsManager/domain/events.py`
- Modify: `AssetsManager/application/runtime_events.py`
- Modify: `AssetsManager/application/auth_service.py`
- Modify: `AssetsManager/application/share_service.py`
- Modify: `AssetsManager/lan/routes/users.py`
- Modify: `AssetsManager/lan/routes/shares.py`
- Modify: `webui/src/hooks/useSearch.ts`
- Modify: `webui/src/components/admin/InviteManagement.tsx`
- Modify: `webui/src/components/admin/ShareManagement.tsx`
- Modify: `webui/src/components/admin/UserManagement.tsx`
- Modify: `webui/src/components/admin/ActivityLog.tsx`
- Modify: `webui/src/components/admin/OnlineUsers.tsx`
- Modify: `webui/src/components/layout/StatusBar.tsx` only if stats availability needs a contract change
- Test: `tests/integration/test_runtime_events.py`
- Test: `tests/lan/test_runtime_realtime.py`
- Modify: `webui/src/hooks/useSearch.test.tsx`
- Modify: `webui/src/components/admin/AdminManagement.test.tsx`
- Create or modify: `webui/src/components/admin/ShareManagement.test.tsx`
- Create or modify: `webui/src/components/admin/InviteManagement.test.tsx`
- Modify: `webui/src/components/admin/ActivityLog.test.tsx`
- Modify: `webui/src/components/admin/OnlineUsers.test.tsx`

**Interfaces:**
- Consumes: `EventBus.publish(DomainEvent)`, `RuntimeEventRouter.EVENT_DOMAINS`, existing HTTP list/activity/online/stats APIs.
- Produces: session-scoped share/user/invite invalidations only after successful mutation; active search/share/invite/admin consumers refetch authoritative HTTP snapshots; stats is measured or explicitly unavailable.

- [x] **Step 1: Add red producer mapping tests.**

  Define immutable event records carrying `library_root` and `session_token`
  for share, user/invite, activity and online-presence mutations. Publish
  each after its state mutation succeeds, subscribe through a Runtime router,
  and assert the expected projection domain. Publish the same event with
  another token/root and assert no invalidation. Assert failed repository
  operations publish no event.

- [x] **Step 2: Choose and test the stats contract.**

  If request/connection/activity metrics have reliable producers, add the
  corresponding session-safe `stats` invalidation and assert measured values.
  If a metric has no producer, change its DTO/UI representation to `null` or
  “unavailable” and add a regression preventing a fabricated zero. Do not add
  a synthetic timer-only event source.

- [x] **Step 3: Implement Runtime mappings and route producers.**

  Extend `ProjectionDomain` and `EVENT_DOMAINS` only for domains with a real
  event producer. Publish events after successful share create/delete/download
  counter mutation, invite/user mutation, activity-log mutation and visible
  online-presence mutation, preserving the rule that notification failure
  cannot roll back the business transaction.

- [x] **Step 4: Replace local projection synthesis with refetch.**

  In `useSearch`, refetch the active query on `files`/`metadata` invalidation
  using its existing generation guard. In InviteManagement,
  ShareManagement and UserManagement, refetch canonical lists after local
  mutations and matching remote invalidations instead of synthesizing or
  patching rows. ActivityLog and OnlineUsers consume their dedicated
  producer-backed domains. All five admin projections clear their snapshots
  and invalidate in-flight requests when `identityGeneration` changes. Keep
  invalidation registrations limited to the domains each projection consumes.

- [x] **Step 5: Run the producer/projection gate.**

  Run:

  ```powershell
  python -m pytest tests/integration/test_runtime_events.py tests/lan/test_runtime_realtime.py -q
  npm --prefix webui test -- --run src/hooks/useSearch.test.tsx src/components/admin/AdminManagement.test.tsx src/components/admin/ShareManagement.test.tsx src/components/admin/ActivityLog.test.tsx src/components/admin/OnlineUsers.test.tsx
  npm --prefix webui run typecheck
  ```

  Actual final evidence: the Task C backend/router/public-contract gate passed
  with `77 passed`; the focused WebUI search/admin/stats gate passed with
  `7 files / 35 tests passed`; WebUI typecheck and production build passed
  with `1632 modules transformed`; measured stats kept unavailable bytes
  explicit as `null`/`Unavailable`. The full Python suite passed with
  `1555 passed, 1 skipped`; the full WebUI suite passed with
  `37 files / 286 tests passed`. The one Python skip is the Windows directory
  symlink case.

---

### Task D: Remove only proven migration fallbacks

**Covers:** [S5] Scope and non-goals; original Tasks 7, 8 and 16.

**Files:**
- Modify: `AssetsManager/window.py`
- Modify: `AssetsManager/window_lifecycle_coordinator.py`
- Modify: `AssetsManager/application/bootstrap.py`
- Modify: `AssetsManager/application/library_service.py`
- Modify: `AssetsManager/application/metadata_service.py`
- Modify: `AssetsManager/application/tag_service.py`
- Modify: `AssetsManager/core/database.py` only if the root-based metadata wrapper has no production caller
- Modify: `webui/src/hooks/useWebSocket.ts`
- Modify: `webui/src/types/api.ts`
- Modify: `tests/unit/test_architecture_boundaries.py`
- Modify: `tests/core/test_package_contents.py`
- Modify: `scripts/check_package_contents.py`
- Test: `tests/unit/test_bootstrap.py`
- Test: `tests/unit/test_window_session_switching.py`

**Interfaces:**
- Consumes: stable Runtime lifecycle, cookie-only auth and producer-backed projections from Tasks A–C.
- Produces: explicit Desktop `runtime_for(session)` consumption, no production `cleanup_library()` call, no browser token compatibility and no unused page-level transport bridge.

- [x] **Step 1: Add static gates before deleting paths.**

  Add architecture assertions for these exact production patterns:

  ```text
  window.py: ApplicationBootstrap.runtime_for(session)
  window_lifecycle_coordinator.py: no bootstrap.cleanup_library(...)
  webui AuthContext/LoginPage/api types: no token response/state/setToken
  pages/components: no direct raw WebSocket event interpretation
  LAN routes: no raw-connection application-service construction
  ```

  Run the gates and confirm they fail only on the callers being migrated.

- [x] **Step 2: Migrate the verified Desktop callers.**

  Change `MainWindow._scoped_services_for_session()` to resolve
  `runtime = bootstrap.runtime_for(session)` and pass `runtime.services`.
  Remove the `cleanup_library()` call from library switching only after Task A
  proves post-close Runtime cache removal. Preserve explicit session close as
  the sole lifecycle trigger.

- [x] **Step 3: Delete dead compatibility contracts.**

  Remove `setToken`/token fields and any now-unused standalone transport bridge
  only after Task B consumers are migrated. Remove root/current-library
  wrappers only when `rg` shows no production callers and the test fixtures use
  explicit Runtime/session objects. Do not delete legacy domain events still
  consumed by Desktop panels.

- [x] **Step 4: Verify package and boundary closure.**

  Run:

  ```powershell
  python -m pytest tests/unit/test_architecture_boundaries.py tests/core/test_package_contents.py tests/unit/test_bootstrap.py tests/unit/test_window_session_switching.py -q
  npm --prefix webui test -- --run
  npm --prefix webui run typecheck
  npm --prefix webui run build
  ```

  Expected: no unapproved fallback production matches and packaging still
  contains the canonical Runtime/DTO/principal modules.

  Actual: Task D focused Python gate `402 passed`; full Python suite
  `1564 passed, 1 skipped`; full WebUI suite `37 files / 286 tests passed`;
  WebUI typecheck and build passed with `1632 modules transformed`. The only
  Python skip is the Windows directory-symlink case. Production scans contain
  no `for_library(` or `cleanup_library(` residue; the intentionally retained
  `migrate_path_metadata_for_library()` helper remains called by
  `FileOperationService`.

---

### Task E: Run the recalibrated cross-surface release gate

**Covers:** [S1] Current baseline and decision, [S6] Completion rule; original Tasks 14 and 17.

**Files:**
- Modify: `tests/e2e/test_webui_realtime_acceptance.py`
- Modify: `tests/lan/test_runtime_realtime.py`
- Modify: `tests/lan/test_server_lifecycle.py`
- Create: `tests/e2e/test_webui_identity_acceptance.py` only if the existing harness cannot express cookie/logout/401 transitions
- Update: `docs/architecture.md`
- Update: `docs/architecture-diagram.md`
- Update: `docs/adr/0003-library-runtime.md`
- Update: `docs/compose/reports/desktop-lan-webui-architecture-migration.md`
- Create: `docs/compose/reports/desktop-lan-webui-architecture-recalibration.md`

**Interfaces:**
- Consumes: Tasks A–D and the existing hardening evidence.
- Produces: one current release decision with exact automated, browser and platform evidence.

- [x] **Step 1: Run gates serially and record the baseline.**

  Run:

  ```powershell
  python -m pytest -q
  npm --prefix webui test -- --run
  npm --prefix webui run typecheck
  npm --prefix webui run build
  python -m pytest tests/core/test_packaging_entrypoints.py tests/core/test_package_contents.py -q
  ```

  Actual: Python `1568 passed, 1 skipped`; WebUI `37 files / 286 tests`;
  typecheck passed; build passed with `1632 modules transformed`; packaging
  gates `8 passed`. The skip is the Windows directory-symlink case. No
  standalone flaky startup rollback was reproduced in the serial Task E run.

- [x] **Step 2: Execute the real matrix.**

  Verify: Desktop mutation → LAN → Browser; LAN mutation → Desktop;
  first-runtime baseline; disconnect with missed revisions; same-port LAN
  restart; same-root reopen; password/key/user/guest/share authorization;
  logout/401 identity teardown; preview/download/path guards; failed-stop
  retry; and session close with a connected WebSocket.

  Actual: the focused cross-surface slice passed with `186 passed`. Chromium
  covered mutation refresh, revision-gap recovery, same-port restart,
  same-root epoch replacement, logout and 401 teardown. Desktop covered real
  LAN tag mutation and same-session filesystem-event refresh. LAN contract
  coverage passed for password, key, user, guest and share authorization,
  preview/download/path guards and failed-stop/session-close lifecycle.

- [x] **Step 3: Assert residue and isolation.**

  After each journey assert no stale Runtime subscription, no active WebSocket,
  no registered adapter after confirmed close, no live server thread, no
  operation on a closed session, no stale previous-identity response and no
  wrong-library invalidation.

  Actual: the focused acceptance tests assert Runtime subscriptions, EventBus
  handlers, lifecycle adapters, WebSocket clients, server threads,
  closed-session behavior, stale identity suppression and session-filtered
  Desktop invalidation.

- [x] **Step 4: Publish the recalibration report.**

  Write `docs/compose/reports/desktop-lan-webui-architecture-recalibration.md`
  with the final task mapping, exact commands/results, remaining platform
  limitations and one decision: `delivered`, `conditionally ready` or `not
  ready`. Actual: [`desktop-lan-webui-architecture-recalibration.md`](../reports/desktop-lan-webui-architecture-recalibration.md)
  records `delivered` after the Ubuntu WSL Linux directory-symlink gate passed.
  The parent migration report points to this report as the current release
  ledger.

- [x] **Step 5: Verify documentation and stop.**

  Run `git diff --check`, resolve every relative documentation link, scan for
  stale “Phase 5 complete” claims, and leave all unrelated user changes
  untouched. Actual: documentation links and stale release claims were
  reconciled; no commit was created.

## Release decision rules

- `delivered`: Tasks A–E have fresh evidence, no P0/P1/security finding remains and the full matrix passes.
- `conditionally ready`: no P0/P1/security finding remains, but a documented platform/manual gate is unavailable and the release owner explicitly accepts it.
- `not ready`: any P0/P1/security concern, missing producer, stale identity projection, unowned adapter, or unexecuted critical journey remains.
