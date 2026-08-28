# Theme System UI/UX Redesign Spec
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

## [S1] Problem

Current Settings dialog theme section has three separate sections:
1. Appearance Mode (Dark/Light/System radio buttons)
2. Theme Selection (QListWidget with all themes)
3. Custom Themes (separate QListWidget for user themes)

This layout is confusing — mode and theme are separated, the list is hard to navigate, and creating custom themes is complex.

## [S2] Solution

Replace the three-section layout with two popup menu buttons:

```
主题
┌─────────────────────────────────────────┐
│ [深色 ▼]  [Forest Dark ▼]               │
└─────────────────────────────────────────┘
```

### Mode Button [深色 ▼]
- Popup menu: Dark / Light
- Selected mode updates button text
- Switching mode auto-selects first theme in that mode

### Theme Button [Forest Dark ▼]
- Popup menu contents depend on current mode:
  - Built-in themes for current mode (with color swatch icons)
  - Separator
  - Custom themes for current mode (if any, else no separator)
  - Separator
  - "New Custom Theme" menu item
  - "Edit Current Theme Colors" menu item (enabled only for custom themes)
  - "Import Theme File" menu item
  - "Delete Custom Theme" menu item (enabled only for custom themes)
- Selecting a theme updates button text and applies immediately

### Custom theme mode assignment
- By base color brightness: luminance < 128 → Dark, else → Light

## [S3] Implementation details

### Files to modify
- `AssetsManager/dialogs/settings_dialog.py` — replace `_setup_theme_section` with new two-button layout
- Keep existing `_on_theme_selected`, `_on_appearance_mode_changed`, `_on_preview_theme` handlers as they are reusable
- Remove `_custom_list` and related custom theme section code

### New widgets
- `_mode_btn`: QPushButton with popup menu (Dark/Light)
- `_theme_btn`: QPushButton with dynamic popup menu
- No QListWidget needed

### Behavior
- Mode change: update button text, save to AppSettings, rebuild theme menu, apply first theme in mode
- Theme change: update button text, call `themes.set_theme(name)`, save to AppSettings
- New custom: use existing `_on_new_custom_theme` logic, but update theme button after
- Edit colors: open ThemePreviewDialog for current theme
- Import: use existing import logic
- Delete: use existing delete logic, update theme button after

## [S4] Acceptance criteria

- Two buttons replace the three-section layout
- Mode switch filters theme list correctly
- Custom themes are auto-assigned to Dark/Light by base color brightness
- "New Custom Theme" creates and selects the new theme
- "Edit Current Theme Colors" opens preview dialog
- "Delete Custom Theme" removes and selects next available theme
- Theme changes apply immediately (hot reload)
- All existing theme functionality preserved
