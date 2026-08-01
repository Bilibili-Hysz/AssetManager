---
feature: desktop-lan-webui-architecture-migration
status: delivered
specs:
  - docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-design.md
  - docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-closure-design.md
plans:
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-migration.md
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-closure.md
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-task-d.md
branch: master
commits: 77492fe2b3ee9e4bb26e17b982d421993d545136, 945fd1e51a85ce2384f277c1bb9e89396b8fbe7d
evidence_state: tested against the then-current working tree; product baseline captured separately
---

# Desktop–LAN–WebUI Architecture Migration — Final Report (Current State)

## Current decision

The migration is **delivered**. Tasks A, B, C,
D and E of the recalibrated closure chain have executable evidence. The core
Runtime, DTO, principal/capabilities, session-filtered invalidation and React
realtime foundations are present. Supplemental realtime-hardening and Runtime
adapter-ownership work also delivered meaningful subcontracts. The Windows
cross-surface matrix now passes, and the required Linux directory-symlink
platform gate has also passed in Ubuntu WSL with isolated test data.

The completed Task A gate is `210 passed`; the Task B focused WebUI gate is
`74 passed`; the Task C producer/router gate is `77 passed` and its focused
WebUI gate is `7 files / 35 tests passed`; the latest Python full suite is
`1590 passed, 1 skipped`, and the WebUI full suite is `37 files / 289 tests
passed`. Task D's focused Python gate is `402 passed`. Startup rollback passes
repeatedly, and the real
LAN/WebSocket close-session and window stop-failure journeys pass. The one
skip is expected on Windows; the corresponding Ubuntu WSL Linux gate passed
with `1 passed, 23 deselected`.

This report is the current source of truth for the original migration. The
checkboxes in the original plan and the previous closure plan are historical
traceability material. Use the recalibrated plan for executable next work:

- [`2026-07-21-desktop-lan-webui-architecture-closure.md`](../plans/2026-07-21-desktop-lan-webui-architecture-closure.md) (historical)
- [`2026-07-21-desktop-lan-webui-architecture-closure-design.md`](../specs/2026-07-21-desktop-lan-webui-architecture-closure-design.md) (historical)
- [`desktop-lan-webui-architecture-task-a.md`](desktop-lan-webui-architecture-task-a.md)
- [`desktop-lan-webui-architecture-task-b.md`](desktop-lan-webui-architecture-task-b.md)
- [`2026-07-21-desktop-lan-webui-architecture-recalibration.md`](../plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md)
- [`2026-07-21-desktop-lan-webui-architecture-recalibration-design.md`](../specs/2026-07-21-desktop-lan-webui-architecture-recalibration-design.md)
- [`desktop-lan-webui-architecture-recalibration.md`](desktop-lan-webui-architecture-recalibration.md)

## What Was Built

- `ApplicationBootstrap.runtime_for(session)` caches one `LibraryRuntime` for
  the exact canonical live `LibrarySession`; the Runtime owns the eager
  library-scoped service bundle and event router.
- LAN production composition receives the Runtime and validates service
  providers against the Runtime session. Route helpers no longer build a
  second application-service graph from a raw connection on the primary path.
- Public DTOs normalize repository fields, and request identity is represented
  by `SessionPrincipal` plus server-provided `Capabilities`.
- `RuntimeEventRouter` filters by session token and resolved library root,
  increments an in-memory `epoch + revision` cursor and emits invalidation
  hints rather than business objects.
- The LAN/WebSocket path has authority revalidation, cursor reconciliation,
  heartbeat/broadcast eviction, connection accounting and shutdown hardening.
- React has one `RealtimeProvider`, a domain registration hook, generation-safe
  recovery and HTTP snapshot refetch behavior for revision gaps and epoch
  changes. Main Browse, Sidebar, Landing, Detail and admin consumers use the
  provider boundary.
- Metrics now expose measured request/connection/uptime values where the
  server has a producer; unavailable byte values are represented as unavailable
  rather than fabricated measurements.
- Task C now provides producer-backed `shares`, `users`, `activity` and
  `online_users` invalidations. Search and admin projections refetch canonical
  HTTP snapshots and clear identity-scoped state on generation changes.
- Task D now removes the bootstrap composition compatibility APIs and ratchets
  the production/static boundary gates around the canonical Runtime and
  centralized transport.

The final Task E report now supplies fresh Windows cross-surface evidence and
the Linux directory-symlink gate result. The recalibration report is the
authoritative current release ledger.

## Architecture

The current system is a modular monolith with one intended ownership spine:

```text
LibraryService.open_session()
  → canonical LibrarySession
  → ApplicationBootstrap.runtime_for(session)
  → LibraryRuntime.services + RuntimeEventRouter
  → LanServer(runtime) → DTO/principal/WebSocket adapters
  → React RealtimeProvider → HTTP projection refetch
```

SQLite and the filesystem remain authoritative. Runtime events are filtered by
session token and resolved library root; WebSocket payloads contain only
`epoch`, `revision`, invalidation domains and relative paths. Desktop continues
to call application services directly. Task A closes the session/LAN end of
this spine with an adapter-before-DB barrier and retryable generation
ownership. Task B closes the browser identity/projection boundary and Task C
closes producer-backed projection coverage; migration cleanup and final
acceptance still need explicit closure.

### Design Decisions

- Keep the Runtime as the single library-scoped composition boundary; do not
  repair remaining drift by introducing another LAN service factory.
- Treat WebSocket messages as invalidation hints and use HTTP snapshots for
  correctness; this makes missed events recoverable without turning the socket
  into a second data store.
- Treat the original migration plan as historical after this audit. The
  recalibrated plan owns the remaining implementation sequence, while the old
  closure plan is historical and supplemental hardening reports remain
  authoritative only for their named subcontracts.

## Usage

For current implementation work, start with the status ledger in
[`2026-07-21-desktop-lan-webui-architecture-migration.md`](../plans/2026-07-21-desktop-lan-webui-architecture-migration.md), then execute the ordered
tasks in the recalibrated plan
[`2026-07-21-desktop-lan-webui-architecture-recalibration.md`](../plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md). The current verification baseline is:

```powershell
python -m pytest -q
npm --prefix webui test -- --run
npm --prefix webui run typecheck
npm --prefix webui run build
```

These baseline commands are necessary but not sufficient for a release claim;
the completed Task E lifecycle, identity, producer and real cross-surface
acceptance evidence is recorded in the recalibrated report.

## Current status by phase

| Phase | Status | Evidence-based interpretation |
|---|---|---|
| Phase 0 | delivered | Baseline and security/reconnect rails are in place. |
| Phase 1 | delivered | Task B removes browser bearer-token response/client state and keeps auth cookie-only. |
| Phase 2 | delivered for current scope | Runtime caching, LAN injection, adapter-before-DB teardown, generation registration, retryable stop and the Windows lifecycle matrix are covered. |
| Phase 3 | delivered for current scope | Event routing, cursor protocol, producer coverage and the Windows invalidation matrix are evidenced. |
| Phase 4 | delivered for current scope | Protected routing, first-ready recovery, logout/401 teardown and identity-scoped projection reset are evidenced. |
| Phase 5 | delivered | Windows acceptance is green and the Linux directory-symlink validation passed in Ubuntu WSL. |

## Open findings

### P1 — must close before release

No open P1 findings remain in the current recalibration scope. The Linux
directory-symlink platform gate passed in Ubuntu WSL.

### P2 — close during the same chain

- WebSocket baseline delivery happens before authoritative manager admission;
  a rejected client can receive a `runtime_ready` application frame before it
  is rejected. The pending admission barrier protects invalidation ordering;
  this remains a known P2 protocol note covered by the completed Task E gate.
- Task C's producer-backed domain contract is delivered for shares, users,
  activity and online presence; stats remains a measured HTTP snapshot with
  explicit unavailable bytes rather than a synthetic event source.
- `migrate_path_metadata_for_library()` remains a narrow legacy-named helper
  because `FileOperationService` still calls it in production. It is not part
  of Task D's removed service-composition API and requires a separate caller
  migration before deletion.
- The Windows acceptance matrix covers LAN→Desktop projection refresh,
  identity/logout/401 teardown, password/key/user/guest/share authorization,
  preview/download/path guards and teardown after failed stop. The Ubuntu WSL
  directory-symlink result closes the cross-platform release evidence for this
  scope.

## Verification

Fresh commands run during this documentation update:

| Gate | Command | Result |
|---|---|---|
| Task C producer/router gate | `python -m pytest tests/integration/test_task_c_producers.py tests/integration/test_runtime_events.py tests/lan/test_runtime_realtime.py tests/lan/test_public_contracts.py -q` | **77 passed** |
| Task C WebUI focus | `npm --prefix webui test -- --run src/hooks/useSearch.test.tsx src/components/admin/AdminManagement.test.tsx src/components/admin/InviteManagement.test.tsx src/components/admin/ShareManagement.test.tsx src/components/admin/ActivityLog.test.tsx src/components/admin/OnlineUsers.test.tsx src/components/layout/StatusBar.test.tsx` | **7 files, 35 tests passed** |
| Task D focused Python gate | `python -m pytest tests/unit/test_architecture_boundaries.py tests/core/test_package_contents.py tests/unit/test_bootstrap.py tests/unit/test_library_runtime.py tests/unit/test_window_session_switching.py tests/desktop/test_scoped_service_access.py tests/desktop/test_file_list_details.py tests/desktop/test_file_list_shim.py tests/integration/test_event_publishing.py tests/integration/test_file_operation_service.py tests/integration/test_library_service.py tests/integration/test_undo_service.py -q` | **402 passed** |
| Python full suite | `python -m pytest -q` | **1590 passed, 1 skipped**; the skip is the Windows directory-symlink case |
| WebUI full suite | `npm --prefix webui test -- --run` | **37 files, 289 tests passed** |
| WebUI typecheck | `npm --prefix webui run typecheck` | Passed |
| WebUI production build | `npm --prefix webui run build` | Passed; **1632 modules transformed** |
| Task E cross-surface slice | Focused Desktop/LAN/Chromium acceptance command | **186 passed** |
| Packaging gates | `tests/core/test_packaging_entrypoints.py tests/core/test_package_contents.py` | **8 passed** |
| Linux directory-symlink gate | Ubuntu WSL temporary venv with isolated RuntimeData; `python -m pytest tests/integration/test_project_service.py -k symlink -q` | **1 passed, 23 deselected** |

The supplemental hardening reports provide additional focused evidence for
WebSocket admission/revocation, failed-socket cleanup, server shutdown state,
Runtime adapter ownership and Chromium mutation/gap/epoch scenarios. Those
reports remain valid for their named subcontracts. Tasks C, D and E are
delivered, and the Linux platform gate now passes, so this migration is
`delivered` for the recalibrated scope.

## Future task chain

The previous closure chain is historical. Execute the recalibrated plan
[`2026-07-21-desktop-lan-webui-architecture-recalibration.md`](../plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md)
strictly in this order:

| Task | Outcome | Depends on |
|---|---|---|
| A. Canonical session/LAN boundary | **Delivered**: adapter-before-session/DB barrier, generation registration and retryable stop | — |
| B. Cookie-only identity | **Delivered**: token-free DTO, protected route guard, first empty-cursor recovery and stale projection reset | A |
| C. Producer-backed projections | **Delivered**: session-scoped producers, canonical search/admin refetch and measured stats contract | B |
| D. Fallback removal | **Delivered**: canonical Desktop Runtime composition, removed bootstrap compatibility APIs and static boundary gates | A–C |
| E. Final release gate | **Delivered**: Windows automated and real-client matrix plus passing Ubuntu WSL Linux symlink gate | A–D |

The release decision is `delivered` for the recalibrated scope: no P1,
security concern, missing producer or critical unexecuted journey remains.
The Windows symlink skip is complemented by the passing Ubuntu WSL Linux gate.

## Journey Log

> Brief notes on what informed the current-state decision.

- [pivot] The original “Phase 5 complete” statement was replaced after the
  audit separated green automated suites from lifecycle and identity closure.
- [lesson] Supplemental realtime and adapter-ownership reports close their
  own focused contracts; they must not be used as a blanket sign-off for the
  parent migration.
- [lesson] A future task chain must name the exact owner, failure state and
  acceptance evidence for each cross-thread lifecycle boundary.

## Source materials

| File | Role |
|---|---|
| `docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-design.md` | Original target architecture and invariants |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-migration.md` | Historical migration task detail plus current status ledger |
| `docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-closure-design.md` | Historical closure requirements C1–C5; superseded by the recalibration design |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-closure.md` | Historical ordered chain; do not execute in parallel with the recalibrated plan |
| `docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-recalibration-design.md` | Current baseline mapping and scope decision |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md` | Current authoritative A–E implementation chain |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-task-d.md` | Task D compatibility cleanup plan |
| `docs/compose/reports/desktop-lan-webui-architecture-task-a.md` | Task A implementation and verification report |
| `docs/compose/reports/desktop-lan-webui-architecture-task-b.md` | Task B implementation and verification report |
| `docs/compose/reports/desktop-lan-webui-architecture-task-c.md` | Task C implementation and verification report |
| `docs/compose/reports/desktop-lan-webui-architecture-task-d.md` | Task D implementation and verification report |
| `docs/compose/reports/realtime-dataflow-hardening.md` | Delivered realtime hardening subcontracts |
| `docs/compose/reports/runtime-adapter-failure-ownership.md` | Delivered adapter construction/failure ownership subcontracts |
| `docs/adr/0003-library-runtime.md` | Runtime/LAN ownership decision and remaining divergence |
