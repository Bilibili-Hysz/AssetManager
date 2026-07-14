# Custom Theme System — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate theme files to `Assets/Themes/` with `D_/L_/U_` prefix convention, implement dynamic ThemeLoader, and update theme selector UI.

**Architecture:** Theme files move from `AssetsManager/themes/` to `Assets/Themes/` with prefix-based naming. A new `ThemeLoader` class handles scanning, parsing, validation, and file watching. The existing `core/themes.py` delegates to `ThemeLoader`. Settings dialog gets a three-section theme selector.

**Tech Stack:** Python 3.12+, PySide6, QFileSystemWatcher, JSON

**Spec:** `docs/compose/specs/2026-06-18-custom-theme-system-design.md`

---

## File Structure

### New Files
- `AssetsManager/core/theme_loader.py` — ThemeLoader class
- `tests/core/test_theme_loader.py` — ThemeLoader tests
- `Assets/Themes/D_Default.json` — migrated default theme
- `Assets/Themes/D_*.json` — migrated dark themes
- `Assets/Themes/L_*.json` — migrated light themes

### Modified Files
- `AssetsManager/core/themes.py` — delegate to ThemeLoader
- `AssetsManager/core/path_resolver.py` — add `themes_dir()`
- `AssetManager.spec` — update datas path
- `AssetsManager/dialogs/settings_dialog.py` — new theme selector UI

---

### Task 1: Create ThemeLoader Core

**Covers:** S2

**Files:**
- Create: `AssetsManager/core/theme_loader.py`
- Create: `tests/core/test_theme_loader.py`

- [ ] **Step 1: Write ThemeLoader class**

```python
"""ThemeLoader — dynamic theme file scanner and validator."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

_log = logging.getLogger(__name__)

REQUIRED_COLOR_KEYS = {
    "base", "panel", "header", "border", "heading", "body",
    "muted", "accent", "success", "warning", "danger",
}

class ThemeLoader(QObject):
    """Scans theme directory, parses and validates theme files."""

    themes_changed = Signal()

    def __init__(self, themes_dir: Path):
        super().__init__()
        self._dir = themes_dir
        self._themes: dict[str, dict[str, Any]] = {}
        self._scan()

    def _scan(self):
        """Scan directory and parse all theme files."""
        self._themes.clear()
        if not self._dir.exists():
            return
        for path in sorted(self._dir.glob("*.json")):
            name = path.stem
            if not name.startswith(("D_", "L_", "U_")):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if self._validate(data, name):
                    self._themes[name] = data
            except Exception:
                _log.warning("Failed to load theme: %s", path)

    def _validate(self, data: dict, name: str) -> bool:
        """Validate theme JSON schema."""
        if not isinstance(data.get("colors"), dict):
            _log.warning("Theme %s missing 'colors' object", name)
            return False
        missing = REQUIRED_COLOR_KEYS - set(data["colors"].keys())
        if missing:
            _log.warning("Theme %s missing color keys: %s", name, missing)
            return False
        return True

    def get(self, name: str) -> dict[str, Any] | None:
        """Get theme by name (without prefix)."""
        return self._themes.get(name)

    def list_themes(self) -> dict[str, list[str]]:
        """List themes grouped by type (dark/light/user)."""
        groups: dict[str, list[str]] = {"dark": [], "light": [], "user": []}
        for name in sorted(self._themes):
            if name.startswith("D_"):
                groups["dark"].append(name[2:])
            elif name.startswith("L_"):
                groups["light"].append(name[2:])
            elif name.startswith("U_"):
                groups["user"].append(name[2:])
        return groups

    def get_full_name(self, name: str) -> str | None:
        """Get full prefixed name for a theme."""
        for prefix in ("D_", "L_", "U_"):
            if prefix + name in self._themes:
                return prefix + name
        return None

    def reload(self):
        """Reload all themes from disk."""
        self._scan()
        self.themes_changed.emit()

    def create_custom_theme(self, name: str, base_name: str) -> bool:
        """Create a new custom theme based on an existing theme."""
        base = self.get(base_name)
        if base is None:
            return False
        full_name = f"U_{name}"
        if full_name in self._themes:
            return False
        path = self._dir / f"{full_name}.json"
        path.write_text(json.dumps(base, indent=2, ensure_ascii=False), encoding="utf-8")
        self._themes[full_name] = base.copy()
        return True

    def delete_custom_theme(self, name: str) -> bool:
        """Delete a custom theme."""
        full_name = f"U_{name}" if not name.startswith("U_") else name
        if full_name not in self._themes:
            return False
        path = self._dir / f"{full_name}.json"
        path.unlink(missing_ok=True)
        self._themes.pop(full_name, None)
        return True
```

