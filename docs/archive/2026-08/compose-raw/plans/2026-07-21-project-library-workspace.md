# Project Library Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the default React Browse workspace from a generic file list into the legacy-compatible configured-depth project library.

**Architecture:** Keep `ProjectService` and `/api/projects` as the project-identity authority. Introduce a typed frontend project-list API/hook, then make BrowsePage coordinate inspection, explicit ZIP selection, folder navigation, and project detail routing. Generic `/api/files` remains intact but unused by this workspace.

**Tech Stack:** React 18, TypeScript, React Router, Tailwind CSS, Vitest, Testing Library, aiohttp LAN routes, existing `ProjectService`.

## Global Constraints

- `ProjectDepthConfig` and server-supplied `is_project` are the only project-identity authority.
- `/browse` defaults to the project library and does not display ordinary files in its primary list.
- Do not alter `/api/files`; reserve it for a later dedicated general file browser.
- Normal inspection click never mutates ZIP selection; explicit selection controls alone do.
- Preserve same-origin cookie authentication, PathGuard, and backend authorization.
- Do not add permission or share-link work in this batch.
- Use TDD. Do not create commits unless explicitly requested.

---

## File Structure

- `webui/src/types/api.ts`: Add `ProjectListItem` and `ProjectListing` types distinct from generic `ProjectItem`.
- `webui/src/api/projects.ts`: Typed `/api/projects` request boundary.
- `webui/src/hooks/useProjectListing.ts`: Current project-library path, sort, request lifecycle, and stale-request protection.
- `webui/src/pages/BrowsePage.tsx`: Coordinate project/folder inspection, routing, explicit selection, tag state, and panes.
- `webui/src/components/files/ProjectGrid.tsx`, `ProjectList.tsx`, `ProjectCard.tsx`: Render and dispatch semantic project/folder interactions.
- `webui/src/components/files/FileToolbar.tsx`: Project/folder count and explicit selection/download controls.
- `webui/src/components/layout/InfoPanel.tsx`: Folder context or project-detail inspection.
- `webui/src/pages/DetailPage.tsx`: Project detail tag navigation back to `/browse`.
- `webui/src/api/projects.test.ts`, `webui/src/hooks/useProjectListing.test.tsx`, and relevant component/page test files: regression coverage.

### Task 1: Add Typed Project Listing Boundary

**Covers:** [S1, S2, S5, S6, S7, S9, S11]

**Files:**
- Modify: `webui/src/types/api.ts`
- Create: `webui/src/api/projects.ts`
- Create: `webui/src/api/projects.test.ts`
- Create: `webui/src/hooks/useProjectListing.ts`
- Create: `webui/src/hooks/useProjectListing.test.tsx`

**Interfaces:**
- Consumes: `ApiClient.get<T>(path, params?, signal?)` and `/api/projects` response fields.
- Produces:

```ts
export interface ProjectListItem {
  name: string;
  path: string;
  is_project: boolean;
  thumbnail_url: string | null;
  tags: string[];
  total_size: number;
  total_size_fmt: string;
  file_count: number;
  notes: string;
  modified: number;
}

export interface ProjectListing {
  current_path: string;
  parent_path: string;
  items: ProjectListItem[];
  total_count: number;
  folder_count: number;
  project_count: number;
  total_size: number;
  total_size_fmt: string;
}

export function createProjectsApi(api: ApiClient): {
  list(params: { path?: string; sort?: string; order?: 'asc' | 'desc'; search?: string }, signal?: AbortSignal): Promise<ProjectListing>;
}
```

- [ ] **Step 1: Write a failing API serialization test**

```ts
it('requests the server project listing with path and sort fields', async () => {
  const get = vi.fn().mockResolvedValue({ current_path: 'clients', items: [] });
  await createProjectsApi({ get } as unknown as ApiClient).list({ path: 'clients', sort: 'size', order: 'desc' });
  expect(get).toHaveBeenCalledWith('projects', {
    path: 'clients', sort: 'size', order: 'desc', search: undefined,
  }, undefined);
});
```

- [ ] **Step 2: Run the API test and verify RED**

Run: `npm test -- --run src/api/projects.test.ts`

Expected: FAIL because `createProjectsApi` does not exist.

- [ ] **Step 3: Write a failing stale-listing hook test**

