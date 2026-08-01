# Desktop–LAN–WebUI Architecture Closure Design

> [!WARNING]
> **Historical design:** superseded by
> [`2026-07-21-desktop-lan-webui-architecture-recalibration-design.md`](2026-07-21-desktop-lan-webui-architecture-recalibration-design.md).
> The recalibrated design is based on the current code/test baseline and is
> the source for the next task chain.

> [!NOTE]
> This is the follow-up closure scope derived from the current-state audit.
> See the authoritative migration report for the current decision:
> [Desktop–LAN–WebUI Architecture Migration — Current-State Report](../reports/desktop-lan-webui-architecture-migration.md)

> **Status:** Proposed from the 2026-07-21 current-state audit; this is the
> scope for the remaining closure work, not evidence that the original
> migration is complete.

## Purpose

The original migration established most of the Runtime, DTO, principal,
invalidation and React provider foundations. The current HEAD is test-green
for the existing automated suites, but the architecture is not yet closed:
several lifecycle interleavings, identity transitions and projection
producers are not covered by executable evidence, and migration compatibility
paths remain in production.

This closure design turns those findings into a bounded task chain. The order
is intentional: ownership and teardown must be correct before admission and
identity recovery are trusted; only then can projection completeness and
fallback removal be verified.

## [C1] Canonical lifecycle ownership

- A `LibraryRuntime` must stop every registered LAN adapter before the
  `LibrarySession` releases its caches or the database manager closes its
  connection.
- `session_closing` is the pre-resource-release boundary. Adapter stop must
  be attempted there, while the session is already rejecting new operation
  leases but existing leases may still drain.
- A failed adapter stop must remain observable and retryable. The close path
  must not report a clean session close while a server thread, event loop,
  socket or scanner can still access the session.
- A successful `LanServer.start()` generation must be Runtime-owned. A later
  `stop()` may unregister that generation, and a later successful `start()` on
  the same live server must register it again exactly once.
- `ShareManager.stop()` must retain a failed server handle and failed state;
  it must never convert an uncleared live server into `None/stopped`.

## [C2] Authoritative realtime admission and recovery

- A WebSocket cannot receive runtime invalidations until its initial
  `runtime_ready` baseline is delivered and its authoritative admission
  barrier is released.
- The admission path must re-read the cursor after registration and deliver a
  newer baseline before release when a mutation occurs during admission.
- The first `runtime_ready` received by a browser with an empty cursor must
  trigger one authoritative `/api/revision` recovery/fan-out cycle. This
  closes the snapshot-read/admission race instead of treating the first frame
  as proof that the HTTP snapshot is current.
- Rejected or failed-baseline sockets must receive no application invalidation
  frame and must leave no client, pong waiter, presence or connection-count
  residue.

## [C3] Cookie-only identity and route teardown

- Login, registration, password login and key verification set the HttpOnly
  cookie but do not return bearer tokens to JavaScript.
- `AuthContext` stores the server-returned `SessionPrincipal` and
  `Capabilities`; it does not retain a token or fabricate an authenticated
  principal before `/auth/me` succeeds.
- A 401, logout or principal identity change clears route-owned data,
  selection, detail state, search state, cursor and projection registrations.
- Protected `/browse` and `/detail` entry points share one guard. Guest access
  remains capability-driven and public share routes remain separately scoped.

## [C4] Projection producer completeness

The advertised invalidation domains must correspond to a producer and a
canonical HTTP refetch:

| Domain | Required producer/consumer |
|---|---|
| `files`, `tree`, `home`, `project_detail`, `metadata`, `tags` | Existing Runtime event mapping and page refreshes, with first-ready and identity-reset coverage |
| `shares` | Share create/revoke/delete emits a session-scoped event and Share management refetches the list |
| `users` | User/invite mutation emits a session-scoped event and admin projections refetch from HTTP |
| `stats` | Verified request/connection/activity producer or the UI explicitly renders unavailable |

Search results are a `files`/`metadata` projection and must refetch when an
active query is invalidated. Admin create/revoke actions must refetch the
canonical response instead of synthesizing `created_at` or local status.

## [C5] Migration closure and acceptance

After C1–C4 are green:

- remove `for_library()` production consumers, `cleanup_library()`, legacy
  singleton/current-library helpers and the standalone page-level WebSocket
  bridge where no consumer remains;
- remove bearer-token fields and `res.user` compatibility from the public
  login contract;
- add architecture gates proving no raw-connection service assembly, no
  public DTO drift and no unowned runtime adapter;
- execute the complete Desktop→LAN→Browser, LAN→Desktop, disconnect/recovery,
  server restart, same-root reopen, auth matrix and teardown matrix;
- keep the Windows directory-symlink skip explicitly separate from the
  release decision; Linux CI must run it.

## Non-goals

This closure does not introduce a new backend process, persistent revision
store, React Query migration, WebSocket business-object transport, conflict
resolution or database schema replacement. Product-scope gaps unrelated to
Runtime ownership and cross-surface dataflow remain separate plans.
