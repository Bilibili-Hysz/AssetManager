# Custom Theme System — Phase 1: Infrastructure
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

Date: 2026-06-18

## [S1] Directory Structure

### Path
`Assets/Themes/` (project root, packaged via PyInstaller `datas`)

### Prefix Convention

| Prefix | Meaning | Editable | Deletable |
|--------|---------|----------|----------|
| `D_` | Dark built-in | No | No |
| `L_` | Light built-in | No | No |
| `U_` | User custom | Yes | Yes |

### Example
```
Assets/Themes/
├── D_Default.json
├── D_Dracula.json
├── D_Nord.json
├── D_Midnight.json
├── L_Coral.json
├── L_Lavender.json
└── U_MyTheme.json
```

## [S2] Dynamic Loader

### ThemeLoader Architecture

```
ThemeLoader
├── scan_directory()      ← Scan Assets/Themes/ at startup
├── parse_theme(path)     ← Parse JSON, validate schema
├── get_theme(name)       ← Get theme by name
├── list_themes()         ← Return all themes grouped by prefix
├── watch_changes()       ← QFileSystemWatcher on directory
└── reload_on_change()    ← Re-parse on file change, notify via signal
```

### Loading Flow
1. Scan `Assets/Themes/` at startup
2. Parse all `D_*.json`, `L_*.json`, `U_*.json` files
3. Validate JSON schema (must contain `colors`, `properties`)
4. Register `QFileSystemWatcher` on directory
5. On file change: re-parse and emit `theme_changed` signal

### Integration
- `core/themes.py` `get()` reads from `ThemeLoader`
- `_load_all_themes()` replaced by `ThemeLoader.list_themes()`
- `set_theme()` calls `ThemeLoader.get_theme()`

## [S3] Theme Selector UI

### Three Interaction Points

1. **Appearance Mode**: Dark / Light / Follow System toggle
   - Filters theme list automatically
2. **Theme Menu**: Select built-in themes with real-time preview
   - Hover to preview, click to confirm
   - Can copy built-in theme to create custom variant
3. **Custom Theme Menu**: Manage user themes
   - Edit, Export (JSON), Delete, New

### New Theme Flow
1. User clicks "+ New Theme"
2. Dialog: name input, base theme selection (current or any built-in)
3. Generate `U_<name>.json` from base theme
4. Auto-select new theme

### Export/Import
- Export: Save `.json` to user-chosen location
- Import: Validate schema, auto-add `U_` prefix

## [S4] Migration Plan

### File Migration

| Old Path | New Path |
|----------|----------|
| `AssetsManager/themes/default.json` | `Assets/Themes/D_Default.json` |
| `AssetsManager/themes/dracula.json` | `Assets/Themes/D_Dracula.json` |
| `AssetsManager/themes/coral.json` | `Assets/Themes/L_Coral.json` |
| ... | ... |

### Code Changes

| File | Change |
|------|--------|
| `core/themes.py` | Rewrite `get()`, `set_theme()`, `names()` using ThemeLoader |
| `core/path_resolver.py` | Add `themes_dir()` function |
| `AssetManager.spec` | Update datas path |
| `dialogs/settings_dialog.py` | Update theme selector UI |

### Compatibility
- Old theme names auto-map to new prefixes (`default` → `D_Default`)
- `AppSettings` `theme` value migrated to new format
- JSON internal format unchanged (`colors`, `properties`, `background`)
