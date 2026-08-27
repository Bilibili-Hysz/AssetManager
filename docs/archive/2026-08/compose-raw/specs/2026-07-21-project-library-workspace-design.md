# Project Library Workspace Design

## [S1] Objective

Make `/browse` the default **project library workspace**, matching the legacy LAN model: configured-depth directories are projects; shallower directories are folders that organize and lead to projects; ordinary files belong inside project detail rather than the primary workspace list.

The purpose is to restore a coherent user mental model across TreeList, FileList, InfoPanel, detail, selection, and download actions. A separate general file browser is explicitly deferred.

## [S2] Domain Contract

`ProjectDepthConfig` is the authority for project identity. For a directory shown at the current location:

- `is_project: false` means **folder**: an organizational directory below the configured depth boundary.
- `is_project: true` means **project**: the asset unit at or beyond the configured branch depth.
- Ordinary files are not primary-list items. They are displayed in the selected project's detail view.

The SPA project workspace consumes `/api/projects`, which already returns `ProjectListItem` facts: `is_project`, thumbnail, tags, total size, file count, notes, and modified time. It must not infer project identity from a path, file extension, or client-side depth calculation.

## [S3] Information Architecture

### TreeList

TreeList remains the project hierarchy index from `/api/tree`:

- Non-leaf nodes are folders and navigate the FileList into that location.
- `is_leaf` nodes represent project directories and open project detail.
- Project leaves use an explicit project-directory icon and accessible label, not a generic file icon.

### FileList

FileList consumes one `ProjectListing` for the current folder:

- Folder row/card: compact organizational presentation; single click selects it for inspection, double click opens the folder.
- Project row/card: enriched presentation with thumbnail, tags, file count, total size, and modified state; single click selects it for inspection, double click opens project detail.
- List and grid carry the same semantic fields and actions.
- The toolbar counts projects and folders separately rather than treating every item as a generic file.

### InfoPanel

InfoPanel is an inspection view for the selected `ProjectListItem`:

- A selected project loads `/api/projects/{path}` and presents preview, project type, path, file count, total size, modified date, tags, notes, safe links, and project download.
- A selected folder presents minimal navigation-oriented context: folder type, path, and action to open it. It does not request project detail.
- Tags from a selected project activate the existing tag-search workflow.

### Detail

Project detail remains the full-screen project view. Its tags are actionable and route back to `/browse` with the selected tag filter rather than being static decoration.

## [S4] Interaction Rules

### Selection And Opening

- Normal desktop click changes the inspected item only. It does **not** add an item to the ZIP selection set.
- Explicit selection mode or checkbox changes the ZIP selection set. On mobile, selection mode stays explicit through the bottom-bar control.
- Double click / Enter: project -> `/detail?path=...`; folder -> navigate to folder path.
- Mobile single tap outside selection mode follows the same open rule: project -> detail, folder -> navigation.

### Tag Search

- Project tag activation enters the existing server-backed tag search state and visibly identifies the active tag.
- Clearing the filter returns to the current project listing.
- Route changes invalidate tag results, as already required by the current workspace contract.

### Downloads

- Project detail exposes project-directory download.
- Batch ZIP selection is allowed only through explicit selection controls. The existing serialized progress/error behavior is retained.
- Folder/project selection for inspection never implicitly enables ZIP action.

## [S5] Component And API Boundaries

- Add a typed `ProjectListItem` and `ProjectListing` frontend contract separate from generic file types.
- `createProjectsApi(api)` owns `/api/projects` requests and returns typed project listings.
- Replace `useProjects` with a project-listing-oriented hook or rename it only if its generic name becomes misleading. It owns current path, sort, listing state, refresh, and directory-summary-free project loading.
- `BrowsePage` owns selected inspection item, explicit ZIP selection, active tag, pane state, and route synchronization.
- `ProjectGrid` and `ProjectList` receive `ProjectListItem[]` plus semantic `onInspect`, `onOpenFolder`, `onOpenProject`, and explicit selection callbacks; they do not fetch.
- `InfoPanel` receives selected item plus optional `ProjectDetail`; it does not decide a path's project status itself.
- Keep `/api/files` and `AssetService` unchanged for a future standalone file browser; do not remove their routes or overload them with project semantics.

