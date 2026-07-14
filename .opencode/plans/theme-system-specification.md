# AssetManager Theme System — Architecture & Specification

> Version: 2.0.0 | Date: 2026-06-08
> Files: `core/themes.py`, `core/color_utils.py`, `themes/*.json`

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    Theme System v2                            │
├──────────────────────────────────────────────────────────────┤
│  themes/ (JSON data)                                         │
│    ├── navy.json, slate.json, forest.json, amber.json        │
│    ├── dawn.json, silver.json, mint.json                     │
│    └── default.json  (fallback if all else fails)            │
├──────────────────────────────────────────────────────────────┤
│  core/themes.py  (engine)                                    │
│    • Loads JSON → dict, validates schema                     │
│    • API: get(), set_theme(), names(), stylesheet(), apply_to│
│    • NEW: color(token), prop(category, key), is_dark()       │
├──────────────────────────────────────────────────────────────┤
│  core/color_utils.py  (utilities)                            │
│    • alpha(hex, opacity), lighten(hex, f), darken(hex, f)    │
│    • Replace 60+ hardcoded hex-opacity / lighter() calls     │
└──────────────────────────────────────────────────────────────┘
```

### 1.1 Design Principles

| Principle | Description |
|-----------|-------------|
| **Data-driven** | Themes are JSON files, not Python dicts. Add a theme by dropping a `.json`. |
| **Backward compatible** | All 13 legacy token names preserved. `themes.get()`, `set_theme()`, `names()` API unchanged. |
| **Progressive adoption** | New tokens are additive. Old QSS code works without changes. New QSS can gradually adopt. |
| **Single source of truth** | One JSON per theme. No colors duplicated across files. |
| **Validation at load** | JSON schema validated; missing tokens raise clear errors. |

---

## 2. JSON File Format

### 2.1 Schema (v1)

```json
{
  "version": 1,
  "name": "Navy",
  "description": "Deep blue-black interface for low-light environments",
  "dark": true,
  "colors": {
    // ── Legacy tokens (v1, backward compatible) ──
    "base":    "#12121a",
    "panel":   "#1e1e2a",
    "header":  "#282840",
    "border":  "#5a5a7a",
    "heading": "#e0e0f0",
    "body":    "#b0b0c8",
    "muted":   "#6a6a80",
    "accent":  "#4a60b0",
    "success": "#44c98a",
    "warning": "#f0a040",
    "danger":  "#e05555",
    "favorite":"#e8c84a",
    "recent":  "#88aacc",

    // ── Extended tokens (v2) ──
    "on_accent":           "#ffffff",
    "hover_overlay":       "#ffffff",
    "selected_overlay":    "#4a60b0",
    "border_focus":        "#4a60b0",
    "input_bg":            "#1e1e2a",
    "input_text":          "#e0e0f0",
    "scrollbar_track":     "#12121a",
    "scrollbar_thumb":     "#6a6a80",
    "scrollbar_thumb_hover":"#5a5a7a",
    "disabled_text":       "#484860",
    "disabled_bg":         "#161620",
    "tooltip_bg":          "#282840",
    "tooltip_text":        "#e0e0f0"
  },
  "properties": {
    "opacity":         { "hover": 0.15, "disabled": 0.5 },
    "border_radius":   { "sm": 4, "md": 6, "lg": 8 },
    "spacing":         { "xs": 4, "sm": 8, "md": 12, "lg": 16 },
    "font_size":       { "sm": 11, "md": 12, "lg": 13, "xl": 14 },
    "animation":       { "duration_ms": 200 }
  }
}
```

### 2.2 Token Specification

#### Legacy tokens (required, 13)

| Token | Semantic Meaning | Typical Dark Value | Typical Light Value |
|-------|-----------------|-------------------|---------------------|
| `base` | Deepest background (main window, scrollbar track) | Very dark (#12-1a) | Very light (#ee-f0) |
| `panel` | Raised surface (cards, inputs, dialogs, tabs) | Dark (#1e-25) | Near-white (#f5-fa) |
| `header` | Title bar, menu bar, dock headers | Medium-dark (#28-2d) | Light-medium (#e2-e8) |
| `border` | Dividers, borders, separators | Medium (#55-70) | Medium-light (#cc-d4) |
| `heading` | Primary text, titles, group labels | Near-white (#e0) | Near-black (#1a-2c) |
| `body` | Body text, secondary content | Light gray (#b0) | Dark gray (#40-4a) |
| `muted` | Placeholder, hint, dimmed text | Medium gray (#66-80) | Medium gray (#72-8c) |
| `accent` | Primary brand, selection, buttons, links | Vibrant (#4a-5b) | Vibrant (#4a-5b) |
| `success` | Positive status, save confirmations | Green | Green (darker) |
| `warning` | Caution status, confirm dialogs | Orange | Orange (darker) |
| `danger` | Error, destructive actions | Red | Red (darker) |
| `favorite` | Star icon, bookmarks (sidebar) | Gold | Gold (darker) |
| `recent` | Recent items indicator (sidebar) | Steel blue | Steel blue |

#### Extended tokens (new in v2, 13)

| Token | Semantic Meaning | Usage |
|-------|-----------------|-------|
| `on_accent` | Text color on accent backgrounds | Buttons, badges, selected items |
| `hover_overlay` | Standard hover overlay base color | `alpha(t['hover_overlay'], props.hover)` |
| `selected_overlay` | Selected state overlay base color | List items, tabs |
| `border_focus` | Focused input border color | QLineEdit:focus, QComboBox:focus |
| `input_bg` | Input field background | QLineEdit, QSpinBox, QTextEdit |
| `input_text` | Input field text color | QLineEdit, QSpinBox, QTextEdit |
| `scrollbar_track` | Scrollbar track background | QScrollBar |
| `scrollbar_thumb` | Scrollbar handle | QScrollBar::handle |
| `scrollbar_thumb_hover` | Scrollbar handle on hover | QScrollBar::handle:hover |
| `disabled_text` | Disabled control text color | Disabled QLabel, QPushButton |
| `disabled_bg` | Disabled control background | Disabled input/button |
| `tooltip_bg` | Tooltip background | QToolTip |
| `tooltip_text` | Tooltip text color | QToolTip |

### 2.3 Properties (new in v2)

| Category | Keys | Values | Usage |
|----------|------|--------|-------|
| `opacity` | `hover`, `disabled` | float (0.0–1.0) | `alpha(color, opacity)` in QSS |
| `border_radius` | `sm`, `md`, `lg` | int (px) | Uniform border-radius tokens |
| `spacing` | `xs`, `sm`, `md`, `lg` | int (px) | Layout spacing and margins |
| `font_size` | `sm`, `md`, `lg`, `xl` | int (px) | Font size scale |
| `animation` | `duration_ms` | int (ms) | Standard animation duration |

### 2.4 Validation Rules

1. **Required fields**: `version`, `name`, `colors` (with all 13 legacy tokens)
2. **Color format**: All color values must be valid `#RRGGBB` hex (6 chars)
3. **Missing extended tokens**: Auto-populated from legacy tokens (see §5 Fallback)
4. **Invalid JSON**: File skipped, warning printed, falls through to next file

