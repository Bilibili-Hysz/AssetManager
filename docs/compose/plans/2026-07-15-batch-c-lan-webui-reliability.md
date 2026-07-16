# Batch C LAN WebUI Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the active React LAN SPA reliable under authentication and repair its share, download, request-lifecycle, WebSocket, policy, accessibility, and legacy-fallback contracts.

**Architecture:** Preserve aiohttp and the existing React/Vite architecture. Fix the server resource/auth boundary first, then align share/download transport and backend response types, then stabilize React effects and WebSocket cleanup, and finally apply policy/accessibility and minimal legacy fallback repairs. Keep all new behavior behind existing application/service and route boundaries; do not add a new auth or i18n framework.

**Tech Stack:** Python 3.14, aiohttp, pytest, React, TypeScript, Vite, npm.

## Global Constraints

- `webui/dist/index.html` is the active page shell when present; `lan/static` remains a fallback only.
- Do not put new auth tokens in query strings, localStorage, or sessionStorage for share flows.
- Preserve existing route-level permissions, path containment, expiry, download-count, role/capability, and ZIP-size protections.
- Browser navigation and WebSocket authentication use same-origin HttpOnly cookies; middleware-installed request auth context is the source for the WebSocket handler.
- Network requests run only in effects, event handlers, or explicit callbacks; never during render or a `useState` initializer.
- Legacy UI receives fallback-risk fixes only; it does not receive feature-parity work.
- Use TDD for behavior changes: add a failing focused regression test, run it RED, implement the smallest fix, then run it GREEN.
- Run `python -m ruff check . --exclude ".Cython&Noikta"`, `python -m pyright`, `python -m compileall AssetsManager -q`, and `python -m pytest -q` before delivery; run WebUI `npm ci`, `npm run typecheck`, and `npm run build` from `webui/`.

---

### Task 1: SPA Bootstrap, Authentication, and WebSocket Boundary

**Covers:** [S2, S3, S5, S9, S10]

**Files:**
- Modify: `AssetsManager/lan/server.py`
- Modify: `AssetsManager/lan/routes/_helpers.py`
- Modify: `AssetsManager/lan/routes/websocket.py`
- Modify: `AssetsManager/lan/ws.py`
- Modify: `AssetsManager/lan/routes/system.py`
- Modify: `webui/src/stores/AuthContext.tsx`
- Modify: `webui/src/hooks/useWebSocket.ts`
- Modify: `webui/src/components/layout/StatusBar.tsx`
- Test: `tests/lan/test_lan_api.py`
- Test: `tests/lan/test_t2_t4_contracts.py`
- Test: `tests/lan/test_helpers.py`

**Interfaces:**
- Consumes: existing `_auth_middleware`, `get_request_user(request)`, `WebSocketManager`, `lan_token` cookie, and `AuthContext` session state.
- Produces: public `/assets/*` and `/static/*` resource behavior, authenticated `/ws` behavior without query-token transport, stable WebSocket cleanup/reconnect semantics, and authenticated tunnel-status policy.

- [ ] **Step 1: Add failing backend contract tests** for unauthenticated `/assets/<bundle>`, authenticated/protected `/ws`, rejection of `?token=`, and the selected `/api/tunnel/status` policy. Assert that the WebSocket handler consumes middleware context instead of independently parsing a query token.
- [ ] **Step 2: Run focused tests to verify RED**:
  `python -m pytest tests/lan/test_lan_api.py tests/lan/test_t2_t4_contracts.py tests/lan/test_helpers.py -q -k "assets or websocket or tunnel or query_token"`.
- [ ] **Step 3: Make `/assets` public in middleware and retain route-level protection for `/api/*`**. Keep explicit page routes and legacy `/static` behavior unchanged except for the public-resource classification. Ensure `get_auth_token()` prefers a valid explicit Bearer header over a stale cookie and only logs deprecation warnings for legacy query credentials.
- [ ] **Step 4: Make the WebSocket route authorize from `get_request_user(request)`**, reject unauthenticated connections before registration, and add bounded connection cleanup: one heartbeat/ping mechanism, a maximum connection count, dead-client removal, and no reconnect scheduling after intentional close.
- [ ] **Step 5: Update React auth/WebSocket consumers** so no socket opens when unauthenticated, cleanup cancels timers and closes the active socket, unexpected close schedules one bounded retry, auth changes replace the connection once, and `StatusBar` renders the hook's actual state.
- [ ] **Step 6: Run the focused backend and WebUI checks GREEN**:
  `python -m pytest tests/lan/test_lan_api.py tests/lan/test_t2_t4_contracts.py tests/lan/test_helpers.py -q`;
  `npm run typecheck` and `npm run build` from `webui/`.
- [ ] **Step 7: Commit** with `git add AssetsManager/lan tests/lan webui/src && git commit -m "fix: stabilize LAN SPA auth and websocket boundary"`.

### Task 2: Share, Download, and Response Contract

**Covers:** [S3, S6, S7, S10]

