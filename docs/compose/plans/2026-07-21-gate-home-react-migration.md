# Gate Home React Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the Gate prototype's complete home experience into the AssetManager React WebUI while sourcing all images from AssetManager preview APIs.

**Architecture:** Keep `/` as the existing React route and keep authentication, `/login`, and `/browse` behavior unchanged. `LandingPage` owns the Gate presentation and its runtime lifecycle: it reads `/api/info` for server identity/status, `/api/home` for recent project thumbnails, renders a bounded image wall and six-item showcase, and owns theme/background preferences plus transient visual effects. No prototype server endpoint or external image source is introduced.

**Tech Stack:** React 18, TypeScript, React Router, lucide-react, Tailwind CSS utilities plus component-local CSS, Vitest, Testing Library, Vite.

## Global Constraints

- Preserve the existing cookie-only authentication flow and redirect protected unauthenticated/guest users from `/` to `/login`.
- Preserve the existing `/browse` entry action and all current browse routes.
- Replace the prototype `/api/config`, `/api/images`, `/images`, and `/thumb` calls with AssetManager `/api/info`, `/api/home`, and the `thumbnail_url` values returned by `/api/home`.
- Keep the Gate visual language: `#07070d` deep background, `#111122` surface, indigo/violet accents, centered single-column content, blurred image wall, compact status pills, and one primary entry action.
- Support loading, API-unavailable, empty-library, and individual broken-thumbnail states without blocking the library entry action.
- Pause rotating showcase work and background/transient effects when the document is hidden or `prefers-reduced-motion` is active; remove timers and listeners on unmount.
- Keep the page usable at 375px wide and short viewports without horizontal overflow; all controls must have visible focus states and at least 44px touch targets.
- Do not add a new dependency, change LAN API semantics, edit unrelated dirty files, or copy the prototype's static server into the AssetManager repository.

---

## File Structure

- `webui/src/pages/LandingPage.tsx`: Gate composition, AssetManager home-data loading, image wall/showcase lifecycle, theme toggle, transient effects, and Background panel.
- `webui/src/pages/LandingPage.test.tsx`: focused behavior tests for data states, theme/control semantics, lifecycle cleanup, and keyboard interaction.
- `webui/src/types/api.ts`: only if the existing `ServerInfo` or `HomeData` types do not cover the fields consumed by the page.
- `webui/src/api/metadata.ts`: existing `getHome()` contract; modify only if the current signature cannot accept an `AbortSignal`.
- `webui/src/index.css`: only for shared root/body rules required to make the Gate page fill the viewport without affecting browse pages.

### Task 1: Lock the AssetManager Gate Data Contract

**Covers:** D1 data sources, D2 state behavior

**Files:**
- Modify: `webui/src/api/metadata.ts` only if needed to expose `getHome(signal?: AbortSignal): Promise<HomeData>`.
- Modify: `webui/src/types/api.ts` only if needed to align `ServerInfo`, `ProjectItem`, or `HomeData` fields with the existing LAN serializers.
- Test: `webui/src/pages/LandingPage.test.tsx`

**Interfaces:**
- Consumes: `useAuth()` values `serverInfo`, `isLoading`, `isAuthenticated`, `role`, and `api`; `createMetadataApi(api).getHome(signal?)`.
- Produces: a page-level data model with `serverInfo`, `recent_projects.slice(0, 6)`, `stats`, and `thumbnail_url` values; no prototype endpoint names remain in the React page.

- [ ] **Step 1: Add failing contract tests for AssetManager sources**

Add tests that mock the existing `useAuth` and metadata API and verify the page requests one home payload after auth initialization, renders server-backed identity/stat values, and uses returned thumbnail URLs directly:

```tsx
it('loads Gate content from AssetManager info and home data', async () => {
  getHome.mockResolvedValue({
    recent_projects: [{
      name: 'Portrait', path: 'portraits/one.png', type: 'file', size: 12,
      size_fmt: '12 B', modified: 1, extension: '.png', category: 'image',
      thumbnail_url: '/api/thumbnails/portraits%2Fone.png',
    }],
    popular_tags: [],
    stats: { total_projects: 1, total_size: 12, total_size_fmt: '12 B' },
  });

  render(<MemoryRouter><LandingPage /></MemoryRouter>);

  expect(await screen.findByRole('heading', { name: 'Studio Assets' })).toBeInTheDocument();
  expect(screen.getByText('1 asset')).toBeInTheDocument();
  expect(screen.getAllByRole('img', { name: 'Portrait' })[0]).toHaveAttribute(
    'src', '/api/thumbnails/portraits%2Fone.png',
  );
  expect(getHome).toHaveBeenCalledWith(expect.any(AbortSignal));
});
```

- [ ] **Step 2: Run the focused contract tests and verify RED**

Run: `npm test -- src/pages/LandingPage.test.tsx`

Expected: the new assertions fail if the current page still renders only the reduced Gate surface or does not use the current API response fields.

- [ ] **Step 3: Implement the minimal API boundary**

Keep the existing typed `getHome` call and make the page consume only these fields:

```ts
const response = await metadataApi.getHome(controller.signal);
setFeatured(response.recent_projects.slice(0, 6));
setHomeStats(response.stats);
```

Use `serverInfo.share_name`, `serverInfo.welcome_msg`, `serverInfo.footer_text`, `serverInfo.theme_color`, and `serverInfo.library_stats` as server-backed values. Do not synthesize a new endpoint or infer permissions from client state.

- [ ] **Step 4: Run the focused contract tests and verify GREEN**

Run: `npm test -- src/pages/LandingPage.test.tsx`

Expected: the AssetManager data-source assertions pass, while unrelated new Gate visual tests may remain pending until Tasks 2 and 3.

### Task 2: Port the Complete Gate Composition And Theme Controls

**Covers:** D3 composition, D4 visual tokens, D5 responsive/accessibility behavior

**Files:**
- Modify: `webui/src/pages/LandingPage.tsx`
- Modify: `webui/src/index.css` only if the page needs a scoped root reset.
- Test: `webui/src/pages/LandingPage.test.tsx`

**Interfaces:**
- Consumes: Task 1's typed `serverInfo`, `homeStats`, and six `featured` items.
- Produces: a `/` page with the prototype-equivalent Gate information hierarchy: theme control, animated avatar ring, username/library identity, six-item showcase, three status pills, one entry CTA, footer/status text, image wall, and Background tuning panel.

- [ ] **Step 1: Add failing structure and responsive tests**

Cover the visible structure and control semantics without asserting implementation-specific class names:

```tsx
it('renders the complete Gate hierarchy and controls', async () => {
  render(<MemoryRouter><LandingPage /></MemoryRouter>);

  expect(await screen.findByRole('heading', { name: 'Studio Assets' })).toBeInTheDocument();
  expect(screen.getByText('Designer')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /switch to light theme/i })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Tune background' })).toHaveAttribute('aria-controls', 'background-tuning');
  expect(screen.getByRole('link', { name: /enter library/i })).toHaveAttribute('href', '/browse');
  expect(screen.getByRole('status')).toBeInTheDocument();
});

it('keeps the tuning panel keyboard reachable and exposes live values', async () => {
  render(<MemoryRouter><LandingPage /></MemoryRouter>);
  await userEvent.click(screen.getByRole('button', { name: 'Tune background' }));
  expect(screen.getByRole('dialog', { name: 'Background tuning' })).toBeInTheDocument();
  expect(screen.getByRole('slider', { name: 'Blur' })).toHaveAttribute('aria-valuenow');
  await userEvent.keyboard('{Escape}');
  expect(screen.queryByRole('dialog', { name: 'Background tuning' })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the structure tests and verify RED**

Run: `npm test -- src/pages/LandingPage.test.tsx`

Expected: failures identify missing theme toggle, avatar/identity layer, three status pills, footer/status surface, or prototype-equivalent control labels.

- [ ] **Step 3: Implement the Gate structure and scoped visual tokens**

Replace the reduced center markup with:

```tsx
<main className="gate" style={gateStyle}>
  <button type="button" className="gate-theme-toggle" aria-label={isLight ? 'Switch to dark theme' : 'Switch to light theme'} aria-pressed={isLight} onClick={toggleTheme}>
    {isLight ? <Moon size={16} aria-hidden="true" /> : <Sun size={16} aria-hidden="true" />}
  </button>
  <div className="gate-image-wall" aria-hidden="true">...</div>
  <div className="gate-decoration gate-decoration-primary" aria-hidden="true" />
  <div className="gate-decoration gate-decoration-secondary" aria-hidden="true" />
  <section className="gate-center">
    <div className="gate-avatar-ring" aria-hidden="true"><div className="gate-avatar">{avatar}</div></div>
    <p className="gate-username">{username}</p>
    <p className="gate-repository">{name}</p>
    <div className="gate-showcase">...</div>
    <div className="gate-status" role="status" aria-live="polite">...</div>
    <Link className="gate-enter" to="/browse">...</Link>
    <p className="gate-footer">{serverInfo?.footer_text || fallbackFooter}</p>
  </section>
  <button ... aria-expanded={tuningOpen} aria-controls="background-tuning">...</button>
  {tuningOpen && <section id="background-tuning" role="dialog">...</section>}
