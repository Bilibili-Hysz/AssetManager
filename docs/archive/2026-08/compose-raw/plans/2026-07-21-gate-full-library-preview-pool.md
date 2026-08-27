# Gate Full-Library Preview Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Gate represent the whole asset library by feeding it every valid baked preview, while keeping recent-project summaries and asset counts semantically correct.

**Architecture:** Keep `recent_projects` capped at 20 for recent-project UI. Add a separate `preview_pool` response field built from valid directory and baked thumbnail cache records across all discovered projects. LandingPage uses `preview_pool` for the background wall/showcase and uses library statistics for the `assets` count.

**Tech Stack:** Python, SQLite, aiohttp JSON contracts, React, TypeScript, Vitest, pytest.

## Global Constraints

- `recent_projects` remains a recent-project summary and remains capped at 20.
- Gate background/showcase preview candidates come from the full-library `preview_pool`, not `recent_projects`.
- Use only existing `directory_cache.preview_path` and baked `thumbnail_cache` records; do not recursively scan assets or create a new image store.
- Preserve `/api/thumbnails/{relative-path}` as the only browser image transport and preserve existing permission/path checks.
- The Gate `assets` status must display library statistics, not the number of usable preview URLs.
- Preserve current failed-image fallback, one-time shuffle, preloading, and `/browse` navigation behavior.

---

### Task 1: Add Full-Library Home Preview Pool

**Covers:** full-library source, cache validity, response compatibility

**Files:**
- Modify: `AssetsManager/application/project_service.py`
- Modify: `tests/integration/test_project_service.py`

**Interfaces:**
- Consumes: the existing full project collection, `directory_cache`, and `thumbnail_cache`.
- Produces: `ProjectHome.preview_pool: list[dict]`, where each item contains the project `name`, `path`, and valid `thumbnail_url`; `recent_projects` remains capped at 20.

- [ ] **Step 1: Write failing contract tests**

Add a test with more than 20 projects and valid baked thumbnail rows spread beyond the most-recent 20. Assert `recent_projects` remains length 20 while `preview_pool` contains all valid project preview items. Add a test asserting invalid/stale baked rows do not enter `preview_pool`.

- [ ] **Step 2: Run the tests and verify RED**

Run: `pytest -q tests/integration/test_project_service.py -k "preview_pool"`

Expected: FAIL because `ProjectHome` and `get_home()` do not expose `preview_pool`.

- [ ] **Step 3: Implement the minimal response extension**

Extend the `ProjectHome` dataclass and `to_response()` with `preview_pool`. Reuse the existing cache-only attachment logic to collect valid preview URLs for every project before slicing recent projects. Preserve directory-cache precedence, baked-cache fallback, mtime checks, root containment, WebP existence checks, and URL quoting. Do not duplicate image scanning.

- [ ] **Step 4: Run focused backend tests and verify GREEN**

Run: `pytest -q tests/integration/test_project_service.py -k "home or preview_pool"`

Expected: all selected project-service tests pass, including recent-project cap and full preview-pool coverage.

### Task 2: Wire Gate to Full Pool and Correct Asset Count

**Covers:** Gate full-library presentation and status semantics

**Files:**
- Modify: `webui/src/types/api.ts`
- Modify: `webui/src/pages/LandingPage.tsx`
- Modify: `webui/src/pages/LandingPage.test.tsx`

**Interfaces:**
- Consumes: Home `preview_pool` and existing `stats.total_projects`.
- Produces: Gate background/showcase sourced from `preview_pool`; top status displays `stats.total_projects` followed by `assets`; missing/empty preview pool still leaves the Gate entry usable.

- [ ] **Step 1: Write failing Gate tests**

Add a Home fixture with 25 `recent_projects` entries but 107 `preview_pool` entries. Assert the rendered status contains the library total, not the preview-pool length, and assert background/showcase image URLs can come from an item beyond the recent-project list. Keep a test for empty `preview_pool` that still renders `/browse`.

- [ ] **Step 2: Run the tests and verify RED**

Run: `npm --prefix webui test -- --run src/pages/LandingPage.test.tsx`

Expected: FAIL because LandingPage currently builds its pool from `recent_projects` and displays `visiblePool.length` as assets.

- [ ] **Step 3: Implement the minimal frontend contract change**

Add `preview_pool?: ProjectItem[]` to the Home response type. In LandingPage, build candidates from `response.preview_pool ?? []`, retain the existing trim/dedup/shuffle/preload/failure logic, and set the first status number from `stats.total_projects` (with existing loading/unavailable handling). Do not alter recent-project consumers outside Gate.

- [ ] **Step 4: Run focused frontend tests and verify GREEN**

Run: `npm --prefix webui test -- --run src/pages/LandingPage.test.tsx`

Expected: all LandingPage tests pass, including full-pool selection, correct asset count, failure fallback, and Browse entry.

### Task 3: Cross-Layer Verification

**Files:**
- Modify: only Task 1-2 files if a focused regression is found.

- [ ] **Step 1: Run backend verification**

Run: `pytest -q tests/integration/test_project_service.py tests/lan/test_lan_api.py -k "home or preview_pool or thumbnail or project_service"`

Expected: selected backend tests pass.

- [ ] **Step 2: Run WebUI verification**

Run: `npm --prefix webui test -- --run`

Expected: all WebUI test files and tests pass.

- [ ] **Step 3: Run typecheck and build**

Run: `npm --prefix webui run typecheck` and `npm --prefix webui run build`

Expected: both commands exit successfully.

- [ ] **Step 4: Check image transport and diff formatting**

Run: `rg -n -S "preview_pool|/api/thumbnails/|recent_projects|visiblePool.length" AssetsManager/application/project_service.py webui/src/pages/LandingPage.tsx webui/src/types/api.ts; git diff --check`

Expected: Gate consumes `preview_pool`, assets count does not use `visiblePool.length`, and only the existing thumbnail transport appears.
