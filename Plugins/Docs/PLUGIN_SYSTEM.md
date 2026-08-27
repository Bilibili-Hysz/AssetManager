# Plugin System — Architecture & Implementation

> 状态:**FROZEN(v1 手册,2026-06-09)** · 冻结登记:2026-08-27 · **v2 已落地**:当前插件 API 以 `AssetsManager/plugin_api/`(types.py/__init__.py)与 `AssetsManager/core/plugins/host_context.py` 为准;本文仅作 v1 历史参考。

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

### API 代际边界（legacy v1 / v2）

本手册主体描述 **legacy v1**（`plugin.json` + 顶层 `match()`/`parse()` 元数据解析器）。**v2 是当前推荐入口**：插件在 `register(host)` 中调用 `host.register_class(cls)` 注册贡献类（`CommandOperator` / `FileParser` / `ContextMenuItem` / `MenuContributor` / `PanelContributor` / `EventHook` / `CategoryContributor` / `ThemeTokenContributor` / `Preferences`，均定义于 `AssetsManager.plugin_api`），并在回调中通过 getter 风格的 `PluginContext` 访问宿主。两组 API 并存：旧插件（v1）不经修改继续可用（兼容层），新插件只应使用 v2。


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
| `permissions` | list[string] | ❌ | Capability tokens gating the host's own APIs (see §12). Cannot restrict plugin code. |
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

## 6. 插件管理器（legacy v1 路径）

> ⚠️ `AssetsManager.core.plugin_manager` 模块**已不存在**，请勿再引用。legacy `match`/`parse` 解析器仍被兼容层支持，但运行时位于 `AssetsManager/core/plugins/`（`PluginManagerService` + `PluginHostContext`），对外公开 SDK 在 `AssetsManager.plugin_api`。

### Singleton access

```python
from AssetsManager.core.plugins.manager import PluginManagerService
pm = PluginManagerService.get()  # 默认扫描 RuntimeData/Shared/plugins/ 与 Plugins/Addons/
```

### discover_plugins()（legacy 语义）

Scans `Plugins/Addons/` (plus `RuntimeData/Shared/plugins/`), loads all folders with valid `plugin.json` where `enabled: true`.

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

## 10. Extension Points（消费状态一览）

> 本表描述**扩展点的实际消费状态**（注册 API 是否被宿主 UI 调用/渲染）。「注册 API 存在」表示 `PluginHostContext` 已提供对应 `register_*` 或 v2 贡献类（含 §12 的权限门）；「未接线」表示当前没有 UI 消费方，贡献不会被展示——即不视为当前可用能力。

| Extension | Status | Description |
|-----------|--------|-------------|
| `info.fields` | ✅ 已接线 | Display metadata fields in InfoPanel（legacy `display_fields` + v2 `FileParser`） |
| 右键菜单动作（`file.actions`） | ✅ 已接线 | `register_context_menu_item()` / `ContextMenuItem`，文件右键菜单 UI 已消费 |
| 菜单与工具面板 | ✅ 已接线 | `register_menu_contribution()` / `register_tool_window()`（`MenuContributor`/`PanelContributor`），窗口菜单与 dock 已消费 |
| 主题令牌 / 事件钩子 / 自定义分类 | ✅ 已接线 | `register_theme_token()` / `hook()` / `register_category()`，主题 fallback、事件总线、过滤器下拉已消费 |
| `file.columns` | ⚠️ 注册 API 存在、无 UI 消费（Future） | `register_column()` 可登记列，但文件列表 UI 未渲染它 |
| `search.providers` | ⚠️ 注册 API 存在（`filesystem.read` 门）、无 UI 消费（Future） | `register_search_provider()` 可登记搜索提供者，但搜索 UI 未调用它 |

> 与 §12 的关系：§12 的权限表中 `register_search_provider()` / `register_file_handler()` / `open_path()` 的 `filesystem.read` 门是真实的宿主 API 门禁；"未接线"仅指这些注册项目前没有 UI 消费方，二者不矛盾。

To wire up a new extension point:
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

### Permissions gate host APIs — they are not a sandbox

The `permissions` field in `plugin.json` declares what capabilities the plugin intends to use:

```json
{
  "permissions": ["filesystem.read", "settings.write", "host.services"]
}
```

The host checks these tokens on its own APIs: a call made without the declared permission is refused and a warning is logged (read-style APIs return `None`, registrations are dropped). What each token gates:

| Token | Host enforcement point | Nature |
|-------|------------------------|--------|
| `host.services` | `ctx.services()` / `ctx.session` / `ctx.window` return `None` without it | Real boundary — the only route to the service bundle and library session |
| `settings.write` | `register_category()` / `register_theme_token()` refused without it | Real boundary — global host registries reachable only through the host API |
| `filesystem.read` | `register_file_handler()` / `register_search_provider()` / `open_path()` refused without it | Advisory — a plugin can read any file with `open()`/`pathlib` directly |
| `settings.read` / `settings.write` | `ctx.preferences()` returns `None` without either | Advisory — a plugin can import the preferences module directly |
| `database.read` / `database.write` | no separate check — database access is bundled into `host.services` (the library session) | Intent declaration only |
| `filesystem.write` / `network.request` / `clipboard.read` / `clipboard.write` | no host API exists for these capabilities — nothing to gate | Intent declaration only |

**These gates are honesty/intent boundaries, not security.** Plugin code runs in the same Python interpreter with full stdlib access: every gate above (including `host.services`) can be bypassed with a direct `import` (e.g. `pathlib`, `urllib.request`, `QApplication.clipboard()`, or the host's own modules). A hostile plugin needs no permission tokens at all. Declaring permissions is what makes the host's own APIs usable; the checks catch honest mistakes and document intent. Only subprocess isolation or a sandbox could turn them into a real boundary.

### 身份门（subject/owner 限定）与宿主方法

除按权限 token 门控外，部分宿主方法还按“插件身份（subject）”门控，防止一个插件冒用另一插件或主机的身份：

| 方法 | 门 | 语义 |
|------|----|------|
| `execute_command(cid)` | 身份门 | 插件 subject 只能执行自己的命令（v2 owner 取自 `_class_owners`，legacy 取自贡献的 `plugin_id`）；主机（无 subject）可执行任意命令。越权拒绝并告警 |
| `undo_last_command()` | 身份门 | 只能撤销自己的 `undoable` v2 算子；撤销栈仅覆盖 v2 `CommandOperator`，legacy handler 的操作不入栈。当前无 UI 入口，仅测试在调用 |
| `unregister_plugin(pid)` | 身份门 | 插件只能注销自己；主机可注销任意插件（manager 卸载 / 加载失败清理 / 管理对话框） |
| `grant_permissions(pid, ...)` | 身份门 | 仅在无活动插件 subject（主机加载路径）时可调用；任何插件（含自授权）都被拒绝 |
| `preferences(pid)` | advisory（`settings.read`/`settings.write`，二者任一） | owner 由调用 subject 解析，跨插件 id 被忽略并告警 |
| `open_path(path)` | advisory（`filesystem.read`） | 同解释器中可被 `os.startfile`/`subprocess` 直接绕过 |
| `services()/session/window` | 强制（`host.services`） | 缺权限返回 `None`，服务束/库会话/主窗口没有第二条路径 |

**已关闭**：`plugin_execution()` / `plugin_registration()` 现在拒绝身份切换 —— 当已有插件 subject 活动时，传入其他 id（或空串洗白成主机）会记 WARNING 并保持原身份不变，`with` 块照常执行。主机自身的嵌套派发（hook、`when` 判定、operator handler、加载/卸载）走私有 `_host_identity_scope`，因为这类切换是合法的。卸载时的 undo 记录与通知也已按 owner 清理。

**仍不是安全边界**：subject 由 `ContextVar` 承载，未标记的新线程（Python 3.14 起 `Thread` 默认不继承调用方 context）subject 为空，而权限助手当前把空 subject 视为主机放行；插件仍可直接调用 `_host_identity_scope` 或改写 `_executing_plugin_var` / `_permissions_by_plugin` 等私有状态绕过上述门。同解释器内无法防御，详见交接文档 `docs/full-review/11-plugin-api-v2-handover.md`。
