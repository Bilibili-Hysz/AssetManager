# Unified Theme and InfoPanel Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify Gate and WebUI theme state and make InfoPanel image previews open the existing high-resolution ImageViewer through a tested interaction.

**Architecture:** A shared `useTheme` external state will be the only source for `am_theme`, system-theme fallback, document theme classes, and Gate/Browse synchronization. InfoPanel will resolve selected image URLs through the existing thumbnail route at a larger size and render the existing `ImageViewer` locally, preserving its zoom, navigation, keyboard, and focus behavior.

**Tech Stack:** React 18, TypeScript, React Router, Vitest, Testing Library, Tailwind CSS, CSS media/color rules.

## Global Constraints

- User theme setting has priority; without a setting use `prefers-color-scheme`; default to dark when unavailable.
- Migrate Gate’s old `assets-manager.gate-theme` value into the shared `am_theme` state.
- Keep Gate background tuning settings separate from the shared theme preference.
- Reuse `ImageViewer`; do not create a second image viewer implementation.
- InfoPanel preview clicks use the existing `/api/thumbnails/{path}?size=2048` route; do not add an unauthenticated original-file endpoint.
- Preserve existing Browse selection, metadata loading, DetailPage gallery, download, share, and keyboard behavior.
- All asset preview surfaces must opt out of forced browser color transformation with a shared class.

---

### Task 1: Shared Theme State and Gate/Browse Synchronization

**Covers:** Shared theme preference, browser fallback, document synchronization, Gate integration, light/dark visual tokens, and reduced-motion compatibility.

**Files:**
- Modify: `webui/src/hooks/useTheme.ts`
- Modify: `webui/src/pages/LandingPage.tsx`
- Modify: `webui/src/pages/LandingPage.css`
- Modify: `webui/src/index.css`
- Modify: `webui/index.html`
- Modify: `webui/src/hooks/useTheme.test.tsx` (create if absent)
- Modify: `webui/src/pages/LandingPage.test.tsx`
- Modify: `webui/src/components/layout/Header.test.tsx`

**Interfaces:**
- Produces: `useTheme(): { theme: 'dark' | 'light'; toggleTheme: () => void; setTheme: (theme: Theme) => void }` backed by one `am_theme` external store.
- Consumes: `prefers-color-scheme`, legacy `assets-manager.gate-theme`, existing Gate background settings.

- [ ] **Step 1: Write failing theme tests**

Add tests that prove: no stored theme follows `matchMedia('(prefers-color-scheme: light)')`; stored `am_theme` wins over the media query; `assets-manager.gate-theme=light` migrates to `am_theme=light`; toggling updates `document.documentElement` classes/`data-theme` and causes a second mounted consumer to observe the same theme.

```tsx
it('shares a stored theme between consumers and document state', async () => {
  localStorage.setItem('am_theme', 'light');
  render(<ThemeProbe />);
  expect(screen.getByTestId('theme')).toHaveTextContent('light');
  expect(document.documentElement).toHaveAttribute('data-theme', 'light');
  fireEvent.click(screen.getByRole('button', { name: 'toggle' }));
  expect(screen.getByTestId('theme')).toHaveTextContent('dark');
  expect(localStorage.getItem('am_theme')).toBe('dark');
});
```

- [ ] **Step 2: Run theme tests and verify RED**

Run: `npm --prefix webui test -- --run src/hooks/useTheme.test.tsx`

Expected: FAIL because the current hook uses component-local state, does not expose `setTheme`, does not migrate Gate storage, and does not synchronize external consumers.

- [ ] **Step 3: Implement the shared theme store**

Use module-level `currentTheme` plus a listener set (the same pattern as `src/i18n/index.ts`) so all hook consumers update together. Initialization order must be: valid `am_theme`, valid legacy Gate value migrated to `am_theme`, `matchMedia` light preference, then dark. Each state change must update `document.documentElement.classList` (`dark`/`light`), `data-theme`, and `style.colorScheme`, then persist `am_theme` and notify listeners.

Replace LandingPage’s local `isLight`/`assets-manager.gate-theme` toggle with `useTheme()`. Continue to key Gate background tuning by the shared theme name, but do not store a second theme preference. Keep the Gate’s existing pointer effects and reduced-motion behavior intact.

- [ ] **Step 4: Add actual light/dark visual tokens and image-safe base rules**

Update `index.css` so `body` and core surfaces use semantic variables for background, surface, elevated surface, border, primary text, and secondary text. Add `.asset-preview-surface` rules with `color-scheme: only light`, `forced-color-adjust: none`, `filter: none`, and normal blending. Ensure `html`, `body`, and `#root` fill the viewport without relying on the static `bg-slate-950` body class.

- [ ] **Step 5: Run theme tests and verify GREEN**