**Files:**
- Modify: `AssetsManager/lan/routes/shares.py`
- Modify: `AssetsManager/lan/routes/downloads.py`
- Modify: `webui/src/api/files.ts`
- Modify: `webui/src/api/shares.ts`
- Modify: `webui/src/pages/ShareReceivePage.tsx`
- Modify: `webui/src/pages/DetailPage.tsx`
- Modify: `webui/src/types/api.ts`
- Test: `tests/lan/test_lan_api.py`
- Test: `tests/lan/test_helpers.py`
- Test: `webui/src/**/*.test.tsx` or the existing configured SPA test location

**Interfaces:**
- Consumes: scoped HttpOnly share-cookie helpers from Task 1, backend `to_response()`/`to_public_dict()` serializers, and the existing API client Blob support.
- Produces: cookie-backed password-share info/preview/download, JSON batch-download Blob transport, sanitized download headers, and frontend types matching actual backend payloads.

- [ ] **Step 1: Add failing backend tests** for share-cookie scope and lifetime, sanitized password-share info without/mismatched cookie, full info with matching cookie, preview/download rejection without the cookie, JSON batch download, and safe `Content-Disposition` filenames including non-ASCII names.
- [ ] **Step 2: Add failing SPA fixtures/tests** asserting verification replaces limited `shareInfo` with `res.share`, image fields use `url`/`thumb_url`, file downloads build a valid relative path from the project path and file name, and batch download sends `{ paths }` and handles a Blob.
- [ ] **Step 3: Run the focused tests to verify RED** with `python -m pytest tests/lan/test_lan_api.py tests/lan/test_helpers.py -q -k "share or download or filename"` and the configured WebUI test command if present.
- [ ] **Step 4: Implement the minimal server contract**: set the distinct HttpOnly `share_token` cookie scoped to the share API, validate it against the requested share ID, return sanitized limited info for missing/mismatched credentials, preserve existing authorization checks, and emit safe `Content-Disposition` values using the shared filename sanitizer and `filename*` for non-ASCII names where required.
- [ ] **Step 5: Implement the minimal SPA contract**: use cookie-backed native navigation for single/share downloads, send JSON through the authenticated client for batch downloads, never persist share tokens, replace pre-verification state from the verify response, and align `ProjectDetail` types/components with backend serializers.
- [ ] **Step 6: Run focused backend and WebUI checks GREEN**:
  `python -m pytest tests/lan/test_lan_api.py tests/lan/test_helpers.py -q`;
  `npm run typecheck` and `npm run build` from `webui/`.
- [ ] **Step 7: Commit** with `git add AssetsManager/lan webui/src tests/lan && git commit -m "fix: align SPA share and download contracts"`.

### Task 3: React Request Lifecycle and Navigation State

**Covers:** [S4, S7, S10]

**Files:**
- Modify: `webui/src/hooks/useProjects.ts`
- Modify: `webui/src/hooks/useThumbnailCache.ts`
- Modify: `webui/src/pages/BrowsePage.tsx`
- Modify: `webui/src/pages/DetailPage.tsx`
- Modify: `webui/src/components/layout/Sidebar.tsx`
- Modify: `webui/src/components/layout/StatusBar.tsx`
- Modify: `webui/src/components/layout/Header.tsx`
- Test: existing configured WebUI unit/component test files

**Interfaces:**
- Consumes: stable API objects from `AuthContext`, Task 2 API types, and the existing `useI18n`, `useTheme`, and routing/query-state APIs.
- Produces: effect-only requests with abort/generation guards, stable dependencies, visible thumbnail state updates, path-query navigation, and reactive language changes.

- [ ] **Step 1: Add failing tests** proving `useProjects` does not fetch during render, refetches after mount and on path/sort changes, stale responses cannot overwrite current state, thumbnail completion causes a rerender, and rerenders do not create duplicate polling intervals.
- [ ] **Step 2: Run the configured SPA test command to verify RED**; if the repository has no test script, add only the smallest existing-compatible test runner configuration needed for these tests and record it in `webui/package.json`.
- [ ] **Step 3: Move all initial and path-dependent fetches into `useEffect`**, use `AbortController` or a generation guard for superseded requests, and keep API wrapper dependencies stable by obtaining them from `AuthContext` rather than constructing them during render.
- [ ] **Step 4: Make thumbnail cache updates state/version-driven**, key loading by visible items, and ensure status polling owns at most one interval with cleanup on unmount or dependency change.
- [ ] **Step 5: Wire header search path changes into Browse state**, ensure language changes rerender Header/Browse/Detail/Share text through `useI18n`, and preserve existing `useTheme` persistence rather than introducing duplicate theme state.
- [ ] **Step 6: Run the SPA tests, typecheck, and build GREEN** from `webui/`.
- [ ] **Step 7: Commit** with `git add webui/src webui/package.json webui/package-lock.json && git commit -m "fix: stabilize React request lifecycles"`.

### Task 4: Accessibility, Responsive Controls, and Policy Guardrails

**Covers:** [S7, S9, S10]

**Files:**
- Modify: `AssetsManager/lan/routes/system.py`
- Modify: `webui/src/components/layout/**/*.tsx`
- Modify: `webui/src/components/ui/**/*.tsx`
- Modify: `webui/src/pages/*.tsx`
- Test: `tests/lan/test_lan_api.py`
- Test: existing configured WebUI unit/component test files

