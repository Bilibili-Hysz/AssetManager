# WebUI Resource Library And Workspace Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the sparse SPA root page with the Gate resource-library home and deliver the selected legacy LAN interactions as a cohesive, accessible React three-pane workspace.

**Architecture:** Keep the existing React SPA and LAN API modules as boundaries. `LandingPage` owns the Gate foyer lifecycle, `BrowsePage` coordinates workspace state, `Sidebar` owns one expanded-path set, FileList components render server facts and emit actions, and InfoPanel renders selection details only. API contract additions precede UI use; cookie authentication remains unchanged.

**Tech Stack:** React 18, TypeScript, React Router, Tailwind CSS, Vitest, Testing Library, aiohttp LAN API.

## Global Constraints

- The current `webui/` React SPA is the implementation target; do not copy legacy `static/app.js` or raw DOM handlers into it.
- Preserve cookie-only SPA authentication and same-origin LAN API/WebSocket contracts.
- Use the Gate reference at `D:\~Vibe-Coding\Projects\AssetsManager_Web_Gate_Design\DESIGN.md` as the root-route visual foundation.
- Do not invent client-side permissions or share URLs; display server-backed facts and retain server authorization as authoritative.
- The selected scope is batch ZIP/progress, tags, permission cues, share-link copy, tree controls, viewer gestures, mobile controls, and shortcuts. Deferred legacy features remain out of scope.
- Use focused TDD cycles. Do not create commits unless the user explicitly requests one.

---

## File Structure

- `webui/src/pages/LandingPage.tsx`: Gate resource-library home, real service identity, featured assets, reduced-motion-safe lifecycle.
- `webui/src/pages/BrowsePage.tsx`: path/selection/tag/pane coordination, no direct legacy DOM behavior.
- `webui/src/components/layout/Sidebar.tsx`: controlled tree expansion/filter interactions.
- `webui/src/components/layout/InfoPanel.tsx`: selected-asset preview/details/actions.
- `webui/src/components/files/FileToolbar.tsx`, `ProjectGrid.tsx`, `ProjectList.tsx`, `ProjectCard.tsx`: FileList commands and server-backed status cues.
- `webui/src/components/ui/DownloadProgress.tsx`: app-level determinate/indeterminate download transfer surface.
- `webui/src/components/viewer/ImageViewer.tsx`: viewer-scoped navigation, zoom, pan, touch behavior.
- `webui/src/api/files.ts`, `webui/src/api/metadata.ts`, `webui/src/api/shares.ts`, `webui/src/types/api.ts`: typed SPA contracts only.
- `AssetsManager/lan/routes/*.py` and `tests/lan/*.py`: touched only if a required UI fact has no current endpoint.

### Task 1: Establish A Verified WebUI Baseline

**Covers:** [S5, S7, S8, S10]

**Files:**
- Modify only files currently changed by unfinished WebUI work when required to restore the existing public interfaces.
- Test: `webui/src/pages/BrowsePage.test.tsx`, affected component/API tests.

**Interfaces:**
- Consumes: existing `ApiClient`, `useProjects`, `FilesApi`, and component prop interfaces.
- Produces: a green `npm run typecheck`, `npm test`, and `npm run build` baseline before redesign work.

- [ ] **Step 1: Capture the existing failures**

Run: `npm run typecheck && npm test && npm run build`

Expected: record every compiler/test failure with its file and line; do not hide errors with casts, ignored diagnostics, or deleted tests.

- [ ] **Step 2: Write a failing regression test for each behavioral correction required by the baseline**

Example for a partially written batch download contract:

```ts
it('uses same-origin credentials for a batch archive request', async () => {
  global.fetch = vi.fn().mockResolvedValue(new Response(new Blob(['zip']), {
    headers: { 'Content-Length': '3' },
  }));
  await createFilesApi({} as ApiClient).batchDownload(['asset.png']);
  expect(fetch).toHaveBeenCalledWith('/api/download/batch', expect.objectContaining({
    credentials: 'same-origin',
    body: JSON.stringify({ paths: ['asset.png'] }),
  }));
});
```

- [ ] **Step 3: Implement the smallest correction**

