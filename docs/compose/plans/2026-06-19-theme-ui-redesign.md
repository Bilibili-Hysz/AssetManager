# Theme System UI/UX Redesign — Implementation Plan
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three-section theme UI (Mode/Theme List/Custom List) in SettingsDialog with two compact popup menu buttons (Mode + Theme).

**Architecture:** Replace `_setup_theme_section` in `SettingsDialog` with new button-based layout. Mode button has 2-item popup. Theme button has dynamic popup rebuilt on each click. Helper functions determine mode from base color brightness. TDD approach — write test for mode detection first.

**Tech Stack:** PySide6 (QPushButton, QMenu, QAction), existing `themes` module, `ThemeLoader`.

**Spec:** `docs/compose/specs/2026-06-19-theme-ui-redesign.md`

---

### Task 1: Helper function — determine theme mode from base color

**Covers:** [S3]

**Files:**
- Modify: `AssetsManager/core/themes.py`
- Test: `tests/core/test_themes.py`

- [ ] **Step 1: Write the failing test**

```python
def test_theme_mode_from_base_color():
    from AssetsManager.core.themes import theme_mode_for_base
    assert theme_mode_for_base("#1a1a1a") == "dark"   # very dark
    assert theme_mode_for_base("#ffffff") == "light"  # white
    assert theme_mode_for_base("#252525") == "dark"
    assert theme_mode_for_base("#f0f0f0") == "light"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_themes.py::test_theme_mode_from_base_color -v`
Expected: FAIL with "cannot import name 'theme_mode_for_base'"

- [ ] **Step 3: Implement**

```python
def theme_mode_for_base(hex_color: str) -> str:
    """Return 'dark' or 'light' based on base color luminance."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        return "dark"
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "light" if luminance >= 128 else "dark"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_themes.py::test_theme_mode_from_base_color -v`
Expected: PASS

---

### Task 2: Replace _setup_theme_section with two-button layout

**Covers:** [S2, S3]

**Files:**
- Modify: `AssetsManager/dialogs/settings_dialog.py`

- [ ] **Step 1: Backup current `_setup_theme_section` method**

Keep the old method body commented out temporarily as reference.

- [ ] **Step 2: Implement new `_setup_theme_section`**

Replace the three-section layout with two buttons. The method should:
1. Create a horizontal layout
2. Add a mode button (`QPushButton` with text "深色" or "浅色")
3. Add a theme button (`QPushButton` with text = current theme name)
4. Connect mode button click to `_on_mode_menu_requested`
5. Connect theme button click to `_on_theme_menu_requested`
6. Save references: `self._mode_btn`, `self._theme_btn`

```python
def _setup_theme_section(self, layout):
    from AssetsManager.core.ui_scale import scaled_px

    layout.addWidget(self.make_heading(tr("settings.theme")))

    btn_row = QHBoxLayout()
    btn_row.setSpacing(scaled_px(8))

    current_mode = AppSettings.instance().get("appearance_mode", "dark")
    mode_text = tr("settings.dark_mode") if current_mode == "dark" else tr("settings.light_mode")
    self._mode_btn = QPushButton(mode_text + " ▾")
    self._mode_btn.setMinimumWidth(scaled_px(100))
    self._mode_btn.clicked.connect(self._on_mode_menu_requested)
    btn_row.addWidget(self._mode_btn)

    current_theme = themes.name()
    self._theme_btn = QPushButton(current_theme + " ▾")
    self._theme_btn.setMinimumWidth(scaled_px(160))
    self._theme_btn.clicked.connect(self._on_theme_menu_requested)
    btn_row.addWidget(self._theme_btn)

    btn_row.addStretch()
    layout.addLayout(btn_row)

    self._current_mode = current_mode
```

- [ ] **Step 3: Implement `_on_mode_menu_requested`**

```python
def _on_mode_menu_requested(self):
    from PySide6.QtWidgets import QMenu
    menu = QMenu(self)
    dark_action = menu.addAction(tr("settings.dark_mode"))
    light_action = menu.addAction(tr("settings.light_mode"))
    chosen = menu.exec(self._mode_btn.mapToGlobal(self._mode_btn.rect().bottomLeft()))
    if chosen == dark_action:
        self._apply_mode("dark")
    elif chosen == light_action:
        self._apply_mode("light")
```

- [ ] **Step 4: Implement `_apply_mode`**

```python
def _apply_mode(self, mode: str):
    self._current_mode = mode
    mode_text = tr("settings.dark_mode") if mode == "dark" else tr("settings.light_mode")
    self._mode_btn.setText(mode_text + " ▾")
    AppSettings.instance().set("appearance_mode", mode)
    AppSettings.instance().save()
    # Auto-select first theme in this mode
    loader = themes._get_loader()
    groups = loader.list_themes()
    group_name = "Dark" if mode == "dark" else "Light"
    theme_list = groups.get(group_name, [])
    if theme_list:
        first = theme_list[0].get("name", "")
        if first:
            themes.set_theme(first)
            self._theme_btn.setText(first + " ▾")
```

- [ ] **Step 5: Implement `_on_theme_menu_requested`**