---

## 3. File Layout

### 3.1 Directory Structure

```
AssetsManager/
├── themes/                  (JSON data)
│   ├── default.json         (fallback — loaded if all else fails)
│   ├── navy.json            (deep blue-black with vibrant blue accents)
│   ├── slate.json           (neutral gray with teal accents)
│   ├── forest.json          (deep forest green with emerald accents)
│   ├── amber.json           (warm dark brown with golden accents)
│   ├── dawn.json            (warm cream-white with rich blue accents)
│   ├── silver.json          (cool gray-white with vibrant blue accents)
│   ├── mint.json            (fresh green-white with emerald accents)
│   ├── dracula.json         (dark with purple/magenta accents)
│   ├── nord.json            (arctic blue-gray with frost accents)
│   ├── gruvbox.json         (retro warm with vibrant orange accents)
│   └── rosepine.json        (gentle dark with rose/pine accents)
│
└── core/
    ├── themes.py            (engine — rewritten for JSON loading)
    └── color_utils.py       (utilities — new file)
```

### 3.2 PyInstaller Bundling

JSON files must be included as `datas` in `AssetManager.spec`. The engine resolves paths relative to `__file__` and `sys._MEIPASS`.

### 3.3 Loading Priority

```
1. sys._MEIPASS/themes/  (PyInstaller bundle)
2. os.path.dirname(__file__)/../themes/  (development)
3. Built-in default.json fallback  (shipped with source)
```

---

## 4. API Reference

### 4.1 Core API (unchanged from v1)

```python
import AssetsManager.core.themes as themes

t = themes.get()           # dict of current theme (all tokens + properties merged)
t = themes.get("Slate")    # dict of specific theme
themes.set_theme("Dawn")   # switch theme, persist to AppSettings, emit signal
names = themes.names()     # ["Navy", "Slate", "Forest", "Amber", "Dawn", "Silver", "Mint", "Dracula", "Nord", "Gruvbox", "Rose Pine"]
css = themes.stylesheet()  # global QSS string for MainWindow/Docks (cached)
themes.apply_to(widget)    # apply stylesheet() to a widget
```

### 4.2 New API (v2)

```python
# Access specific tokens
themes.color("accent")         # "#4a60b0"

# Access theme properties
themes.prop("border_radius", "md")  # 6 (int)
themes.prop("spacing", "lg")        # 16
themes.prop("font_size", "sm")      # 11

# Query theme metadata
themes.is_dark()               # True for dark, False for light
themes.name()                  # "Navy" (current theme name)
```

### 4.3 Color Utilities

