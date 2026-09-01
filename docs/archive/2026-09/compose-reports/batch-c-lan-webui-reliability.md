---
feature: batch-c-lan-webui-reliability
status: delivered
specs:
  - docs/compose/specs/2026-07-15-lan-webui-reliability-design.md
plans:
  - docs/compose/plans/2026-07-15-batch-c-lan-webui-reliability.md
branch: batch-c-lan-webui-reliability
implementation_range: 8d7a566..e360fe8
---

# Batch C LAN WebUI Reliability Delivery Report

## Delivery Boundary

This report was audited against the isolated `batch-c-lan-webui-reliability` worktree, its files, and every branch-local commit after base `8d7a566`. The exact implementation range is `8d7a566..e360fe8`, and `e360fe8` is the final implementation delivery endpoint. This report update may be committed after that endpoint; it is documentation-only and does not redefine the implementation endpoint. Delivery status is branch-local: it means the implementation and gates below pass on this branch. It does not claim integration to `master`, a packaged-application smoke test, or deployment.

The approved spec and plan at the front-matter paths were outside the isolated implementation branch and are not part of the implementation range, but they are tracked with the integrated delivery on `master`. Some foundational contracts described by the spec, including public SPA asset routing, the normal `lan_token` browser session, scoped share-cookie helpers, batch JSON/Blob transport, and backend-shaped detail/share types, existed at the base. Batch C retained their regression coverage and hardened the failure modes listed below rather than reimplementing unchanged baseline code.

## Delivered Behavior

### P0: SPA Bootstrap, Authentication, and WebSocket Reliability

- Preserved the public `/assets/*` and `/static/*` bootstrap boundary while protected APIs remain subject to middleware and route authorization. Segment-boundary tests prevent similarly prefixed paths from inheriting public treatment.
- Preserved same-origin HttpOnly `lan_token` cookie authentication for browser requests and WebSocket handshakes. Explicit Bearer credentials take precedence over stale cookies; deprecated query credentials remain outside new SPA flows.
- Changed `/ws` to trust middleware-installed user context, reject `?token=` and `?key=` even when valid, reject unauthenticated handshakes before registration, and cap concurrent clients.
- Added one concurrent, bounded heartbeat cycle for all sockets. Every PING has a unique byte payload and only the correlated PONG satisfies that client's waiter; missing, unrelated, failed, or slow responses are removed and closed without holding the client lock. Waiters and heartbeat tasks are cleaned on removal/shutdown.
- Bounded the React hook to one retry after an unexpected close, no retry after intentional cleanup, no unauthenticated connection, and one replacement when authentication becomes enabled.
- Confirmed tunnel status requires an authenticated administrator and open registration remains exposed consistently in both access-key and password login modes.

### P1: Share and Download Contracts

- Browser password-share verification omits the token from the response and sets a scoped HttpOnly `share_token` cookie. An explicit `X-AssetsManager-API-Client: 1` request instead returns `{token, share}` without setting the cookie; the returned token is bound to that share.
- Existing share-cookie scope, `SameSite=Lax`, one-hour lifetime, share binding, expiry, preview/download authorization, path containment, and download-count protections remain covered.
- Normal and shared downloads now emit sanitized `Content-Disposition` values. Non-ASCII names receive an ASCII fallback plus RFC 5987 `filename*=UTF-8''...`, preventing raw unsafe header values while retaining the intended filename.
- Existing single-file cookie-backed navigation, JSON batch-download/Blob handling, share state replacement, and detail response contracts remain covered by backend and frontend contract tests.

### P1-P2: React Lifecycle, Navigation, i18n, Accessibility, and Mobile