- Restore `BrowsePage` handler declaration order so hooks do not reference temporal-dead-zone callbacks.
- Remove unused imports and dead provider wiring.
- Keep `FilesApi.batchDownload(paths, onProgress?)` as the sole batch archive interface; it must return a rejected promise for an unsuccessful HTTP response.
- Revert any local state or type extension that is unsupported by the current LAN response until its route contract is added in Task 4.

- [ ] **Step 4: Verify the baseline**

Run: `npm run typecheck && npm test && npm run build`

Expected: all commands pass; output becomes the baseline for subsequent tasks.

### Task 2: Build The Gate Resource-Library Home

**Covers:** [S1, S2, S3, S4, S6, S7, S8, S9, S10]

**Files:**
- Modify: `webui/src/pages/LandingPage.tsx`, `webui/src/index.css`, `webui/src/App.tsx` only if provider/route wiring is necessary.
- Create: `webui/src/pages/LandingPage.test.tsx`.
- Modify: `webui/src/api/metadata.ts`, `webui/src/types/api.ts` only if existing API response types are insufficient.

**Interfaces:**
- Consumes: `useAuth(): { serverInfo, isLoading, isAuthenticated, role, api }`, `createMetadataApi(api)`, `ServerInfo`.
- Produces: `<LandingPage />` that redirects unauthenticated protected libraries to `/login`, otherwise renders a named Gate home with one `/browse` entry action.

- [ ] **Step 1: Write Gate route tests**

```tsx
it('sends an unauthenticated protected library to login', () => {
  mockAuth({ isLoading: false, isAuthenticated: false, role: null, serverInfo: { auth_enabled: true } });
  render(<MemoryRouter><Routes><Route path="/" element={<LandingPage />} /><Route path="/login" element={<p>Login</p>} /></Routes></MemoryRouter>);
  expect(screen.getByText('Login')).toBeInTheDocument();
});

it('shows the server identity and one browse entry action', async () => {
  mockAuth({ isLoading: false, isAuthenticated: true, serverInfo: { auth_enabled: true, share_name: 'Studio Assets', welcome_msg: 'Local library' } });
  render(<MemoryRouter><LandingPage /></MemoryRouter>);
  expect(screen.getByRole('heading', { name: 'Studio Assets' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /enter library/i })).toHaveAttribute('href', '/browse');
});
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `npm test -- src/pages/LandingPage.test.tsx`

Expected: FAIL because the existing sparse landing page has no Gate structure or featured-asset lifecycle.

- [ ] **Step 3: Implement the Gate page**

- Use one central column: library identity, concise status, up to six preview tiles, then `Link to="/browse"`.
- Obtain featured assets from an existing typed endpoint; if none exists, use the first six response items from an existing safe listing endpoint and treat empty/error states distinctly.
- Implement `prefers-reduced-motion`, document visibility pause/resume, image preloading, `onError` removal, and timer/listener cleanup in React `useEffect` cleanup.
- Store background tuning in per-theme localStorage keys and apply it only through root CSS custom properties.
- Keep all actions keyboard focusable and label the background panel with `aria-expanded` and `aria-controls`.

- [ ] **Step 4: Verify the Gate slice**

Run: `npm test -- src/pages/LandingPage.test.tsx && npm run typecheck && npm run build`

Expected: PASS.

### Task 3: Repair TreeList State And Workspace Frame

**Covers:** [S3, S4, S5, S6, S7, S8, S9, S10]

**Files:**
- Modify: `webui/src/components/layout/Sidebar.tsx`, `webui/src/components/layout/AppLayout.tsx`, `webui/src/index.css`.
- Test: `webui/src/components/layout/Sidebar.test.tsx`, `webui/src/components/layout/AppLayout.test.tsx`.

**Interfaces:**
- Consumes: `TreeItem[]`, `currentPath: string`, `onNavigate(path: string): void`.
- Produces: `Sidebar` with controlled `expandedPaths: Set<string>` and semantic `onNavigate` behavior.

- [ ] **Step 1: Write focused TreeList tests**

```tsx
it('expands every branch from the pane command and collapses them again', async () => {
  render(<Sidebar onNavigate={vi.fn()} currentPath="" />);
  await screen.findByRole('button', { name: /expand all/i });
  await userEvent.click(screen.getByRole('button', { name: /expand all/i }));
  expect(screen.getByRole('button', { name: /nested folder/i })).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: /collapse all/i }));
  expect(screen.queryByRole('button', { name: /nested folder/i })).not.toBeInTheDocument();
});