- [ ] **Step 2: Write tests**

```python
"""Tests for ThemeLoader."""
import json
import pytest
from pathlib import Path
from AssetsManager.core.theme_loader import ThemeLoader


@pytest.fixture
def themes_dir(tmp_path):
    d = tmp_path / "Themes"
    d.mkdir()
    # Dark theme
    (d / "D_Default.json").write_text(json.dumps({
        "name": "Default", "dark": True,
        "colors": {
            "base": "#1a1a1a", "panel": "#252525", "header": "#2d2d2d",
            "border": "#555555", "heading": "#e0e0e0", "body": "#b0b0b0",
            "muted": "#666666", "accent": "#606060", "success": "#44c98a",
            "warning": "#f0a040", "danger": "#e05555",
        },
        "properties": {"border_radius": {"sm": 4, "md": 6, "lg": 8}},
    }))
    # Light theme
    (d / "L_Coral.json").write_text(json.dumps({
        "name": "Coral", "dark": False,
        "colors": {
            "base": "#ffffff", "panel": "#f5f5f5", "header": "#eeeeee",
            "border": "#cccccc", "heading": "#1a1a1a", "body": "#333333",
            "muted": "#888888", "accent": "#ff6b6b", "success": "#44c98a",
            "warning": "#f0a040", "danger": "#e05555",
        },
        "properties": {"border_radius": {"sm": 4, "md": 6, "lg": 8}},
    }))
    # Invalid theme (missing colors)
    (d / "D_Bad.json").write_text(json.dumps({"name": "Bad"}))
    return d


def test_scan_loads_valid_themes(themes_dir):
    loader = ThemeLoader(themes_dir)
    assert loader.get("Default") is not None
    assert loader.get("Coral") is not None
    assert loader.get("Bad") is None


def test_list_themes_groups(themes_dir):
    loader = ThemeLoader(themes_dir)
    groups = loader.list_themes()
    assert "Default" in groups["dark"]
    assert "Coral" in groups["light"]
    assert len(groups["user"]) == 0


def test_create_custom_theme(themes_dir):
    loader = ThemeLoader(themes_dir)
    assert loader.create_custom_theme("MyTheme", "Default") is True
    assert loader.get("MyTheme") is not None
    assert (themes_dir / "U_MyTheme.json").exists()


def test_delete_custom_theme(themes_dir):
    loader = ThemeLoader(themes_dir)
    loader.create_custom_theme("MyTheme", "Default")
    assert loader.delete_custom_theme("MyTheme") is True
    assert loader.get("MyTheme") is None


def test_invalid_json_skipped(themes_dir):
    (themes_dir / "D_Broken.json").write_text("not json")
    loader = ThemeLoader(themes_dir)
    assert loader.get("Broken") is None
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/core/test_theme_loader.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add AssetsManager/core/theme_loader.py tests/core/test_theme_loader.py
git commit -m "feat: add ThemeLoader for dynamic theme scanning and validation"
```

---

### Task 2: Migrate Theme Files to Assets/Themes/

**Covers:** S1, S4

**Files:**
- Create: `Assets/Themes/` directory
- Move: All files from `AssetsManager/themes/` to `Assets/Themes/`
- Modify: `AssetManager.spec`

- [ ] **Step 1: Create directory and migrate files**

Create `Assets/Themes/` and move all theme files with prefix renaming:

| Old Name | New Name |
|----------|----------|
| `default.json` | `D_Default.json` |
| `dracula.json` | `D_Dracula.json` |
| `navy.json` | `D_Navy.json` |
| `midnight.json` | `D_Midnight.json` |
| `slate.json` | `D_Slate.json` |
| `charcoal.json` | `D_Charcoal.json` |
| `espresso.json` | `D_Espresso.json` |
| `nord.json` | `D_Nord.json` |
| `gruvbox.json` | `D_Gruvbox.json` |
| `rosepine.json` | `D_Rosepine.json` |
| `forest.json` | `D_Forest.json` |
| `amber.json` | `D_Amber.json` |
| `mint.json` | `D_Mint.json` |
| `coral.json` | `L_Coral.json` |
| `lavender.json` | `L_Lavender.json` |
| `lilac.json` | `L_Lilac.json` |
| `peach.json` | `L_Peach.json` |
| `rose.json` | `L_Rose.json` |
| `sage.json` | `L_Sage.json` |
| `sky.json` | `L_Sky.json` |
| `silver.json` | `L_Silver.json` |
| `dawn.json` | `L_Dawn.json` |

- [ ] **Step 2: Update JSON name field**

In each migrated file, update the `"name"` field to match the new display name (without prefix):
- `D_Default.json` → `"name": "Default"`
- `D_Dracula.json` → `"name": "Dracula"`
- `L_Coral.json` → `"name": "Coral"`

- [ ] **Step 3: Update AssetManager.spec**

Replace the themes datas line:
```python
# Old:
(str(_root / 'AssetsManager' / 'themes'), 'AssetsManager/themes'),
# New:
(str(_root / 'Assets' / 'Themes'), 'Assets/Themes'),
```

- [ ] **Step 4: Add path_resolver.themes_dir()**

In `AssetsManager/core/path_resolver.py`, add:
```python
def themes_dir() -> Path:
    """Return the themes directory."""
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            bundled = Path(meipass) / "Assets" / "Themes"
            if bundled.exists():
                return bundled
    return Path(__file__).resolve().parent.parent.parent / "Assets" / "Themes"
```

- [ ] **Step 5: Run quality gate**

```
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add Assets/Themes/ AssetManager.spec AssetsManager/core/path_resolver.py
git rm -r AssetsManager/themes/
git commit -m "feat: migrate theme files to Assets/Themes/ with D_/L_ prefix convention"
```

---

### Task 3: Integrate ThemeLoader into themes.py

**Covers:** S2, S4

**Files:**
- Modify: `AssetsManager/core/themes.py`

- [ ] **Step 1: Add ThemeLoader integration**

In `AssetsManager/core/themes.py`, replace the theme loading mechanism:

```python
# At module level, replace _load_all_themes() with ThemeLoader
from AssetsManager.core.theme_loader import ThemeLoader
from AssetsManager.core.path_resolver import themes_dir

_loader: ThemeLoader | None = None

def _get_loader() -> ThemeLoader:
    global _loader
    if _loader is None:
        _loader = ThemeLoader(themes_dir())
    return _loader

def _load_all_themes() -> dict[str, dict]:
    """Load all themes via ThemeLoader."""
    loader = _get_loader()
    # Convert to old format for compatibility
    result = {}
    for name in loader.list_themes()["dark"] + loader.list_themes()["light"] + loader.list_themes()["user"]:
        full_name = loader.get_full_name(name)
        if full_name:
            result[name] = loader.get(name)
    return result

def names() -> list[str]:
    """Return sorted theme names (without prefix)."""
    loader = _get_loader()
    groups = loader.list_themes()
    return groups["dark"] + groups["light"] + groups["user"]
```

- [ ] **Step 2: Add migration for old theme names**

Add a migration function to handle old settings:
```python
def _migrate_theme_name(old_name: str) -> str:
    """Migrate old theme name to new format."""
    # Old names were lowercase (e.g., "navy", "dracula")
    # New names are capitalized without prefix (e.g., "Navy", "Dracula")
    return old_name.capitalize() if old_name else "Default"
```

- [ ] **Step 3: Update set_theme() to handle migration**

```python
def set_theme(name: str):
    global _current_theme_name
    loader = _get_loader()
    # Try direct match first
    theme = loader.get(name)
    if theme is None:
        # Try migration
        migrated = _migrate_theme_name(name)
        theme = loader.get(migrated)
        if theme:
            name = migrated
    if theme is None:
        _log.warning("Theme not found: %s", name)
        return
    _current_theme_name = name
    _apply_theme(theme)
```

