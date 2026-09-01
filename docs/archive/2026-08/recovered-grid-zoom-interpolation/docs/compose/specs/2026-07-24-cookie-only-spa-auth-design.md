# Cookie-Only SPA Authentication Design

## [S1] Problem

The LAN login, registration, password, and access-key routes set the generated authentication token as the HttpOnly `lan_token` cookie and also return that same token in JSON. The React SPA currently passes the JSON token through `LoginPage` into `AuthContext`, where it is retained and exposed to JavaScript consumers. This violates the browser authentication boundary: the SPA must not retain the credential protected by the HttpOnly cookie.

## [S2] Solution

Make SPA authentication Cookie-only without changing LAN response compatibility. The SPA will not store, expose, or require `LoginResponse.token`. Authentication commands will rely on the response user only when available; otherwise they will call cookie-authenticated `GET /api/auth/me` through `refreshMe()` to establish the public user, role, and permission state.

The LAN server continues returning `token` in JSON for explicit API/Bearer compatibility. This fix changes only the React browser consumer and does not change cookie attributes, server-side token generation, middleware, WebSocket authentication, or external API contracts.

## [S3] Public Interface

`AuthContextValue` must not contain a `token` property. Replace:

```ts
setToken: (token: string | null, user?: User | null) => void;
```

with:

```ts
setSessionUser: (user?: User | null) => void;
```

`setSessionUser(user)` sets role, user, and permissions from public user data. `setSessionUser()` without a user sets guest role and guest permissions. `logout()` calls the cookie-authenticated endpoint and then resets public session state.

## [S4] Login and Restore Flow

```text
POST /api/auth/login|register|verify_key
  -> server sets HttpOnly lan_token cookie
  -> SPA ignores JSON token
  -> SPA uses response user when provided
  -> otherwise SPA calls refreshMe()
  -> GET /api/auth/me sends same-origin cookie
  -> SPA stores only user, role, and permissions
```

Password-only and access-key responses have no `user` field, so their success flow must call `refreshMe()` before navigating. User login and registration may use their returned user to update visible state, but they must never retain the response token.

## [S5] Required Tests

Add or update frontend tests to prove:

1. `AuthContextValue` exposes no token field and no setter accepts a token value.
2. Updating session state from a user retains only public user, role, and permissions.
3. Calling `refreshMe()` restores public state from `authApi.me()` without a credential value.
4. Login, registration, password-only, and key flows ignore the token response value. Password-only and key flows call `refreshMe()` before navigating.
5. Existing API client requests remain `credentials: "same-origin"`.

Run TypeScript checking, all Vitest tests, production Vite build, and the LAN auth/PathGuard/contract pytest suites after the frontend change.

## [S6] Non-Goals

- Do not remove the JSON token field from LAN responses.
- Do not change `lan_token` cookie flags or server auth middleware.
- Do not add localStorage, sessionStorage, a new bearer transport, or a browser-accessible credential cache.
- Do not modify WebSocket URL or reconnect behavior.
- Do not upgrade dependencies in this fix.