```python
from AssetsManager.core.color_utils import alpha, lighten, darken

alpha("#4a60b0", 0.19)         # "#4a60b0" with 19% opacity → hex string
lighten("#1e1e2a", 1.3)        # Lighten by factor 1.3
darken("#faf7f2", 0.8)         # Darken by factor 0.8
```

---

## 5. Fallback & Migration

### 5.1 Legacy Token Only

If a JSON file has only the 13 legacy tokens (no extended tokens), the engine auto-generates:

| Extended Token | Fallback Source |
|----------------|----------------|
| `on_accent` | `"#ffffff"` (constant — works for both dark/light) |
| `hover_overlay` | `"#ffffff"` if dark, `"#000000"` if light |
| `selected_overlay` | `colors.accent` |
| `border_focus` | `colors.accent` |
| `input_bg` | `colors.panel` |
| `input_text` | `colors.heading` |
| `scrollbar_track` | `colors.base` |
| `scrollbar_thumb` | `colors.muted` |
| `scrollbar_thumb_hover` | `colors.border` |
| `disabled_text` | `colors.muted` darkened/lowered |
| `disabled_bg` | `colors.base` darkened/lowered |
| `tooltip_bg` | `colors.header` |
| `tooltip_text` | `colors.heading` |

### 5.2 Missing JSON Recovery

1. `default.json` provides minimal viable theme (Slate grayscale)
2. If `default.json` is also missing → hardcoded dict in code (last resort)
3. All errors logged to stderr; app never crashes from theme load failure

---

## 6. Migration Guide (Phase 2)

### 6.1 QSS Template Changes

| Pattern (Old) | Pattern (New) | Rationale |
|---------------|---------------|-----------|
| `f"color: white;"` | `f"color: {t['on_accent']};"` | No hardcoded "white" |
| `f"background: {t['accent']}{t['body']}30;"` | `alpha(t['hover_overlay'], t['properties']['opacity']['hover'])` | Explicit opacity |
| `f"background: {t['muted']};"` (for scrollbar) | `f"background: {t['scrollbar_thumb']};"` | Dedicated scrollbar tokens |
| `.lighter(130)` on panel color | `lighten(t['panel'], 1.3)` | Utility function |

### 6.2 Files to Update (Priority Order)

| Priority | File | Changes |
|----------|------|---------|
| P0 | `core/themes.py` → `stylesheet()` / `tabbed_dialog._dialog_qss()` | Replace hardcoded white/transparent with tokens |
| P1 | `core/startup.py` | ~20 hex-opacity patterns → `alpha()` |
| P1 | `widgets/workspace_bar.py` | ~10 hex-opacity patterns → `alpha()` |
| P2 | `panels/` subdirectory files | ~15 hex-opacity patterns → `alpha()` |
| P3 | Remaining files (info, sidebar, etc.) | Replace `"white"` → `t["on_accent"]` |

---

## 7. Color Design Standards

### 7.1 Contrast Requirements

| Context | Minimum Ratio | Token Pair |
|---------|--------------|------------|
| Body text on background | 4.5:1 | `body` on `panel` / `base` |
| Heading text | 7:1 | `heading` on `panel` |
| Button text | 4.5:1 | `on_accent` on `accent` |
| Disabled text | No requirement | `disabled_text` on `disabled_bg` |
| Scrollbar handle | 3:1 | `scrollbar_thumb` on `scrollbar_track` |

### 7.2 Light Theme Guidelines

1. `base` → `#eef0f2` range (not pure white, which causes eye strain)
2. `panel` → ~5–10% darker than `base` (card elevation effect)
3. `heading` → `#1a0000` range (near-black, not pure `#000`)
4. `body` → `#400000` range (dark gray, not pure black)
5. `accent` → Must have 4.5:1 contrast with `on_accent` (typically white)
6. `hover_overlay` → Use `"#000000"` (dark overlay over light bg, opposite of dark themes)
7. Success/warning/danger → Use darker, more saturated variants (light bg shows colors differently)

### 7.3 Theme Naming Convention

- **Dark themes**: Single word describing mood/color — Navy, Slate, Forest, Amber
- **Light themes**: Single word evoking morning/light — Dawn, Silver, Mint
- Names appear in Settings radio group; keep short (≤10 chars)
- JSON filename: lowercase, no spaces (navy.json, silver.json)

---

## 8. Validation Checklist

When adding a new theme, verify:

- [ ] All 13 legacy tokens present in `colors` section
- [ ] All 13 extended tokens present (or will auto-generate correctly)
- [ ] `version: 1` field present
- [ ] `dark: true/false` correctly set (affects hover_overlay fallback)
- [ ] All colors are valid `#RRGGBB` 6-char hex
- [ ] `on_accent` has 4.5:1 contrast against `accent`
- [ ] `heading` has 7:1 contrast against `panel`
- [ ] `body` has 4.5:1 contrast against `panel`
- [ ] `muted` has at least 3:1 contrast against `panel`
- [ ] JSON is valid (no trailing commas, proper quoting)
- [ ] File named `themes/lowercase_name.json` matches theme name case-insensitively
