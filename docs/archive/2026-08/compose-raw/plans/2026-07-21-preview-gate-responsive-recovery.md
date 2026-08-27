# Preview, Gate Effects, and Responsive Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore visible InfoPanel image previews, complete Gate pointer particle effects, and restore desktop panel state after leaving the mobile breakpoint.

**Architecture:** InfoPanel derives image preview URLs directly from the selected asset path, so preview rendering does not depend on optional list thumbnail data. Gate effect nodes remain in `document.body`, but receive their resolved accent color inline because the Gate CSS variable is scoped to the React root. BrowsePage preserves panel visibility just before entering the mobile breakpoint and restores that snapshot once it returns to desktop.

**Tech Stack:** React 18, TypeScript, Vitest, Testing Library, Tailwind CSS.

## Global Constraints

- Preserve unrelated user changes and do not create a Git commit.
- Use TDD: every new behavior must fail before its implementation is written.
- Do not add dependencies or expand the three reported behaviors.

---

### Task 1: InfoPanel image preview source

**Covers:** S1

**Files:**
- Modify: `webui/src/components/layout/InfoPanel.tsx`
- Test: `webui/src/components/layout/InfoPanel.test.tsx`

**Interfaces:**
- Consumes: `BrowsableItem.path`, `BrowsableItem.extension`, and `BrowsableItem.category`.
- Produces: An InfoPanel `<img>` for every image asset, sourced from `/api/thumbnails/<encoded-path>?size=512`.

- [ ] **Step 1: Write the failing test**

```tsx
it('renders an image preview when the list item has no thumbnail URL', () => {
  render(<InfoPanel metadata={null} selected={{
    name: 'hero.png', path: 'characters/hero.png', type: 'file',
    extension: '.png', category: 'images',
  }} />);

  expect(screen.getByAltText('hero.png preview').getAttribute('src')).toBe(
    '/api/thumbnails/characters/hero.png?size=512',
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix webui test -- InfoPanel.test.tsx`

Expected: FAIL because the preview trigger is absent without `thumbnail_url`.

- [ ] **Step 3: Write minimal implementation**

```tsx
const previewUrl = selected && isImage ? thumbnailUrlFor(selected.path, 512) : null;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix webui test -- InfoPanel.test.tsx`

Expected: PASS.

### Task 2: Gate body effect color

**Covers:** S2

**Files:**
- Modify: `webui/src/pages/LandingPage.tsx`
- Test: `webui/src/pages/LandingPage.test.tsx`

**Interfaces:**
- Consumes: The resolved `accent` string from LandingPage theme state.
- Produces: `.gate-particle` and `.gate-ripple` nodes with an inline CSS custom property usable outside `.gate`.

- [ ] **Step 1: Write the failing test**

```tsx
fireEvent.pointerMove(gate, { pointerType: 'mouse', clientX: 42, clientY: 24 });

expect(document.querySelector<HTMLElement>('.gate-particle')?.style.getPropertyValue('--gate-effect-color')).toBeTruthy();
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix webui test -- LandingPage.test.tsx`

Expected: FAIL because body-level effect nodes have no resolved accent value.

- [ ] **Step 3: Write minimal implementation**

```tsx
particle.style.setProperty('--gate-effect-color', accent);
ripple.style.setProperty('--gate-effect-color', accent);
```

```css
.gate-particle { background: var(--gate-effect-color); }
.gate-ripple { border-color: var(--gate-effect-color); }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix webui test -- LandingPage.test.tsx`

Expected: PASS.

### Task 3: Restore desktop panel state

**Covers:** S3

**Files:**
- Modify: `webui/src/pages/BrowsePage.tsx`
- Test: `webui/src/pages/BrowsePage.test.tsx`

**Interfaces:**
- Consumes: `isMobile`, `sidebarOpen`, and `infoOpen`.
- Produces: Restored sidebar and InfoPanel state after a mobile-to-desktop transition.

- [ ] **Step 1: Write the failing test**

```tsx
setMediaQueryMatches('(max-width: 768px)', false);
renderBrowsePage();
act(() => setMediaQueryMatches('(max-width: 768px)', true));
act(() => setMediaQueryMatches('(max-width: 768px)', false));

expect(screen.getByRole('complementary', { name: /sidebar/i })).toBeDefined();
expect(screen.getByRole('complementary', { name: /information/i })).toBeDefined();
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix webui test -- BrowsePage.test.tsx`

Expected: FAIL because only mobile closing is implemented.

- [ ] **Step 3: Write minimal implementation**

```tsx
const desktopPanelsRef = useRef({ sidebar: sidebarOpen, info: infoOpen });
useEffect(() => {
  if (isMobile) {
    desktopPanelsRef.current = { sidebar: sidebarOpen, info: infoOpen };
    setSidebarOpen(false);
    setInfoOpen(false);
    return;
  }
  setSidebarOpen(desktopPanelsRef.current.sidebar);
  setInfoOpen(desktopPanelsRef.current.info);
}, [isMobile]);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix webui test -- BrowsePage.test.tsx`

Expected: PASS.

### Task 4: Full verification

**Covers:** S1, S2, S3

**Files:**
- Verify: `webui/src/components/layout/InfoPanel.test.tsx`
- Verify: `webui/src/pages/LandingPage.test.tsx`
- Verify: `webui/src/pages/BrowsePage.test.tsx`

- [ ] **Step 1: Run focused regression tests**

Run: `npm --prefix webui test -- InfoPanel.test.tsx LandingPage.test.tsx BrowsePage.test.tsx`

Expected: PASS.

- [ ] **Step 2: Run full WebUI verification**

Run: `npm --prefix webui test && npm --prefix webui run typecheck && npm --prefix webui run build`

Expected: all tests, TypeScript typecheck, and production build PASS.
