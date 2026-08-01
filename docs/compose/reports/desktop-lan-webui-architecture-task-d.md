---
feature: desktop-lan-webui-architecture-task-d
status: delivered
specs:
  - docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-recalibration-design.md
plans:
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-task-d.md
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md
branch: master
evidence_state: pre-baseline working tree; baseline captured in repository-baseline-2026-08-01.md
---

# Desktop–LAN–WebUI Architecture Task D — Final Report

## What Was Built

Task D removes the proven service-composition compatibility paths from the
Desktop/LAN architecture. `MainWindow` now resolves panel services through
`ApplicationBootstrap.runtime_for(session).services`, and library switching
uses the canonical `LibraryService.close_session(old_session)` lifecycle
boundary without a second cleanup call.

`ApplicationBootstrap.for_library()` and `ApplicationBootstrap.cleanup_library()`
are deleted. All affected Python fixtures and integration tests now use the
explicit Runtime/session contract. The provider error messages in
`MetadataService` and `TagService` now describe the required explicit
provider/connection inputs without advertising the removed API.

Task D does not remove `migrate_path_metadata_for_library()`: it still has a
real production caller in `FileOperationService`. It also does not change the
workspace tab `current_library()` UI state or the centralized realtime
transport. `RealtimeContext.tsx` remains the sole production consumer of
`WebSocketTransportHost`, which continues to own the `useWebSocket` connection
and fan-out boundary.

## Architecture

The canonical Desktop composition path is now:

```text
LibrarySession
  → ApplicationBootstrap.runtime_for(session)
  → LibraryRuntime.services
  → Desktop panels / LAN adapters
```

Session teardown remains owned by `LibraryService.close_session()`. The window
coordinator stops the LAN server and quiesces panel work before closing the old
session, then opens the replacement session and resolves its Runtime services.
There is no post-close bootstrap cleanup path that can duplicate or race the
Runtime lifecycle listeners.

Static architecture gates enforce the boundary across the codebase:

- no production `for_library()` or `cleanup_library()` definitions/calls;
- `window.py` contains the canonical `runtime_for(session)` composition call;
- page/component code does not consume WebSocket transport directly;
- `RealtimeContext.tsx` is the only production `WebSocketTransportHost`
  consumer;
- browser auth types/context/login code contain no bearer-token state or
  `setToken()` compatibility API;
- LAN route modules do not construct application services from raw connections;
- canonical Runtime, DTO and principal package contents remain present.

### Design Decisions

- We chose to remove `for_library()` instead of keeping it as a forwarding
  alias because it represented a second public composition vocabulary after
  Runtime ownership was established.
- We chose session close as the only Desktop teardown trigger because Runtime
  cleanup is already registered on the canonical session lifecycle and a
  second root-based cleanup call could duplicate ownership decisions.
- We retained `migrate_path_metadata_for_library()` because its current
  `FileOperationService` production caller proves it is not dead compatibility
  code yet.
- We retained the centralized WebSocket hook/host because it is active
  transport infrastructure, while static gates continue to forbid page-level
  raw WebSocket interpretation.

## Usage

Desktop callers that need library-scoped application services must hold the
canonical live session and use:

```python
runtime = bootstrap.runtime_for(session)
services = runtime.services
```

A closed, stale, reconstructed or foreign `LibrarySession` continues to be
rejected by `runtime_for()`. No migration-specific cleanup call is needed after
`library_service.close_session(session)`.

The focused Task D gate is:

```powershell
python -m pytest tests/unit/test_architecture_boundaries.py tests/core/test_package_contents.py tests/unit/test_bootstrap.py tests/unit/test_library_runtime.py tests/unit/test_window_session_switching.py tests/desktop/test_scoped_service_access.py tests/desktop/test_file_list_details.py tests/desktop/test_file_list_shim.py tests/integration/test_event_publishing.py tests/integration/test_file_operation_service.py tests/integration/test_library_service.py tests/integration/test_undo_service.py -q
npm --prefix webui test -- --run
npm --prefix webui run typecheck
npm --prefix webui run build
```

