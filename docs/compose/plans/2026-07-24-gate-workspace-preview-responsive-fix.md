# Gate And Workspace Interaction Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore Gate pointer effects, place workspace panel controls beside the file breadcrumb, make InfoPanel image viewing use a valid LAN thumbnail path, and make narrow layouts automatically collapse both panels.

**Architecture:** Keep Gate effects local to `LandingPage`, use a small shared thumbnail URL helper for browser-facing image paths, and let `BrowsePage` own responsive panel state while `AppLayout` renders the resulting desktop or drawer layout. The breadcrumb row receives the panel controls so the controls remain adjacent to the file-list navigation they affect.

**Tech Stack:** React 18, TypeScript, Vitest, Testing Library, Tailwind utility classes, Vite.

## Global Constraints

- Preserve the existing AssetManager visual language and do not add dependencies.
- Keep Gate effects disabled under `prefers-reduced-motion` and remove effect nodes on unmount.
- Preserve slash separators in LAN thumbnail paths while encoding each non-separator URL segment.
- On the mobile breakpoint `(max-width: 768px)`, close both workspace panels and persist that closed state.
- Do not modify unrelated user changes and do not create commits.

---

### Task 1: Restore Gate Pointer Effects

**Files:**
- Modify: `webui/src/pages/LandingPage.tsx`
- Modify: `webui/src/pages/LandingPage.test.tsx`

**Interfaces:**
- Produces: a `gate-cursor-glow` element that tracks mouse pointers and is absent for touch/reduced motion.

- [ ] **Step 1: Write the failing test**

```tsx
it('renders and positions a cursor glow for mouse movement', async () => {
  getHome.mockResolvedValue({ recent_projects: [], preview_pool: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });
  render(<MemoryRouter><LandingPage /></MemoryRouter>);
  fireEvent.pointerMove(screen.getByRole('main'), { pointerType: 'mouse', clientX: 84, clientY: 126 });
  const glow = document.querySelector<HTMLElement>('.gate-cursor-glow');
  expect(glow?.style.left).toBe('84px');
  expect(glow?.style.top).toBe('126px');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix webui test -- src/pages/LandingPage.test.tsx`

Expected: FAIL because no `.gate-cursor-glow` is mounted.

- [ ] **Step 3: Write minimal implementation**

```tsx
const [cursorPosition, setCursorPosition] = useState<{ x: number; y: number } | null>(null);

const onPointerMove = useCallback((event: React.PointerEvent<HTMLElement>) => {
  if (reducedMotion || event.pointerType === 'touch') return;
  setCursorPosition({ x: event.clientX, y: event.clientY });
  // Keep existing throttled particle behavior.
}, [reducedMotion]);

{cursorPosition && <span className="gate-cursor-glow" aria-hidden="true" style={{ left: cursorPosition.x, top: cursorPosition.y }} />}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix webui test -- src/pages/LandingPage.test.tsx`

Expected: PASS.

### Task 2: Keep Valid Thumbnail URL Paths

**Files:**
- Modify: `webui/src/components/layout/InfoPanel.tsx`
- Modify: `webui/src/components/layout/InfoPanel.test.tsx`

**Interfaces:**
- Produces: `thumbnailUrlFor(path: string, size?: number): string` within `InfoPanel.tsx`, returning `/api/thumbnails/${encodedSegments}?size=${size}`.

- [ ] **Step 1: Write the failing test**

```tsx
it('keeps directory separators in the viewer thumbnail path', () => {
  render(<InfoPanel metadata={null} selected={{ name: 'hero.png', path: 'characters/hero.png', type: 'file', extension: '.png', category: 'images', thumbnail_url: '/api/thumbnails/characters/hero.png' }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Open hero.png preview' }));
  expect(screen.getByRole('img', { name: 'Image 1' }).getAttribute('src')).toBe('/api/thumbnails/characters/hero.png?size=2048');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix webui test -- src/components/layout/InfoPanel.test.tsx`

Expected: FAIL because the implementation encodes `/` as `%2F`.

- [ ] **Step 3: Write minimal implementation**

```tsx
function thumbnailUrlFor(path: string, size: number): string {
  const encodedPath = path.split('/').map(segment => encodeURIComponent(segment)).join('/');
  return `/api/thumbnails/${encodedPath}?size=${size}`;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix webui test -- src/components/layout/InfoPanel.test.tsx`

Expected: PASS.

### Task 3: Place Workspace Controls Beside Breadcrumb

**Files:**
- Modify: `webui/src/components/files/Breadcrumb.tsx`
- Modify: `webui/src/components/files/Breadcrumb.test.tsx`
- Modify: `webui/src/components/layout/Header.tsx`
- Modify: `webui/src/components/layout/Header.test.tsx`
- Modify: `webui/src/pages/BrowsePage.tsx`

**Interfaces:**
- `Breadcrumb` consumes optional `onSidebarToggle`, `onInfoToggle`, `sidebarOpen`, and `infoOpen` props.
- `Header` no longer consumes panel-toggle props.

- [ ] **Step 1: Write the failing breadcrumb test**