- [ ] **Step 4: Add reload_themes() function**

```python
def reload_themes():
    """Reload themes from disk (called on file change)."""
    _get_loader().reload()
```

- [ ] **Step 5: Run quality gate**

```
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add AssetsManager/core/themes.py
git commit -m "refactor: integrate ThemeLoader into themes.py with migration support"
```

---

### Task 4: Update Settings Dialog Theme Selector

**Covers:** S3

**Files:**
- Modify: `AssetsManager/dialogs/settings_dialog.py`

- [ ] **Step 1: Read current theme selector code**

Read `AssetsManager/dialogs/settings_dialog.py` to understand the current theme selector implementation.

- [ ] **Step 2: Add three-section theme selector**

Replace the flat theme list with three sections:

```python
def _setup_theme_section(self):
    """Setup the three-part theme selector."""
    from AssetsManager.core.themes import _get_loader
    from AssetsManager.core import themes
    
    loader = _get_loader()
    groups = loader.list_themes()
    
    # Section 1: Appearance Mode
    mode_group = QGroupBox(tr("settings.appearance_mode"))
    mode_layout = QVBoxLayout(mode_group)
    self._mode_dark = QRadioButton(tr("settings.dark_mode"))
    self._mode_light = QRadioButton(tr("settings.light_mode"))
    self._mode_system = QRadioButton(tr("settings.follow_system"))
    mode_layout.addWidget(self._mode_dark)
    mode_layout.addWidget(self._mode_light)
    mode_layout.addWidget(self._mode_system)
    
    # Section 2: Theme Selection
    theme_group = QGroupBox(tr("settings.theme"))
    theme_layout = QVBoxLayout(theme_group)
    self._theme_list = QListWidget()
    for name in groups["dark"]:
        item = QListWidgetItem(f"  {name}")
        item.setData(Qt.ItemDataRole.UserRole, name)
        self._theme_list.addItem(item)
    for name in groups["light"]:
        item = QListWidgetItem(f"  {name}")
        item.setData(Qt.ItemDataRole.UserRole, name)
        self._theme_list.addItem(item)
    theme_layout.addWidget(self._theme_list)
    
    # Section 3: Custom Themes
    custom_group = QGroupBox(tr("settings.custom_themes"))
    custom_layout = QVBoxLayout(custom_group)
    self._custom_list = QListWidget()
    for name in groups["user"]:
        self._add_custom_theme_item(name)
    add_btn = QPushButton(tr("settings.new_theme"))
    add_btn.clicked.connect(self._on_new_theme)
    custom_layout.addWidget(self._custom_list)
    custom_layout.addWidget(add_btn)
```

- [ ] **Step 3: Add new theme dialog**

```python
def _on_new_theme(self):
    """Show dialog to create a new custom theme."""
    from AssetsManager.core.themes import _get_loader
    loader = _get_loader()
    
    name, ok = QInputDialog.getText(self, tr("settings.new_theme"), tr("settings.theme_name"))
    if not ok or not name.strip():
        return
    
    # Select base theme
    groups = loader.list_themes()
    all_themes = groups["dark"] + groups["light"]
    base, ok = QInputDialog.getItem(self, tr("settings.base_theme"), tr("settings.select_base"), all_themes, 0, False)
    if not ok:
        return
    
    if loader.create_custom_theme(name.strip(), base):
        self._add_custom_theme_item(name.strip())
    else:
        QMessageBox.warning(self, tr("dialog.error"), tr("settings.theme_exists"))
```

- [ ] **Step 4: Add custom theme management**

