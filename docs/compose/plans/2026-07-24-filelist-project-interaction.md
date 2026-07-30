# Filelist Project Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make desktop Filelist single-click select and inspect, double-click navigate, and stop at configured Project directories by opening the existing independent Project detail page, while preserving mobile single-click navigation.

**Architecture:** The backend will annotate `/api/files` directory items with `is_project` using the same `ProjectDepthConfig` and `sidebar_depth_cfg` used by project discovery. Grid/List will receive semantic click callbacks; BrowsePage will own selection, InfoPanel metadata, and `/detail?path=...` navigation. Existing DetailPage and ProjectDetail API are reused.

**Tech Stack:** Python, aiohttp, pytest, React, TypeScript, React Router, Vitest, Testing Library, lucide-react.

## Global Constraints

- Use the library-configured `sidebar_depth_cfg` / `ProjectDepthConfig`; do not hard-code a path depth in React.
- Desktop normal mode: single click selects and loads InfoPanel; double-click navigates or opens Project detail.
- Mobile: preserve direct single-click navigation; do not require double tap.
- Batch selection mode remains explicit and retains its current selection behavior.
- Reuse `/detail?path=...` and `getProjectDetail()`; do not create a second Project detail page.
- Preserve existing thumbnail, context-menu, tag, download, share, and keyboard focus behavior.

---

### Task 1: Backend Project Semantics on Filelist Items

**Covers:** S3, S5, S7, S9

**Files:**
- Modify: `AssetsManager/application/asset_service.py`
- Modify: `AssetsManager/lan/routes/files.py`
- Modify: `tests/integration/test_asset_service.py`
- Modify: `tests/lan/test_lan_api.py`

**Interfaces:**
- Consumes: `DirectoryListOptions.current_depth`, `ProjectDepthConfig`, and `sidebar_depth_cfg`.
- Produces: `/api/files` directory item field `is_project: boolean`; file items either omit the field or return false consistently.

- [ ] **Step 1: Write failing backend tests**

Add a service-level test that creates a root child at the configured project boundary and asserts the directory item is marked as a project, while a shallower organizing directory is not. Add a LAN response test asserting the JSON exposes `is_project` for directories.

```python
def test_directory_listing_marks_configured_project_boundary(tmp_path):
    category = tmp_path / "Avatars"
    project = category / "Aurellia"
    project.mkdir(parents=True)

    listing = AssetService().list_directory(
        tmp_path, category,
        DirectoryListOptions(current_depth=1, project_depth=2),
    )

    assert listing.items[0].is_project is True
```

- [ ] **Step 2: Run backend tests and verify RED**

Run: `pytest -q tests/integration/test_asset_service.py tests/lan/test_lan_api.py -k "project_boundary or is_project"`

Expected: FAIL because `AssetListItem` and `/api/files` do not currently carry the configured Project semantic.

- [ ] **Step 3: Implement the semantic field**

Add the smallest configuration input needed to `DirectoryListOptions` and pass the current `ProjectDepthConfig` from `handle_files`. Compute the effective branch depth using the same branch naming rules as `ProjectService`; mark a direct child as `is_project` when its resulting depth reaches the configured boundary. Preserve `summaries`, sorting, filters, and all existing item fields.

- [ ] **Step 4: Run focused backend tests and verify GREEN**

Run: `pytest -q tests/integration/test_asset_service.py tests/lan/test_lan_api.py -k "project_boundary or is_project or files"`

Expected: selected service and LAN contract tests pass.

### Task 2: Desktop Grid/List Event Semantics

**Covers:** S2, S5, S6, S8, S9

**Files:**
- Modify: `webui/src/components/files/ProjectGrid.tsx`
- Modify: `webui/src/components/files/ProjectList.tsx`
- Modify: `webui/src/components/files/ProjectCard.tsx`
- Modify: `webui/src/types/api.ts`
- Test: `webui/src/components/files/ProjectGrid.test.tsx`
- Test: `webui/src/components/files/ProjectList.test.tsx`
- Test: `webui/src/components/files/ProjectCard.test.tsx`

**Interfaces:**
- Consumes: `BrowsableItem.is_project`, `onSelect(item)`, `onOpen(item)`, `isMobile`, and existing `selectionMode`.
- Produces: single-click callbacks that never navigate in desktop normal mode; double-click callbacks for directory navigation/detail decisions; mobile branch remains direct navigation.

- [ ] **Step 1: Write failing component tests**

Add tests for Grid and List covering: desktop directory single click calls selection only; desktop directory double click calls open; Project directory double click is passed to the semantic open callback; mobile directory click retains navigation; Enter activates the same open action; selection mode still toggles selection.