```tsx
it('keeps the newer directory listing when an older request resolves last', async () => {
  const first = deferred<ProjectListing>();
  const second = deferred<ProjectListing>();
  list.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  const { result } = renderHook(() => useProjectListing());
  act(() => result.current.navigateTo('clients'));
  second.resolve(listing('clients', ['Client A']));
  await waitFor(() => expect(result.current.data?.current_path).toBe('clients'));
  first.resolve(listing('', ['Stale']));
  expect(result.current.data?.current_path).toBe('clients');
});
```

- [ ] **Step 4: Run hook test and verify RED**

Run: `npm test -- --run src/hooks/useProjectListing.test.tsx`

Expected: FAIL because the hook does not exist.

- [ ] **Step 5: Implement types, API, and minimal hook**

```ts
export function useProjectListing(initialPath = '') {
  const { api } = useAuth();
  const projectsApi = useMemo(() => createProjectsApi(api), [api]);
  const [currentPath, setCurrentPath] = useState(initialPath);
  const [sort, setSort] = useState<SortConfig>({ sort: 'name', order: 'asc' });
  const requestId = useRef(0);
  // Fetch with AbortController; accept a response only when its request id is current.
}
```

- [ ] **Step 6: Verify green and preserve generic file browser API**

Run: `npm test -- --run src/api/projects.test.ts src/hooks/useProjectListing.test.tsx && npm run typecheck`

Expected: PASS. Confirm `webui/src/api/files.ts` is unchanged.

### Task 2: Rewire BrowsePage To The Project Library Model

**Covers:** [S1, S2, S3, S4, S5, S6, S7, S8, S9, S11]

**Files:**
- Modify: `webui/src/pages/BrowsePage.tsx`
- Modify: `webui/src/pages/BrowsePage.test.tsx`
- Modify: `webui/src/components/files/Breadcrumb.tsx` only if project listing parent navigation needs its exact typed `parent_path`.

**Interfaces:**
- Consumes: `useProjectListing()` from Task 1, `ProjectListItem`, `ProjectDetail`, current tag-search API.
- Produces semantic callbacks:

```ts
onInspect(item: ProjectListItem): void
onOpenFolder(path: string): void
onOpenProject(path: string): void
onToggleZipSelection(path: string): void
```

- [ ] **Step 1: Write failing interaction tests**

```tsx
it('inspects a project on normal click without adding it to ZIP selection', async () => {
  renderBrowseWithListing([project('brand-kit')]);
  await userEvent.click(screen.getByRole('button', { name: /inspect brand-kit/i }));
  expect(screen.getByTestId('selected-project-path')).toHaveTextContent('brand-kit');
  expect(screen.queryByRole('button', { name: /download 1 selected/i })).not.toBeInTheDocument();
});

it('opens folders and projects through different paths', async () => {
  renderBrowseWithListing([folder('clients'), project('brand-kit')]);
  await userEvent.dblClick(screen.getByRole('button', { name: /inspect clients/i }));
  expect(mockNavigateTo).toHaveBeenCalledWith('clients');
  await userEvent.dblClick(screen.getByRole('button', { name: /inspect brand-kit/i }));
  expect(mockNavigate).toHaveBeenCalledWith('/detail?path=brand-kit');
});
```

- [ ] **Step 2: Run test and verify RED**

Run: `npm test -- --run src/pages/BrowsePage.test.tsx`

Expected: FAIL because BrowsePage still consumes `useProjects` and applies generic file behavior.

- [ ] **Step 3: Replace generic listing coordination**

- Replace `useProjects` with `useProjectListing` in BrowsePage.
- Retain current URL path synchronization, active tag cancellation, serialized ZIP transfer, pane state, and WebSocket refresh.
- When tag results are active, map server results to project list entries only if their existing response carries project facts; otherwise retain tag search as a detail/navigation action and do not synthesize `is_project`.
- Normal click assigns `inspectedItem`; it does not alter `zipSelectedPaths`.
- Enter/double click/mobile open uses `is_project ? onOpenProject : onOpenFolder`.
- Explicit selection mode alone calls `onToggleZipSelection`.

- [ ] **Step 4: Add mobile opening test**

```tsx
it('opens a project but navigates a folder on mobile single tap outside selection mode', async () => {
  mockMobile(true);
  renderBrowseWithListing([folder('clients'), project('brand-kit')]);
  await userEvent.click(screen.getByRole('button', { name: /inspect clients/i }));
  expect(mockNavigateTo).toHaveBeenCalledWith('clients');
  await userEvent.click(screen.getByRole('button', { name: /inspect brand-kit/i }));
  expect(mockNavigate).toHaveBeenCalledWith('/detail?path=brand-kit');
});
```

