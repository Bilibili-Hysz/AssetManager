# InfoPanel and Viewer Image Fit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show all image aspect ratios completely in InfoPanel and provide reliable 25%–500% zoom relative to a full-image fit in ImageViewer.

**Architecture:** CSS `object-contain` establishes the visual fit baseline in both surfaces. ImageViewer's numeric scale is relative to that fitted image, with `1` meaning fit-to-canvas, `0.25` the minimum, and `5` the maximum; reset and image navigation return to the fit baseline.

**Tech Stack:** React 18, TypeScript, Tailwind utilities, Vitest, Testing Library.

## Global Constraints

- Preserve the existing dark workspace visual language and controls.
- InfoPanel uses a stable preview region and never crops the image.
- Viewer starts with the complete image visible.
- Viewer zoom range is 25%–500% relative to fit-to-canvas.
- Reset and image navigation restore 100% fit-to-canvas.
- Keep pointer, wheel, double-click, keyboard, focus restoration, and gallery navigation behavior.
- Modify only InfoPanel/ImageViewer implementation and tests; do not commit.

---

### Task 1: Make InfoPanel previews complete and stable

**Covers:** complete display of square, portrait, and landscape previews.

**Files:**
- Modify: `webui/src/components/layout/InfoPanel.tsx`
- Modify: `webui/src/components/layout/InfoPanel.test.tsx`

**Interfaces:**
- Consumes: existing `previewUrl`.
- Produces: a stable aspect-video neutral preview canvas containing an `object-contain` image.

- [ ] Add a failing test asserting the preview image uses `object-contain` and not `object-cover`.
- [ ] Run `npm --prefix webui test -- InfoPanel.test.tsx` and confirm RED.
- [ ] Move the aspect ratio to the preview button/canvas and change the image to `h-full w-full object-contain`.
- [ ] Run the focused test and confirm GREEN.

### Task 2: Make ImageViewer fit-first and zoomable below 100%

**Covers:** complete initial image display, zoom-out, reset, navigation reset, wheel and pinch bounds.

**Files:**
- Modify: `webui/src/components/viewer/ImageViewer.tsx`
- Modify: `webui/src/components/viewer/ImageViewer.test.tsx`

**Interfaces:**
- Produces: `MIN_SCALE = 0.25`, `FIT_SCALE = 1`, `MAX_SCALE = 5`; the image fills the viewer canvas box with `object-contain`, and transforms apply relative to the fitted image.

- [ ] Add failing tests that assert the image uses `object-contain`, Zoom out reaches `scale(0.5)`, wheel down reaches below `1`, and Reset restores `scale(1)`.
- [ ] Run `npm --prefix webui test -- ImageViewer.test.tsx` and confirm RED.
- [ ] Separate `FIT_SCALE` from `MIN_SCALE`, update reset/double-click/drag gates, and make the image/canvas occupy all available viewer space with `object-contain`.
- [ ] Run ImageViewer, InfoPanel, typecheck, full WebUI tests, and production build; require zero failures.