```tsx
it('does not navigate on a desktop directory single click', () => {
  render(<ProjectGrid items={[{ ...directory, is_project: false }]} isMobile={false} onSelect={onSelect} onNavigate={onNavigate} />);
  fireEvent.click(screen.getByRole('button', { name: /Assets/ }));
  expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ path: 'Assets' }));
  expect(onNavigate).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run component tests and verify RED**

Run: `npm --prefix webui test -- --run src/components/files/ProjectGrid.test.tsx src/components/files/ProjectList.test.tsx src/components/files/ProjectCard.test.tsx`

Expected: new desktop single-click assertions fail because current directory click calls `onNavigate` immediately.

- [ ] **Step 3: Implement semantic callbacks**

Add `is_project?: boolean` to `BrowsableItem`. Make Grid/List pass the complete item to `onSelect` and `onOpen`, with `isMobile` controlling the mobile direct-navigation branch. Keep ProjectCard as a keyboard-operable button with visible focus. Do not make thumbnail clicks or context actions navigate independently.

- [ ] **Step 4: Run focused component tests and verify GREEN**

Run: `npm --prefix webui test -- --run src/components/files/ProjectGrid.test.tsx src/components/files/ProjectList.test.tsx src/components/files/ProjectCard.test.tsx`

Expected: all new event semantics and existing selection/thumbnail tests pass.

### Task 3: BrowsePage Selection, Project Boundary, and Detail Navigation

**Covers:** S2, S4, S5, S7, S8, S9

**Files:**
- Modify: `webui/src/pages/BrowsePage.tsx`
- Modify: `webui/src/pages/BrowsePage.test.tsx`
- Modify: `webui/src/components/layout/InfoPanel.tsx` only if a focused selection affordance is required

**Interfaces:**
- Consumes: semantic `onSelect(item)` / `onOpen(item)` callbacks and `BrowsableItem.is_project`.
- Produces: desktop InfoPanel selection on single click; normal directory navigation on desktop double click; Project detail navigation via `/detail?path=...`; mobile single-click navigation/detail; preserved browser back path.

- [ ] **Step 1: Write failing BrowsePage tests**

Add tests using the existing mocks to assert: selecting a directory calls metadata and leaves the Browse URL unchanged; double-clicking an ordinary directory updates `?path=`; double-clicking an `is_project` directory navigates to `/detail?path=...`; mobile single-click follows the direct navigation/detail rule; Enter/detail route remains encoded.

- [ ] **Step 2: Run BrowsePage tests and verify RED**

Run: `npm --prefix webui test -- --run src/pages/BrowsePage.test.tsx`

Expected: directory single-click and Project boundary tests fail against current immediate-navigation behavior.

- [ ] **Step 3: Implement BrowsePage callbacks**

Change `handleSelect` to accept an item in normal mode, update `selectedItem`, load metadata through the existing abortable `handleCardClick`, and keep path unchanged. Keep batch selection mode path-based. Add `handleItemOpen(item)` that routes `is_project` directories to `/detail?path=...`, ordinary directories to `handleNavigate(item.path)`, and files to the existing detail behavior. Pass `isMobile` and these callbacks into Grid/List. Preserve context-menu detail navigation and InfoPanel actions.

- [ ] **Step 4: Run BrowsePage focused tests and verify GREEN**

Run: `npm --prefix webui test -- --run src/pages/BrowsePage.test.tsx`

Expected: all BrowsePage tests pass, including existing tag, selection, metadata, context-menu, and navigation cases.

### Task 4: Detail Route and Responsive Accessibility Verification

**Covers:** S4, S7, S8, S9

**Files:**
- Modify: `webui/src/pages/DetailPage.tsx` only for a focused back-link/focus improvement
- Test: `webui/src/pages/DetailPage.test.tsx` if absent, otherwise existing detail tests
- Modify: `webui/src/App.tsx` only if route handling requires a named project-detail route

- [ ] **Step 1: Write failing detail navigation test**

Render `/detail?path=folder%2FProject`, assert `getProjectDetail('folder/Project')` receives the decoded path, the Back control is available, and browser history can return to `/browse?path=folder`.

- [ ] **Step 2: Run detail tests and verify RED**

Run: `npm --prefix webui test -- --run src/pages/DetailPage.test.tsx`

Expected: only fail if the existing DetailPage lacks the required deep-link/back behavior; do not change the route if it already satisfies the test.

- [ ] **Step 3: Implement only required detail compatibility**

Reuse the existing `/detail` route and decoded `path` query. Add an accessible label/focus target for Back only if the test demonstrates a gap. Do not create a duplicate `/project-detail` route unless the existing route cannot represent the required URL.

- [ ] **Step 4: Run responsive/accessibility focused verification**

Run: `npm --prefix webui test -- --run src/pages/DetailPage.test.tsx src/pages/BrowsePage.test.tsx src/components/files/ProjectGrid.test.tsx src/components/files/ProjectList.test.tsx`

Expected: keyboard Enter, desktop single/double click, mobile branch, detail back path, and focus semantics pass.

### Task 5: Cross-Layer Quality Gates

**Files:**
- Modify: only Task 1-4 files if verification reveals a focused regression.

- [ ] **Step 1: Run backend quality gates**

Run: `pytest -q tests/integration/test_asset_service.py tests/lan/test_lan_api.py tests/integration/test_project_service.py tests/unit/test_architecture_boundaries.py`

Expected: all selected backend tests pass.

- [ ] **Step 2: Run complete WebUI tests**

Run: `npm --prefix webui test -- --run`

Expected: all WebUI test files and tests pass.

- [ ] **Step 3: Run typecheck and production build**

Run: `npm --prefix webui run typecheck` and `npm --prefix webui run build`

Expected: both exit successfully.

- [ ] **Step 4: Review interaction contract**

Run: `rg -n "is_project|onDoubleClick|onOpen|onNavigate|handleItemOpen|handleCardClick|/detail\\?path" AssetsManager/lan/routes/files.py AssetsManager/application/asset_service.py webui/src/components/files webui/src/pages/BrowsePage.tsx webui/src/pages/DetailPage.tsx; git diff --check`

Expected: project semantics come from backend, desktop directory single-click does not navigate, double-click routes by item semantics, and no unrelated interaction path is changed.
