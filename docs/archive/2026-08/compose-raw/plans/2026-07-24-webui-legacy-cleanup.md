# WebUI Legacy Cleanup and Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the legacy LAN WebUI and make the React/Vite build the only page runtime while keeping the existing WebUI source responsibility structure and API contracts.

**Architecture:** Page routes will resolve only `webui/dist/index.html`; absent build output returns an explicit 503. The `/static` legacy asset route and old `AssetsManager/lan/static/` tree will be removed, while `/assets` remains the public Vite asset route. Existing React directories remain in place; cleanup focuses on runtime boundaries, tests, and generated-file hygiene rather than broad file moves.

**Tech Stack:** Python, aiohttp, pytest, React, TypeScript, Vite, Vitest, Testing Library, Git ignore rules.

## Global Constraints

- Remove `AssetsManager/lan/static/` old HTML/JS/CSS/i18n pages and their fallback logic.
- When `webui/dist/index.html` is absent, page routes return HTTP 503 and never serve old static pages.
- Preserve existing `/api`, `/ws`, Cookie authentication, download, thumbnail, and share data protocols.
- Keep the existing `pages / components / api / hooks / stores / types` source boundaries; do not perform a feature-first full migration.
- Remove the old `/static/*` public asset entry; keep `/assets/*` for the React SPA.
- Preserve unrelated user working-tree changes and do not delete RuntimeData or user assets.

---

### Task 1: Make SPA Page Routes Explicit and Remove Legacy Route Wiring

**Covers:** S1, S4, S7, S8

**Files:**
- Modify: `AssetsManager/lan/routes/pages.py`
- Modify: `AssetsManager/lan/routes/shares.py`
- Modify: `AssetsManager/lan/api.py`
- Modify: `AssetsManager/lan/server.py`
- Modify: `AssetsManager/lan/security.py`
- Test: `tests/lan/test_lan_api.py`
- Test: `tests/lan/test_t2_t4_contracts.py`

**Interfaces:**
- Consumes: `SPA_DIR / index.html`, existing aiohttp route setup, public path declarations.
- Produces: page handlers that return SPA index or 503; no `/static` route; `/assets` remains public and served from `webui/dist/assets`.

- [ ] **Step 1: Write failing route-contract tests**

Add tests that invoke page handlers with a missing `webui/dist/index.html` and assert HTTP 503 with a message containing `WebUI` and `build`. Add a test that `/static/index.html` is not registered/served and `/assets` remains public when an assets directory exists. Update the share page test to assert the SPA-or-503 contract rather than legacy `share.html` fallback.

```python
async def test_page_route_reports_missing_react_build(self, tmp_path, monkeypatch):
    monkeypatch.setattr(pages, "SPA_DIR", tmp_path / "missing-webui")
    response = await pages.handle_index(make_request())
    assert response.status == 503
    assert "WebUI" in response.text
    assert "build" in response.text
```

- [ ] **Step 2: Run route tests and verify RED**

Run: `pytest -q tests/lan/test_lan_api.py tests/lan/test_t2_t4_contracts.py -k "legacy_static or fallback or page or assets"`

Expected: FAIL because current handlers serve `AssetsManager/lan/static/*.html` when SPA output is absent and `setup_routes` registers `/static`.

- [ ] **Step 3: Implement the single SPA runtime**

In `pages.py`, replace `STATIC_DIR` fallback reads with one helper that returns `web.FileResponse(SPA_DIR / "index.html")` when it exists and `web.Response(status=503, text="WebUI build unavailable. Run the webui build before starting the LAN server.")` otherwise. Make `handle_index`, `handle_browse_page`, `handle_detail_page`, and `handle_login_page` use that helper. In `shares.py`, make `handle_share_page` use the same SPA-or-503 behavior.

In `api.py`, retain `/assets` registration when `webui/dist/assets` exists and delete the `/static/{filename:.*}` handler. Remove `STATIC_DIR` from `server.py` if it becomes unused. Remove `/static` from public path prefixes and rate-limit skip lists while keeping `/assets` public. Do not alter API route registration.

- [ ] **Step 4: Run focused route tests and verify GREEN**

Run: `pytest -q tests/lan/test_lan_api.py tests/lan/test_t2_t4_contracts.py -k "page or assets or static or fallback or share"`

Expected: page routes return SPA index with a build fixture, return 503 without it, `/static` is unavailable, and `/assets` remains public.

### Task 2: Migrate LAN and Package Tests Away from Old Static Source

**Covers:** S5, S6, S8

**Files:**
- Modify: `tests/lan/test_lan_api.py`
- Modify: `tests/lan/test_t2_t4_contracts.py`
- Modify: `tests/core/test_package_contents.py`
- Modify: any test file found by `rg -n "lan/static|static/(app|detail|login|share|style|icons|i18n)" tests`

**Interfaces:**
- Consumes: Task 1 SPA-or-503 route behavior and existing package resource checker.
- Produces: tests that validate React build resources and removed `/static` behavior without reading old page source.

- [ ] **Step 1: Identify and rewrite legacy-source assertions**

Replace tests that read `AssetsManager/lan/static/*.html`, `*.js`, `*.css`, or old i18n files with tests that either:

1. construct a temporary `webui/dist/index.html` and `webui/dist/assets/app.js` fixture and assert the route serves the fixture; or
2. assert `/static/...` returns 404/503 and does not expose old file content.

