# Plugin API — AssetManager

Plugins are Python packages in `Plugins/Addons/`, each a folder with `plugin.json` + entry module.

---

## plugin.json schema

```json
{
  "name": "Human-readable plugin name",
  "id": "unique_plugin_id",
  "version": "1.0.0",
  "author": "Your name",
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

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Display name for plugin manager UI |
| `id` | string | ✅ | Unique ID (used as key in metadata dict) |
| `version` | string | ✅ | Semver version string |
| `author` | string | ❌ | Author name |
| `description` | string | ❌ | Plugin description |
| `enabled` | bool | ❌ | Default `true`. User can toggle off |
| `entry` | string | ✅ | Entry module filename (default `parser.py`) |
| `provides` | list | ❌ | Capability tags (e.g. `["info.fields"]`) |
| `display_fields` | list | ❌ | Fields to render in InfoPanel metadata section |
| `config_schema` | dict | ❌ | Future: settings schema for plugin UI |

### display_fields entries

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key` | string | ✅ | Key in parser output dict |
| `label_key` | string | ✅ | i18n key for label text (falls back to `key` if missing) |
| `type` | string | ❌ | `"text"` (default), `"url"`, `"number"`, `"bool"` |

---

## Entry module contract

The entry module (`parser.py`) must define these two functions:

```python
def match(file_path: str) -> bool:
    """Return True if this parser handles the given file path."""
    ...

def parse(file_path: str) -> dict:
    """Parse the file and return a dict of metadata fields.
    Keys must match display_fields[].key in plugin.json."""
    ...
```

### `match(file_path: str) -> bool`

Called with an absolute path. Return `True` if this file is relevant to your parser.

### `parse(file_path: str) -> dict`

Called when `match()` returns `True`. Return a dict of parsed metadata.

---

## Execution model

```
InfoPanel.update_info(path)
  → PluginManager.parse_file(path)
    → for each enabled plugin:
        if plugin.match(path):
            result[id] = plugin.parse(path)
  → PluginManager.get_display_fields()
    → return all display_fields from all enabled plugins
  → _render_plugin_fields(path)
    → create/update QLabel widgets for each field
    → hide fields with empty values
```

- `match()` and `parse()` are called synchronously in the GUI thread.
- Keep them fast (< 100ms). For heavy I/O, use cached results or background threads.
- Plugin load order is alphabetical by folder name.
- Parsing errors in one plugin are logged and skipped (don't crash others).

---

## Examples

### Booth Link Parser (`booth_link/`)

Parses `_link/*.txt` files produced by Booth download tools:

```
_product_12345.txt:
  https://booth.pm/ja/items/12345
  
  商品名称: Sample Product
  作者: AuthorName
  商品ID: 12345
```

Match condition: file ends with `.txt` AND is inside a `_link/` subdirectory.
