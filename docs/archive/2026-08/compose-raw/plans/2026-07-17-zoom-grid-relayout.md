# Zoom Grid Relayout Implementation Plan
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep existing card textures during each zoom animation frame so card-size changes do not repeatedly rebuild visible cards.

**Architecture:** Add keyword-only `relayout_only` to `FileListGridWidget.update_layout()`. It recomputes geometry and scroll range without changing `_textures` or `_dirty`. The QWidget grid zoom frame uses this light path; zoom completion retains existing texture invalidation, full layout, and visible-thumbnail loading.

**Tech Stack:** Python, PySide6, pytest.

## Global Constraints

- Preserve zoom duration, easing, presets, loader sizing, and visible-thumbnail requests.
- Light relayout preserves textures and dirty state.
- Full layout keeps current dirty behavior on column changes.
- Zoom completion still invalidates textures before full layout.
- Do not change loader/session/cache/navigation/selection/rendering style.

---

### Task 1: Preserve Grid Textures During Zoom Frames

**Files:**
- Modify: `AssetsManager/panels/file_list/_grid_widget.py`
- Modify: `AssetsManager/panels/file_list/__init__.py`
- Modify: `tests/desktop/test_file_list_grid_widget.py`

- [ ] Write RED tests for light relayout state preservation and zoom-frame invocation.
- [ ] Add `relayout_only=True` and use it from `_on_zoom_frame()`.
- [ ] Verify grid/file-list regressions and Ruff.
- [ ] Commit `perf: preserve textures during zoom`.
