# FileList Scroll Boundary Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the FileList scrollbar by extracting the breadcrumb and controls into a fixed header sibling and giving only the asset canvas a reliable scroll boundary.

**Architecture:** BrowsePage will render a full-height page root with a fixed `file-list-header` containing Breadcrumb, tag feedback, and FileToolbar. A sibling `file-list-canvas` will own `flex: 1`, `min-height: 0`, and `overflow-y: auto`; context menus and dialogs remain outside both layout regions so they do not affect height calculation. AppLayout will provide a non-scrolling, shrinkable main slot.

**Tech Stack:** React, TypeScript, Tailwind utility classes, Vitest, Testing Library, Vite.

## Global Constraints

- Do not change file actions, sorting, selection, panel state, or responsive behavior.
- Keep FileToolbar and Breadcrumb outside `file-list-canvas` in the rendered DOM.
- Only `file-list-canvas` owns vertical scrolling for BrowsePage content.
- Preserve unrelated existing working-tree changes and do not create a Git commit.
- Follow TDD: add a failing regression test before changing production layout code.

---

### Task 1: Rebuild the FileList scroll boundary

**Covers:** fixed header/content sibling hierarchy, visible canvas scrollbar, unchanged Browse behavior.

**Files:**
- Modify: `webui/src/pages/BrowsePage.tsx`
- Modify: `webui/src/pages/BrowsePage.test.tsx`
- Modify: `webui/src/components/layout/AppLayout.tsx`
- Modify: `webui/src/components/files/FileToolbar.tsx`

**Interfaces:**
- Consumes: existing `AppLayout`, `Breadcrumb`, `FileToolbar`, `ProjectGrid`, `ProjectList`, and BrowsePage state/handlers.
- Produces: `data-testid="file-list-header"` and `data-testid="file-list-canvas"`; the header is not a descendant of the canvas, and the canvas has `flex-1 min-h-0 overflow-y-auto`.

- [ ] **Step 1: Write the failing test**

Extend the existing BrowsePage layout regression to assert the explicit header sibling:

```tsx
const workspace = screen.getByTestId('browse-workspace');
const header = screen.getByTestId('file-list-header');
const canvas = screen.getByTestId('file-list-canvas');
const toolbar = screen.getByTestId('file-toolbar');

expect(workspace.className).toContain('overflow-hidden');
expect(header.className).toContain('flex-shrink-0');
expect(canvas.className).toContain('flex-1');
expect(canvas.className).toContain('min-h-0');
expect(canvas.className).toContain('overflow-y-auto');
expect(header.contains(toolbar)).toBe(true);
expect(canvas.contains(header)).toBe(false);
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix webui test -- BrowsePage.test.tsx`

Expected: FAIL because the current BrowsePage has no `file-list-header` test node and the page root does not explicitly establish the overflow boundary.

- [ ] **Step 3: Write the minimal implementation**

In `BrowsePage.tsx`, use this structure inside `AppLayout`:

```tsx
<div data-testid="browse-workspace" className="flex h-full min-h-0 flex-col overflow-hidden">
  <div data-testid="file-list-header" className="flex-shrink-0">
    <Breadcrumb ... />
    {activeTag && <div ...>...</div>}
    <FileToolbar ... />
  </div>

  <div data-testid="file-list-canvas" className="min-h-0 flex-1 overflow-y-auto">
    {/* loading, error, empty, grid, and list branches */}
  </div>

  {/* ContextMenu remains outside header and canvas */}
</div>
```

Keep the existing handlers and content branches unchanged. In `AppLayout.tsx`, retain `main` as a non-scrolling shrinkable slot:

```tsx
<main className="flex min-h-0 min-w-0 flex-1 overflow-hidden">{children}</main>
```

Keep `FileToolbar`'s `data-testid="file-toolbar"` on its root element so the DOM relationship remains testable.

- [ ] **Step 4: Run focused and type checks**

Run:

```bash
npm --prefix webui test -- BrowsePage.test.tsx AppLayout.test.tsx FileToolbar.test.tsx
npm --prefix webui run typecheck
```

Expected: all focused tests pass and TypeScript exits successfully.

- [ ] **Step 5: Run full verification**

Run:

```bash
npm --prefix webui test
npm --prefix webui run build
git diff --check -- webui/src/pages/BrowsePage.tsx webui/src/pages/BrowsePage.test.tsx webui/src/components/layout/AppLayout.tsx webui/src/components/files/FileToolbar.tsx
```

Expected: all WebUI tests pass, Vite production build succeeds, and `git diff --check` reports no whitespace errors.