## [S6] Error Handling And Accessibility

- Project-list fetch failures display a recoverable inline list error; prior successful listings must not be relabeled as a different path.
- A failed project-detail request affects only the InfoPanel and keeps folder navigation/list state usable.
- Tree project leaves, project cards, folder cards, detail links, and selection controls have distinct accessible names that state their action.
- Folder/project icons communicate the same semantics as text; color alone is not the distinction.
- Keyboard Enter follows the same folder/project split as double click; explicit selection stays controllable by keyboard.

## [S7] Test And Acceptance Requirements

- API tests assert `/api/projects` query serialization and typed response mapping.
- Hook tests cover path navigation, sort, stale-response rejection, and listing error.
- Grid/list tests verify project and folder render differently and dispatch their respective open callbacks.
- BrowsePage tests cover normal click inspection without ZIP selection; project/folder desktop and mobile opening; tag filtering and explicit selection/download coexistence.
- InfoPanel tests cover project detail rendering, project-detail error, and folder minimal view with no project-detail request.
- DetailPage tests cover tag navigation back to browse filter.
- LAN route tests remain unchanged unless a response fact is missing; existing `/api/projects` contract must be verified before implementation.

## [S8] Implementation Sequence

1. Establish frontend project-list types/API/hook and focused contract tests.
2. Rewire BrowsePage, FileList grid/list, breadcrumb, and toolbar to the project listing model.
3. Split inspect/open/explicit-select interactions and verify desktop/mobile behavior.
4. Upgrade InfoPanel and project detail tag navigation.
5. Run full WebUI gates and affected LAN API contract tests.

## [S9] Constraints And Non-Goals

- Do not alter `ProjectDepthConfig` or client-side reimplement its depth logic.
- Do not display ordinary files in the project workspace list.
- Do not replace `/api/files`; it remains reserved for later general file browsing.
- Do not make folder/project identity dependent on visual heuristics.
- Do not add share-link or permission-surface work in this batch.
- Do not weaken cookie-only authentication, path guard, or backend authorization.

## [S10] Decision Trace

```json
[
  {
    "decision": "Make project library the only default Browse workspace",
    "reason": "The legacy product and existing ProjectService both define the asset unit as a configured-depth project directory, while the current generic file listing breaks that interaction model.",
    "alternatives": ["Keep generic file browsing as the default", "Ship project and file modes together"],
    "tradeoff": "Ordinary files are not immediately visible from the primary workspace until a separate file-browser mode is designed."
  },
  {
    "decision": "Use server-supplied is_project instead of deriving project state in React",
    "reason": "ProjectDepthConfig supports branch-specific depth and is already applied by the LAN project service; client derivation would drift from the desktop and API model.",
    "alternatives": ["Infer by path depth in React", "Treat all directories as projects"],
    "tradeoff": "The workspace depends on the project listing endpoint rather than one generic files endpoint."
  },
  {
    "decision": "Separate inspection selection from ZIP selection",
    "reason": "Legacy desktop interaction uses click to inspect and an explicit control to enter batch selection, preventing accidental download operations while browsing.",
    "alternatives": ["Make every click toggle selection", "Remove batch selection"],
    "tradeoff": "The UI needs a visible explicit selection affordance in both grid and list views."
  },
  {
    "decision": "Make InfoPanel project-detail driven only for projects",
    "reason": "Project detail provides the meaningful asset summary; requesting it for folders or files produces incorrect or failing behavior.",
    "alternatives": ["Always request project detail", "Show metadata-only details for all items"],
    "tradeoff": "Folder inspection is intentionally lighter than project inspection."
  }
]
```

## [S11] Workflow

Implement in isolated worktree slices with test-first changes. Every slice passes `npm run typecheck`, `npm test`, and `npm run build`; LAN tests are run only if existing project-route contracts require modification. No commit is created without explicit user request.