- [ ] **Step 5: Verify green**

Run: `npm test -- --run src/pages/BrowsePage.test.tsx && npm run typecheck`

Expected: PASS with generic-file BrowsePage tests updated or removed only when their behavior belongs to the deferred file-browser mode.

### Task 3: Render Distinct Folder And Project FileList Items

**Covers:** [S2, S3, S4, S6, S7, S8, S9, S11]

**Files:**
- Modify: `webui/src/components/files/ProjectCard.tsx`
- Modify: `webui/src/components/files/ProjectGrid.tsx`
- Modify: `webui/src/components/files/ProjectList.tsx`
- Modify: `webui/src/components/files/FileToolbar.tsx`
- Modify: `webui/src/components/files/ProjectCard.test.tsx`
- Modify: `webui/src/components/files/ProjectList.test.tsx`
- Create: `webui/src/components/files/ProjectGrid.test.tsx` if no grid behavior test exists.

**Interfaces:**
- Consumes: `ProjectListItem` and semantic callbacks from Task 2.
- Produces: Project cards/rows with project facts; folder cards/rows with navigation context; explicit ZIP selection controls.

- [ ] **Step 1: Write failing project/folder render tests**

```tsx
it('renders project facts and an explicit selection control', () => {
  render(<ProjectCard item={project('brand-kit')} onInspect={vi.fn()} onOpen={vi.fn()} onToggleZipSelection={vi.fn()} />);
  expect(screen.getByText('3 files')).toBeInTheDocument();
  expect(screen.getByText('24 MB')).toBeInTheDocument();
  expect(screen.getByRole('checkbox', { name: /select brand-kit for zip/i })).toBeInTheDocument();
});

it('renders folders as navigation containers without project metadata', () => {
  render(<ProjectCard item={folder('clients')} onInspect={vi.fn()} onOpen={vi.fn()} onToggleZipSelection={vi.fn()} />);
  expect(screen.getByText('clients')).toBeInTheDocument();
  expect(screen.queryByText(/files/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm test -- --run src/components/files/ProjectCard.test.tsx src/components/files/ProjectList.test.tsx`

Expected: FAIL because components still take generic `ProjectItem` fields and selection-on-click callbacks.

- [ ] **Step 3: Implement semantic item rendering**

- Project cards/rows show thumbnail fallback, tags, `file_count`, `total_size_fmt`, and modified date.
- Folder cards/rows show folder icon/name and direct navigation context only.
- Add an actual checkbox/button for ZIP selection with separate accessible name; inspect button/card does not toggle it.
- Provide `aria-label` values that distinguish `Inspect project <name>`, `Inspect folder <name>`, `Open project <name>`, and `Open folder <name>`.
- Toolbar text uses project/folder counts from `ProjectListing`; selected ZIP command uses only explicit ZIP selection count.

- [ ] **Step 4: Verify grid/list parity**

Run: `npm test -- --run src/components/files/ProjectCard.test.tsx src/components/files/ProjectGrid.test.tsx src/components/files/ProjectList.test.tsx && npm run typecheck`

Expected: PASS.

### Task 4: Make InfoPanel Project-Aware And Restore Detail Tag Navigation

**Covers:** [S3, S4, S5, S6, S7, S8, S9, S11]

**Files:**
- Modify: `webui/src/components/layout/InfoPanel.tsx`
- Modify: `webui/src/components/layout/InfoPanel.test.tsx`
- Modify: `webui/src/pages/BrowsePage.tsx`
- Modify: `webui/src/pages/DetailPage.tsx`
- Create: `webui/src/pages/DetailPage.test.tsx`

**Interfaces:**
- Consumes: `inspectedItem: ProjectListItem | null`, `projectDetail: ProjectDetail | null`, `projectDetailLoading`, `projectDetailError`.
- Produces:

```ts
<InfoPanel
  item={inspectedItem}
  projectDetail={projectDetail}
  loading={projectDetailLoading}
  error={projectDetailError}
  onOpenFolder={(path) => void 0}
  onTagClick={(tag) => void 0}
  onDownloadProject={(path) => void 0}
/>
```

- [ ] **Step 1: Write failing InfoPanel tests**

