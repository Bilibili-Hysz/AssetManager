# Module Interfaces — Extension Points

> 状态:**FROZEN(v1 扩展点手册)** · 冻结登记:2026-08-27 · 现状以代码为准;v2 贡献类型见 `plugin_api/types.py`(CommandOperator/FileParser/EventHook/PanelContributor 等)。

Each module in AssetManager exposes a stable interface for plugins to hook into.

---

## Info Panel (`panels/info.py`)

**Extension point**: `info.fields`

Plugins can add custom metadata fields to the InfoPanel's metadata section.

### Integration point: `_render_plugin_fields(path: str)`

```python
def _render_plugin_fields(self, path: str):
    """Called during update_info() after standard fields are populated."""
    pm = get_plugin_manager()
    results = pm.parse_file(path)
    fields = pm.get_display_fields()
    # ... creates/updates QLabel widgets for each field
```

### Data flow

```
update_info(path)
  ├── standard fields (type, size, date, path, link, tags, notes)
  └── _render_plugin_fields(path)
        → plugin_manager.parse_file(path) → dict[plugin_id, dict[key, val]]
        → plugin_manager.get_display_fields() → list[dict] from all plugins
        → create/update QWidget rows with label + value
        → hide rows with empty values
```

### Rendered field structure

```
┌─────────────────────────────────────────────┐
│ Label          │  Value                     │
│ (QLabel)       │  (QLabel, selectable text) │
│ style: muted   │  style: body, word-wrap    │
└─────────────────────────────────────────────┘
```

- Label text comes from `tr(field.label_key)` — falls back to `field.key` if i18n key missing
- Value text from `results[plugin_id][field.key]`
- Fields with empty values are hidden

---

## Sidebar (`panels/sidebar.py`)

**No plugin extension yet.** Future: custom tree item actions, custom folders.

---

## File List (`panels/file_list/`)

**No plugin extension yet.** Future: custom columns, custom right-click actions.

---

## Search (LAN API)

**No plugin extension yet.** Future: search providers, result formatters.
