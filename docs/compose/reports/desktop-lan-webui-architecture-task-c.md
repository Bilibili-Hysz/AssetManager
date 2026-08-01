---
feature: desktop-lan-webui-architecture-task-c
status: delivered
specs:
  - docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-recalibration-design.md
plans:
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md
branch: master
evidence_state: pre-baseline working tree; baseline captured in repository-baseline-2026-08-01.md
---

# Desktop–LAN–WebUI Architecture Task C — Final Report

## What Was Built

Task C makes the advertised LAN invalidation domains producer-backed and makes
the corresponding WebUI projections canonical. Share, user, invite, activity
and online-presence changes now produce immutable, session-scoped events after
the underlying state mutation succeeds. Event notification is best effort: a
subscriber or injected EventBus failure is logged and cannot turn a committed
business mutation into a failed request.

The Runtime router accepts only events whose session token and resolved library
root match the live `LibrarySession`. It maps `shares`, `users`, `activity` and
`online_users` to their real producers. Search and admin projections refetch
authoritative HTTP snapshots after matching invalidations and after local
mutations. Invite, share, user, activity and online-user views also clear their
rendered snapshots and invalidate in-flight requests when `identityGeneration`
changes, so a previous identity cannot remain visible or repopulate the new
session.

Stats remain a measured HTTP snapshot. The StatusBar continues polling the
stats endpoint, and unavailable byte measurements stay explicit as `null` in
the response and `Unavailable` in the UI; Task C does not fabricate a stats
event or a zero byte count.

## Architecture

The final Task C data flow is:

```text
repository / visible LAN state mutation
  → immutable session-scoped DomainEvent
  → RuntimeEventRouter exact token + root filter
  → LAN projection_invalidated hint
  → React RealtimeProvider domain registration
  → canonical HTTP snapshot refetch
```

`ShareService` publishes `ShareChanged` after share creation, deletion and
successful download-counter increments. `AuthService` publishes
`UserChanged` and `InviteChanged` after user and invite mutations.
`ActivityLog` and `OnlineUsers` publish `ActivityChanged` and
`PresenceChanged` after their visible in-memory projections change. The LAN
server wires each helper with the canonical session root and event token.

The WebUI keeps business data in HTTP responses. `useSearch` refetches an
active query on `files` or `metadata` invalidation. Invite, share and user
management refetch their list after create/revoke/delete/toggle and on remote
invalidation. ActivityLog listens to `activity`; OnlineUsers listens to
`online_users`; StatusBar uses measured stats polling. Every async projection
uses request-generation protection, and every admin projection resets on
identity generation changes.

### Design Decisions

- We chose dedicated `activity` and `online_users` domains because those
  projections have independent visible-state producers; using `users` as a
  catch-all would hide missing producer coverage.
- We publish share download-counter changes through `ShareChanged` because the
  counter is part of the canonical share DTO and changes through a repository
  mutation just like create and delete.
- We keep WebSocket messages as invalidation hints and refetch HTTP snapshots
  because the repository and filesystem remain authoritative and missed or
  reordered socket messages must be recoverable.
- We keep stats on measured HTTP polling because no trustworthy stats event
  producer exists for every displayed metric; unavailable values are explicit
  rather than synthetic.

## Usage

No new user-facing configuration is required. Existing LAN mutations and
WebSocket connections automatically use the canonical session event identity.
The browser continues to consume normal list/activity/online/stats APIs; a
realtime message only schedules the relevant refetch. A login, logout, 401 or
identity switch clears the five admin snapshots before the new generation is
loaded.

The focused verification commands are:

```powershell
python -m pytest tests/integration/test_task_c_producers.py tests/integration/test_runtime_events.py tests/lan/test_runtime_realtime.py tests/lan/test_public_contracts.py -q
npm --prefix webui test -- --run src/hooks/useSearch.test.tsx src/components/admin/AdminManagement.test.tsx src/components/admin/InviteManagement.test.tsx src/components/admin/ShareManagement.test.tsx src/components/admin/ActivityLog.test.tsx src/components/admin/OnlineUsers.test.tsx src/components/layout/StatusBar.test.tsx
npm --prefix webui run typecheck
npm --prefix webui run build
```

