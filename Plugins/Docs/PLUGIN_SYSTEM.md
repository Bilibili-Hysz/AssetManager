# Plugin System — Architecture & Implementation

> Version: 1.0.0 | Date: 2026-06-09
> Status: Stable — first-party booth_link parser working

---

## 1. Overview

AssetManager's plugin system allows external Python scripts to provide **file metadata parsing** to the Info Panel. Plugins are discovered from `Plugins/Addons/`, loaded at startup, and invoked whenever a file is selected.

### Design principles

| Principle | Description |
|-----------|-------------|
| **Zero-config** | Drop a folder into `Plugins/Addons/`, restart — done |
| **Minimal interface** | Plugin needs only 2 functions: `match()` and `parse()` |
| **Full trust** | Plugins are loaded as local Python modules with `importlib` and have full Python interpreter access (filesystem, network, subprocess, etc.). Plugins are NOT sandboxed. Only install plugins from trusted sources. |
| **Transparent** | Plugin metadata merges into InfoPanel with the same label/value layout as built-in fields |

---

## 2. Directory Layout

```
Project/
├── AssetsManager/
├── RuntimeData/
└── Plugins/
    ├── Docs/
    │   ├── API.md                ← Plugin interface spec
    │   ├── MODULE_INTERFACES.md  ← Extension point definitions
    │   └── PLUGIN_SYSTEM.md      ← This document
    └── Addons/
        ├── booth_link/           ← First-party: Booth _link parser
        │   ├── plugin.json       ← Manifest
        │   └── parser.py         ← Entry module
        └── download_tracker/     ← Example: disabled placeholder
            ├── plugin.json
            └── tracker.py
```

---

## 3. `plugin.json` Schema

```json
{
  "name": "Human-readable name",
  "id": "unique_snake_case_id",
  "version": "1.0.0",
  "author": "Author",
  "description": "What this plugin does",
  "enabled": true,
  "entry": "parser.py",
  "provides": ["info.fields"],
  "display_fields": [
    {"key": "url",    "label_key": "info.field_link",   "type": "url"},
    {"key": "author", "label_key": "info.field_author",  "type": "text"},
    {"key": "shop",   "label_key": "info.field_shop",    "type": "text"}
  ],
  "config_schema": {}
}
```

### Fields reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Display name |
| `id` | string | ✅ | Unique key used as result dict key and cache namespace |
| `version` | string | ✅ | Semver |
| `author` | string | ❌ | Author name |
| `description` | string | ❌ | Description |
| `enabled` | bool | ❌ | Default `true`. Disabled plugins are skipped at discovery. |
| `entry` | string | ❌ | Entry module filename (default `parser.py`) |
| `provides` | list[string] | ❌ | Capability tags for future extension points |
| `permissions` | list[string] | ❌ | Advisory permission declarations (see §12). Does NOT restrict plugin code. |
| `display_fields` | list[DisplayField] | ❌ | Fields to render in InfoPanel |
| `config_schema` | dict | ❌ | Future: plugin settings UI schema |

### DisplayField

| Field | Required | Description |
|-------|----------|-------------|
| `key` | ✅ | Key in `parse()` return dict |
| `label_key` | ✅ | i18n key for label (falls back to key if missing) |
| `type` | ❌ | `"text"` (default), `"url"`, `"number"`, `"bool"` |

---

## 4. Entry Module Contract

Each plugin's entry module must define exactly 2 top-level functions:

```python
def match(file_path: str) -> bool:
    """Return True if this parser handles the given path.
    Called once per file selection. Must be fast."""

def parse(file_path: str) -> dict:
    """Parse the file and return metadata.
    Called only when match() returned True.
    Keys must match display_fields[].key.
    Return {} if no data found."""
```

### match(file_path)

- Receives absolute path (string)
- Called on every file selection (every click in file list)
- Must be fast — no I/O, just string checks
- Return `True` if `parse()` should run on this path

### parse(file_path)

- Called only when `match()` returned `True`
- May do file I/O (read text file, parse content)
- Must return `dict[str, str]` — keys must match `display_fields[].key`
- Return `{}` on failure — UI will hide all fields

---

## 5. Runtime Flow

```
User selects file in File List
  → InfoPanel.update_info(path)
    → _render_plugin_fields(path)
      → PluginManager.parse_file(path)
        → for each enabled plugin:
            if plugin.match(path):
              plugin.parse(path) → dict
        → merge results → {plugin_id: {key: value, ...}}
      → PluginManager.get_display_fields()
        → return all display_fields from all enabled plugins
      → for each field:
          val = results[plugin_id][field.key]
          if val: create/show QWidget row (QLabel + QLabel/DragLabel)
          else:   hide existing row
```

**Key behavior:**
- Fields are created once, then reused (show/hide) on subsequent selections
- `type: "url"` fields render as `<a href="...">` links (clickable, open in browser)
- Fields with no value are hidden (no empty space)
- `tr(label_key)` is called once at creation time; not refreshed on language change

---

## 6. `core/plugin_manager.py` — PluginManager

### Singleton access

```python
from AssetsManager.core.plugin_manager import get_plugin_manager
pm = get_plugin_manager()  # discover() called on first access
```

### discover()

Scans `Plugins/Addons/`, loads all folders with valid `plugin.json` where `enabled: true`.

For each valid plugin:
- Imports `entry` module via `importlib.util`
- Validates that `match()` and `parse()` exist and are callable
- Stores in `self._plugins` (meta) and `self._parsers` (runtime)

### parse_file(file_path: str) → dict

Runs all matching parsers, returns merged result:
```python
{
  "booth_link": {"url": "https://...", "name": "...", "author": "...", "item_id": "..."},
  "other_plugin": {"field1": "value1"}
}
```

