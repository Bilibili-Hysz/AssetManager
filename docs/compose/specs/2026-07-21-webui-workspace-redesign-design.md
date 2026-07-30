# WebUI Resource Library And Workspace Redesign

## [S1] Objective

Replace the React SPA root route (`/`) with the AssetsManager Gate resource-library home experience, then evolve `/browse` into a reliable three-pane asset workspace. The result must preserve the existing cookie-only authentication, LAN API contracts, and React routing while restoring the useful old LAN interactions selected by the user: batch ZIP download with progress, tag filtering, permission/status cues, share-link copying, directory-tree expansion controls, image-viewer gestures, mobile workspace controls, and keyboard shortcuts.

The default user journey is:

1. Arrive at the Gate homepage and understand which library is online.
2. Enter the library.
3. Navigate in the TreeList, scan and select in the FileList, then inspect and act in the InfoPanel.

## [S2] Product Context And Scope

The current `webui/` React SPA is the implementation target. The old LAN static UI is behavioral reference material only; its global mutable DOM state and page-specific scripts are not copied into the SPA.

The reference Gate design at `D:\~Vibe-Coding\Projects\AssetsManager_Web_Gate_Design\DESIGN.md` is the durable visual basis for `/`: a dark local-library foyer, image-wall atmosphere, one prominent entry action, real service status, and reduced-motion-safe effects.

In scope:

- Gate homepage at `/`.
- Three-pane `/browse` workspace.
- Selected legacy interactions numbered 2, 3, 6, 7, 8, 9, 10, 11, and 12.


## [S3] Visual Foundations

### Workspace

- **Base:** `#020617` background, `#0f172a` structural surfaces, `#1e293b` elevated surfaces, `#334155` separators.
- **Accents:** indigo is the selection/focus system (`#6366f1`); amber identifies folders; emerald represents download-ready/success states; red is reserved for errors or protected restrictions.
- **Density:** compact desktop workspace: 32px row rhythm in TreeList, 40px command-bar rhythm, 8px spacing unit. Avoid dashboard-card grids inside navigation panes.
- **Typography:** existing system sans stack; file names receive visual priority, supporting metadata stays 11-12px, pane titles stay 12px semibold.
- **Surfaces:** hard-working panels use flat layered surfaces and one-pixel separators, not large-radius floating cards. Rounded corners are limited to controls, thumbnails, dialogs, and temporary notices.

### Gate Homepage

- Use the existing Gate palette: dark base `#07070d`, surface `#111122`, main text `#f1f5f9`, indigo `#6366f1`, violet `#a78bfa`.
- Full-viewport asset image wall is atmospheric background, not a content carousel.
- One central action, **Enter Library**, prevents the page from becoming a dashboard duplicate.

## [S4] Information Architecture And Interaction

### Gate Homepage (`/`)

1. Identify the library: avatar/mark, library name, concise welcome copy.
2. Establish trust: service status and a concise image/library summary from real APIs.
3. Preview up to six featured assets as the content anchor.
4. Offer one primary entry action to `/browse`.
5. Offer the low-priority Background control from the reference design, with persistent local visual tuning and an accessible close path.

If authentication is required, unauthenticated users are redirected to `/login`; authenticated users still see the Gate home rather than being forced straight into the workspace.

### TreeList (left pane)

- A dedicated pane header contains the title, tree filter, and compact expand-all/collapse-all actions.
- Expansion state belongs to one `expandedPaths` set in `Sidebar`, not each recursive node. This makes global controls, path restoration, and filtering deterministic.
- Clicking a directory selects and navigates it in the FileList. Its chevron only expands or collapses; it never changes selection.
- Active-path ancestors expand automatically. Filtering exposes matching branches and their ancestors without losing the user’s non-filter expansion state.
- The tree is a navigation index, not a second file browser: no duplicate action menus or metadata cards.

### FileList (center pane)

- The current path, breadcrumb, search state, sort, grid/list switch, and selection commands form a stable command strip.
- Single click selects. Double click or Enter opens. Selection mode is explicit on mobile; desktop supports modifier selection when the backend/item model permits it.
- Tags in cards and InfoPanel activate a visible filter chip in the command strip. Clearing the chip returns to the current directory listing.
- Selected items expose batch ZIP download. The command shows item count, remains disabled while no items are selected, and reports preparation/download failure through the existing toast system.
- Downloads show a non-modal progress bar when the response exposes `Content-Length`; otherwise they show an indeterminate transfer state. Browser download behavior remains standard after the Blob is assembled.
- Permission badges communicate information only: view-only, download unavailable, and password-protected. Backend authorization remains authoritative.
- Quick share-link copy appears only where a valid existing share link is available. Creating a share remains a deliberate ShareDialog flow; no client-side fabricated URLs.

### InfoPanel (right pane)

- The panel is selection-driven, never a second navigation tree.
- Header: selected file name/type, close control, compact primary actions that match permission state.
- Body order: preview (when available), tags, notes, trusted external URLs, technical metadata, share/download affordances.
- Loading retains panel geometry with skeletons. Empty state explains that an item must be selected.
- Clicking a tag dispatches the same filter action as FileList tag clicks.

### Image Viewer

- Retain Escape and arrow navigation.
- Add wheel/pinch zoom focused at the pointer/pinch center; drag pans only while zoomed beyond 1x.
- Double click/tap toggles between fit and a readable magnification. `0` resets fit.
- A short hint is announced visually only and respects `prefers-reduced-motion`; controls remain usable without gestures.

### Mobile And Keyboard

- Mobile bottom bar exposes menu/tree, view switch, details, and explicit selection mode. It uses stateful labels and `aria-pressed` for selection mode.
- `/` focuses the workspace search. `Esc` clears transient selection/filter first, then closes an open mobile pane. `g` toggles grid/list. `s` enters or exits selection mode. Image-viewer keys remain scoped to the viewer.
- Shortcuts never intercept typing in text inputs, selects, or editable content.