- Added disposal, abort, and generation guards so superseded project lists, sidebar trees, header searches, tag searches, and metadata requests cannot overwrite newer state or clear a newer loading state. URL navigation invalidates pending tag and metadata work.
- Stabilized search API wrappers and status polling; polling owns one interval and translated status text rerenders when language changes.
- Made Browse tag results update the `path` query, synchronized router path changes, and prevented stale tag results from navigating after a newer search or URL change.
- Made metadata URL parsing defensive in Python and restricted rendered links to absolute HTTP(S). Malformed URLs are discarded instead of failing the response.
- Added localized English, Chinese, and Japanese labels for search-empty state, disclosure controls, password visibility, sidebar/info controls, and mobile selection completion.
- Replaced hover-only header menus with controlled native-button disclosures, outside-click/Escape closing, focus restoration, and correct Enter/Space activation.
- Added accessible names to icon-only controls, hid decorative icons, added toast/live status semantics, and separated asset selection from detail activation for keyboard users.
- Wired mobile information-panel state and grid/list selection mode. Normal mobile activation opens detail; explicit selection mode selects without issuing metadata requests, exposes `aria-pressed`, and provides a localized Done action.
- Completed the final frontend metadata/selection/i18n hardening in `ffb9497`, then localized project controls and admin management labels through `e360fe8`; metadata requests preserve abort handling, mobile selection avoids accidental detail fetches, responsive info controls stay state-consistent, and the added labels are localized in English, Chinese, and Japanese.

### P2: Legacy Fallback

- Corrected the legacy user-dropdown outside-click selector from `.header__user` to the actual `.app-header__user` markup.
- Retained regression coverage for the shared `image-viewer.visible` contract across `app.js`, `detail.js`, `share.js`, and `style.css`.
- Retained case-insensitive nested `.bak`/`.bak2` rejection and offline operation without mandatory Google Fonts or unpkg resources.
- The legacy UI remains a stopgap fallback when `webui/dist/index.html` is unavailable; no feature-parity claim is made.

## Spec Coverage

| Spec | Branch-local implementation and retained contract evidence | Changed files and tests |
|---|---|---|
| S2 Deployment truth and routing | Public SPA/legacy resources and explicit SPA fallback behavior were retained and regression-tested; `/ws` remained separate and authenticated. | `tests/lan/test_lan_api.py`, `tests/lan/test_t2_t4_contracts.py`; auth boundary touched in `AssetsManager/lan/server.py`. |
| S3 Authentication and download transport | Bearer-over-cookie precedence; no WebSocket query auth; browser share verification uses a scoped cookie while explicit API-client verification returns a share-bound bearer token; safe normal/share filenames. Existing user/share cookies and JSON batch transport remained covered. | `AssetsManager/lan/routes/_helpers.py`, `server.py`, `shares.py`, `downloads.py`; `tests/lan/test_helpers.py`, `test_lan_api.py`, `test_t2_t4_contracts.py`. |
| S4 React API/lifecycle rules | Stable search wrapper, stale/disposal guards for search/tree/project/metadata work, metadata aborts, one polling interval. Existing thumbnail stability remained in the full SPA suite. | `webui/src/api/metadata.ts`, `hooks/useSearch.ts`, `pages/BrowsePage.tsx`, `components/layout/Sidebar.tsx`, `StatusBar.tsx`; corresponding `useSearch`, `useProjects`, `BrowsePage`, `Sidebar`, and `StatusBar` tests. |
| S5 WebSocket contract | Middleware-context authorization, query-token rejection, connection cap, bounded correlated-PONG heartbeat, dead-client isolation, bounded frontend reconnect. | `AssetsManager/lan/routes/websocket.py`, `lan/ws.py`, `lan/server.py`, `webui/src/hooks/useWebSocket.ts`; `tests/lan/test_lan_api.py`, `test_t2_t4_contracts.py`, `webui/src/hooks/useWebSocket.test.tsx`. |
| S6 Backend/frontend response contract | Existing detail/share fixtures remained covered; browser verification uses a scoped HttpOnly cookie, while explicit API-client verification returns a share-bound token without setting a cookie; Unicode download response headers are hardened. | `AssetsManager/lan/routes/shares.py`, `downloads.py`; `tests/lan/test_lan_api.py`; retained `webui/src/api/files-shares.contract.test.ts` in the full SPA run. |
| S7 Active SPA functional repairs | Path-query navigation, localized rerenders, metadata URL filtering, mobile info/select behavior, registration affordance, and accessible controls. | `metadata.py`, `webui/src/pages/BrowsePage.tsx`, `LoginPage.tsx`, layout/file/admin/toast components, `webui/src/i18n/{en,zh,ja}.ts`; new/updated component and page tests. |
| S8 Legacy fallback | Dropdown selector fixed; viewer-class, backup rejection, and offline-dependency contracts retained. | `AssetsManager/lan/static/app.js`; fallback assertions in `tests/lan/test_lan_api.py`. |
| S9 Security and policy | Explicit Bearer wins over stale cookie, WebSocket query credentials are rejected, tunnel status is admin-only, malformed metadata URLs are discarded, and share/download protections remain covered. | `_helpers.py`, `server.py`, `metadata.py`, `shares.py`, `websocket.py`; `tests/lan/test_helpers.py`, `test_lan_api.py`, `test_t2_t4_contracts.py`; `LoginPage.test.tsx`. |
| S10 Test strategy/gates | Backend route, heartbeat, share/download, lifecycle, navigation, i18n, accessibility, mobile, fallback, full Python, full SPA, type, build, and architecture gates passed. | `tests/lan/*.py`, 17 WebUI test files, and the verification commands below. |
| S11 Delivery phases | Branch commits progress through P0 WebSocket/auth, P1 share/download, P1 lifecycle, P2 navigation/accessibility/mobile, fallback, correlated-PONG heartbeat completion, final frontend metadata/selection/i18n hardening, restored API-client share tokens, localized project controls and admin labels, heartbeat duplicate-close cleanup, and audited reporting. | Complete implementation range through `e360fe8`. |

