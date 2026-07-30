# Layered Preview Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Project desktop-baked directory previews into Gate and Filelist, render them with a shared single-cover layered preview, and randomize Gate's usable preview pool once per Home response.

**Architecture:** Reuse the per-library SQLite `directory_cache.preview_path` cache for Home project cover URLs and keep `/api/thumbnails/{path}` as the only image transport. Add a presentational `LayeredPreview` component; pass directory URLs through the existing summary hydration and use a stable shuffled pool in LandingPage.

**Tech Stack:** Python, aiohttp, SQLite directory cache, React 18, TypeScript, lucide-react, Vitest, Testing Library, pytest, Vite.

## Global Constraints

- Use only existing RuntimeData-backed `directory_cache.preview_path` entries; do not add recursive scans or a new preview endpoint.
- Keep `/api/thumbnails/{path}` as the image transport and preserve its existing permission/path validation behavior.
- Use one cover image plus two subtle backing layers; no multi-image folder collage.
- Preserve existing Gate authentication, `/browse` navigation, Filelist selection, navigation, and context-menu behavior.
- Do not edit unrelated dirty files or add dependencies.

---

### Task 1: Project Home Cache Projection

**Covers:** S2, S3, S6, S7

**Files:**
- Modify: `AssetsManager/application/project_service.py`
- Test: `tests/integration/test_project_service.py`

**Interfaces:**
- Consumes: `directory_cache` state from the per-library SQLite connection and `find_first_image` URL convention used by project listings.
- Produces: `ProjectService.get_home()` items with optional `thumbnail_url` only when `directory_cache.preview_path` is current and the cached source file exists.

- [ ] **Step 1: Write failing Home cache projection tests**

Add tests that seed `directory_cache` for `library/alpha` and assert Home returns the encoded URL, then add stale/missing-cache cases that assert no stale URL is returned:

```python
def test_get_home_projects_projected_from_directory_preview_cache(tmp_path, schema_db):
    library = tmp_path / "library"
    project = library / "alpha"
    project.mkdir(parents=True)
    preview = project / "cover.png"
    preview.write_bytes(b"cached-source")
    schema_db.execute(
        "INSERT INTO directory_cache (dir_path, item_count, preview_path, mtime, scanned_at) VALUES (?, ?, ?, ?, ?)",
        (str(project), 1, str(preview), project.stat().st_mtime, 1.0),
    )
    schema_db.commit()

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    assert home["recent_projects"][0]["thumbnail_url"] == "/api/thumbnails/alpha/cover.png"

def test_get_home_ignores_stale_or_missing_directory_preview_cache(tmp_path, schema_db):
    library = tmp_path / "library"
    project = library / "alpha"
    project.mkdir(parents=True)
    preview = project / "cover.png"
    preview.write_bytes(b"cached-source")
    schema_db.execute(
        "INSERT INTO directory_cache (dir_path, item_count, preview_path, mtime, scanned_at) VALUES (?, ?, ?, ?, ?)",
        (str(project), 1, str(preview), project.stat().st_mtime - 1, 1.0),
    )
    schema_db.commit()

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    assert "thumbnail_url" not in home["recent_projects"][0]
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `pytest -q tests/integration/test_project_service.py -k "home_projects_projected or home_ignores_stale"`

Expected: the projection test fails because `_collect_projects()` does not currently read `directory_cache` or include `thumbnail_url`.

- [ ] **Step 3: Implement cache-only Home projection**

Pass the Home DB connection into `_collect_projects()`. For each project directory, read `directory_cache` through `DirectoryCache`, require `entry.mtime == directory.stat().st_mtime`, require `preview_path` to exist and be inside `library_root`, then add a URL using `quote(relative_preview, safe='/')`. Keep the existing `name`, `path`, and `mtime` fields unchanged.

- [ ] **Step 4: Run focused backend tests and verify GREEN**

Run: `pytest -q tests/integration/test_project_service.py -k "home or list_projects or project_detail"`

Expected: all selected project-service tests pass, including the new cache projection and stale-cache tests.

### Task 2: Shared LayeredPreview and Filelist Wiring

**Covers:** S4, S5, S6, S7

**Files:**
- Create: `webui/src/components/files/LayeredPreview.tsx`
- Modify: `webui/src/components/files/ProjectCard.tsx`
- Modify: `webui/src/components/files/ProjectGrid.tsx`
- Modify: `webui/src/components/files/ProjectList.tsx`
- Modify: `webui/src/pages/BrowsePage.tsx`
- Test: `webui/src/components/files/LayeredPreview.test.tsx`
- Test: `webui/src/components/files/ProjectCard.test.tsx`
- Test: `webui/src/components/files/ProjectList.test.tsx`

**Interfaces:**
- Consumes: `thumbnail?: string`, `isDir`, and `size: 'grid' | 'list'`.
- Produces: a presentational `<LayeredPreview>` that renders one image plus backing layers or a lucide fallback, and a `thumbnailMap` containing both file base64 previews and directory `thumbnail_url` values.

- [ ] **Step 1: Write failing component and wiring tests**

Test the shared component's image/fallback behavior and render a directory `ProjectCard` with a thumbnail URL:

```tsx
it('renders a layered directory cover and falls back after image error', () => {
  const { rerender } = render(<LayeredPreview src="/api/thumbnails/folder/cover.png" alt="Assets" isDir size="grid" />);
  expect(screen.getByRole('img', { name: 'Assets' })).toHaveAttribute('src', '/api/thumbnails/folder/cover.png');
  expect(screen.getAllByTestId('layered-preview-back')).toHaveLength(2);
  fireEvent.error(screen.getByRole('img', { name: 'Assets' }));
  expect(screen.queryByRole('img', { name: 'Assets' })).toBeNull();
  expect(screen.getByTestId('layered-preview-folder')).toBeInTheDocument();
  rerender(<LayeredPreview alt="Assets" isDir size="list" />);
  expect(screen.getByTestId('layered-preview-folder')).toBeInTheDocument();
});

