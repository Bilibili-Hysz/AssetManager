---
feature: desktop-lan-webui-architecture-task-a
status: delivered
specs:
  - docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-recalibration-design.md
plans:
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md
branch: master
evidence_state: pre-baseline working tree; baseline captured in repository-baseline-2026-08-01.md
---

# Desktop–LAN–WebUI Task A — Final Report

## What Was Built

Task A closes the canonical Desktop–LAN lifecycle boundary for a live
`LibrarySession`. Runtime lifecycle adapters are stopped during session
pre-close while the session and its database connection are still usable.
Existing operation leases then drain, Runtime-owned cleanup completes, and only
successful teardown releases session cache ownership and closes the per-library
database connection.

Adapter stop, server stop, Runtime post-close cleanup and global session-close
failures retain the Runtime/session/database ownership needed for an explicit
retry. Successful close remains idempotent and does not replay pre-close
listeners.

LAN server generations no longer register during construction. A generation is
registered after its site has started and before startup success is published;
confirmed stop unregisters it exactly once. Registration and unregistration
callbacks are serialized, run outside the server lifecycle lock, and cannot
leave a stale adapter when stop races with registration. `ShareManager.stop()`
propagates server-stop failures and retains the failed server handle.

## Architecture

The implemented close path is:

```text
LibrarySession._begin_close()
  → Runtime.mark_closing() / Runtime.close_adapters()
  → drain existing session.operation() leases
  → LibrarySession._finish_close()
  → Runtime.close() post-close cleanup
  → DatabaseManager.close_library()
  → remove session and Runtime cache ownership
```

`LibraryRuntime.close_adapters()` owns adapter-stop serialization and retry
state. `LibraryRuntime.close()` reuses that state and performs undo-service
cleanup without double-stopping an adapter already stopped during pre-close. If
later cleanup fails, the adapter list and Runtime ownership stay available for
retry.

`_LanServerImpl` uses explicit registration state (`unregistered`, `registering`,
`registered`, `unregistering`) guarded by a condition. External Runtime
callbacks are not invoked while the server lifecycle lock is held.

## Design Decisions

- Runtime adapter shutdown happens before session cache and DB release because
  LAN teardown may still need the live session connection.
- Post-close cleanup failures retain ownership because losing the retry handle
  would turn a recoverable stop failure into leaked or orphaned resources.
- Startup registration occurs after the listening site is ready but before the
  generation advertises startup success; this prevents clients from observing a
  generation that Runtime cannot close.
- WebSocket and Runtime event behavior remains unchanged; Task A modifies
  ownership and teardown boundaries, not business-event transport.

## Verification

Fresh verification after the final Task A changes:

| Gate | Result |
|---|---|
| Task A focused suites | `210 passed` |
| Python full suite | `1590 passed, 1 skipped` |
| Real LAN close-session/WebSocket teardown | `3 passed` |
| Startup rollback repeated three times | `3 passed` |
| Python compilation | Passed via `python -m compileall -q AssetsManager` |
| Diff formatting | Passed via `git diff --check`; Git emitted only existing LF/CRLF warnings |

The one skipped Python test requires directory symlinks unavailable on
Windows. It remains a Linux CI/platform gate and is not counted as a passing
cross-platform release result.

The overall recalibration chain remains `partial / not release-ready`: Tasks B
and C are delivered, while Tasks D–E still cover fallback removal and the
final cross-surface acceptance matrix. See the current parent migration report
and [Task C final report](desktop-lan-webui-architecture-task-c.md) for the
latest chain state.

## Journey Log

- [dead end] The first red ordering test showed the existing sequence was
  `finish → adapter → DB`, proving the post-close listener was still the first
  real adapter-stop boundary.
- [pivot] Cleanup retention was extended from adapter stop failures to Runtime
  post-close failures after a red test showed DB/session ownership was being
  released while Runtime cleanup had failed.
- [lesson] Startup registration callbacks must run outside the server lifecycle
  lock; a deterministic callback re-acquisition test exposed the deadlock.
- [lesson] Aggregate green tests were insufficient; the final gate included
  repeated startup rollback, real WebSocket teardown and concurrent close tests.

## Source Materials

| File | Role |
|---|---|
| `docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-recalibration-design.md` | Recalibrated architecture scope and contracts |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md` | Authoritative A–E task chain; Task A is complete |
| `docs/archive/2026-09/compose-reports/desktop-lan-webui-architecture-migration.md` | Parent migration status and remaining release decision |
| `AssetsManager/application/library_service.py` | Session close barrier and ownership retention |
| `AssetsManager/application/runtime.py` | Runtime adapter stop state and retry behavior |
| `AssetsManager/lan/server.py` | LAN generation registration and shutdown ownership |
| `tests/unit/test_library_runtime.py` | Deterministic Runtime/session regression coverage |
| `tests/lan/test_server_lifecycle.py` | Deterministic LAN generation and startup/stop coverage |
