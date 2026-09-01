# Day 3 WebUI and LAN Contract Closure

## Scope and Environment

- Isolated worktree: `.worktrees/grid-zoom-interpolation-fix`.
- Verified HEAD: `0885d77c74baa6caa94f0a6e98b155a5f3fef399`.
- Entry state was the specified clean HEAD plus two pre-existing, untracked Day 2 reports: `docs/compose/reports/2026-07-22-grid-zoom-investigation.md` and `docs/compose/reports/2026-07-23-python-session-desktop-closure.md`.
- No application code, test code, dependency manifest, or lockfile was changed. This report is the sole Day 3 file created.
- Commands were executed on Windows with the repository-relative commands recorded below. This report omits machine-absolute paths, credentials, and tokens.

## Commands and Results

From `webui/`:

```powershell
npm ci
```

Result: passed. `237` packages added and `238` audited. The SHA-256 of `package-lock.json` was identical before and after, so the lockfile was not changed. The install audit summary was `5` vulnerabilities: `3 moderate`, `1 high`, and `1 critical`; `46` packages request funding. `npm audit --omit=dev --json` reported zero production dependency vulnerabilities. The full audit attributes the findings to development tooling: direct `vite` (high) and direct `vitest` (critical), with transitive `@vitest/mocker`, `esbuild`, and `vite-node`; available fixes require a major-version upgrade.

```powershell
npm run typecheck
```

Result: passed (`tsc --noEmit`).

```powershell
npm test
```

Result: passed: `17` files and `59` tests. React Router future-flag warnings were emitted by existing tests; they did not fail the command.

```powershell
npm run build
```

Result: passed (`tsc -b && vite build`). Production output contains `webui/dist/index.html` and hashed JavaScript/CSS under `webui/dist/assets`.

From the repository root, the required command was initially started concurrently with the production build:

```powershell
python -m pytest tests/lan/test_lan_api.py tests/lan/test_path_guard.py -q
```

Initial result: `1 failed, 149 passed`. Exact failing node: `tests/lan/test_lan_api.py::TestMiddlewarePrecedenceRegression::test_spa_assets_are_public_when_server_auth_is_enabled[asyncio]`. Reproducer: start that pytest command before `npm run build` has produced a JavaScript file under `webui/dist/assets`; its `next(spa_assets.glob("*.js"))` assertion raises `StopIteration` at `tests/lan/test_lan_api.py:2215`. This is a P1 test-ordering/verification issue, not a server assertion failure.

The exact required command was then rerun after the build completed:

```powershell
python -m pytest tests/lan/test_lan_api.py tests/lan/test_path_guard.py -q
```

Final serial result: passed, `150 passed in 9.46s`.

From the repository root, the supplemental contract command was executed after the serial required suite:

```powershell
python -m pytest tests/lan/test_t2_t4_contracts.py -q
```

Result: passed, `4 passed in 1.84s`. This execution covers query-token rejection for both an invalid query token and a valid issued token, legacy SPA fallback when no build exists, and the legacy password-share script's prohibition on URL tokens.

Final repository checks:

```powershell
git diff --check
git status --short
```

`git diff --check` completed with no output. The final short status contains only the two retained Day 2 reports plus this Day 3 report; there are no changes under `AssetsManager/`, `webui/src/`, `tests/`, dependency manifests, or lockfiles.

## Contract-to-Test Mapping

### Same-origin API client and credentials

- Implementation evidence: `webui/src/api/client.ts` constructs API URLs from `window.location.origin` and uses `credentials: 'same-origin'` for both JSON and Blob requests.
- Coverage gap: no Vitest node asserts the generated same-origin URL or either `credentials: 'same-origin'` fetch option. This implementation inspection is not behavioral browser coverage.

### Cookie-backed `/api/auth/me` session restore without JavaScript credential access

