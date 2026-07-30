# InfoPanel, Grid, and FileList Scroll Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make InfoPanel previews diagnosable and reliable, make the FileList grid adapt smoothly to its container, and keep the FileList controls fixed while only the asset canvas scrolls.

**Architecture:** InfoPanel derives a single LAN thumbnail URL from the selected path, tracks image loading explicitly, and uses the same path contract for the high-resolution viewer. BrowsePage becomes a fixed-height flex workspace whose breadcrumb, tag state, and toolbar are outside a dedicated `FileListCanvas`; ProjectGrid uses an auto-fill CSS grid with a bounded card width so columns change smoothly with available space.

**Tech Stack:** React 18, TypeScript, Vitest, Testing Library, Tailwind CSS, Vite, aiohttp LAN routes.

## Global Constraints

- Preserve unrelated user changes and do not create a Git commit.
- Use TDD: every new behavior must fail before its implementation is written.
- Keep asset names, paths, and notes selectable; only decorative media and layout surfaces are non-selectable.
- Do not add dependencies or change the LAN thumbnail endpoint contract.

---

### Task 1: InfoPanel preview diagnostics and source contract

**Covers:** S1

**Files:**
- Modify: `webui/src/components/layout/InfoPanel.tsx`
- Test: `webui/src/components/layout/InfoPanel.test.tsx`
- Test: `webui/src/api/metadata.test.ts` if the existing API contract test location supports it

**Interfaces:**
- Consumes: `BrowsableItem.path`, `BrowsableItem.category`, `BrowsableItem.extension`, and optional `thumbnail_url`.
- Produces: One canonical thumbnail URL with path-segment encoding, explicit loading/success/error rendering, and a 2048-size viewer URL derived from the same path.

- [ ] **Step 1: Write the failing tests**

```tsx
it('shows a loading state before an InfoPanel preview image loads', () => {
  render(<InfoPanel metadata={null} selected={{
    name: 'hero.png', path: 'characters/hero.png', type: 'file',
    extension: '.png', category: 'images',
  }} />);

  expect(screen.getByRole('status', { name: 'Loading preview' })).toBeDefined();
});

it('uses the selected path contract even when the list thumbnail is absent', () => {
  render(<InfoPanel metadata={null} selected={{
    name: 'hero.png', path: 'characters/hero.png', type: 'file',
    extension: '.png', category: 'images',
  }} />);

  expect(screen.getByAltText('hero.png preview').getAttribute('src')).toBe(
    '/api/thumbnails/characters/hero.png?size=512',
  );
});
```

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `npm --prefix webui test -- InfoPanel.test.tsx`

Expected: FAIL because the current preview has no explicit loading status.

- [ ] **Step 3: Implement the minimum preview state machine**

```tsx
const [previewState, setPreviewState] = useState<'loading' | 'ready' | 'error'>('loading');
const previewUrl = selected && isImage ? thumbnailUrlFor(selected.path, 512) : null;

useEffect(() => {
  setPreviewState(previewUrl ? 'loading' : 'ready');
}, [previewUrl]);
```

Render `role="status"` while loading, set `ready` on image `onLoad`, and set `error` on image `onError`. Keep the existing visible error message and viewer trigger.

- [ ] **Step 4: Run the focused tests to verify GREEN**

Run: `npm --prefix webui test -- InfoPanel.test.tsx`

Expected: PASS with the existing path, viewer, and error tests.

### Task 2: Adaptive ProjectGrid layout

**Covers:** S2

**Files:**
- Modify: `webui/src/components/files/ProjectGrid.tsx`
- Modify: `webui/src/pages/BrowsePage.tsx`
- Test: `webui/src/components/files/ProjectGrid.test.tsx`

**Interfaces:**
- Consumes: the existing `ProjectGrid` item and interaction props.
- Produces: A `data-testid="project-grid"` container using `grid-template-columns: repeat(auto-fill, minmax(168px, 1fr))` and the same layout class for loading skeletons.

- [ ] **Step 1: Write the failing layout tests**

```tsx
it('uses container-driven auto-fill columns instead of fixed breakpoint columns', () => {
  render(<ProjectGrid items={[]} selected={new Set()} onSelect={vi.fn()} thumbnailMap={{}} />);

  const grid = screen.getByTestId('project-grid');
  expect(grid.className).toContain('grid-cols-[repeat(auto-fill,minmax(168px,1fr))]');
});
```

