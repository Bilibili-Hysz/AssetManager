# Cookie-Only SPA Authentication Remediation

## Scope

- Branch: `fix/grid-zoom-interpolation`
- HEAD base: `0885d77c74baa6caa94f0a6e98b155a5f3fef399`
- Fixed risk: the SPA retained the same credential that LAN authentication placed in the HttpOnly `lan_token` cookie.
- Server JSON token responses remain unchanged for explicit API/Bearer compatibility.

## Root Cause

LAN login, registration, password, and access-key handlers set the generated token as the HttpOnly `lan_token` cookie and return the same token in JSON. The browser `LoginPage` passed `res.token` into `AuthContext`, where the credential was retained and exposed to React consumers.

## Remediation

- `AuthContext` no longer contains token state, a token property, or `setToken`.
- `AuthContext` exposes `setSessionUser(user?: User | null)` and stores only public user, role, and permission state.
- `refreshMe()` calls cookie-authenticated `/api/auth/me` and returns `true` only after a public user is restored; it returns `false` and resets guest state on failure.
- User login and registration use only `res.user`.
- Password-only and access-key login ignore the JSON token, require successful `refreshMe()`, and do not navigate when cookie session restoration fails.
- No LAN server, cookie flag, middleware, WebSocket, dependency, or lockfile change was made.

## TDD Evidence

The new tests were run in RED before the production change:

- The old Context failed because `setSessionUser` did not exist and exposed `token`.
- The old `refreshMe()` resolved `undefined` rather than `false` after `authApi.me()` failed.
- Password-only and key login previously navigated after a failed refresh and did not display their flow-specific error.

The final focused AuthContext and LoginPage tests pass with coverage for public session state, cookie session restoration, failed restoration, user login, registration, password-only login, and access-key login.

## Verification

| Check | Result |
| --- | --- |
| Focused AuthContext/LoginPage tests | `2 files, 11 tests passed` |
| `npm run typecheck` | Passed |
| `npm test` | `17 files, 67 tests passed` |
| `npm run build` | Passed |
| Post-build LAN regression | `154 passed` for LAN API, PathGuard, and T2/T4 contract suites |
| `git diff --check` | Passed with no whitespace errors |
| Production auth-flow credential search | No `setToken` or `res.token` match in `AuthContext.tsx` or `LoginPage.tsx` |

## Remaining Risk

- The LAN server still returns JSON tokens for external compatibility. Browser flows now ignore them, but a future API compatibility decision may remove them only after auditing non-browser consumers.
- Browser-level integration coverage for real Cookie transport, `/api/auth/me` remount restoration, and WebSocket Cookie handshake remains a Day 4 acceptance concern.

## Release Impact

The confirmed P0 React credential exposure is closed in the SPA scope. This does not independently establish release readiness; remaining Day 2 coverage gaps, Day 3 browser-integration gaps, and real LAN acceptance still require completion.