it('passes directory thumbnail through ProjectCard', () => {
  render(<ProjectCard item={{ name: 'Assets', path: 'Assets', type: 'dir', size: 0, size_fmt: '4 items', modified: 1, extension: '', category: 'folder', thumbnail_url: '/api/thumbnails/Assets/cover.png' }} thumbnail="/api/thumbnails/Assets/cover.png" />);
  expect(screen.getByRole('img', { name: '' })).toHaveAttribute('src', '/api/thumbnails/Assets/cover.png');
});
```

- [ ] **Step 2: Run focused frontend tests and verify RED**

Run: `npm test -- --run src/components/files/LayeredPreview.test.tsx src/components/files/ProjectCard.test.tsx`

Expected: the new component import/render assertions fail because `LayeredPreview` does not exist and ProjectCard still renders a plain Folder icon.

- [ ] **Step 3: Implement LayeredPreview and wire grid/list**

Create the component with fixed dimensions, two absolutely positioned backing layers, a foreground `<img>`, and Folder/File fallback. Replace ProjectCard's thumbnail branch with it. Add `thumbnailMap` to ProjectList and pass `thumbnailMap[item.path]` from BrowsePage. Build the map from existing file base64 cache plus every directory item's `thumbnail_url`; keep `useThumbnailCache` requests limited to image files.

- [ ] **Step 4: Run focused frontend tests and verify GREEN**

Run: `npm test -- --run src/components/files/LayeredPreview.test.tsx src/components/files/ProjectCard.test.tsx src/components/files/ProjectList.test.tsx src/pages/BrowsePage.test.tsx`

Expected: component, directory propagation, and existing Browse behavior tests pass.

### Task 3: Gate Preview Pool and Randomized Cover Selection

**Covers:** S3, S6, S7

**Files:**
- Modify: `webui/src/pages/LandingPage.tsx`
- Test: `webui/src/pages/LandingPage.test.tsx`

**Interfaces:**
- Consumes: Home `recent_projects[*].thumbnail_url` values and `LayeredPreview` for showcase tiles.
- Produces: one-time shuffled `previewPool`, background wall and showcase sourced from that pool, existing preload-before-rotation, and fallback-safe failed image handling.

- [ ] **Step 1: Write failing Gate pool tests**

Add a Home fixture with multiple `thumbnail_url` values and assert the wall/showcase use those URLs. Render twice after unrelated state changes and assert the initial showcase order remains stable; assert entries without URLs never render as image sources.

- [ ] **Step 2: Run focused Gate tests and verify RED**

Run: `npm test -- --run src/pages/LandingPage.test.tsx`

Expected: the new stable-pool assertions fail against the current direct `recent_projects` ordering and empty-URL handling.

- [ ] **Step 3: Implement one-time preview pool selection**

On Home success, filter items with non-empty `thumbnail_url`, deduplicate by URL/path, shuffle using a local Fisher-Yates helper once, and store the resulting items in state. Use the pool for `wallItems` and initial `showcasePaths`; keep existing failed-path removal and 20-second preloading tied to pool candidates. Render showcase entries through `LayeredPreview` with `isDir` semantics.

- [ ] **Step 4: Run Gate tests and verify GREEN**

Run: `npm test -- --run src/pages/LandingPage.test.tsx`

Expected: all Gate data, pool, failure, theme, tuning, and navigation tests pass.

### Task 4: Cross-Layer Verification

**Covers:** S2-S7

**Files:**
- Modify: only Task 1-3 files if verification reveals a focused regression.

- [ ] **Step 1: Run backend focused verification**

Run: `pytest -q tests/integration/test_project_service.py tests/integration/test_asset_service.py tests/lan/test_lan_api.py -k "home or summary or thumbnail or project_service or directory"`

Expected: selected backend contract tests pass.

- [ ] **Step 2: Run complete WebUI test suite**

Run from `webui/`: `npm test -- --run`

Expected: all WebUI test files and tests pass.

- [ ] **Step 3: Run TypeScript and production build**

Run from `webui/`: `npm run typecheck` and `npm run build`

Expected: both exit with code 0.

- [ ] **Step 4: Inspect final diff and endpoint boundary**

Run: `git diff --check; rg -n "(/api/config|/api/images|/images|/thumb)" webui/src/pages/LandingPage.tsx webui/src/components/files webui/src/api`

Expected: no prototype image endpoint remains in production code, and only the intentional `/api/thumbnails` transport is used.
