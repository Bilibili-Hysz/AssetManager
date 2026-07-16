# LAN WebUI Reliability Repair Design

**Status:** Approved for planning

## [S1] Problem and Scope

The LAN server currently serves the React SPA whenever `webui/dist/index.html` exists. This is the active deployment mode. `AssetsManager/lan/static/` is a fallback only when the SPA build is missing.

The active SPA has blocking defects in static asset authentication, password-protected shares, API response typing, download transport, React request lifecycles, and WebSocket behavior. The fallback UI has separate visual and deployment risks but is not the primary product path.

This repair covers:

- The active React SPA under `webui/src/` and its Vite build output contract.
- The aiohttp page/static/auth/share/download/WebSocket integration required by that SPA.
- Minimal fallback WebUI risk reduction only: broken image viewer class, exposed `.bak` files, and external CDN reliance.

This repair does not redesign the visual system, replace React Router, replace aiohttp, or add a new i18n framework.

## [S2] Deployment Truth and Routing Contract

`webui/dist/index.html` is the active page shell when present. The server must expose this behavior consistently:

| Request | Expected response |
|---|---|
| `/`, `/browse`, `/detail`, `/login`, `/s/{id}` | SPA `index.html` when the build exists; legacy corresponding page otherwise |
| `/assets/{file}` | Vite output, publicly readable before login |
| `/static/{file}` | Legacy static resource, publicly readable |
| `/api/*` | Existing authentication middleware and route-level authorization |
| `/ws` | Authenticated real-time endpoint when an authenticated user/session exists |

The public route classification must include `/assets` alongside `/static`, because the public SPA shell cannot bootstrap without its JavaScript and CSS. Asset paths must remain same-origin and must not require an application token before the login page renders.

Page routes remain explicit for the current Router paths. The implementation must add a controlled SPA fallback only for future non-API, non-static GET page routes if it can do so without shadowing API, `/assets`, `/static`, `/ws`, or share/download endpoints. Otherwise, the Router path list and aiohttp route list must be maintained together and covered by tests.

## [S3] Authentication and Download Transport

### User sessions

The existing `lan_token` HttpOnly cookie is the browser-navigation credential. It must be set by successful user/password/access-key authentication and remain usable by:

- `fetch` requests with same-origin credentials;
- plain `<a>` downloads;
- `window.open()` downloads;
- form-based browser downloads, if retained;
- WebSocket handshakes.

The React API client may continue to attach a Bearer token for compatibility, but sessionStorage is not the sole authorization source for routes that a browser navigation cannot header-authenticate. API client responses must treat a cookie-authenticated session as valid even when no sessionStorage token exists.

### Share sessions

Password verification for a share must set a distinct HttpOnly share cookie. The cookie must be:

- scoped to the share API path (or a similarly narrow share-only scope);
- `SameSite=Lax`;
- time-limited to the existing share-token lifetime;
- independent from the user `lan_token` cookie;
- cleared or naturally expired without affecting a normal user session.

The server validates this cookie only for the share ID it represents. For password-protected `GET /api/shares/{id}/info`, missing or mismatched cookies return a deliberately sanitized `200` response containing only password/expiry/preview status needed to render the password prompt; a matching cookie returns the full public share. Preview and download require a matching cookie and return `401` on absence or mismatch. The SPA must update its `shareInfo` from the successful verify response (`res.share`), but must not persist the raw share token in URL query strings, localStorage, or sessionStorage.

This allows image `src`, preview URLs, and native anchor downloads to work after verification without exposing credentials through browser history, referrers, access logs, or copied links.

### Download transport

The SPA must use a consistent transport per endpoint:

- Single-file normal download: a same-origin navigation is permitted because the session cookie is sent.
- Batch download: client sends JSON `{ "paths": [...] }` through the authenticated API client, receives a Blob, and triggers a local object-URL download. It must not submit an HTML form because the backend requires JSON.
- Password-protected share download: a same-origin anchor is permitted after share-cookie verification.

The implementation must not use deprecated query `?token=` or `?key=` authentication for new SPA flows.

## [S4] React API Client and Lifecycle Rules

API wrapper instances are stable for the lifetime of their auth context. Components must not create wrapper objects during render and then place those wrappers in effect dependency arrays.

The architecture is:

1. `AuthContext` creates stable `ApiClient`, auth API, and system API objects when its token/session source changes.
2. Feature hooks either obtain a stable client from context or create memoized wrapper objects from that client.
3. Network requests run only in `useEffect`, event handlers, or explicit callbacks; never in render or a `useState` initializer.
4. Requests that may be superseded by navigation use `AbortController` or an equivalent generation guard. Stale results must not overwrite current page state.
5. Thumbnail cache updates use React state/versioning so successful asynchronous loads visibly rerender consumers.

Required lifecycle corrections:

- `useProjects` moves its initial fetch to an effect and reacts to query-path changes.
- Detail, Sidebar, StatusBar, admin list, and other API-consuming components have stable request dependencies.
- Browse thumbnails load from an effect keyed by visible items, not while rendering.
- Status polling owns at most one interval and cleans it up on unmount/change.

## [S5] WebSocket Contract

The WebSocket hook receives stable `getToken` and `onEvent` callbacks. It must distinguish intentional cleanup from an unexpected socket close:

- cleanup clears pending reconnect timers and closes the current socket without scheduling a reconnect;
- unexpected close schedules exactly one bounded exponential retry;
- changing auth state replaces the connection once;
- unauthenticated Browse does not initiate a guaranteed-failing `/ws` connection.

The preferred authenticated browser transport is the existing same-origin `lan_token` cookie. The SPA must not append long-lived Bearer credentials as a `?token=` query parameter. The server WebSocket handler should consume middleware-provided auth context rather than independently requiring a second token verification after middleware already authorized the request.