```tsx
it('places panel controls on either side of the breadcrumb navigation', () => {
  render(<Breadcrumb path="assets/icons" onNavigate={vi.fn()} onSidebarToggle={vi.fn()} onInfoToggle={vi.fn()} sidebarOpen infoOpen />);
  const row = screen.getByLabelText('Workspace navigation');
  expect(row.firstElementChild?.getAttribute('aria-label')).toBe('Close sidebar');
  expect(row.lastElementChild?.getAttribute('aria-label')).toBe('Close information panel');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix webui test -- src/components/files/Breadcrumb.test.tsx`

Expected: FAIL because `Breadcrumb` does not render panel controls.

- [ ] **Step 3: Write minimal implementation**

```tsx
<nav aria-label="Workspace navigation" className="flex items-center gap-2 px-4 py-3">
  <button type="button" onClick={onSidebarToggle} aria-label={sidebarOpen ? t('action.close_sidebar') : t('action.open_sidebar')}><PanelLeft size={16} /></button>
  <div className="min-w-0 flex-1">{/* existing breadcrumb links */}</div>
  <button type="button" onClick={onInfoToggle} aria-label={infoOpen ? t('action.close_info') : t('mobile.info')}><PanelRight size={16} /></button>
</nav>
```

- [ ] **Step 4: Pass controls from BrowsePage and remove header duplicates**

```tsx
<Breadcrumb path={currentPath} onNavigate={handleNavigate} onSidebarToggle={handleSidebarToggle} onInfoToggle={handleInfoToggle} sidebarOpen={sidebarOpen} infoOpen={infoOpen} />
```

- [ ] **Step 5: Run focused layout tests**

Run: `npm --prefix webui test -- src/components/files/Breadcrumb.test.tsx src/components/layout/Header.test.tsx src/pages/BrowsePage.test.tsx`

Expected: PASS.

### Task 4: Collapse Panels At Mobile Breakpoint

**Files:**
- Modify: `webui/src/pages/BrowsePage.tsx`
- Modify: `webui/src/pages/BrowsePage.test.tsx`
- Modify: `webui/src/components/layout/AppLayout.tsx`
- Modify: `webui/src/components/layout/AppLayout.test.tsx`

**Interfaces:**
- `BrowsePage` reacts to `isMobile` transitions by setting and persisting both panel states to closed.
- `AppLayout` receives the already-normalized states and uses its existing drawer rendering on mobile.

- [ ] **Step 1: Write the failing responsive-state test**

```tsx
it('closes and persists both desktop panels when the viewport becomes mobile', async () => {
  vi.mocked(useMediaQuery).mockReturnValue(false);
  const view = render(<MemoryRouter><TestBrowsePage /></MemoryRouter>);
  vi.mocked(useMediaQuery).mockReturnValue(true);
  view.rerender(<MemoryRouter><TestBrowsePage /></MemoryRouter>);
  await waitFor(() => {
    expect(localStorage.getItem('am_sidebar_open')).toBe('0');
    expect(localStorage.getItem('am_info_open')).toBe('0');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix webui test -- src/pages/BrowsePage.test.tsx`

Expected: FAIL because breakpoint transitions currently retain panel state.

- [ ] **Step 3: Write minimal implementation**

```tsx
useEffect(() => {
  if (!isMobile) return;
  setSidebarOpen(false);
  setInfoOpen(false);
  localStorage.setItem('am_sidebar_open', '0');
  localStorage.setItem('am_info_open', '0');
}, [isMobile]);
```

- [ ] **Step 4: Add desktop-only breadcrumb controls**

```tsx
{!isMobile && <Breadcrumb /* panel-control props */ />}
{isMobile && <Breadcrumb path={currentPath} onNavigate={handleNavigate} />}
```

- [ ] **Step 5: Run responsive and layout tests**

Run: `npm --prefix webui test -- src/pages/BrowsePage.test.tsx src/components/layout/AppLayout.test.tsx`

Expected: PASS.

### Task 5: Verify The Complete Browser-Facing Change

**Files:**
- Verify only: `webui/dist/`

- [ ] **Step 1: Run all WebUI tests**

Run: `npm --prefix webui test`

Expected: PASS with no failing test files.

- [ ] **Step 2: Run TypeScript validation**

Run: `npm --prefix webui run typecheck`

Expected: exit code 0.

- [ ] **Step 3: Build production assets**

Run: `npm --prefix webui run build`

Expected: exit code 0 and refreshed `webui/dist/index.html` assets.

- [ ] **Step 4: Check build output for the repaired contracts**

Run: `rg -n "gate-cursor-glow|asset-preview-surface|am_sidebar_open" webui/dist/assets --glob "*.js" --glob "*.css"`

Expected: output contains all three strings.

- [ ] **Step 5: Check whitespace errors**

Run: `git diff --check -- webui/src/pages/LandingPage.tsx webui/src/components/layout/InfoPanel.tsx webui/src/components/files/Breadcrumb.tsx webui/src/components/layout/Header.tsx webui/src/pages/BrowsePage.tsx webui/src/components/layout/AppLayout.tsx`

Expected: exit code 0 with no output.
