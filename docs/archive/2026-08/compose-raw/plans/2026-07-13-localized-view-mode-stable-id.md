# Localized View Mode Stable ID Implementation Plan
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep file-list behavior independent of the translated text displayed by its view-mode combo box, so folder thumbnails load in every UI language.

**Architecture:** The combo box displays `tr()` output but stores stable `"Grid"` and `"Details"` IDs as item data. The `_view_mode` property reads that item data, while view-change handlers treat the combo signal only as a notification. Temporary diagnostic logging is removed once the regression is covered.

**Tech Stack:** Python, PySide6 `QComboBox`, pytest, pytest-qt.

## Global Constraints

- Keep view-mode display strings fully localized through `tr()`.
- Do not compare translated UI text in application logic.
- Preserve existing `"Grid"` and `"Details"` internal identifiers.
- Remove all temporary `[DIAG]` logs and DEBUG logging configuration added for this investigation.

---

### Task 1: Stabilize File-List View Mode IDs

**Files:**
- Modify: `AssetsManager/panels/file_list/_base.py:141-145,290-292,350-360`
- Modify: `AssetsManager/panels/file_list/__init__.py:496-508,566-590`
- Modify: `AssetsManager/panels/file_list/_loader.py:18-20,193-266`
- Modify: `AssetsManager/panels/file_list/_grid_widget.py:525-533`
- Modify: `AssetsManager/app.py:12-15`
- Test: `tests/desktop/test_file_list_grid_widget.py`

**Interfaces:**
- Consumes: `QComboBox.addItem(text, userData)`, `QComboBox.currentData()`, existing internal IDs `"Grid"` and `"Details"`.
- Produces: `FileListPanel._view_mode: str` returning a stable internal view ID regardless of UI language.

- [ ] **Step 1: Write the failing regression test**

```python
def test_view_mode_uses_stable_item_data_when_display_text_is_localized(qtbot):
    panel = QWidgetFileListPanel()
    qtbot.addWidget(panel)
    panel._view_combo.setItemText(0, "网格")
    panel._view_combo.setCurrentIndex(0)

    assert panel._view_mode == "Grid"
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m pytest tests/desktop/test_file_list_grid_widget.py -q -k view_mode_uses_stable_item_data`

Expected: FAIL because `_view_mode` derives behavior from the translated combo text or item data is absent.

- [ ] **Step 3: Implement the minimum stable-ID behavior**

```python
self._view_combo.addItem(tr("filelist.view.grid"), userData="Grid")
self._view_combo.addItem(tr("filelist.view.details"), userData="Details")
self._view_combo.currentIndexChanged.connect(self._on_view_changed)

@property
def _view_mode(self):
    return self._view_combo.currentData() or self._view_combo.currentText()

def _on_view_changed(self, _index):
    mode = self._view_mode
```

Keep all internal checks against `"Grid"` and `"Details"`. Remove every temporary `[DIAG]` statement and DEBUG-level configuration from the affected files.

- [ ] **Step 4: Run focused regression coverage**

Run: `python -m pytest tests/desktop/test_file_list_grid_widget.py -q`

Expected: PASS.

- [ ] **Step 5: Run syntax and targeted test verification**

Run: `python -m compileall AssetsManager/panels/file_list AssetsManager/app.py -q && python -m pytest tests/desktop/test_file_list_grid_widget.py -q`

Expected: no compile errors; focused tests pass.

- [ ] **Step 6: Commit**

```bash
git add AssetsManager/panels/file_list/_base.py AssetsManager/panels/file_list/__init__.py AssetsManager/panels/file_list/_loader.py AssetsManager/panels/file_list/_grid_widget.py AssetsManager/app.py tests/desktop/test_file_list_grid_widget.py
git commit -m "fix: decouple file-list view mode from translations"
```