Delete tests whose only purpose is checking old viewer implementation details, such as legacy icons, old mobile info access, old script versions, and old HTML script references.

- [ ] **Step 2: Run migrated tests and verify RED/GREEN boundary**

Run before production cleanup: `pytest -q tests/lan/test_lan_api.py tests/lan/test_t2_t4_contracts.py tests/core/test_package_contents.py`

Expected before route/test changes: legacy-only assertions fail after Task 1; after migration they pass against the new SPA contract.

- [ ] **Step 3: Update package-content expectations**

Keep package tests requiring `_internal/webui/dist/index.html` and `_internal/webui/dist/assets`; remove assertions that require old static pages as runtime content. Preserve checks that fail when the React index or assets are missing.

- [ ] **Step 4: Run migrated test set**

Run: `pytest -q tests/lan/test_lan_api.py tests/lan/test_t2_t4_contracts.py tests/core/test_package_contents.py`

Expected: all migrated tests pass with no old static source reads.

### Task 3: Delete Legacy Static Tree and Clean WebUI Generated-File Boundaries

**Covers:** S2, S3, S5, S7

**Files:**
- Delete: `AssetsManager/lan/static/index.html`
- Delete: `AssetsManager/lan/static/detail.html`
- Delete: `AssetsManager/lan/static/login.html`
- Delete: `AssetsManager/lan/static/share.html`
- Delete: `AssetsManager/lan/static/app.js`
- Delete: `AssetsManager/lan/static/detail.js`
- Delete: `AssetsManager/lan/static/login.js`
- Delete: `AssetsManager/lan/static/share.js`
- Delete: `AssetsManager/lan/static/style.css`
- Delete: `AssetsManager/lan/static/detail.css`
- Delete: `AssetsManager/lan/static/icons.js`
- Delete: `AssetsManager/lan/static/i18n.js`
- Delete: `AssetsManager/lan/static/i18n/en.json`
- Delete: `AssetsManager/lan/static/i18n/ja.json`
- Delete: `AssetsManager/lan/static/i18n/zh.json`
- Modify: `.gitignore`
- Modify: `docs/compose/specs/2026-07-24-webui-legacy-cleanup-design.md` only if implementation reveals a contract correction

**Interfaces:**
- Consumes: migrated tests and Task 1 route behavior.
- Produces: one source WebUI tree (`webui/src`) plus generated Vite output boundary; no old static runtime files.

- [ ] **Step 1: Confirm no production references remain**

Run: `rg -n "lan/static|STATIC_DIR|/static/|static_dir|detail\.html|login\.html|share\.html|app\.js|detail\.js|login\.js|share\.js" AssetsManager tests --glob '*.py' --glob '*.js' --glob '*.html'`

Expected: only intentional negative tests or migration documentation remain; no page handler or public path uses old files.

- [ ] **Step 2: Remove the exact legacy tree**

Delete only the listed tracked legacy files. Do not recursively delete `AssetsManager/lan/`, `RuntimeData/`, `webui/src/`, or any broad directory. If the directory becomes empty, remove the empty `static` directory through the patch/delete operation.

- [ ] **Step 3: Update ignore rules**

Add explicit ignores for `/webui/dist/` and `/webui/.vite/` alongside existing `/webui/node_modules/` and `tsconfig.tsbuildinfo`. Keep package-lock and all source/config files tracked. Do not add broad `webui/**` ignores.

- [ ] **Step 4: Verify cleanup state**

Run: `git status --short; rg --files AssetsManager/lan/static webui/dist webui/.vite 2>$null; git diff --check`

Expected: old static files are absent, generated paths are ignored or absent, source/config files remain, and diff check has no whitespace errors.

### Task 4: Final WebUI Structure and Runtime Verification

**Covers:** S1, S3, S4, S6, S8, S10

**Files:**
- Modify: only focused files from Tasks 1-3 if verification reveals a real regression.

- [ ] **Step 1: Verify source structure and import closure**

Run: `rg --files webui/src | Sort-Object; rg -n "from ['\"]\.\./|from ['\"]\./" webui/src --glob '*.ts' --glob '*.tsx'`

Expected: all source remains inside the documented `api/components/hooks/i18n/pages/stores/types` boundaries; no import points to a removed legacy tree.

- [ ] **Step 2: Run LAN and package tests**

Run: `pytest -q tests/lan tests/core/test_package_contents.py`

Expected: all LAN and package-content tests pass.

- [ ] **Step 3: Run the complete WebUI test and build gates**

Run: `npm --prefix webui test -- --run`, `npm --prefix webui run typecheck`, and `npm --prefix webui run build`

Expected: all Vitest files pass, TypeScript has no errors, and Vite produces `webui/dist/index.html` plus `webui/dist/assets`.

- [ ] **Step 4: Perform final legacy scan**

Run: `rg -n "lan/static|/static/|detail\.html|login\.html|share\.html|static_dir|STATIC_DIR" AssetsManager tests webui --glob '!webui/node_modules/**' --glob '!webui/dist/**'`

Expected: no runtime references; any remaining match is an explicit negative test or migration documentation.

- [ ] **Step 5: Run final diff validation**

Run: `git diff --check; git status --short`

Expected: no diff-check errors; unrelated existing modifications remain untouched and the cleanup diff contains only the approved WebUI scope.