## [S5] Component Boundaries And Data Flow

- `LandingPage`: consumes existing server config/auth APIs plus a narrow featured-assets source; owns Gate-only visual lifecycle.
- `BrowsePage`: owns workspace state coordination only: path, selection, active tag, pane visibility/width, and overlay/dialog state.
- `Sidebar`: receives current path and navigation callbacks; owns `expandedPaths` and filter presentation state.
- `FileToolbar` and FileList: receive commands and selection state; do not call LAN APIs directly.
- `InfoPanel`: renders selected metadata and emits semantic actions (`onTagFilter`, `onDownload`, `onShare`).
- API modules remain the only fetch boundary. New optional fields must be backed by routes/contracts before UI uses them.
- `DownloadProgress` is provider state owned at app level, so batch downloads can outlive a local card or toolbar rerender.

## [S6] Error Handling And Accessibility

- API failures use concise toasts or inline pane messages; no silent `catch(() => {})` for user-initiated work.
- Gate image failures remove only the failed tile and leave the home action usable.
- Every icon-only action has an accessible name; tree chevrons are buttons, not clickable spans.
- Focus is restored when a mobile drawer, InfoPanel dialog, or image viewer closes.
- `prefers-reduced-motion` disables Gate background motion and viewer transition embellishments, without disabling navigation or zoom controls.
- Desktop and mobile must support 375px width without horizontal overflow.

## [S7] Testing And Acceptance

- Unit tests: TreeList global expansion/collapse, active ancestor expansion, tag filter dispatch, selected-item download command state, keyboard scoping, permission badge rendering, and image viewer reset/navigation.
- Component/API tests: batch download sends cookie-authenticated request, handles error response, and exposes determinate/indeterminate progress correctly.
- Browser tests: Gate root route entry, mobile bottom-bar modal focus/close behavior, drag-resize boundaries, and one full TreeList -> FileList -> InfoPanel flow.
- Existing `npm run typecheck`, `npm test`, and `npm run build` remain mandatory. Python LAN contract tests run whenever an API route changes.

## [S8] Implementation Sequence

1. Stabilize the currently edited WebUI files and restore a clean WebUI typecheck/test baseline before feature work.
2. Build the Gate homepage from the existing reference design using React and real SPA APIs.
3. Correct TreeList state ownership and establish the workspace visual tokens/layout behavior.
4. Add FileList selection commands, tag state, permission cues, and share-link affordances only after validating their LAN API support.
5. Improve InfoPanel and image viewer interactions.
6. Complete mobile/keyboard behavior, then run visual/browser and full quality gates.

## [S9] Anti-Patterns And Decision-Making

- Do not copy legacy `static/app.js`, static CSS, or raw DOM event handlers into React.
- Do not invent client-side permission/share state; display server-provided facts and keep server authorization authoritative.
- Do not turn the Gate homepage into a generic SaaS dashboard, a gradient hero, or a six-card marketing grid.
- Do not use individual TreeNode local expansion state for global tree actions.
- Do not introduce browser-readable authentication tokens or query-string WebSocket credentials.
- Do not broaden scope to deferred legacy features while completing the selected interaction set.

## Decision Trace

```json
[
  {
    "decision": "Use the Gate design as the React root route and keep /browse as the work surface",
    "reason": "The user explicitly wants the Gate resource library as the WebUI home while the current three-pane work requires a dense, task-first environment.",
    "alternatives": ["Embed the Gate design inside the browse workspace", "Keep the existing sparse landing page"],
    "tradeoff": "Users take one intentional step before browsing instead of landing directly in the file list."
  },
  {
    "decision": "Treat the TreeList, FileList, and InfoPanel as separate responsibility boundaries",
    "reason": "The requested interaction gaps arise from mixing navigation, selection, and inspection concerns; each pane needs one durable job.",
    "alternatives": ["A single adaptive content column", "Duplicate file actions in all panes"],
    "tradeoff": "Cross-pane coordination requires explicit state contracts in BrowsePage."
  },
  {
    "decision": "Centralize expanded tree paths in Sidebar",
    "reason": "Global expand/collapse and active-path restoration cannot work reliably when every recursive node owns private expanded state.",
    "alternatives": ["Force rerendering local TreeNode state", "Always render the full tree expanded"],
    "tradeoff": "Sidebar manages a path set and must prune it when the tree changes."
  },
  {
    "decision": "Show permission badges as server-backed status cues only",
    "reason": "The LAN API remains the security boundary; visual affordances must not imply client-side authorization.",
    "alternatives": ["Hide permissions entirely", "Disable actions using locally inferred roles"],
    "tradeoff": "Some badges wait on API contract support before they can appear."
  },
  {
    "decision": "Use a non-modal app-level download progress surface",
    "reason": "A ZIP transfer should remain observable without blocking navigation or selection during long LAN downloads.",
    "alternatives": ["Modal download dialog", "No transfer feedback"],
    "tradeoff": "Progress is indeterminate when the server does not supply Content-Length."
  },
  {
    "decision": "Keep Gate animation constrained by motion and lifecycle rules from its existing DESIGN.md",
    "reason": "The image wall is the intentional visual identity, but a local asset tool must not continue expensive background work when hidden or motion is reduced.",
    "alternatives": ["Static hero background", "Always-running particle effects"],
    "tradeoff": "The homepage needs explicit effect cleanup and more lifecycle tests."
  }
]
```

## [S10] Workflow

Implementation occurs in reviewable vertical slices. Each slice must include its focused React tests and pass WebUI typecheck/test/build before the next slice changes a separate pane. No commit is created unless explicitly requested.