- Implementation evidence: `webui/src/api/auth.ts` maps `me()` to `GET auth/me`; `webui/src/stores/AuthContext.tsx` calls `refreshMe()` when server auth is enabled and documents its cookie-authenticated session-restore intent.
- Partial backend evidence: `tests/lan/test_lan_api.py::test_websocket_accepts_middleware_authenticated_cookie_context` accepts a `lan_token` cookie in a WebSocket handshake; `tests/lan/test_lan_api.py::TestP0ShareCookieAuthentication::test_successful_share_verify_returns_share_and_http_only_cookie` asserts an HttpOnly share cookie and no response token for the browser share flow.
- Coverage gap: no executed test logs into the server, reloads/remounts `AuthProvider`, invokes `/api/auth/me` through `fetch` with the browser cookie, and asserts restored user state while JavaScript cannot read the credential.
- Confirmed S10 P0 credential exposure: `AssetsManager/lan/routes/auth.py:23-25`, `:31-33`, `:61-63`, and `:83-85` each construct a JSON response containing `token` and then pass that same `token` variable to `set_auth_cookie`. `AssetsManager/lan/routes/_helpers.py:313-316` writes that value to the HttpOnly `lan_token` cookie. `webui/src/pages/LoginPage.tsx:77`, `:92`, and `:137` then pass `res.token` to `setToken`; `webui/src/stores/AuthContext.tsx:8`, `:30`, `:51-53`, and `:116-128` stores and exposes it in React state and context. Therefore the JSON token and the HttpOnly cookie are the same credential, and that credential is available to JavaScript. No credential value is recorded in this report. `webui/src/stores/AuthContext.test.tsx::AuthProvider > retains the supplied token after login` explicitly asserts the retained-token behavior. This is a confirmed violation of S10's approved requirement that the HttpOnly credential not be put in React state.

### Download JSON and Blob behavior

- Direct test: `webui/src/api/files-shares.contract.test.ts::file and share API contracts > posts selected download paths as JSON and saves the Blob response` asserts `postBlob('download/batch', { paths })`, `Blob` object-URL creation, click, and URL revocation.
- Implementation evidence: `webui/src/api/client.ts` serializes JSON and consumes Blob responses with `response.blob()`.
- Coverage gap: the existing test mocks `postBlob`; it does not assert the client fetch request's JSON content-type/body or the `response.blob()` branch end-to-end.

### WebSocket same-origin, ws/wss, no query token, and finite reconnect

- Implementation evidence: `webui/src/hooks/useWebSocket.ts` derives `ws:` or `wss:` from `window.location.protocol`, uses `window.location.host`, connects to `/ws` without a query string, and caps retry at one reconnect.
- Direct reconnect tests: `webui/src/hooks/useWebSocket.test.tsx::useWebSocket > reconnects once after an unexpected close` and `::does not reconnect after intentional cleanup` verify the bounded reconnect and cleanup behavior.
- Executed backend query-token rejection: `tests/lan/test_t2_t4_contracts.py::test_websocket_query_token_does_not_authenticate_a_connection` and `::test_websocket_valid_query_token_does_not_authenticate_a_connection` passed in the supplemental suite and require HTTP 401 for `/ws?token=...`, including when the query value is a valid issued credential.
- Backend cookie handshake: `tests/lan/test_lan_api.py::test_websocket_accepts_middleware_authenticated_cookie_context` accepts a cookie-authenticated `/ws` connection.
- Coverage gap: the frontend WebSocket test records only connection count, not the constructed URL. It does not assert `ws` versus `wss`, same-origin host, or absence of query token. No browser integration test proves the browser sends the HttpOnly cookie during the SPA WebSocket handshake.

### PathGuard/validated paths for LAN input

