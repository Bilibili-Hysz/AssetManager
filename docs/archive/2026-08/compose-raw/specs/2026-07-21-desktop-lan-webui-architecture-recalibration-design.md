# Desktop–LAN–WebUI Architecture Recalibration Design

> [!NOTE]
> This document may not reflect the current implementation.
> See the [recalibration final report](../reports/desktop-lan-webui-architecture-recalibration.md)
> for the latest Task E evidence and current release decision.

> [!NOTE]
> This design supersedes the previous closure sequencing, not the original
> architecture target. It is based on the current code and fresh baseline
> runs from 2026-07-21. The implementation scope is architecture closure only;
> unrelated UI product gaps remain separate work. Task A is delivered; see the
> [Task A report](../reports/desktop-lan-webui-architecture-task-a.md) for the
> current lifecycle implementation and verification.

## [S1] Current baseline and decision

The original migration has delivered the main structural foundations:
`LibraryRuntime` caching, Runtime-injected LAN composition, DTOs,
`SessionPrincipal`/capabilities, session-filtered invalidations,
`epoch + revision`, WebSocket authority/eviction hardening, the React
`RealtimeProvider`, and major projection migration.

The current baseline is:

| Gate | Current result | Interpretation |
|---|---|---|
| Python full suite | `1590 passed, 1 skipped` | Green aggregate suite; Windows directory-symlink test is skipped |
| WebUI full suite | `37 files, 289 tests passed` | Green aggregate suite |
| Runtime/LAN lifecycle focus | `210 passed` after Task A | Includes deterministic close ordering, retry retention, generation registration and startup lock regressions |
| Task C producer/router gate | `77 passed` | Session/root producer mapping, canonical projection regressions and measured stats contract |
| Task C WebUI focus | `7 files, 35 tests passed` | Search, admin canonical refetch, identity teardown and stats polling |
| Task E cross-surface focus | `186 passed` | Real Chromium, LAN-to-Desktop, lifecycle, auth/path and teardown acceptance |

The recalibrated architecture status is `delivered` for the defined scope: the Windows cross-surface matrix passed and the Ubuntu WSL directory-symlink gate supplied the platform-specific evidence. The new task chain must not repeat delivered hardening. Product-level data safety, performance thresholds and broader service-boundary cleanup remain separate roadmap work.

The baseline above includes the prerequisite Tasks A–C and the final Task E
cross-surface result. Their implementation and focused verification evidence
are recorded in the
[Task B final report](../reports/desktop-lan-webui-architecture-task-b.md).
Task C is also delivered; see the [Task C final report](../reports/desktop-lan-webui-architecture-task-c.md).
Task D is also delivered; see the [Task D final report](../reports/desktop-lan-webui-architecture-task-d.md).
Task E and the overall recalibration chain are delivered; the Linux directory-symlink gate is recorded in the [recalibration final report](../reports/desktop-lan-webui-architecture-recalibration.md).

## [S2] Mapping from original Task 1–17

| Original tasks | Recalibrated status | New disposition |
|---|---|---|
| 1–4 | delivered | Evidence-only prerequisite; retain existing tests |
| 5 | partial | Move bearer-token removal and cookie-only identity into Task B |
| 6 | partial | Move session close ordering into Task A |
| 7 | partial | Move successful restart-generation registration into Task A |
| 8 | delivered for Task D scope | Remove proven production service-composition callers and retain only explicitly justified helpers |
| 9 | partial | Keep existing six-domain router; add only producer-backed domains in Task C |
| 10–11 | hardening delivered, integration partial | Do not repeat admission/revocation/eviction implementation; add only first-ready and cross-surface evidence in Tasks A/E |
| 12 | partial | Add first empty-cursor recovery in Task B or the smallest independent realtime subtask |
| 13 | partial | Keep migrated pages; fix search/admin canonical refresh in Task C |
| 14 | evidence completed; platform gate pending | Task E cross-surface acceptance |
| 15 | partial | Keep truthful metrics; decide stats producer/UI availability in Task C |
| 16 | delivered for Task D scope | Remove proven compatibility paths and ratchet static architecture gates |
| 17 | evidence completed; platform gate pending | Task E final evidence and release decision |

The prior seven-task closure plan is therefore historical. It over-grouped
already-delivered WebSocket hardening with still-open lifecycle, identity and
projection work.

## [S3] Target ownership and state contracts

The canonical close sequence is:

```text
live session
  → mark session closed to new operation leases
  → stop every Runtime lifecycle adapter while session resources are live
  → drain existing operation leases
  → clear session-owned caches
  → remove Runtime cache ownership
  → close the per-library database resource
```

`LibraryRuntime` remains the only owner of library-scoped services and LAN
adapter registrations. A server generation has exactly one registration after
successful `start()`, no registration before construction/startup commit, and
no registration after confirmed `stop()`. Incomplete cleanup retains an
actionable handle and failed state for retry.

## [S4] Identity and projection contracts

Authentication success responses set the HttpOnly `lan_token` cookie but do
not return `token` to JavaScript. The browser calls `/api/auth/me` and uses its
`SessionPrincipal`/`Capabilities` response as the authoritative identity.

Identity generation changes—login, logout, 401, user switch or server epoch
replacement—must invalidate protected route data, selection/detail state,
search results, cursor state and projection registrations. `/browse` and
`/detail` use one capability-aware route boundary; public landing and share
receive routes remain separate.

The advertised projection domains have an evidence rule:

| Domain | Required current-state contract |
|---|---|
| `files/tree/home/project_detail/metadata/tags` | Existing event mapping plus authoritative page refetch |
| `shares` | Share create/delete/revoke publishes a session-scoped event and ShareManagement refetches |
| `users` | User/invite mutation publishes a session-scoped event and admin consumers refetch |
| `activity` | ActivityLog publishes a session-scoped event and refetches |
| `online_users` | Visible presence changes publish a session-scoped event and refetch |
| `stats` | A measured producer exists, or UI represents unavailable data explicitly |

Search is a `files`/`metadata` projection. Active queries must refetch after a
matching invalidation. Invite/share management must not synthesize server
timestamps or status from browser-local state.

## [S5] Scope and non-goals

This chain covers only Runtime ownership, LAN lifecycle, cookie identity,
realtime cursor integration, projection consistency, migration boundaries and
cross-surface acceptance. It does not include login-page visual improvements,
mobile UX, share UI redesign, tag filtering UX, download progress, themes or
other independent product gaps.

No task may introduce a second service assembly path, a persistent revision
store, a new backend process, Redis/Kafka, React Query or WebSocket business
object transport.

## [S6] Completion rule

The chain is delivered only when Tasks A–E have fresh focused evidence, all
P1/security findings are closed, the full matrix has run, the Windows symlink
case is either passed in Linux CI or explicitly accepted as a platform gate,
and the final report states the exact release decision. Green aggregate tests
alone are insufficient.
