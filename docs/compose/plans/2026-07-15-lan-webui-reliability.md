# LAN WebUI Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the active React LAN SPA boot under authentication and repair its core auth, share, download, and data-contract flows.

**Architecture:** Fix the server/public-resource boundary first, then share/download transport, then React request lifecycle and API shape alignment. Retain `lan/static` only as a safe fallback.

**Tech Stack:** aiohttp, Python, React 18, TypeScript, Vite.

## Global Constraints

- SPA is the primary UI when `webui/dist/index.html` exists.
- Do not put new auth tokens in query strings, localStorage, or sessionStorage for share flows.
- Preserve existing route-level permissions and share containment checks.
- Legacy UI receives fallback-risk fixes only.

---

### Task 1: Public SPA Assets and Scoped Share Cookie

**Covers:** [S2, S3, S9, S10]

**Files:**
- Modify: `AssetsManager/lan/server.py`
- Modify: `AssetsManager/lan/routes/_helpers.py`
- Modify: `AssetsManager/lan/routes/shares.py`
- Test: `tests/lan/test_lan_api.py`

- [ ] Add failing tests for unauthenticated `/assets/*` access and password-share cookie verification.
- [ ] Run `python -m pytest tests/lan/test_lan_api.py -q -k "assets or share"` and confirm RED.
- [ ] Make `/assets` public; set/read a share-scoped HttpOnly cookie after successful password verification.
- [ ] Re-run focused tests until GREEN.

### Task 2: SPA Share and Download Contract

**Covers:** [S3, S6, S7, S10]

**Files:**
- Modify: `webui/src/api/files.ts`
- Modify: `webui/src/api/shares.ts`
- Modify: `webui/src/pages/ShareReceivePage.tsx`
- Modify: `webui/src/pages/DetailPage.tsx`
- Modify: `webui/src/types/api.ts`
- Test: `webui/src/**/*.test.tsx` or configured SPA test runner

- [ ] Add failing tests/fixtures for verified share state, project image URLs, project file download paths, and JSON batch download.
- [ ] Send batch paths as JSON through the API client and download the returned Blob.
- [ ] Replace limited pre-verify share state with `res.share`; rely on the scoped share cookie for native preview/download URLs.
- [ ] Align detail types/components with backend `{name,url,thumb_url}` images and file name-based paths.
- [ ] Run `npm run typecheck && npm run build`.

### Task 3: Stable React Requests and WebSocket

**Covers:** [S4, S5, S7, S10]

**Files:**
- Modify: `webui/src/stores/AuthContext.tsx`
- Modify: `webui/src/hooks/useProjects.ts`
- Modify: `webui/src/hooks/useThumbnailCache.ts`
- Modify: `webui/src/hooks/useWebSocket.ts`
- Modify: `webui/src/pages/BrowsePage.tsx`
- Modify: `webui/src/pages/DetailPage.tsx`
- Modify: `webui/src/components/layout/{Sidebar,StatusBar}.tsx`
- Test: SPA test files

- [ ] Write failing tests for no render-time requests, query-path refresh, and stable WebSocket cleanup.
- [ ] Memoize API wrappers; move requests to effects with abort/generation guards.
- [ ] Render thumbnail cache from state/version changes; wire StatusBar to hook status.
- [ ] Do not open unauthenticated sockets; suppress reconnect after intentional cleanup.
- [ ] Run SPA tests, `npm run typecheck`, and `npm run build`.

### Task 4: Policy and Legacy Stopgap

**Covers:** [S7, S8, S9, S10]

**Files:**
- Modify: `AssetsManager/lan/server.py`, `AssetsManager/lan/routes/system.py`
- Modify: `webui/src/components/{layout,ui}/**/*.tsx`, `webui/src/pages/*.tsx`
- Modify: `AssetsManager/lan/static/{app.js,detail.js,share.js,style.css,index.html}`
- Test: `tests/lan/test_lan_api.py`

- [ ] Add policy tests for tunnel status authentication.
- [ ] Validate metadata URL schemes, language reactivity, mobile info access, and accessible names.
- [ ] Fix fallback viewer selector, remove/move `.bak` static artifacts, and eliminate mandatory external CDN dependency.
- [ ] Run `python -m pytest tests/lan -q && npm run typecheck && npm run build`.