Run: `npm --prefix webui test -- --run src/hooks/useTheme.test.tsx src/pages/LandingPage.test.tsx src/components/layout/Header.test.tsx`

Expected: all theme synchronization, Gate theme, existing Gate preview, Header toggle, and reduced-motion tests pass.

### Task 2: InfoPanel High-Resolution Preview and ImageViewer

**Covers:** Selected image detection, high-resolution preview source, InfoPanel click behavior, viewer lifecycle, image-safe styling, and regression compatibility.

**Files:**
- Modify: `webui/src/components/layout/InfoPanel.tsx`
- Modify: `webui/src/components/layout/InfoPanel.test.tsx`
- Modify: `webui/src/components/viewer/ImageViewer.tsx` only for shared image-safe class/label props if required
- Modify: `webui/src/pages/BrowsePage.tsx` only if the selected item needs a focused preview URL resolver
- Modify: `webui/src/types/api.ts` only if the resolver needs a typed optional original/preview field

**Interfaces:**
- Consumes: `selected: BrowsableItem`, existing `Metadata`, `ImageViewer`, and selected item `path`.
- Produces: clickable InfoPanel image preview; viewer uses `/api/thumbnails/${encodeURIComponent(path)}?size=2048`; close restores InfoPanel trigger focus.

- [ ] **Step 1: Write failing InfoPanel tests**

Add tests that render an image selected with `category: 'images'` and assert the InfoPanel displays a preview button/image; clicking it renders `ImageViewer` with the high-resolution URL; closing removes the dialog and returns focus to the preview trigger. Add a test for `.bmp`, `.tiff`, `.ico`, and `.svg` extension recognition, and a non-image test that renders no preview.

```tsx
it('opens the selected image in the high-resolution viewer', async () => {
  render(<InfoPanel metadata={null} selected={imageItem} />);
  fireEvent.click(screen.getByRole('button', { name: /open .* preview/i }));
  expect(screen.getByRole('dialog', { name: /image viewer/i })).toBeInTheDocument();
  expect(screen.getByRole('img', { name: /image 1/i })).toHaveAttribute(
    'src',
    '/api/thumbnails/characters%2Fhero.png?size=2048',
  );
});
```

- [ ] **Step 2: Run InfoPanel tests and verify RED**

Run: `npm --prefix webui test -- --run src/components/layout/InfoPanel.test.tsx`

Expected: FAIL because InfoPanel currently renders a plain `<img>`, does not classify `images` correctly for all extensions, and does not mount ImageViewer.

- [ ] **Step 3: Implement the preview resolver and viewer wiring**

Add a local `isImageItem` predicate covering the backend `images` category and the backend-supported image extensions. Resolve the high-resolution URL from the selected relative path using `encodeURIComponent` with the existing `/api/thumbnails/` route and `size=2048`; retain the selected `thumbnail_url` only as the small preview/fallback source. Render the preview as a real button with an accessible label and `asset-preview-surface` wrapper. Track `viewerOpen` locally and pass `[highResolutionUrl]`, index `0`, close callback, and image-safe styling to `ImageViewer`.

- [ ] **Step 4: Preserve image failure and focus behavior**

If the high-resolution image fails, keep the viewer mounted long enough for its existing image element/error behavior and leave the InfoPanel preview fallback available. Ensure the preview trigger is the viewer’s focus restoration target. Do not change DetailPage’s existing gallery viewer behavior.

- [ ] **Step 5: Run focused GREEN verification**

Run: `npm --prefix webui test -- --run src/components/layout/InfoPanel.test.tsx src/components/viewer/ImageViewer.test.tsx src/pages/BrowsePage.test.tsx src/pages/DetailPage.test.tsx`

Expected: InfoPanel viewer tests, existing viewer gesture/focus tests, Browse selection tests, and DetailPage gallery tests all pass.

### Task 3: Cross-Page Verification and Regression Gates

**Files:**
- Modify: only Task 1–2 files if a focused test exposes a real regression.

- [ ] **Step 1: Run all WebUI tests**

Run: `npm --prefix webui test -- --run`

Expected: all Vitest files pass, including Gate, Header, theme, InfoPanel, ImageViewer, BrowsePage, and DetailPage.

- [ ] **Step 2: Run typecheck and production build**

Run: `npm --prefix webui run typecheck` and `npm --prefix webui run build`

Expected: TypeScript exits cleanly and Vite produces an SPA build without warnings caused by the new theme/viewer code.

- [ ] **Step 3: Review interaction and visual contracts**

Run: `rg -n "assets-manager.gate-theme|am_theme|useTheme|data-theme|asset-preview-surface|ImageViewer|size=2048|category === 'images'" webui/src webui/index.html; git diff --check`

Expected: one shared theme key/source, Gate no longer owns a separate theme state, InfoPanel opens the existing ImageViewer via a high-resolution thumbnail URL, all image surfaces use the protective class, and no unrelated files are changed.