</main>
```

Use scoped CSS variables derived from `serverInfo.theme_color` for the accent while keeping the prototype fallback indigo palette. Preserve the prototype's compact rounded controls, 80px desktop avatar ring, 64px mobile avatar ring, 48px desktop showcase items, 40px mobile showcase items, and 44px minimum control dimensions. Do not put the main content inside a card or add a second CTA.

- [ ] **Step 4: Implement theme persistence and tuning persistence**

Use separate browser keys for the current library theme and background settings:

```ts
const THEME_KEY = 'assets-manager.gate-theme';
const themeKey = `assets-manager.gate-background.${serverInfo?.theme_color || 'default'}`;
```

Apply theme and background changes through root CSS variables. The theme toggle must update `document.documentElement` or the scoped page class without refetching home data. The panel must expose Blur, Brightness, Saturation, Canvas opacity, and Item opacity, each with a live `output` and visible focus ring; Reset restores the current theme defaults.

- [ ] **Step 5: Run the structure and persistence tests and verify GREEN**

Run: `npm test -- src/pages/LandingPage.test.tsx`

Expected: structure, theme, panel, Escape, persistence, empty, unavailable, and broken-thumbnail tests pass.

### Task 3: Port Gate Motion, Showcase Rotation, And Runtime Cleanup

**Covers:** D6 motion lifecycle, D7 interaction polish

**Files:**
- Modify: `webui/src/pages/LandingPage.tsx`
- Test: `webui/src/pages/LandingPage.test.tsx`

**Interfaces:**
- Consumes: six AssetManager thumbnail URLs and the Gate settings/state from Task 2.
- Produces: bounded image-wall rendering, 20-second showcase rotation with preloading, page-visibility pause/resume, reduced-motion pause, cursor particle/ripple effects, and complete unmount cleanup.

- [ ] **Step 1: Add failing lifecycle tests**

Use fake timers and mocked `matchMedia`/document visibility to cover the timing contract:

```tsx
it('rotates the showcase only after the replacement image preloads', async () => {
  vi.useFakeTimers();
  const first = createProject('first.png');
  const second = createProject('second.png');
  getHome.mockResolvedValue(homeWith([first, second]));
  render(<MemoryRouter><LandingPage /></MemoryRouter>);

  await flushPromises();
  vi.advanceTimersByTime(20_000);
  expect(screen.getByAltText('first.png')).toBeInTheDocument();
  resolveNextImageLoad();
  await flushPromises();
  expect(screen.getByAltText('second.png')).toBeInTheDocument();
});

it('does not keep timers or transient effects after unmount', async () => {
  const add = vi.spyOn(document, 'addEventListener');
  const remove = vi.spyOn(document, 'removeEventListener');
  const { unmount } = render(<MemoryRouter><LandingPage /></MemoryRouter>);
  unmount();
  expect(remove).toHaveBeenCalledWith('visibilitychange', expect.any(Function));
  expect(remove).toHaveBeenCalledWith('keydown', expect.any(Function));
  expect(add).toHaveBeenCalledWith('visibilitychange', expect.any(Function));
});

