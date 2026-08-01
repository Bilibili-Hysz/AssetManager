---
feature: desktop-lan-webui-architecture-task-b
status: delivered
specs:
  - docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-recalibration-design.md
plans:
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md
branch: master
evidence_state: pre-baseline working tree; baseline captured in repository-baseline-2026-08-01.md
---

# Desktop–LAN–WebUI Task B — Final Report

## What Was Built

Task B closes the browser identity and protected-projection boundary for the
LAN SPA. User login, password login, registration and access-key verification
set the HttpOnly `lan_token` cookie, but their JSON responses do not expose a
server bearer token. User responses use the public `UserResponse` DTO, so
`password_hash` is not serialized.

The browser obtains its authoritative identity from cookie-authenticated
`/api/auth/me`. `AuthContext` contains no token state and exposes no
`setToken()`. Login and registration refresh `/api/auth/me` before navigation.
Logout and API 401 handling clear the principal, advance
`identityGeneration`, release stale refresh ownership and permit a new refresh
to begin.

`/browse` and `/detail` share one capability-aware `ProtectedRoute`. Guest
principals go to `/login`; authenticated principals without `browse` go to the
public landing route. Landing, login and share-receive routes remain outside
the protected boundary.

## Architecture

The implemented browser identity flow is:

```text
auth mutation
  → HttpOnly lan_token cookie
  → GET /api/auth/me with same-origin credentials
  → AuthContext principal/capabilities + identityGeneration
  → ProtectedRoute and identity-scoped HTTP projections
  → RealtimeProvider invalidation hints + HTTP snapshot recovery
```

`createApiClient` sends `credentials: 'same-origin'` and does not construct an
Authorization header. `RealtimeProvider` includes the identity generation in
its transport identity. A generation change resets the cursor to
`{ epoch: "", revision: 0 }`, invalidates recovery state and isolates
registrations from the previous identity. The first valid `runtime_ready`
after that reset performs one `/api/revision` recovery and null-event fan-out.
WebSocket messages remain invalidation hints; HTTP projections remain the
source of business data.

Browse list, selection, metadata, detail, tag results and thumbnail cache
responses are guarded by the current identity generation. Stale responses and
old registrations cannot repopulate the new identity's protected view.

### Design Decisions

- Use an HttpOnly cookie plus `/api/auth/me` because browser JavaScript must
  not receive or retain the server credential.
- Use an explicit `identityGeneration` in addition to principal identity so a
  logout or 401 is a teardown boundary even when the next principal has the
  same visible identity.
- Reset the realtime cursor on identity changes and recover through the
  authoritative revision endpoint because an empty cursor is not a valid
  permanent synchronization baseline.
- Preserve scoped share-token flows; Task B removes browser-visible server
  authentication tokens only and does not redesign share authorization.

## Usage

Authentication consumers call the existing `authApi` methods. After a
successful mutation, `LoginPage` calls `refreshMe()` and navigates only when
the cookie-authenticated principal refresh succeeds. Protected pages are
entered through the application route tree and do not need to manage tokens.

The focused verification commands are:

```powershell
python -m pytest tests/lan/test_lan_api.py::test_auth_register_route_returns_user_token tests/lan/test_t2_t4_contracts.py::test_auth_cookie_is_httponly -q
npm --prefix webui test -- --run src/stores/AuthContext.test.tsx src/components/auth/ProtectedRoute.test.tsx src/pages/BrowsePage.test.tsx src/pages/DetailPage.test.tsx src/stores/RealtimeContext.test.tsx
npm --prefix webui run typecheck
npm --prefix webui run build
```

## Verification

Fresh evidence from the current workspace and session:

| Gate | Result |
|---|---|
| Task B WebUI identity/projection focus | `5 files / 70 tests passed` |
| Task B LAN cookie focus | `2 passed` |
| LAN auth/realtime suites | `236 passed` |
| WebUI full suite | `35 files / 267 tests passed` |
| Python full suite | `1535 passed, 1 skipped` |
| WebUI typecheck | Passed |
| WebUI production build | Passed; `1632 modules transformed` |
| Diff formatting | `git diff --check` passed; only LF/CRLF warnings |

The skipped Python test requires directory symlinks unavailable on Windows.
It remains a Linux CI/platform gate and is not counted as passing
cross-platform release evidence. The earlier Task B gate recorded in the
project history (`74 passed`) remains valid historical evidence; the counts
above are the fresh focused recheck used for this report.

## Journey Log

- [pivot] Authentication moved from browser-readable bearer state to an
  HttpOnly cookie followed by an authoritative `/api/auth/me` refresh.
- [lesson] Principal equality alone is insufficient for teardown; an explicit
  identity generation prevents same-principal logout/login state reuse.
- [lesson] A first `runtime_ready` with an empty cursor must trigger recovery,
  otherwise the client can mistake an incomplete baseline for synchronized
  state.

## Source Materials

| File | Role | Notes |
|---|---|---|
| `docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-recalibration-design.md` | Architecture specification | Defines the identity and projection contracts; baseline is explicitly historical after Task B. |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md` | Implementation plan | Task B steps 1–5 are complete; Tasks C–E remain. |
| `AssetsManager/lan/routes/auth.py` | LAN auth boundary | Sets cookies and returns safe public responses. |
| `AssetsManager/lan/dto.py` | Public DTOs | Prevents password-hash serialization. |
| `webui/src/api/client.ts` | Browser transport | Uses same-origin credentials without bearer headers. |
| `webui/src/stores/AuthContext.tsx` | Identity lifecycle | Owns principal, refresh, logout and generation changes. |
| `webui/src/components/auth/ProtectedRoute.tsx` | Route gate | Enforces authentication and `browse` capability. |
| `webui/src/stores/RealtimeContext.tsx` | Realtime boundary | Resets cursor and performs first-ready recovery. |
| `webui/src/hooks/useProjects.ts` | List projection | Rejects stale identity-generation responses. |
| `webui/src/pages/BrowsePage.tsx` | Browse projection | Clears selection and metadata state on identity changes. |
| `webui/src/pages/DetailPage.tsx` | Detail projection | Aborts and rejects stale detail requests. |
| `webui/src/stores/AuthContext.test.tsx` | Identity regressions | Covers token absence, logout, 401 and stale refresh behavior. |
| `webui/src/components/auth/ProtectedRoute.test.tsx` | Route regressions | Covers guest, denied-capability and allowed access. |
| `webui/src/stores/RealtimeContext.test.tsx` | Realtime regressions | Covers cursor reset, recovery count and registration isolation. |
| `tests/lan/test_lan_api.py` | LAN auth regressions | Covers cookie-only login/register/key responses and safe DTOs. |
| `tests/lan/test_t2_t4_contracts.py` | Cookie contract | Covers HttpOnly cookie behavior. |

## Remaining Chain

Task B is delivered. Tasks C and D are now also delivered; the overall
recalibration chain remains `partial / not release-ready` until Task E
cross-surface acceptance is complete. See the [Task C final
report](desktop-lan-webui-architecture-task-c.md) for the producer-backed
projection evidence.