## Verification

The following commands and results are the current known verification record for implementation endpoint `e360fe8`; fresh verification may be rerun after this report-only update:

- `python -m ruff check . --exclude ".Cython&Noikta"`: `All checks passed!`
- `python -m pyright`: `0 errors, 0 warnings, 0 informations` (plus an informational newer-version notice).
- `python -m compileall AssetsManager -q`: passed with no output.
- `python -m pytest -q`: `833 passed` (current known Python test count; fresh verification may be rerun).
- `python -m pytest tests/unit/test_architecture_boundaries.py -q`: `15 passed in 6.63s`.
- `npm ci` from `webui/`: installed/audited `238 packages`; npm reported `5 vulnerabilities (3 moderate, 1 high, 1 critical)`.
- `npm test -- --run` from `webui/`: `17 passed` test files and `57 passed` tests (current known WebUI count); React Router emitted only v7 future-flag warnings. Fresh verification may be rerun.
- `npm run typecheck` from `webui/`: passed with no TypeScript errors.
- `npm run build` from `webui/`: passed; Vite transformed `1621 modules` and built in `5.58s`.

Earlier fallback TDD evidence recorded on this branch was `1 failed, 2 passed, 107 deselected` before the selector fix and `3 passed, 107 deselected` afterward. The final full suites supersede the earlier aggregate of 827 Python tests.

No manual browser end-to-end pass was run. No packaged-application smoke test, deployment test, or independent `npm audit` remediation was run, and none is claimed.

## Residual Risks

