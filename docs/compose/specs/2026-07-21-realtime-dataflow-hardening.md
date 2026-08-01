# Desktop–WebUI Realtime Dataflow Hardening

> [!NOTE]
> **Scope status:** The named realtime hardening scope and its parent
> recalibrated Desktop–LAN–WebUI acceptance boundary are delivered.
> Product roadmap work remains separate and is tracked in the repository
> baseline and DeepSeek roadmap.

> [!NOTE]
> This design records the supplemental hardening scope identified by the dataflow audit. The implementation plan and final report are authoritative for the delivered state.

## [S1] Scope and invariants

Harden the existing Desktop → `LibraryRuntime` → LAN WebSocket → React projection recovery path without changing the authority model. SQLite and the filesystem remain authoritative; WebSocket messages remain invalidation hints containing `epoch`, `revision`, domains, and relative paths only. Desktop continues to call application services directly rather than using local HTTP.

The hardening must preserve session/root isolation, HttpOnly-cookie authentication, query-credential rejection for WebSockets, explicit principal capabilities, and the existing `epoch + revision` recovery protocol.

## [S2] Atomic WebSocket admission

A newly accepted WebSocket must receive a valid `runtime_ready` cursor before it becomes eligible for runtime invalidation broadcasts. The admission sequence must prevent a mutation from being delivered before the client has a baseline. If the baseline cannot be delivered, the socket must not remain an active broadcast client.

The implementation must include a deterministic test that places a runtime invalidation between the current implementation's registration and baseline-send boundary and proves the client receives a safe ordered protocol or is rejected/closed without receiving an unsafe early invalidation.

## [S3] Live authorization revocation

WebSocket authorization is not permanent solely because the handshake succeeded. Each connection must retain enough canonical identity to be revalidated or explicitly revoked when user activity, role, capability, or token validity changes. Revoked connections must stop receiving invalidations and be closed through the normal lifecycle cleanup path.

The implementation must cover disabled/deleted/demoted users or equivalent token revocation, and must not weaken the current handshake checks or permit query-string credentials.

## [S4] Shutdown state correctness

`LanServer.stop()` must distinguish confirmed termination from timeout/failure. It must not clear the actionable loop/thread references or report a stopped server while the server thread remains alive. Restart must be rejected or deferred while the previous server thread is still alive. Successful shutdown must remain idempotent.

Tests must retain the pre-stop thread reference and exercise both shutdown timeout and join timeout paths.

## [S5] Failed-socket lifecycle cleanup

Heartbeat and broadcast send failures must use one cleanup path that removes the socket, closes it, updates connection accounting, and allows the route's presence cleanup to run. `OnlineUsers` and server connection counts must not retain failed clients.

Tests must cover both heartbeat eviction and broadcast-send eviction, including connection count and presence cleanup, while preserving healthy-client delivery.

## [S6] Verification gates

Each task must use TDD and pass its focused tests before the next task begins. The final hardening gate must pass the LAN realtime/public-contract/security suites, React realtime tests, WebUI typecheck/build, and real Chromium acceptance for mutation, reconnect, revision gap, epoch replacement, authentication, and teardown. Existing Windows-only symlink skips and React Router warnings must remain explicitly documented rather than treated as failures.