## Verification

Fresh evidence from the completed Task C closure pass:

| Gate | Result |
|---|---|
| Task C Python producer/router/public-contract/realtime gate | `77 passed` |
| Focused WebUI search/admin/stats gate | `7 files / 35 tests passed` |
| WebUI typecheck | Passed |
| WebUI production build | Passed; `1632 modules transformed` |
| Python full suite | `1555 passed, 1 skipped` |
| WebUI full suite | `37 files / 289 tests passed` |
| Window lifecycle close-frame regressions | `2 passed` |
| Independent Task C review | No actionable findings |
| `git diff --check` | Passed; only existing line-ending warnings |

The single Python skip is the directory-symlink test, which is unavailable on
Windows and remains a Linux CI/platform gate. Task D is now delivered for its
compatibility-cleanup scope; the full recalibration chain remains not
release-ready because Task E cross-surface acceptance is still open.

## Journey Log

> Brief notes on what informed the final design.

- [pivot] Stats stayed on measured HTTP polling with explicit unavailable
  bytes instead of gaining a synthetic timer-only event source.
- [lesson] Canonical admin refetches need both request-generation guards and
  identity-generation teardown; either one alone leaves a stale-session path.
- [pivot] Activity and online presence received dedicated producer-backed
  domains after tracing their mutations showed they were not user mutations.
- [lesson] Presence invalidations can advance the Runtime revision during
  WebSocket admission, so close-frame tests must consume queued hint frames
  before asserting final transport closure.

## Source Materials

| File | Role | Notes |
|---|---|---|
| `docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-recalibration-design.md` | Architecture specification | Defines S4 producer, projection and stats contracts. |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md` | Implementation plan | Task C steps 1–5 are complete; Tasks D–E remain. |
| `AssetsManager/domain/events.py` | Event records | Immutable session/root-scoped producer events. |
| `AssetsManager/application/runtime_events.py` | Runtime routing | Exact identity filtering and producer-backed domain mapping. |
| `AssetsManager/application/auth_service.py` | User/invite producer | Publishes only after successful repository mutation. |
| `AssetsManager/application/share_service.py` | Share producer | Covers create, delete and download-counter mutation. |
| `AssetsManager/lan/routes/_helpers.py` | LAN projection producers | Publishes activity and visible presence changes. |
| `webui/src/hooks/useSearch.ts` | Search projection | Refetches active canonical query with identity and request guards. |
| `webui/src/components/admin/InviteManagement.tsx` | Invite projection | Canonical refetch and identity teardown. |
| `webui/src/components/admin/ShareManagement.tsx` | Share projection | Canonical refetch and identity teardown. |
| `webui/src/components/admin/UserManagement.tsx` | User projection | Canonical refetch and identity teardown. |
| `webui/src/components/admin/ActivityLog.tsx` | Activity projection | Dedicated activity invalidation and identity teardown. |
| `webui/src/components/admin/OnlineUsers.tsx` | Presence projection | Dedicated online-presence invalidation and identity teardown. |
| `webui/src/components/layout/StatusBar.tsx` | Stats projection | Measured polling and explicit unavailable bytes. |
| `tests/integration/test_task_c_producers.py` | Producer regressions | Success ordering, failure isolation and notification failure coverage. |
| `tests/integration/test_runtime_events.py` | Router regressions | Mapping, immutability and session/root isolation. |

## Remaining Chain

Task C is delivered. Task D is now also delivered for its compatibility-cleanup
scope. The overall Desktop–LAN–WebUI recalibration remains
`partial / not release-ready` until Task E runs the final automated, platform
and real-client acceptance matrix.