### get_display_fields() → list[dict]

Returns all `display_fields` from all enabled plugins, merged:
```python
[
  {"plugin_id": "booth_link", "key": "url",     "label_key": "info.field_link",  "type": "url"},
  {"plugin_id": "booth_link", "key": "author",  "label_key": "info.field_author", "type": "text"},
]
```

---

## 7. Info Panel Integration

### Field container

In `__init__`, after the standard link field:
```python
self._plugin_fields: dict[tuple[str,str], tuple[QLabel, QLabel]] = {}
self._plugin_container = QWidget()
self._plugin_layout = QVBoxLayout(self._plugin_container)
```

### Theme refresh

```python
def _refresh_plugin_fields_theme(self):
    t = themes.get()
    for lbl, val_w in self._plugin_fields.values():
        lbl.setStyleSheet(f"color: {t['muted']}; ...")
        val_w.setStyleSheet(f"color: {t['body']}; ...")
```

### URL type rendering

`type: "url"` fields render as clickable links:
```python
val_w = QLabel(f'<a href="{val}">{val}</a>')
val_w.setTextFormat(Qt.TextFormat.RichText)
val_w.setOpenExternalLinks(True)
```

---

## 8. Booth Link Parser (`booth_link/parser.py`)

### match()

```python
def match(file_path: str) -> bool:
    name = os.path.basename(file_path).lower()
    parent = os.path.basename(os.path.dirname(file_path)).lower()
    return name.endswith(".txt") and parent == "_link"
```

Case-insensitive. Matches `.txt` files inside `_link/` directories.

### parse()

Reads file, extracts URL from line 1, then parses key-value pairs:
```
https://booth.pm/ja/items/123456        ← url
                                         ← blank
商品名称: Sample Product                  ← name
作者: AuthorName                          ← author
商品ID: 12345                             ← item_id
```

Supports multiple key variants:
- `商品名称:` / `商品名:` → `name`
- `店铺:` / `作者:` → `author`
- `商品ID:` / `商品编号:` → `item_id`

---

## 9. How to Create a New Plugin

1. Create folder: `Plugins/Addons/my_plugin/`
2. Create `plugin.json` with all required fields
3. Create `parser.py` with `match()` and `parse()`
4. Restart app (or call `get_plugin_manager().discover()`)

### Example: GitHub Issue Linker

```json
{
  "name": "GitHub Issue Linker",
  "id": "github_issue",
  "version": "1.0.0",
  "author": "",
  "description": "Parse .github-issue.txt files for GitHub metadata",
  "enabled": true,
  "entry": "parser.py",
  "display_fields": [
    {"key": "issue_url", "label_key": "GitHub Issue", "type": "url"},
    {"key": "repo",      "label_key": "Repository",   "type": "text"}
  ]
}
```

```python
# parser.py
import os

def match(file_path: str) -> bool:
    return os.path.basename(file_path).lower().endswith(".github-issue.txt")

def parse(file_path: str) -> dict:
    with open(file_path, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    if not lines:
        return {}
    url = lines[0]
    repo = url.split("github.com/")[1] if "github.com" in url else ""
    return {"issue_url": url, "repo": repo}
```

---

## 10. Extension Points (Future)

The plugin system currently supports one extension point:

| Extension | Status | Description |
|-----------|--------|-------------|
| `info.fields` | ✅ Active | Display metadata fields in InfoPanel |
| `file.actions` | ❌ Not implemented | Context menu actions |
| `file.columns` | ❌ Not implemented | Custom columns in file list |
| `search.providers` | ❌ Not implemented | Custom search result providers |

To add a new extension point:
1. Define the interface (e.g., `file.actions` requires `menu_items(path) -> list`)
2. Call `plugin_manager.get_extension("file.actions", path)` in the relevant UI code
3. Document the contract in `API.md`

---

## 11. Troubleshooting

| Symptom | Cause |
|---------|-------|
| Plugin not loading | Check `plugin.json` has `"enabled": true` and valid `entry` filename |
| Fields not showing | `match()` returns `False` for the selected file |
| Values empty | `parse()` returns empty dict — check file format |
| No theme refresh | Plugin fields not in `_plugin_fields` dict — only `display_fields` are rendered |
| Fields show wrong values | Plugin's `key` in `display_fields` doesn't match `parse()` output key |

---

## 12. Security & Trust Model

### Plugins are fully trusted local code

AssetManager plugins are **not sandboxed**. They run as normal Python code with full interpreter access — they can read/write files, make network requests, spawn subprocesses, and import any installed package.

**Only install plugins from sources you trust.** A malicious plugin can compromise your system.

### Permissions are advisory, not enforced

The `permissions` field in `plugin.json` declares what capabilities the plugin intends to use:

```json
{
  "permissions": ["filesystem.read", "network.request", "settings.write"]
}
```

These declarations serve as **documentation for users and developers** — they signal the plugin's intended behavior but do NOT constrain what the plugin can actually do. The host logs a warning when a plugin registers contributions that require undeclared permissions, but never blocks the action.

Declared permissions do not create a security boundary because plugin code already has unrestricted Python access.

Available permission tokens:
| Token | Meaning |
|-------|---------|
| `filesystem.read` | Plugin reads files from disk |
| `filesystem.write` | Plugin writes files to disk |
| `network.request` | Plugin makes HTTP/network requests |
| `database.read` | Plugin reads from the AssetManager database |
| `database.write` | Plugin writes to the AssetManager database |
| `settings.read` | Plugin reads application settings |
| `settings.write` | Plugin writes application settings or registers extensions |
| `clipboard.read` | Plugin reads from the system clipboard |
| `clipboard.write` | Plugin writes to the system clipboard |
