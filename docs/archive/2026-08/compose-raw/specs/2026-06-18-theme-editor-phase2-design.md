# Theme Editor Phase 2 — Preview Interface
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

Date: 2026-06-18

## [S1] Preview Interface Layout

### Layout
Left-right split: settings panel on left, preview on right.

```
┌─ Settings Dialog ─────────────────────────────────────┐
│ ┌─ Left Panel ─────┐ ┌─ Right Preview ──────────────┐ │
│ │ Appearance Mode   │ │ ┌─ Buttons ────────────────┐ │ │
│ │ ○ Dark            │ │ │ [Primary] [Secondary]     │ │ │
│ │ ○ Light           │ │ │ [Danger]  [Disabled]      │ │ │
│ │ ○ Follow System   │ │ └─────────────────────────┘ │ │
│ │                   │ │ ┌─ Inputs ──────────────────┐ │ │
│ │ Theme List        │ │ │ [Text]  [Search]          │ │ │
│ │ ● Default         │ │ │ [Password] [Disabled]     │ │ │
│ │   Dracula         │ │ └─────────────────────────┘ │ │
│ │   Nord            │ │ ┌─ Labels ──────────────────┐ │ │
│ │                   │ │ │ Heading Body Muted         │ │ │
│ │ Custom Themes     │ │ │ Success Warning Danger     │ │ │
│ │   MyTheme         │ │ └─────────────────────────┘ │ │
│ │   + New           │ │ ┌─ List ────────────────────┐ │ │
│ │                   │ │ │ ● Selected  ○ Normal       │ │ │
│ │                   │ │ └─────────────────────────┘ │ │
│ │                   │ │ ┌─ Table ───────────────────┐ │ │
│ │                   │ │ │ Col1  Col2  Col3  Col4    │ │ │
│ │                   │ │ │ Data  Data  Data  Data    │ │ │
│ │                   │ │ └─────────────────────────┘ │ │
│ │                   │ │ ┌─ Dialog Mock ─────────────┐ │ │
│ │                   │ │ │ [Title Bar]          [×]  │ │ │
│ │                   │ │ │ Content area              │ │ │
│ │                   │ │ │           [OK] [Cancel]   │ │ │
│ │                   │ │ └─────────────────────────┘ │ │
│ └───────────────────┘ └─────────────────────────────┘ │
└───────────────────────────────────────────────────────┘
```

### Preview Components

| Component | Content |
|-----------|---------|
| Buttons | Primary, secondary, danger, disabled states |
| Inputs | Text, search, password, disabled, multiline |
| Labels | Heading, body, muted, disabled, success, warning, danger |
| Lists | Selected, normal, hover, disabled items |
| Table | Header, data rows, alternating row colors |
| Dialog | Title bar, content area, button bar |
| Checkbox/Radio | Checked/unchecked states |
| Slider | Slider control |
| Progress | Progress bar |
| GroupBox | Group box with title |

## [S2] Implementation Architecture

### Component Structure

```
ThemePreviewDialog(QDialog)
├── QSplitter (horizontal)
│   ├── LeftPanel (QWidget)
│   │   ├── AppearanceMode (radio buttons)
│   │   ├── ThemeList (QListWidget with swatches)
│   │   └── CustomThemes (QListWidget + buttons)
│   └── RightPanel (QWidget)
│       └── PreviewWidget (QWidget)
│           ├── ButtonSection
│           ├── InputSection
│           ├── LabelSection
│           ├── ListSection
│           ├── TableSection
│           ├── DialogSection
│           ├── CheckboxRadioSection
│           ├── SliderSection
│           ├── ProgressSection
│           └── GroupBoxSection
```

### Real-time Preview Flow

1. User selects theme in left panel
2. `ThemePreviewRenderer.apply_theme(theme_data)` applies theme to right panel
3. Preview components render with theme colors, fonts, spacing
4. User clicks "Apply" to confirm selection

### Integration

- `ThemeLoader.get_theme(name)` — get theme data
- `themes.set_theme(name)` — apply to main application
- `themes.invalidate_cache()` — refresh cache

## [S3] Preview Component Details

### Button Section
- Primary, secondary, danger, disabled buttons
- Small, medium, large sizes
- Shows: background, text, border, hover, pressed, disabled states

### Input Section
- Text input, search, password, disabled, multiline
- Shows: background, text, border, focus, placeholder, disabled states

### Label Section
- Heading, body, muted, disabled text
- Success, warning, danger colored text

### List Section
- Selected, normal, hover, disabled items
- Shows: background, text, selection highlight

### Table Section
- Header row, data rows, alternating row colors
- Shows: header background, cell text, grid lines

### Dialog Mock Section
- Title bar, content area, button bar
- Shows: header background, panel background, border

### Checkbox/Radio Section
- Checked/unchecked states
- Shows: indicator color, border, background

### Slider Section
- Slider control with track and handle
- Shows: track color, handle color, value indicator

### Progress Section
- Progress bar with fill
- Shows: track color, fill color

### GroupBox Section
- Group box with title
- Shows: border, title color, content background

## [S4] Color Picker

### Features
- HSV color wheel (hue + saturation)
- Brightness slider
- RGB/HSV mode toggle
- HEX input
- Color preview
- Confirm/Cancel buttons

### Layout
```
┌─ Color Picker ─────────────────────────────┐
│ ┌─ HSV Wheel ─────────────────────────────┐│
│ │ ████████████████████████████████████    ││
│ │ ████████████████████████████████████    ││
│ │ ████████████████████████████████████    ││
│ └─────────────────────────────────────────┘│
│ ┌─ Brightness ────────────────────────────┐│
│ │ ████████████████████████████████████    ││
│ └─────────────────────────────────────────┘│
│ ○ HSV  ○ RGB                               │
│ ┌─ Values ────────────────────────────────┐│
│ │ H: [___] S: [___] V: [___]              ││
│ │ R: [___] G: [___] B: [___]              ││
│ │ HEX: [#ffffff]    Preview: [■]          ││
│ └─────────────────────────────────────────┘│
│                        [OK] [Cancel]       │
└─────────────────────────────────────────────┘
```

### Integration
- Click color swatch in preview → open color picker
- Real-time preview update on color change
- Apply to theme JSON on confirm
