# Legacy InfoPanel Project Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the legacy LAN InfoPanel behavior where selecting a project loads its project detail, displays its cover thumbnail, and opens the project image gallery.

**Architecture:** BrowsePage owns asynchronous inspection data. It requests `ProjectDetail` for project/directory selections and `Metadata` for file selections, with the existing abort/generation guard. InfoPanel receives optional `projectDetail`; project cover/gallery data takes precedence, while a selected image file keeps the direct single-image preview fallback.

**Tech Stack:** React 18, TypeScript, React Router, Vitest, Testing Library, existing `/api/projects/{path}` and `/api/thumbnails/{path}` LAN contracts.

## Global Constraints

- Match the old `AssetsManager/lan/static/app.js` semantics for project preview.
- Project cover source is `ProjectDetail.thumbnail_url`.
- Project viewer source list is `ProjectDetail.images[].url`, with the cover image selected when its `thumb_url` matches `thumbnail_url`.
- Preserve direct preview for ordinary selected image files.
- Abort stale detail requests and prevent stale responses from replacing the current selection.
- Do not change backend response shapes or unrelated BrowsePage behavior.
- Preserve unrelated working-tree changes and do not create a Git commit.

---

### Task 1: Render project cover and gallery in InfoPanel

**Covers:** legacy project cover and multi-image viewer semantics.

**Files:**
- Modify: `webui/src/components/layout/InfoPanel.tsx`
- Modify: `webui/src/components/layout/InfoPanel.test.tsx`

**Interfaces:**
- Consumes: `projectDetail?: ProjectDetail | null`.
- Produces: cover `<img src={projectDetail.thumbnail_url}>` and ImageViewer `images={projectDetail.images.map(image => image.url)}` with the matched cover index.

- [ ] Write a failing test that passes a selected project directory and `ProjectDetail`, then asserts the cover URL and gallery URLs.
- [ ] Run `npm --prefix webui test -- InfoPanel.test.tsx` and confirm failure because `projectDetail` is not supported.
- [ ] Add the optional prop and resolve preview/viewer sources from project detail before the direct image-file fallback.
- [ ] Run the focused test and confirm all InfoPanel tests pass.

### Task 2: Load project detail from BrowsePage inspection

**Covers:** legacy `/api/projects/{path}` data flow and stale-request safety.

**Files:**
- Modify: `webui/src/pages/BrowsePage.tsx`
- Modify: `webui/src/pages/BrowsePage.test.tsx`

**Interfaces:**
- Consumes: `metaApi.getProjectDetail(path, signal)`.
- Produces: `selectedProjectDetail: ProjectDetail | null` passed to InfoPanel; file inspection continues to call `getMeta`.

- [ ] Extend the metadata API mock and BrowsePage InfoPanel mock, then write a failing test asserting project inspection calls `getProjectDetail` and passes its cover to InfoPanel.
- [ ] Run `npm --prefix webui test -- BrowsePage.test.tsx` and confirm failure because all selections currently call `getMeta`.
- [ ] Add an optional AbortSignal to `getProjectDetail`, branch inspection by `item.type === 'dir' || item.is_project`, and clear opposite detail state before each request.
- [ ] Run BrowsePage and InfoPanel tests, then typecheck.

### Task 3: Verify the restored chain

**Covers:** frontend and LAN contract closure.

**Files:**
- Verify: `webui/src/components/layout/InfoPanel.tsx`
- Verify: `webui/src/pages/BrowsePage.tsx`
- Verify: `tests/lan/test_lan_api.py`

**Interfaces:**
- Confirms `/api/projects/{path}` returns `thumbnail_url` and `images`, and thumbnail URLs return image content.

- [ ] Run `npm --prefix webui test` and require zero failures.
- [ ] Run `npm --prefix webui run typecheck` and require success.
- [ ] Run `pytest -q tests/lan/test_lan_api.py -k thumbnail` and require success.
- [ ] Run `npm --prefix webui run build` and require a successful production build.
- [ ] Run `git diff --check` for touched files and require no whitespace errors.
