# Theme Editor Phase 3 — Color Picker Implementation Plan
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task.

**Goal:** Add an HSV/RGB color picker with HEX input for theme color editing.

**Architecture:** A `ColorPickerDialog` with HSV wheel, brightness slider, RGB/HSV mode toggle, HEX input, and color preview. Integrated into ThemePreviewWidget via clickable color swatches.

**Spec:** `docs/compose/specs/2026-06-18-theme-editor-phase2-design.md` [S4]

---

## Tasks

### Task 1: Create ColorPickerDialog
- Create `AssetsManager/dialogs/color_picker_dialog.py`
- HSV wheel widget, brightness slider
- RGB/HSV mode toggle
- HEX input with validation
- Color preview
- OK/Cancel buttons

### Task 2: Create HSV Wheel Widget
- Create `AssetsManager/widgets/hsv_wheel.py`
- Custom painted HSV color wheel
- Click/drag to select hue + saturation
- Signal on color change

### Task 3: Integrate into ThemePreviewWidget
- Add clickable color swatches to preview sections
- Click opens ColorPickerDialog
- Color change updates preview in real-time
- Apply changes to theme JSON

### Task 4: Final Integration
- Run quality gate
- Manual testing
- Commit
