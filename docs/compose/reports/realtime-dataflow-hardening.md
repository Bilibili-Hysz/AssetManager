---
feature: realtime-dataflow-hardening
status: delivered
specs:
  - docs/compose/specs/2026-07-21-realtime-dataflow-hardening.md
plans:
  - docs/compose/plans/2026-07-21-realtime-dataflow-hardening.md
branch: master
commits: uncommitted-workspace
---

# Desktop–WebUI Realtime Dataflow Hardening — Final Report

## What Was Built

The Desktop → `LibraryRuntime` → LAN WebSocket → React projection recovery path is now hardened around the existing `epoch + revision` protocol. SQLite and the filesystem remain authoritative; realtime messages remain invalidation hints, and React refetches authoritative HTTP projections after accepted cursor transitions.

The LAN boundary now provides atomic WebSocket admission, live authorization revalidation, truthful server shutdown state, and one idempotent failed-socket eviction path. The browser acceptance harness verifies mutation refresh, revision-gap recovery, epoch replacement, cookie authentication boundaries, and teardown on the production SPA served by the real aiohttp/WebSocket stack.

## Architecture

`AssetsManager/lan/routes/websocket.py` sends the initial `runtime_ready` cursor before registration, then uses a manager admission barrier to reconcile a cursor change that occurs during registration. A client is only broadcast-eligible after the baseline succeeds. Each connection retains canonical principal authority and is revalidated at admission, authority transitions, and send/heartbeat boundaries; revocation routes through normal eviction and presence cleanup.

`AssetsManager/lan/ws.py` owns client admission, authority leases, bounded send/heartbeat operations, callback serialization, and idempotent `evict()`/`close_all()` teardown. Eviction removes clients and pong waiters, closes the transport, updates connection accounting, and invokes route-owned presence cleanup exactly once. Callback predecessors and reservation tails are shielded so follower cancellation cannot cancel shared lifecycle state.

`AssetsManager/lan/server.py` models startup, running, stopping, failed, and stopped states. `stop()` preserves actionable thread/loop references across shutdown and join timeouts, rejects restart while the old thread is alive, and clears references only after confirmed termination. Failed startup cleanup is retried on the owner loop, including the race where a future fails between reconciliation and `result()`; ordinary stop failures still propagate.

## Design Decisions

- WebSocket admission uses a two-cursor barrier because a handshake baseline alone cannot cover an invalidation emitted during registration.
- Authorization is tied to canonical authority leases rather than a one-time handshake result, so disable/delete/demotion/token revocation can close an active connection before another invalidation is delivered.
- Shutdown is treated as a two-phase lifecycle: publish failure or timeout truthfully first, then reconcile cleanup on the original owner thread before releasing references.
- Failed transport handling is centralized in one idempotent path so heartbeat, broadcast, and route `finally` cleanup cannot diverge in accounting or presence behavior.

## Usage

Run the focused hardening gate from the repository root:

```powershell
python -m pytest tests/lan/test_runtime_realtime.py tests/lan/test_public_contracts.py tests/lan/test_t2_t4_contracts.py tests/lan/test_role_permissions.py tests/unit/test_architecture_boundaries.py -q
python -m pytest tests/lan -q
python -m pytest tests/e2e/test_webui_realtime_acceptance.py -q
npm --prefix webui test -- --run
npm --prefix webui run typecheck
npm --prefix webui run build
```

WebSocket credentials must be supplied through the authenticated HttpOnly-cookie/session boundary. Query-string `token` and `key` credentials are rejected, and each principal must carry the explicit realtime capability.

## Verification

Fresh verification in this workspace:

| Gate | Result |
|---|---|
| Realtime/security/architecture Python gate | **134 passed** |
| Server lifecycle + LAN API suites | **207 passed** |
| Full LAN suite | **314 passed** |
| Chromium realtime acceptance | **4 passed** |
| React realtime projection subset | **4 files, 67 tests passed** |
| Full WebUI Vitest suite | **34 files, 256 tests passed** |
| WebUI typecheck | **passed** |
| WebUI production build | **passed**, 1626 modules transformed |
| Hardening-scoped Ruff | **All checks passed** |
| `git diff --check` | **passed** |
| Production forbidden-pattern scan | **no `DatabaseManager.current` fallback; one expected shared `useWebSocket` construction** |

The Chromium tests cover `test_browser_realtime_refreshes_after_desktop_mutation`, `test_real_lan_server_restarts_on_same_port`, `test_browser_recovers_revision_gap_after_websocket_disconnect`, and `test_browser_recovers_epoch_after_same_root_server_restart`. React Router v7 future-flag warnings remain non-failing test warnings. The Windows environment's directory-symlink limitation remains an existing documented platform gap where applicable.

## Journey Log

- [dead end] A completed failed startup-cleanup future could still be observed as pending and then raise from `result()` without a retry; a deterministic future double exposed the interleaving.
- [pivot] Cleanup retry was kept on the original owner loop and guarded by the startup-cleanup marker, preserving ordinary stop-failure propagation and preventing overlapping shutdown work.
- [lesson] `asyncio.CancelledError` and shared callback-tail futures require explicit cancellation-safe teardown; catching only `Exception` or directly awaiting a shared predecessor is insufficient.

## Source Materials

| File | Role | Notes |
|---|---|---|
| `docs/compose/specs/2026-07-21-realtime-dataflow-hardening.md` | Hardening specification | Atomic admission, revocation, shutdown, eviction, and gates |
| `docs/compose/plans/2026-07-21-realtime-dataflow-hardening.md` | Implementation plan | Five task boundaries and verification commands |
| `AssetsManager/lan/routes/websocket.py` | WebSocket route | Principal admission and runtime cursor barrier |
| `AssetsManager/lan/ws.py` | WebSocket manager | Authority leases, bounded delivery, eviction, teardown |
| `AssetsManager/lan/server.py` | LAN lifecycle | Shutdown truthfulness and owner-loop cleanup retry |
| `tests/lan/test_runtime_realtime.py` | Runtime realtime contracts | Admission, revocation, cursor, isolation, teardown |
| `tests/lan/test_server_lifecycle.py` | Server lifecycle contracts | Timeout, restart, owner-thread retry, idempotence |
| `tests/e2e/test_webui_realtime_acceptance.py` | Browser acceptance | Mutation, revision gap, epoch, same-port teardown |