```python
def _add_custom_theme_item(self, name: str):
    """Add a custom theme item with edit/export/delete buttons."""
    item = QListWidgetItem(f"  {name}")
    item.setData(Qt.ItemDataRole.UserRole, name)
    self._custom_list.addItem(item)

def _on_export_theme(self, name: str):
    """Export custom theme to file."""
    from AssetsManager.core.themes import _get_loader
    loader = _get_loader()
    theme = loader.get(name)
    if theme is None:
        return
    path, _ = QFileDialog.getSaveFileName(self, tr("settings.export_theme"), f"{name}.json", "JSON (*.json)")
    if path:
        Path(path).write_text(json.dumps(theme, indent=2, ensure_ascii=False), encoding="utf-8")

def _on_delete_theme(self, name: str):
    """Delete a custom theme."""
    from AssetsManager.core.themes import _get_loader
    loader = _get_loader()
    if loader.delete_custom_theme(name):
        # Remove from list
        for i in range(self._custom_list.count()):
            item = self._custom_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == name:
                self._custom_list.takeItem(i)
                break
```

- [ ] **Step 5: Run quality gate**

```
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add AssetsManager/dialogs/settings_dialog.py
git commit -m "feat: update settings dialog with three-section theme selector"
```

---

### Task 5: Add i18n Keys

**Covers:** S3

**Files:**
- Modify: `AssetsManager/i18n/en.json`
- Modify: `AssetsManager/i18n/zh.json`
- Modify: `AssetsManager/i18n/ja.json`

- [ ] **Step 1: Add new i18n keys**

In `en.json`:
```json
"settings.appearance_mode": "Appearance Mode",
"settings.dark_mode": "Dark Mode",
"settings.light_mode": "Light Mode",
"settings.follow_system": "Follow System",
"settings.theme": "Theme",
"settings.custom_themes": "Custom Themes",
"settings.new_theme": "New Theme",
"settings.theme_name": "Theme Name",
"settings.base_theme": "Base Theme",
"settings.select_base": "Select base theme:",
"settings.theme_exists": "Theme already exists",
"settings.export_theme": "Export Theme",
"settings.import_theme": "Import Theme"
```

Add corresponding translations in `zh.json` and `ja.json`.

- [ ] **Step 2: Run quality gate**

```
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

- [ ] **Step 3: Commit**

```bash
git add AssetsManager/i18n/
git commit -m "feat: add i18n keys for custom theme system"
```

---

### Task 6: Add File Watcher for Auto-Reload

**Covers:** S2

**Files:**
- Modify: `AssetsManager/core/theme_loader.py`
- Modify: `AssetsManager/core/themes.py`

- [ ] **Step 1: Add QFileSystemWatcher to ThemeLoader**

In `theme_loader.py`, add watcher setup:
```python
from PySide6.QtCore import QFileSystemWatcher

def _setup_watcher(self):
    """Watch theme directory for changes."""
    self._watcher = QFileSystemWatcher()
    if self._dir.exists():
        self._watcher.addPath(str(self._dir))
    self._watcher.directoryChanged.connect(self._on_directory_changed)

def _on_directory_changed(self, path: str):
    """Handle directory change."""
    self._scan()
    self.themes_changed.emit()
```

- [ ] **Step 2: Connect watcher in themes.py**

```python
def _get_loader() -> ThemeLoader:
    global _loader
    if _loader is None:
        _loader = ThemeLoader(themes_dir())
        _loader.themes_changed.connect(_on_themes_changed)
    return _loader

def _on_themes_changed():
    """Handle theme file changes."""
    # Re-apply current theme if it still exists
    if _current_theme_name:
        set_theme(_current_theme_name)
```

- [ ] **Step 3: Run quality gate**

```
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

- [ ] **Step 4: Commit**

```bash
git add AssetsManager/core/theme_loader.py AssetsManager/core/themes.py
git commit -m "feat: add file watcher for auto-reload themes on change"
```

---

### Task 7: Final Integration and Testing

**Covers:** S1, S2, S3, S4

**Files:**
- All modified files

- [ ] **Step 1: Run full quality gate**

```
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

- [ ] **Step 2: Manual testing checklist**

- [ ] App starts with new theme directory
- [ ] All 22 built-in themes load correctly
- [ ] Theme switching works
- [ ] Custom theme creation works
- [ ] Custom theme deletion works
- [ ] File watcher detects changes
- [ ] Old theme names migrate correctly
- [ ] Settings dialog shows three sections

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: complete custom theme system phase 1 — infrastructure"
```