- Automated jsdom and aiohttp coverage does not replace a manual LAN browser pass across unauthenticated login, authenticated Browse/Detail, password shares, native downloads, live WebSocket status, mobile drawers/selection, and forced legacy fallback.
- `npm ci` reports five known dependency vulnerabilities: three moderate, one high, and one critical. This batch did not run a potentially breaking `npm audit fix --force` or otherwise remediate them.
- WebSocket heartbeat behavior is comprehensively unit/integration tested, but real proxy, sleep/wake, packet-loss, and many-client timing behavior still needs deployment-level observation.
- After the last ordinary client disconnect, the heartbeat task can remain asleep until the next 30-second cycle before exiting. It retains no client or PONG waiter, does not block requests, and `close_all()` cancels it promptly during server shutdown, so this is a non-blocking cleanup delay rather than a shutdown blocker.
- The implementation range does not contain the approved spec/plan files themselves; the integrated `master` delivery tracks them at the referenced paths.
- Legacy fallback remains intentionally below SPA feature parity and receives only isolated-LAN and essential-interaction safeguards.

## Lessons

- Delivery reports must audit the entire base-to-HEAD range; a late fallback commit is not representative of a multi-phase branch.
- Cookie-authenticated WebSockets still need explicit query-credential rejection, and a successful PING write is not liveness evidence without a bounded, payload-correlated PONG.
- Concurrent heartbeat checks avoid one slow client serially delaying every other client, but all waiter registration and cleanup paths need tests to prevent retained state.
- Async UI correctness requires guarding success, failure, and `finally`; guarding only the successful result still lets stale cleanup corrupt current loading state.
- URL navigation is itself an invalidation event for outstanding tag and metadata requests.
- Native button keyboard behavior is safer than duplicating Enter/Space handlers, which can double-toggle disclosures.
- Download filenames need both sanitization and standards-compliant non-ASCII encoding; interpolating a cleaned Unicode value directly into a header is insufficient.
- Verification evidence should separate branch-local delivery, anchor-workspace documentation, manual browser coverage, package audit state, and master/package integration claims.

## Commit Accounting

The exact implementation range is `8d7a566..e360fe8`. It contains the implementation commits listed below, including the final implementation endpoint `e360fe8`:

| Commit | Delivery contribution |
|---|---|
| `c44bfdc` | Hardened LAN WebSocket authentication. |
| `17fc6aa` | Bounded frontend reconnect and initial heartbeat behavior. |
| `898010e` | Hardened share/download response contracts. |
| `40c4c60` | Made LAN WebSocket heartbeat checks concurrent. |
| `1f30912` | Hardened WebUI request lifecycles. |
| `bea25c0` | Prevented stale Browse search updates. |
| `a41b92b` | Ignored stale Browse tag searches. |
| `b29c4fc` | Invalidated tag search on URL navigation. |
| `572a952` | Aligned WebUI accessibility policies. |
| `2b86dac` | Hardened LAN metadata and mobile accessibility. |
| `2380da0` | Made header disclosures state-controlled. |
| `f80fc25` | Relied on native header button activation. |
| `0fe8ea0` | Hardened legacy LAN fallback interactions. |
| `d174a4e` | Recorded intermediate Batch C LAN WebUI evidence. |
| `de900b0` | Finalized intermediate Batch C commit evidence. |
| `f3c6676` | Completed the unique-payload, correlated-PONG heartbeat and its regression coverage. |
| `ffb9497` | Completed frontend metadata, mobile selection, responsive state, and i18n hardening. |
| `038961c` | Audited and updated this delivery report; the report is included in the delivery range. |
| `e267869` | Added the WebUI test step to CI. |
| `d7cd35b` | Finalized the prior delivery accounting; documentation-only and not the implementation endpoint. |
| `504af1f` | Restored API-client share tokens and updated the LAN API contract tests. |
| `8ecf1fe` | Localized project controls and fixed heartbeat duplicate-close cleanup. |
| `e360fe8` | Localized admin management labels; this is the final implementation delivery endpoint. |

The report update commit follows `e360fe8` and is documentation-only; it does not redefine the implementation endpoint or imply that the report-only commit is an implementation change. If implementation changes after `e360fe8`, establish a new reviewed endpoint and rerun the affected gates before treating this report as current.