it('expands ancestors of the active path without navigating when its chevron is clicked', async () => {
  const onNavigate = vi.fn();
  render(<Sidebar onNavigate={onNavigate} currentPath="parent/child" />);
  await userEvent.click(screen.getByRole('button', { name: /toggle parent/i }));
  expect(onNavigate).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `npm test -- src/components/layout/Sidebar.test.tsx`

Expected: FAIL because each recursive node currently owns isolated expansion state and chevrons are non-semantic spans.

- [ ] **Step 3: Implement controlled tree behavior and compact pane styling**

- Derive initial expanded ancestors from `currentPath`.
- Pass `expandedPaths`, `onToggle(path)`, and filter match information through recursive nodes.
- Implement `expandAll` with all directory paths and `collapseAll` with an empty set; never force rerender tree data to simulate expansion.
- Render chevrons as `button` elements with `aria-label`, `aria-expanded`, and click propagation stopped.
- Keep the pane header to tree title, a filter input, and two compact icon/text actions.

- [ ] **Step 4: Verify desktop/mobile frame behavior**

Run: `npm test -- src/components/layout/Sidebar.test.tsx src/components/layout/AppLayout.test.tsx && npm run typecheck`

Expected: PASS.

### Task 4: Add Server-Backed FileList Commands And Status Cues

**Covers:** [S4, S5, S6, S7, S8, S9, S10]

**Files:**
- Modify: `webui/src/api/files.ts`, `webui/src/api/shares.ts`, `webui/src/types/api.ts`, `webui/src/hooks/useProjects.ts`, `webui/src/components/ui/DownloadProgress.tsx`, `webui/src/components/files/FileToolbar.tsx`, `webui/src/components/files/ProjectCard.tsx`, `webui/src/components/files/ProjectGrid.tsx`, `webui/src/components/files/ProjectList.tsx`, `webui/src/pages/BrowsePage.tsx`.
- Modify only if contract absent: `AssetsManager/lan/routes/files.py`, `AssetsManager/lan/routes/shares.py` and matching `tests/lan/` files.
- Test: `webui/src/api/files-shares.contract.test.ts`, `webui/src/components/files/ProjectCard.test.tsx`, `webui/src/pages/BrowsePage.test.tsx`, new `webui/src/components/ui/DownloadProgress.test.tsx`.

**Interfaces:**
- Consumes: `FilesApi.batchDownload(paths, onProgress?)`, `ShareLink.url`, server item capability fields when available.
- Produces: `activeTag: string | null`, `onTagFilter(tag)`, a determinate/indeterminate progress model, and server-backed share URL copy behavior.

- [ ] **Step 1: Write API and command tests**

```ts
it('reports determinate transfer progress and clicks a generated archive link', async () => {
  const stream = new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array([1, 2])); controller.close(); },
  });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream, { headers: { 'Content-Length': '2' } })));
  const progress = vi.fn();
  await createFilesApi({} as ApiClient).batchDownload(['a.png'], progress);
  expect(progress).toHaveBeenLastCalledWith(1);
});

it('does not render a copied share link until the server provides one', () => {
  render(<ProjectCard item={fileWithoutShareCapability} />);
  expect(screen.queryByRole('button', { name: /copy share link/i })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run focused tests and confirm they fail**

Run: `npm test -- src/api/files-shares.contract.test.ts src/components/files/ProjectCard.test.tsx`

Expected: FAIL until the typed contract and command behavior are correctly wired.

- [ ] **Step 3: Validate or add LAN response facts before UI usage**

- Inspect actual `/api/files`, `/api/search`, and share-create/list responses.
- If a response already includes capabilities/share URLs, type them exactly.
- If it does not, add the smallest route serializer fields and a LAN pytest asserting the response; do not infer role/capability client-side.
- Keep creating a share inside `ShareDialog`; a card only copies a URL previously returned by the server.

- [ ] **Step 4: Implement FileList behavior**

- `useProjects` owns `activeTag` and returns a filtered/query-backed item set. Tag chips in ProjectCard and InfoPanel call one `onTagFilter` callback; toolbar renders a clearable active-tag chip.
- `FileToolbar` exposes a selected-count ZIP command, disabled at zero selections; it calls `FilesApi.batchDownload` and shows toast errors.
- `DownloadProgress` supports `{ state: 'hidden' | 'indeterminate' | 'determinate', progress: number, label: string }`; it does not block navigation.
- Cards/list rows render only typed permission indicators. Permission visuals never replace backend enforcement.
- Add the server-returned share URL as a quick-copy affordance only after a valid share is available; otherwise open `ShareDialog`.

- [ ] **Step 5: Verify contract and UI behavior**

Run: `npm test -- src/api/files-shares.contract.test.ts src/components/files/ProjectCard.test.tsx src/pages/BrowsePage.test.tsx src/components/ui/DownloadProgress.test.tsx && npm run typecheck`

Expected: PASS. If LAN routes changed, also run the exact affected `python -m pytest tests/lan/... -q` command.

### Task 5: Complete The InfoPanel And Image Viewer Interaction Model

**Covers:** [S4, S5, S6, S7, S8, S9, S10]

**Files:**
- Modify: `webui/src/components/layout/InfoPanel.tsx`, `webui/src/components/viewer/ImageViewer.tsx`, `webui/src/pages/BrowsePage.tsx`.
- Test: `webui/src/components/layout/InfoPanel.test.tsx`, create `webui/src/components/viewer/ImageViewer.test.tsx`.

**Interfaces:**
- Consumes: `Metadata`, selected `ProjectItem`, `onTagFilter(tag)`, `onDownload(path)`, `onShare(paths)`.
- Produces: an inspection-only InfoPanel and viewer navigation/zoom behavior scoped to the open viewer.

- [ ] **Step 1: Write the failing interaction tests**

```tsx
it('sends an InfoPanel tag through the shared tag-filter callback', async () => {
  const onTagFilter = vi.fn();
  render(<InfoPanel metadata={{ path: 'a.png', tags: ['portrait'], notes: '', urls: [] }} onTagClick={onTagFilter} />);
  await userEvent.click(screen.getByRole('button', { name: 'portrait' }));
  expect(onTagFilter).toHaveBeenCalledWith('portrait');
});

it('resets a zoomed image with the zero key without closing the viewer', async () => {
  render(<ImageViewer images={['/a.png']} currentIndex={0} onClose={vi.fn()} />);
  await userEvent.dblClick(screen.getByAltText('Image 1'));
  await userEvent.keyboard('0');
  expect(screen.getByAltText('Image 1')).toHaveStyle({ transform: expect.stringContaining('scale(1)') });
});
```

- [ ] **Step 2: Run focused tests and confirm they fail**

Run: `npm test -- src/components/layout/InfoPanel.test.tsx src/components/viewer/ImageViewer.test.tsx`

Expected: FAIL for missing action contracts or non-scoped gesture behavior.

- [ ] **Step 3: Implement the minimal inspection and viewer changes**

- InfoPanel header displays selected identity/type and close control; render preview only for a supported thumbnail/image URL.
- Keep body ordering: tags, notes, trusted URLs, technical details, then relevant server-backed actions.
- Viewer consumes wheel/pointer/touch events only inside its content region. Do not close it from a gesture; only its close button/Escape closes it.
- Restrict pan to `scale > 1`; keep arrow navigation and `0` reset; respect `prefers-reduced-motion` for transition duration.

- [ ] **Step 4: Verify the slice**

Run: `npm test -- src/components/layout/InfoPanel.test.tsx src/components/viewer/ImageViewer.test.tsx && npm run typecheck && npm run build`

Expected: PASS.

### Task 6: Finish Mobile And Workspace Keyboard Semantics

**Covers:** [S4, S6, S7, S8, S10]

**Files:**
- Modify: `webui/src/components/layout/AppLayout.tsx`, `webui/src/pages/BrowsePage.tsx`, `webui/src/index.css`.
- Test: `webui/src/components/layout/AppLayout.test.tsx`, `webui/src/pages/BrowsePage.test.tsx`.

**Interfaces:**
- Consumes: `onSidebarToggle`, `onInfoToggle`, `onViewModeToggle`, `onSelectModeToggle`, `selectMode`.
- Produces: mobile actions with proper focus/ARIA state and global shortcuts that never intercept editable elements.

- [ ] **Step 1: Write focused mobile and shortcut tests**

```tsx
it('does not trigger workspace shortcuts while typing in the search field', async () => {
  render(<BrowsePage />);
  const search = screen.getByRole('searchbox');
  await userEvent.click(search);
  await userEvent.keyboard('g');
  expect(screen.getByRole('button', { name: /list view/i })).not.toHaveAttribute('aria-pressed', 'true');
});

it('reports mobile selection mode as pressed and restores focus after closing details', async () => {
  render(<AppLayout {...props} selectMode={false} />);
  await userEvent.click(screen.getByRole('button', { name: /select/i }));
  expect(props.onSelectModeToggle).toHaveBeenCalledOnce();
});
```

- [ ] **Step 2: Run focused tests and confirm they fail**

Run: `npm test -- src/components/layout/AppLayout.test.tsx src/pages/BrowsePage.test.tsx`

Expected: FAIL until focus and keyboard scope are explicit.

- [ ] **Step 3: Implement mobile/keyboard behavior**

- Make workspace search discoverable with `role="searchbox"` or an explicit associated label.
- `/` focuses search only when focus is not in an input, select, textarea, or contenteditable element.
- `Esc` clears transient filter/selection before closing mobile overlays; `g` changes view; `s` toggles selection mode.
- Use `aria-pressed` for view/selection controls and focus restoration for mobile dialog dismissal.
- Retain the existing four-action bottom bar; do not add a separate floating action cluster.

- [ ] **Step 4: Run full WebUI verification**

Run: `npm run typecheck && npm test && npm run build`

Expected: PASS.

### Task 7: Cross-Layer Regression And Acceptance Pass

**Covers:** [S1, S2, S3, S4, S5, S6, S7, S8, S9, S10]

**Files:**
- Modify: only failures discovered during verification.
- Test: existing WebUI suite, affected LAN tests, browser acceptance coverage if configured.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: release-quality evidence for the completed selected interaction set.

- [ ] **Step 1: Run WebUI quality gates**

Run: `npm run typecheck && npm test && npm run build`

Expected: all pass with no new React Router or TypeScript diagnostics.

- [ ] **Step 2: Run LAN regression gates when contracts changed**

Run: `python -m pytest tests/lan/test_lan_api.py tests/lan/test_path_guard.py -q`

Expected: PASS. If this task did not modify a LAN route or serializer, record that the Python gate was not required rather than running unrelated edits.

- [ ] **Step 3: Perform responsive interaction acceptance**

Verify at desktop and 375px wide:

1. Root Gate page enters `/browse` and handles reduced motion.
2. Tree expand/collapse, navigation, and active ancestor behavior are correct.
3. File selection feeds InfoPanel; tag filtering is visible and clearable.
4. Batch download shows a progress state and preserves same-origin cookies.
5. Mobile menu/details drawers close with Escape and restore focus.
6. Image viewer keyboard, wheel/pinch, pan, and reset behavior remain scoped.

- [ ] **Step 4: Record final evidence**

Append actual commands and results to `docs/compose/reports/2026-07-21-webui-resource-library-workspace.md`. Include known API limitations explicitly; do not mark a UI capability complete if the LAN route does not supply its source fact.

## Plan Self-Review

- Spec coverage: S1-S10 are mapped across Tasks 1-7; cross-layer verification covers the end-to-end requirements.
- Placeholder scan: no unresolved implementation placeholders are used; conditional LAN work is explicitly bounded by contract inspection and tests.
- Type consistency: `FilesApi.batchDownload(paths, onProgress?)`, `expandedPaths`, `activeTag`, and semantic InfoPanel action names are defined consistently before dependent tasks.