**Interfaces:**
- Consumes: Task 2 API contracts and Task 3 stable state/i18n hooks.
- Produces: explicit metadata URL scheme validation, accessible names/live regions, keyboard-operable asset controls, usable mobile information controls, and policy-consistent tunnel/registration behavior.

- [ ] **Step 1: Add failing tests** for tunnel-status authorization, registration policy text/validation, rejection of non-`http:`/`https:` metadata URLs, accessible names on icon controls, live toast/status semantics, keyboard Space/Enter asset interactions, and mobile information-panel controls.
- [ ] **Step 2: Run focused backend and SPA tests to verify RED**.
- [ ] **Step 3: Enforce the existing selected policy** for tunnel status and registration without adding a new permission model; preserve route-level permission checks and return the existing deliberate status codes.
- [ ] **Step 4: Validate metadata URLs before creating anchors**, add labels and ARIA live semantics to interactive controls/status surfaces, and ensure asset cards expose native keyboard behavior with a separately labelled context-action control.
- [ ] **Step 5: Wire mobile bottom-bar information/select controls to the existing panel state**, preserving the shared dialog focus behavior in `webui/src/hooks/useDialogFocus.ts` for drawers and viewers.
- [ ] **Step 6: Run focused tests, `npm run typecheck`, and `npm run build` GREEN**.
- [ ] **Step 7: Commit** with `git add AssetsManager/lan webui/src tests/lan && git commit -m "fix: complete SPA policy and accessibility contracts"`.

### Task 5: Legacy Fallback Stopgap and Batch C Delivery Evidence

**Covers:** [S8, S10, S11]

**Files:**
- Modify: `AssetsManager/lan/static/app.js`
- Modify: `AssetsManager/lan/static/detail.js`
- Modify: `AssetsManager/lan/static/share.js`
- Modify: `AssetsManager/lan/static/style.css`
- Modify: `AssetsManager/lan/static/index.html`
- Modify: `AssetsManager/lan/server.py` or static-serving helper when needed to reject backup suffixes
- Test: `tests/lan/test_lan_api.py`
- Create: `docs/compose/reports/batch-c-lan-webui-reliability.md`

**Interfaces:**
- Consumes: all prior task contracts and the approved Batch C design at `docs/compose/specs/2026-07-15-lan-webui-reliability-design.md`.
- Produces: offline-safe legacy fallback, no served `.bak` artifacts, corrected viewer/control selectors, complete verification evidence, and a final-state delivery report.

- [ ] **Step 1: Add failing fallback tests** for consistent image-viewer open/close classes, backup-file rejection from legacy static serving, offline operation without mandatory Google Fonts/unpkg dependencies, and corrected user-dropdown/essential-control selectors.
- [ ] **Step 2: Run `python -m pytest tests/lan/test_lan_api.py -q -k "static or backup or fallback"` to verify RED**.
- [ ] **Step 3: Apply only the required fallback stopgaps**: standardize viewer class names across legacy scripts/CSS, reject `.bak`/`.bak2` resources or move them outside the served root, replace mandatory external CDN dependencies with system fonts/local or inline assets, and fix the highest-impact selector drift.
- [ ] **Step 4: Run the focused fallback tests GREEN**, then run the complete quality gate:
  `python -m ruff check . --exclude ".Cython&Noikta"`;
  `python -m pyright`;
  `python -m compileall AssetsManager -q`;
  `python -m pytest -q`;
  `npm ci`, `npm run typecheck`, and `npm run build` from `webui/`.
- [ ] **Step 5: Write `docs/compose/reports/batch-c-lan-webui-reliability.md`** with front matter linking this spec and plan, the final commit range, architecture summary, changed behavior, focused/full verification commands and actual outputs, residual risks, and lessons. Do not claim manual browser/package checks unless executed.
- [ ] **Step 6: Run `python -m pytest tests/unit/test_architecture_boundaries.py -q`** and review the complete diff for scope creep, new boundary exceptions, token leakage, and untested fallback paths.
- [ ] **Step 7: Commit** with `git add AssetsManager/lan/static AssetsManager/lan/server.py tests/lan docs/compose/reports/batch-c-lan-webui-reliability.md && git commit -m "docs: finalize Batch C LAN WebUI reliability report"`.

## Self-Review

- Spec coverage: [S2] Task 1; [S3] Tasks 1-2; [S4] Task 3; [S5] Task 1; [S6] Task 2; [S7] Tasks 2-4; [S8] Task 5; [S9] Tasks 1, 2, and 4; [S10] all tasks; [S11] Task 5.
- No `TBD`, `TODO`, or unassigned spec sections are used in this plan.
- Interfaces are stable across tasks: Task 1 supplies cookie/WebSocket behavior, Task 2 consumes it and supplies response types, Task 3 consumes those types and supplies stable UI state, Task 4 consumes that state, and Task 5 verifies the complete deployment/fallback surface.
- `create_folder` and `duplicate` remain outside Batch C, consistent with the previous Batch B scope decision.