it('suppresses pointer effects when reduced motion is enabled', async () => {
  mockReducedMotion(true);
  render(<MemoryRouter><LandingPage /></MemoryRouter>);
  fireEvent.pointerMove(document, { clientX: 40, clientY: 40 });
  expect(document.querySelectorAll('.gate-particle')).toHaveLength(0);
});
```

- [ ] **Step 2: Run lifecycle tests and verify RED**

Run: `npm test -- src/pages/LandingPage.test.tsx`

Expected: failures expose missing rotation/preload behavior, cleanup, or reduced-motion gating.

- [ ] **Step 3: Implement bounded image-wall and showcase rotation**

Render at most 72 wall nodes from the currently available `recent_projects`, deduplicating by `path`. Start a 20-second timer only when there are at least two candidates, the document is visible, and reduced motion is disabled. Before replacing a showcase item, create an `Image`, attach `load` and `error` handlers, and commit the replacement only if the component generation and candidate index are still current. A failed image removes only that candidate from the visible set.

- [ ] **Step 4: Implement lifecycle-safe transient effects**

Use named handlers and tracked timer/frame IDs for:

- cursor glow and particles, throttled to at most one emission per 66ms and removed after 700ms;
- two click ripple layers with 700ms/900ms cleanup;
- one initial sweep and staged rise transitions;
- `visibilitychange`, `resize` debounce, `pointermove`, and `pointerdown` listeners.

The cleanup function must clear every timer/frame, abort in-flight home requests, remove listeners, and remove any transient nodes created by the page. Reduced motion must disable particles, ripples, sweep, rise, and rotation while preserving static content and controls.

- [ ] **Step 5: Run lifecycle tests and verify GREEN**

Run: `npm test -- src/pages/LandingPage.test.tsx`

Expected: all focused Gate lifecycle tests pass with fake timers restored in `afterEach`.

### Task 4: Full WebUI Verification And Rendered Gate QA

**Covers:** D8 acceptance

**Files:**
- Modify: only files from Tasks 1–3 if verification exposes a focused regression.
- Test: existing `webui/src/**/*.test.{ts,tsx}` suite.

**Interfaces:**
- Consumes: complete Gate page implementation.
- Produces: verified typecheck, tests, production build, and desktop/mobile rendered screenshots for the `/` route.

- [ ] **Step 1: Run the complete WebUI test suite**

Run from `webui/`: `npm test`

Expected: all existing and new tests pass with zero test failures.

- [ ] **Step 2: Run TypeScript verification**

Run from `webui/`: `npm run typecheck`

Expected: `tsc --noEmit` exits with code 0.

- [ ] **Step 3: Run the production build**

Run from `webui/`: `npm run build`

Expected: Vite emits `webui/dist` successfully with no TypeScript build errors.

- [ ] **Step 4: Capture the Gate route at required viewports**

Start the normal Vite development server and an AssetManager LAN server backed by a temporary library containing at least six image assets. Capture `/` at 1440×900 and 390×844 with authentication disabled. Also capture the loading, empty-home, and unavailable-home states through the existing test harness or controlled API responses.

- [ ] **Step 5: Check rendered acceptance criteria**

Confirm all of the following from the rendered page:

- The background wall fills the viewport and remains behind the centered Gate content.
- The avatar ring, identity, six-image showcase, three status pills, CTA, theme toggle, and Background control are visible without overlap at desktop width.
- At 390px width, the content remains reachable, the CTA and controls do not overflow, and the Background panel scrolls internally when opened.
- Theme switching changes tokens without refetching images; reduced motion removes transient effects; Escape closes the tuning panel; the CTA navigates to `/browse`.

- [ ] **Step 6: Record final verification output**

Report the exact test count, typecheck result, build result, screenshots/viewport names, and any residual limitation. Do not claim prototype parity if any required Gate surface remains intentionally absent.