```python
def _on_theme_menu_requested(self):
    from PySide6.QtWidgets import QMenu, QAction
    from PySide6.QtGui import QPixmap, QPainter, QColor, QIcon
    from AssetsManager.core.themes import _get_loader, theme_mode_for_base

    loader = _get_loader()
    groups = loader.list_themes()
    menu = QMenu(self)

    # Determine which group to show
    group_name = "Dark" if self._current_mode == "dark" else "Light"
    theme_list = groups.get(group_name, [])

    current_theme = themes.name()

    # Built-in themes
    for td in theme_list:
        name = td.get("name", "")
        accent = td.get("colors", {}).get("accent", "#888")
        pixmap = QPixmap(12, 12)
        pixmap.fill(QColor(accent))
        icon = QIcon(pixmap)
        action = menu.addAction(icon, name)
        action.setData(name)
        if name == current_theme:
            action.setCheckable(True)
            action.setChecked(True)

    # Custom themes for current mode
    user_themes = groups.get("User", [])
    user_in_mode = [td for td in user_themes
                    if theme_mode_for_base(td.get("colors", {}).get("base", "#1a1a1a")) == self._current_mode]

    if user_in_mode:
        menu.addSeparator()
        for td in user_in_mode:
            name = td.get("name", "")
            accent = td.get("colors", {}).get("accent", "#888")
            pixmap = QPixmap(12, 12)
            pixmap.fill(QColor(accent))
            icon = QIcon(pixmap)
            action = menu.addAction(icon, name)
            action.setData(name)
            if name == current_theme:
                action.setCheckable(True)
                action.setChecked(True)

    # Actions
    menu.addSeparator()
    new_action = menu.addAction(tr("settings.new_theme"))
    edit_action = menu.addAction(tr("settings.theme_preview"))
    import_action = menu.addAction(tr("settings.import_theme"))
    delete_action = menu.addAction(tr("settings.delete_theme"))

    # Enable/disable based on selection
    is_custom = any(td.get("name") == current_theme for td in user_themes)
    edit_action.setEnabled(is_custom)
    delete_action.setEnabled(is_custom)

    chosen = menu.exec(self._theme_btn.mapToGlobal(self._theme_btn.rect().bottomLeft()))
    if not chosen:
        return

    chosen_name = chosen.data()
    if chosen_name:
        themes.set_theme(chosen_name)
        self._theme_btn.setText(chosen_name + " ▾")
    elif chosen == new_action:
        self._on_new_custom_theme()
    elif chosen == edit_action:
        self._on_preview_theme()
    elif chosen == import_action:
        self._import_theme()
    elif chosen == delete_action:
        self._delete_custom_theme()
```

- [ ] **Step 6: Implement `_import_theme`**

```python
def _import_theme(self):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    path, _ = QFileDialog.getOpenFileName(
        self, tr("settings.import_theme"), "",
        "JSON Files (*.json);;All Files (*)")
    if not path:
        return
    import shutil, json
    from AssetsManager.core.path_resolver import themes_dir
    from AssetsManager.core.themes import _get_loader, theme_mode_for_base
    try:
        data = json.loads(open(path, encoding="utf-8").read())
        name = data.get("name", "")
        if not name:
            QMessageBox.warning(self, tr("dialog.error"), "Theme file has no name.")
            return
        loader = _get_loader()
        if loader.get_theme(name):
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.theme_exists"))
            return
        # Determine prefix from mode
        base = data.get("colors", {}).get("base", "#1a1a1a")
        mode = theme_mode_for_base(base)
        prefix = "D_" if mode == "dark" else "L_"
        dest = themes_dir() / f"{prefix}{name.replace(' ', '_')}.json"
        shutil.copy2(path, dest)
        themes.reload_themes()
        themes.set_theme(name)
        self._theme_btn.setText(name + " ▾")
    except Exception as e:
        QMessageBox.warning(self, tr("dialog.error"), str(e))
```

- [ ] **Step 7: Implement `_delete_custom_theme`**

```python
def _delete_custom_theme(self):
    from PySide6.QtWidgets import QMessageBox
    from AssetsManager.core.themes import _get_loader
    current = themes.name()
    loader = _get_loader()
    if loader.delete_custom_theme(current):
        themes.reload_themes()
        # Select first available theme in current mode
        groups = loader.list_themes()
        group_name = "Dark" if self._current_mode == "dark" else "Light"
        theme_list = groups.get(group_name, [])
        if theme_list:
            first = theme_list[0].get("name", "")
            themes.set_theme(first)
            self._theme_btn.setText(first + " ▾")
    else:
        QMessageBox.warning(self, tr("dialog.error"), "Cannot delete built-in themes.")
```

- [ ] **Step 8: Remove old theme section code**

Delete `_custom_list`, `_custom_new_btn`, `_custom_import_btn`, `_custom_delete_btn`, and related methods that are no longer needed.

- [ ] **Step 9: Run full quality gate**

Run: `python -m ruff check . && python -m pyright && python -m pytest -q`
Expected: All pass.

---

### Task 3: Add _on_new_custom_theme update to refresh button

**Covers:** [S3]

**Files:**
- Modify: `AssetsManager/dialogs/settings_dialog.py`

- [ ] **Step 1: Update `_on_new_custom_theme` to refresh theme button text**

After creating a custom theme and selecting it, update `self._theme_btn.setText(name + " ▾")`.

- [ ] **Step 2: Run full quality gate**

Run: `python -m pytest -q --ignore=tests/desktop --deselect=tests/core/test_settings.py::test_save_load`
Expected: All pass.