```tsx
it('renders project detail facts and requests a project download', async () => {
  render(<InfoPanel item={project('brand-kit')} projectDetail={detail('brand-kit')} onDownloadProject={download} />);
  expect(screen.getByText('3 files')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: /download project brand-kit/i }));
  expect(download).toHaveBeenCalledWith('brand-kit');
});

it('renders folder context without requesting or displaying project detail', () => {
  render(<InfoPanel item={folder('clients')} projectDetail={null} onOpenFolder={openFolder} />);
  expect(screen.getByText(/folder/i)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /download project/i })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test and verify RED**

Run: `npm test -- --run src/components/layout/InfoPanel.test.tsx`

Expected: FAIL because InfoPanel accepts only metadata and has no project/folder split.

- [ ] **Step 3: Implement project-detail loading and panel split**

- BrowsePage requests `getProjectDetail(path)` only when `inspectedItem.is_project`; use AbortController/generation guard.
- Project InfoPanel order: preview, project label/path, file count/size/modified, tags, notes, safe URLs, download.
- Folder InfoPanel shows type/path and Open Folder action. It does not call project detail endpoint.
- Detail loading error stays in InfoPanel and does not clear project list or path.

- [ ] **Step 4: Write a failing DetailPage tag navigation test**

```tsx
it('returns to browse with the selected project tag', async () => {
  renderDetail(detail('brand-kit', { tags: ['identity'] }));
  await userEvent.click(screen.getByRole('button', { name: 'identity' }));
  expect(mockNavigate).toHaveBeenCalledWith('/browse?tag=identity');
});
```

- [ ] **Step 5: Implement tag navigation and verify**

- Make detail tags buttons.
- Navigate with `createSearchParams({ tag })` or equivalent encoded query.
- Update BrowsePage initialization to read `tag` and enter the existing tag filter safely.

Run: `npm test -- --run src/components/layout/InfoPanel.test.tsx src/pages/DetailPage.test.tsx src/pages/BrowsePage.test.tsx && npm run typecheck && npm run build`

Expected: PASS.

### Task 5: Project Library Acceptance And Regression

**Covers:** [S1, S2, S3, S4, S5, S6, S7, S8, S9, S10, S11]

**Files:**
- Modify only files required by failures.
- Create: `docs/compose/reports/2026-07-21-project-library-workspace.md`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: verified evidence that project library behavior matches the approved project model.

- [ ] **Step 1: Run focused WebUI project-library tests**

Run:

```powershell
npm test -- --run src/api/projects.test.ts src/hooks/useProjectListing.test.tsx src/pages/BrowsePage.test.tsx src/components/files/ProjectCard.test.tsx src/components/files/ProjectGrid.test.tsx src/components/files/ProjectList.test.tsx src/components/layout/InfoPanel.test.tsx src/pages/DetailPage.test.tsx
```

Expected: PASS.

- [ ] **Step 2: Run LAN project-route regression tests**

Run:

```powershell
python -m pytest tests/lan/test_lan_api.py -q
```

Expected: PASS. If an existing focused project-route test file exists, include it in the command and record the exact result.

- [ ] **Step 3: Run full WebUI gates**

Run:

```powershell
npm run typecheck
npm test
npm run build
git diff --check
```

Expected: all pass.

- [ ] **Step 4: Manually verify the semantic workflow**

At desktop and 375px width, verify:

1. Tree folder navigates; tree project leaf enters detail.
2. Main list displays folders and projects, but no ordinary files.
3. Folder opens folder; project opens detail.
4. Normal click changes InfoPanel only; ZIP state stays empty.
5. Explicit selection enables ZIP download.
6. Project InfoPanel shows project facts; folder panel remains lightweight.
7. Detail tag enters browse tag filter and clearing returns to the current project listing.

- [ ] **Step 5: Write the evidence report**

Write `docs/compose/reports/2026-07-21-project-library-workspace.md` with actual commands, counts, API contract confirmation, each workflow result, and remaining deferred general-file-browser scope.

## Plan Self-Review

- Spec coverage: S1-S11 map to Tasks 1-5, with Task 5 providing cross-cutting acceptance.
- Placeholder scan: every task includes concrete files, interfaces, test examples, and commands.
- Type consistency: `ProjectListItem`, `ProjectListing`, `createProjectsApi`, `useProjectListing`, `inspectedItem`, and `zipSelectedPaths` are introduced before consumers rely on them.
