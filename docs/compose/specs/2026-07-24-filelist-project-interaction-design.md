# Filelist Project Interaction Design

## [S1] Identity

Product UI Designer working in existing-codebase mode: preserve the dense AssetManager workspace and clarify action semantics through event behavior, hierarchy, and focus state.

## [S2] Objective

Make Filelist selection and navigation predictable on desktop while preserving mobile usability:

- Desktop single click selects an item and loads its detail in the right InfoPanel.
- Desktop double click enters a normal directory.
- Desktop double click on a directory marked as a configured Project opens the existing independent `/detail?path=...` Project detail page.
- Mobile single click retains direct navigation; a configured Project opens the independent detail page.
- Existing batch selection mode remains available and keeps its selection semantics.

## [S3] Product Context

AssetManager has two meaningful browsing levels. The configured Projects level is the boundary between organizing folders and an individual asset project. The current API already has `ProjectDepthConfig`, `ProjectDetail`, `getProjectDetail()`, and `/detail?path=...`; the interaction change should connect those existing capabilities instead of creating a second detail model.

## [S4] Information Architecture

```text
Browse workspace
├── current folder listing
│   ├── single click: selected item -> right InfoPanel
│   └── double click
│       ├── normal directory -> next Filelist path
│       └── is_project directory -> /detail?path=<project>
└── Project detail page
    ├── back -> browser history, preserving the previous Browse URL
    ├── hero preview and project identity
    ├── tags, notes, links
    ├── image gallery
    └── project file list and download actions
```

The backend marks directory list items with `is_project`, calculated from the same `sidebar_depth_cfg`/`ProjectDepthConfig` that defines the Projects level. The frontend does not infer project status from string depth or folder names.

## [S5] Event Matrix

| Surface | Desktop normal mode | Desktop selection mode | Mobile |
|---|---|---|---|
| File single click | select + InfoPanel | toggle batch selection | select + InfoPanel where space permits |
| File double click | existing file detail route | existing selection behavior remains available | existing file detail behavior |
| Normal directory single click | select + InfoPanel, no navigation | no navigation | enter directory |
| Normal directory double click | enter directory | enter directory only through explicit double-click | not required |
| Project directory single click | select + InfoPanel, no navigation | no navigation | open Project detail page |
| Project directory double click | open Project detail page | open Project detail page | not required |

Keyboard follows the desktop semantic model: focus plus Enter activates the same primary item action as double click; Space remains the selection affordance when selection mode is active. Every item retains a visible focus ring.

## [S6] Layout and Visual Behavior

The existing three-column workspace remains intact:

```text
┌────────────┬──────────────────────────────────┬──────────────┐
│ Sidebar    │ Breadcrumb / toolbar             │ InfoPanel    │
│ folders    ├──────────────────────────────────┤ selected item │
│            │ Filelist                         │ metadata     │
│            │ single click keeps this view     │              │
└────────────┴──────────────────────────────────┴──────────────┘
```

The item itself must communicate that a single click is selection/detail inspection and that directory navigation is a deeper action. Existing hover, focus, selected background, thumbnail, and context-menu affordances remain; no new decorative card layer is introduced. The independent Project detail page keeps its current visual language and receives a reliable back path through browser history.

## [S7] Navigation and State

- Directory navigation continues to update `/browse?path=...` through the existing BrowsePage path synchronization.
- Project detail navigation uses `/detail?path=${encodeURIComponent(item.path)}`.
- Browser Back returns to the exact Browse URL that launched the detail page, including the current path and active filters when already represented in the URL.
- InfoPanel selection state is cleared or naturally replaced when Browse listing generation changes; stale metadata requests remain abortable.
- The mobile branch preserves its current direct-navigation ergonomics because mobile does not have a dependable double-click gesture.

## [S8] Accessibility and Feedback

- Item controls remain real buttons or keyboard-operable rows with `aria-label`, `aria-pressed` where selection applies, and visible `focus-visible` rings.
- Double-click is an accelerator, not the only way to reach a Project detail page: focused Enter and the existing context/detail affordance must provide an equivalent path.
- Project detail page keeps a labeled Back control and a focusable main content heading.
- Selection must have a non-color-only state through `aria-pressed`/selected semantics and the existing visual treatment.

## [S9] Testing Contract

- Backend: `/api/files` directory items expose `is_project` according to `sidebar_depth_cfg`; ordinary directories expose false; file items remain unchanged.
- Grid/List: desktop single click invokes selection/inspection without navigation; directory double click invokes navigation; Project double click invokes detail navigation; mobile retains direct directory navigation.
- BrowsePage: selected directory loads InfoPanel metadata; Project detail path is encoded; ordinary directory path remains unchanged; selection mode is not regressed.
- Detail route: `/detail?path=...` receives the project path and existing ProjectDetail rendering remains intact.
- Responsive and accessibility tests cover keyboard Enter, focus state, and mobile branch behavior.

## [S10] Decision Trace

```json
[
  {
    "decision": "Use backend is_project metadata based on ProjectDepthConfig",
    "reason": "The Projects boundary already belongs to sidebar_depth_cfg; duplicating path-depth logic in React would drift across branches and libraries.",
    "alternatives": ["Infer from URL segment count in BrowsePage", "Treat every directory with a thumbnail as a Project"],
    "tradeoff": "Adds one response field and backend tests, but keeps the frontend semantically simple and configuration-correct."
  },
  {
    "decision": "Use the existing independent /detail route for Project double-click",
    "reason": "ProjectDetail, gallery, notes, tags, downloads, and browser history already exist there; replacing BrowsePage would duplicate that surface.",
    "alternatives": ["Replace the Browse workspace in place", "Expand only the right InfoPanel"],
    "tradeoff": "Navigation leaves the Filelist temporarily, so a clear Back action and preserved browser history are required."
  },
  {
    "decision": "Keep mobile single-click navigation",
    "reason": "The requested double-click convention is a desktop computer interaction; touch devices need a direct, reliable navigation gesture.",
    "alternatives": ["Require a mobile double tap", "Add a separate mobile Enter button"],
    "tradeoff": "The same directory has different primary gestures across platforms, but each matches platform expectations."
  },
  {
    "decision": "Keep batch selection mode as an explicit mode",
    "reason": "Single-click selection/detail and multi-file ZIP selection are different intents; conflating them would make bulk operations error-prone.",
    "alternatives": ["Always make single click toggle selection", "Remove selection mode"],
    "tradeoff": "Users must enter selection mode for bulk work, preserving the current deliberate workflow."
  }
]
```

## [S11] Anti-Slop Self-Check

Clean. The design does not add decorative cards, new visual branding, or a second detail surface. It changes event semantics and uses existing hierarchy and detail capabilities to reduce ambiguity.
