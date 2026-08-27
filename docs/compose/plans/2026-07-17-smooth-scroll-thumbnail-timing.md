# Smooth Scroll Thumbnail Timing Implementation Plan
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Defer thumbnail requests during smooth scrolling and load only the final visible area after scrolling settles.

**Architecture:** The active `QWidgetFileListPanel` uses narrow helpers on its base class to coordinate smooth scrolling. Grid scrollbar changes preserve the existing 100ms manual-scroll debounce but ignore only animation-driven changes. A monotonic generation allows only the newest animation completion to schedule the final debounce. The dormant legacy list path is out of scope because the current product does not construct a QListView for it.

**Tech Stack:** Python, PySide6, pytest.

## Global Constraints

- Keep direct user-scroll debounce at 100ms.
- Do not change thumbnail loader, cache, generation/session protection, layout, navigation, or selection.
- Keep 120ms OutCubic smooth scrolling.
- During an animation do not start thumbnail debounce for animation-driven scrollbar updates; only its current completion starts one debounce.
- Do not rebuild or modify the dormant legacy QListView path.

---

### Task 1: Gate Thumbnail Debounce During Smooth Scroll

**Files:**
- Modify: `AssetsManager/panels/file_list/_base.py`
- Modify: `AssetsManager/panels/file_list/__init__.py`
- Modify: `tests/desktop/test_file_list_shim.py`

- [ ] Write RED tests for manual scroll debounce, animation suppression, and stale completion rejection.
- [ ] Add shared generation helpers in `FileListPanel` and route QWidget scrollbar changes through them.
- [ ] Verify focused file-list tests and lint.
- [ ] Commit `fix: defer thumbnails during smooth scroll`.