```tsx
it('uses the same adaptive grid contract for loading placeholders', () => {
  render(<MemoryRouter><TestBrowsePageWithLoading /></MemoryRouter>);
  expect(screen.getByTestId('file-list-loading-grid').className)
    .toContain('grid-cols-[repeat(auto-fill,minmax(168px,1fr))]');
});
```

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `npm --prefix webui test -- ProjectGrid.test.tsx BrowsePage.test.tsx`

Expected: FAIL because the current grid uses fixed `grid-cols-2` through `xl:grid-cols-6` classes and the loading grid duplicates that contract.

- [ ] **Step 3: Implement the adaptive grid contract**

```tsx
<div
  data-testid="project-grid"
  className="grid grid-cols-[repeat(auto-fill,minmax(168px,1fr))] gap-3 p-4"
>
```

Use the same class on BrowsePage’s loading skeleton container. Keep card interactions unchanged.

- [ ] **Step 4: Run the focused tests to verify GREEN**

Run: `npm --prefix webui test -- ProjectGrid.test.tsx BrowsePage.test.tsx`

Expected: PASS.

### Task 3: Fixed FileList controls and independent canvas scroll

**Covers:** S3

**Files:**
- Modify: `webui/src/pages/BrowsePage.tsx`
- Modify: `webui/src/components/layout/AppLayout.tsx` only if the flex child needs `min-h-0`
- Test: `webui/src/pages/BrowsePage.test.tsx`

**Interfaces:**
- Consumes: existing Breadcrumb, FileToolbar, loading/error/empty states, and ProjectGrid/ProjectList.
- Produces: A `data-testid="browse-workspace"` flex column, fixed control region, and `data-testid="file-list-canvas"` sole scrolling region.

- [ ] **Step 1: Write the failing scroll-boundary test**

```tsx
it('keeps workspace controls outside the scrolling FileList canvas', () => {
  render(<MemoryRouter><TestBrowsePage /></MemoryRouter>);

  const workspace = screen.getByTestId('browse-workspace');
  const canvas = screen.getByTestId('file-list-canvas');
  const toolbar = screen.getByTestId('file-toolbar');

  expect(workspace.className).toContain('min-h-0');
  expect(canvas.className).toContain('overflow-y-auto');
  expect(canvas.contains(toolbar)).toBe(false);
});
```

- [ ] **Step 2: Run the focused test to verify RED**

Run: `npm --prefix webui test -- BrowsePage.test.tsx`

Expected: FAIL because the current toolbar has no test identity and is inside the main scrolling element.

- [ ] **Step 3: Implement the workspace boundary**

```tsx
<div data-testid="browse-workspace" className="flex min-h-0 flex-1 flex-col">
  <Breadcrumb ... />
  <div className="flex-shrink-0">...</div>
  <FileToolbar data-testid="file-toolbar" ... />
  <div data-testid="file-list-canvas" className="min-h-0 flex-1 overflow-y-auto">
    {loadingOrErrorOrEmptyOrGrid}
  </div>
</div>
```

Add an optional `data-testid` prop to FileToolbar only if the existing component contract requires it. Ensure AppLayout’s main region has `min-h-0` so the nested canvas can shrink and scroll.

- [ ] **Step 4: Run the focused test to verify GREEN**

Run: `npm --prefix webui test -- BrowsePage.test.tsx`

Expected: PASS with existing navigation, selection, and responsive tests.

### Task 4: Full verification

**Covers:** S1, S2, S3

**Files:**
- Verify: all modified WebUI files and tests

- [ ] **Step 1: Run all WebUI tests**

Run: `npm --prefix webui test`

Expected: all test files and tests pass.

- [ ] **Step 2: Run typecheck and production build**

Run: `npm --prefix webui run typecheck && npm --prefix webui run build`

Expected: TypeScript and Vite build exit successfully.

- [ ] **Step 3: Check whitespace and generated references**

Run: `git diff --check -- webui/src`

Expected: no whitespace errors; verify `webui/dist/index.html` points to the latest generated JS/CSS hashes.