- Direct PathGuard tests: `tests/lan/test_path_guard.py::test_path_guard_blocks_parent_escape`, `::test_path_guard_blocks_absolute_escape`, and `::test_path_guard_existing_key_requires_existing_file`.
- API wrapper tests: `tests/lan/test_lan_api.py::TestPathTraversal::test_validate_path_blocks_escape`, `::test_validated_existing_key_requires_library_path`, and `::test_validated_existing_key_requires_existing_file`.
- Implementation evidence: LAN route modules use `validate_path` or `validated_existing_key`; their helpers delegate to `PathGuard` and convert escape/missing-path errors to HTTP responses.
- Coverage limit: this focused suite proves the guard and representative wrappers, not every route/input combination in a full real-LAN acceptance flow.

### SPA assets and legacy static fallback

- Direct SPA asset test: `tests/lan/test_lan_api.py::TestMiddlewarePrecedenceRegression::test_spa_assets_are_public_when_server_auth_is_enabled` requests a built hashed asset with server authentication enabled and asserts HTTP 200. It passed in the required serial run after the build.
- Executed legacy fallback test: `tests/lan/test_t2_t4_contracts.py::test_spa_page_routes_fall_back_to_legacy_shell_when_no_build_exists` passed in the supplemental suite; it stubs the SPA index absence and asserts expected legacy page shells.
- Executed legacy share no-URL-token test: `tests/lan/test_t2_t4_contracts.py::test_legacy_password_share_uses_verified_cookie_state_without_url_tokens` passed in the supplemental suite and asserts that the legacy share script has verified share state without `?token=`.
- Direct backup-artifact rejection: `tests/lan/test_lan_api.py::TestP0ShareCookieAuthentication::test_static_backup_artifacts_are_not_served` asserts HTTP 404 for `.bak`, `.bak2`, and uppercase/nested variants.
- Coverage limit: the required serial suite executes the SPA asset test, and the supplemental suite executes the legacy fallback and legacy-share URL-token tests. These focused server/script tests do not establish browser same-origin credential delivery, `/auth/me` session restore, or frontend WebSocket URL/cookie behavior.

## Findings and Risk Classification

### P0

- Confirmed S10 credential exposure: login, registration, password-only login, and key verification each return a JSON `token` while setting the same value as the HttpOnly `lan_token` cookie; the SPA passes the JSON credential to `setToken`, and `AuthContext` retains and exposes it. This contradicts the approved HttpOnly-cookie design. The existing frontend test locks in the prohibited behavior. No remediation was attempted because the audit scope prohibits code/test changes.

### P1

- Test ordering is a P1 verification issue: the required LAN command is order-dependent on build output. When run concurrently with `npm run build`, the SPA asset test fails before its HTTP assertion due to absent hashed assets; it passes when rerun after build completion. The required procedure must remain serial, or its test must arrange a fixture/build artifact.
- Cookie `/api/auth/me` restoration lacks a behavioral frontend/browser test. The implementation path and backend cookie behavior are present, but the approved session-restoration contract is not directly demonstrated.
- Same-origin `credentials: 'same-origin'` is implementation evidence only; there is no direct fetch-options test.
- Frontend WebSocket URL construction and browser cookie handshake lack direct assertions. The reconnect limit and backend query-token rejection are covered separately.

### P2

- Full `npm audit` reports five development-tooling vulnerabilities: three moderate, one high, and one critical. The production-only audit reports zero vulnerabilities. Updating the affected Vite/Vitest chain requires a major-version change and is outside the permitted scope.
- Existing React Router future-flag warnings remain during tests; no test fails.
- The PathGuard focused coverage does not demonstrate every LAN endpoint's input path in an end-to-end real-LAN session.

### Deferred

- Refactoring the React auth model to remove token state, adding browser/API contract tests, ensuring deterministic SPA build preconditions, and upgrading audit-affected toolchain dependencies are outside the allowed report-only change scope.

## Release Impact

This validation does not support a release-ready conclusion. The build and required serial LAN suite pass, and server-side SPA/static/path safeguards have meaningful focused coverage. However, the S10 prohibition against storing an HttpOnly credential in React state is currently violated, and browser-level proof of cookie session restoration and same-origin request/WebSocket behavior is missing. The P0 issue and P1 verification gaps must close before a release-readiness claim.