StatusBar must render the hook's returned connection state rather than an unrelated local default.

## [S6] Backend-to-Frontend Response Contract

`webui/src/types/api.ts` is a contract mirror of backend `to_response()` / `to_public_dict()` results. It must be updated from actual backend serializer outputs, not inferred UI needs.

For project detail responses:

- File items expose `name`, `size`, `size_fmt`, `extension`, and `category`; any URL/path needed for download is constructed from the project path plus file name unless the backend intentionally adds a serialized URL.
- Image items expose `name`, `url`, and `thumb_url`; components must use `url` for the full viewer and `thumb_url` for gallery previews.

Share verification responses contain `{ token, share }`. After verification the SPA replaces limited pre-auth share data with `share`, enabling the protected share page to display `paths`, preview permission, expiry, and counters.

Type/API tests must compare representative frontend parsing and URL construction against response fixtures derived from backend serializers.

## [S7] Active SPA Functional Repairs

The SPA repair includes these concrete user-facing behaviors:

- Login and public share pages render under auth because their `/assets/*` dependencies are public.
- Auth-enabled landing behavior sends users without an active valid session to `/login`, unless the backend explicitly exposes an allowed guest capability profile.
- Detail page gallery uses actual `url` / `thumb_url`; file downloads use a valid relative path.
- Batch download sends JSON and downloads the returned archive Blob.
- Password-protected shares show paths immediately after verification, and their preview/download controls function without URL tokens.
- Header search path navigation updates Browse state when `path` query changes.
- Language changes trigger rerendering of all components that render translated text.
- Mobile UI exposes a usable information panel and wires its bottom-bar view/select controls.
- Metadata URLs are accepted only for `http:` and `https:` schemes before rendering clickable anchors.
- Interactive icon controls have accessible names; toast/live status surfaces use appropriate ARIA live semantics.

## [S8] Legacy Fallback Risk Reduction

Legacy `lan/static/` is retained as a deployment fallback but does not receive feature-parity work in this repair.

Required fallback changes:

- Standardize image viewer open/close class names across `app.js`, `detail.js`, `share.js`, and CSS.
- Do not serve `.bak` / `.bak2` files from the legacy static directory. Move these out of `lan/static` or make the static handler reject backup extensions.
- Eliminate mandatory external Google Fonts and unpkg dependencies for fallback operation on isolated LANs. Use system font fallbacks and locally bundled or inline icons already available to the project.
- Correct the user-dropdown outside-click selector and the highest-impact CSS class drift that makes essential controls invisible.

## [S9] Security and Policy Corrections

- `/api/tunnel/status` must require authentication unless a product decision explicitly documents public tunnel URL disclosure.
- Registration UI and endpoint exposure must match the chosen registration policy. If invite-only, registration requires a valid invite and the UI says so; if open registration, that is documented as an intentional LAN policy.
- `get_auth_token()` must not allow a stale cookie to mask a valid explicit Authorization header. Prefer a valid explicit Bearer credential when supplied, otherwise fall back to cookie.
- Share and normal download authorization must continue to pass existing path containment, expiry, count, role/capability, and ZIP-size protections.

## [S10] Test Strategy and Acceptance Gates

### Backend route/integration tests

- Auth-enabled `GET /login` and `GET /s/{id}` followed by `GET /assets/{bundle}` return successful SPA resources without credentials.
- Protected API endpoints still return 401/403 without valid auth.
- Share password verify sets the scoped share cookie; password-protected info is sanitized without or with a mismatched cookie and complete with the matching cookie; preview/download succeed only with the matching cookie and fail without it.
- Batch download accepts JSON and rejects form-encoded input with a deliberate error, or the frontend no longer submits form data.
- Tunnel status follows its final selected access policy.
- WebSocket uses the already-verified middleware context and does not require query token transport.

### SPA unit/component tests

- API wrappers are stable across rerenders; Detail/Sidebar/StatusBar do not refetch solely because local state updates.
- `useProjects` fetches after mount and on path/sort change, never during render.
- Detail fixtures use backend-shaped files/images and render valid image/download URLs.
- Password share verify replaces `shareInfo` with returned `share` and enables display/download through cookie-backed requests.
- Browse path query updates the rendered directory.
- Language change rerenders text in at least Header, Browse, Detail, and Share pages.
- Mobile layout exposes information access.

### Build and regression gates

- `python -m pytest tests/lan -q`
- New targeted backend route tests pass.
- `npm run typecheck` and `npm run build` in `webui/` pass.
- New SPA test command passes when a test runner is added or configured.
- Manual smoke path: unauthenticated login shell; authenticated Browse; Detail image/file; batch download; public plain share; password share; WebSocket status; mobile info panel; fallback launch with SPA build intentionally unavailable.

## [S11] Delivery Phases

1. **P0 - SPA bootstrap and auth transport:** public `/assets`, cookie/session alignment, WebSocket auth/cleanup, tunnel/registration policy.
2. **P1 - Share and download correctness:** share cookie, share state replacement, batch JSON Blob download, detail file/image contract alignment.
3. **P1 - React lifecycle correctness:** stable clients, effects, abort/generation control, thumbnails, status state.
4. **P2 - Navigation, i18n, responsive, accessibility:** query navigation, global language state, mobile info controls, URL scheme validation, ARIA labels.
5. **P2 - Legacy fallback stopgap:** image viewer, backup artifact isolation, offline dependency removal, essential CSS selector corrections.

Each phase must retain passing prior-phase tests. P0 and P1 are required before a LAN build is considered release-ready; P2 can follow only after the primary SPA path is operational.