## Verification

Fresh evidence from the completed Task D pass:

| Gate | Result |
|---|---|
| Task D focused Python gate | `402 passed` |
| Python full suite | `1590 passed, 1 skipped` |
| WebUI full suite | `37 files / 289 tests passed` |
| WebUI typecheck | Passed |
| WebUI production build | Passed; `1632 modules transformed` |
| Production compatibility scan | No `for_library(` or `cleanup_library(` residue |
| Preserved migration helper | `migrate_path_metadata_for_library()` remains called by `FileOperationService` |
| Realtime transport boundary | `RealtimeContext.tsx` is the sole production `WebSocketTransportHost` consumer |
| Independent Task D review | No remaining code findings after documentation/static-gate fixes |

The single Python skip is the directory-symlink test, unavailable on Windows;
the corresponding Ubuntu WSL Linux gate passed with `1 passed, 23 deselected`.
At the Task D handoff, Task E's real-client cross-surface acceptance matrix was
still pending. It has since been executed on Windows and Ubuntu WSL; the
current overall result is recorded as `delivered` in the
[recalibration final report](desktop-lan-webui-architecture-recalibration.md).

## Journey Log

> Brief notes on what informed the final design.

- [pivot] The Desktop migration was implemented against `runtime_for(session)`
  directly, then the forwarding `for_library()` API was removed after all
  callers were migrated.
- [lesson] A broad text scan initially matched the intentionally retained
  `migrate_path_metadata_for_library()` helper; the final static gate uses a
  call-boundary pattern so it does not confuse distinct APIs.
- [lesson] The centralized WebSocket hook is still live infrastructure even
  though page-level transport access is forbidden; static gates must distinguish
  those two cases.
- [lesson] Compatibility removal is incomplete until the plan, parent status
  ledger and final report agree with the production scan.
- [lesson] A production residue scan is only a durable architecture gate when
  its file set covers the entire production package; the cleanup and forwarding
  API checks now share that package-wide scope.

## Source Materials

| File | Role | Notes |
|---|---|---|
| `docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-recalibration-design.md` | Architecture specification | Defines the canonical Runtime boundary and Task D scope. |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-task-d.md` | Task D plan | Detailed migration, static gates and verification steps. |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md` | Recalibration ledger | Task D handoff ledger; current Task E result is in the recalibration final report. |
| `AssetsManager/window.py` | Desktop composition | Resolves `runtime_for(session).services`. |
| `AssetsManager/window_lifecycle_coordinator.py` | Desktop lifecycle | Closes the old session without compatibility cleanup. |
| `AssetsManager/application/bootstrap.py` | Runtime owner | Removed `for_library()` and `cleanup_library()`. |
| `AssetsManager/application/metadata_service.py` | Provider contract | Uses explicit provider error wording. |
| `AssetsManager/application/tag_service.py` | Provider contract | Uses explicit connection/provider error wording. |
| `tests/unit/test_architecture_boundaries.py` | Static architecture gates | Enforces production-wide compatibility and transport boundaries. |
| `tests/unit/test_bootstrap.py` | Runtime cache regressions | Migrated to explicit Runtime access. |
| `tests/desktop/test_file_list_shim.py` | Desktop fixture regressions | Migrated all scoped service fixtures. |
| `scripts/check_package_contents.py` | Package boundary | Canonical SPA/runtime resources remain required. |

## Remaining Chain

Task D is delivered. At the Task D handoff, the overall Desktop–LAN–WebUI
recalibration remained `partial / not release-ready` pending Task E. The
subsequent Task E matrix and Ubuntu WSL directory-symlink result are recorded
in the [recalibration final report](desktop-lan-webui-architecture-recalibration.md);
the current overall decision is `delivered`.
