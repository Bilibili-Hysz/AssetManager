---
feature: runtime-adapter-failure-ownership
status: delivered
specs:
  - docs/compose/specs/2026-07-21-runtime-event-router-design.md
  - docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-design.md
plans:
  - docs/compose/plans/2026-07-21-session-close-lan-websocket-regression.md
  - docs/compose/plans/2026-07-21-runtime-adapter-failure-ownership.md
branch: master
commits: uncommitted-workspace
---

# Runtime Adapter Failure Ownership — Final Report

## What Was Built

The canonical `LibraryRuntime` now owns LAN lifecycle adapters across successful operation, constructor failure, startup rollback, cancellation, concurrent stop, and session close. A LAN server enters the Runtime registry only after all five session-bound service providers and the aiohttp application have been constructed successfully. Terminal startup rollback releases ownership automatically; incomplete cleanup retains ownership and the original event loop so a later `stop()` can retry.

The real session-close regression uses an actual localhost TCP server and authenticated aiohttp WebSocket. It verifies that `LibraryService.close_session()` stops the server exactly once, closes connected clients, removes realtime subscriptions and lifecycle adapters, closes the session, and remains idempotent when called again.

## Architecture

`LibraryRuntime.register_lifecycle_adapter()` accepts adapters only while the Runtime is open. Registration during closing or after closure stops the late adapter synchronously outside the Runtime condition lock, preventing a cleanup-snapshot race. Runtime cleanup snapshots registered adapters, stops them, cleans the undo service, and restores an open/retryable state for any `BaseException` before propagating the original failure.

`_LanServerImpl` validates `metadata_service`, `project_service`, `tag_service`, `search_service`, and `thumbnail_service` against the canonical `LibrarySession.connection_for` provider before registration. A dedicated adapter lock protects the server-owned registration flag. Registration and unregistration callbacks execute outside that lock; callback failures restore the flag for retry.

The server worker treats startup exceptions, cancellation, and rollback failures as lifecycle state rather than thread-local accidents. Complete terminal cleanup closes the owner loop and unregisters the adapter. Incomplete cleanup keeps the worker and owner loop alive. Shared shutdown futures are not submitted twice, while failures discovered during `future.result()`—including a future's own `TimeoutError`—can trigger cleanup retry in the same `stop()` call.

### Design Decisions

- Adapter registration occurs at the constructor commit point because partially constructed servers must never become Runtime-owned resources.
- Server registration state uses a lock separate from the server lifecycle lock because a closed Runtime may synchronously call `server.stop()` from inside registration.
- Complete and incomplete startup rollback retain different ownership: complete cleanup unregisters; incomplete cleanup preserves the adapter and owner loop for retry.
- Runtime cleanup catches `BaseException` only to restore state and notify waiters, then re-raises unchanged so cancellation and process-control exceptions remain visible.

## Usage

No calling API changed. Desktop sharing continues to construct `LanServer(runtime=runtime)`, and library switching may explicitly stop sharing before closing the session. Direct session closure is also safe:

```python
session = bootstrap.library_service.open_session(root)
runtime = bootstrap.runtime_for(session)
server = LanServer(runtime=runtime)
server.start(port=0, bind="127.0.0.1")

bootstrap.library_service.close_session(session)
```

The final call stops the registered LAN server, closes WebSockets, releases realtime subscriptions, and cleans Runtime-owned services before database teardown.

## Verification

Fresh verification from the repository root:

| Gate | Result |
|---|---|
| Full LAN suite | **330 passed** |
| Runtime/Library integration and unit gate | **108 passed** |
| Real Chromium realtime acceptance | **4 passed** |
| Focused ownership final review | **268 passed**, no P0/P1/P2 findings |
| Ruff | **All checks passed** |
| `compileall` | **passed** |
| `git diff --check` | **passed**; existing Windows LF/CRLF warnings only |

The regression chain includes constructor failure for all five session-bound providers, repeated and concurrent stop, startup bind failure, startup `SystemExit`, rollback `BaseException`, startup cancellation cleanup failure, shared cleanup-future failure, future-owned `TimeoutError`, Runtime cleanup `BaseException`, late adapter registration during close, and a real TCP/WebSocket session-close path.

## Journey Log

- [dead end] A test-local pending-worker cache initially made the second `close_session()` assertion false because it reused the first completed result instead of executing again.
- [pivot] Runtime adapter registration moved from early construction to the constructor commit point after provider validation and application construction.
- [lesson] Cleanup-future ownership and cleanup-failure state are separate: a shared future must not be submitted twice, but its failure must still enable retry.
- [lesson] `Future.result(timeout=...)` may raise `TimeoutError` because the wait expired or because the completed operation itself raised `TimeoutError`; lifecycle code must distinguish them.
- [lesson] Catching `BaseException` in cleanup is safe only when state is restored and the original exception is re-raised unchanged.

## Source Materials

| File | Role | Notes |
|---|---|---|
| `docs/compose/plans/2026-07-21-session-close-lan-websocket-regression.md` | Real integration regression plan | Canonical session-close acceptance |
| `docs/compose/plans/2026-07-21-runtime-adapter-failure-ownership.md` | Ownership hardening plan | Constructor and startup failure boundaries |
| `AssetsManager/application/runtime.py` | Runtime owner | Registration state, cleanup retry, closing linearization |
| `AssetsManager/lan/server.py` | LAN adapter | Registration commit, startup rollback, stop retry |
| `tests/lan/test_runtime_realtime.py` | Real TCP/WebSocket regression | Session-close teardown and idempotency |
| `tests/lan/test_server_lifecycle.py` | Failure-state regressions | Startup, cancellation, shared future, timeout paths |
| `tests/lan/test_lan_api.py` | Constructor contracts | Five provider validations and registration ownership |
| `tests/unit/test_library_runtime.py` | Runtime lifecycle contracts | BaseException recovery and late registration |
