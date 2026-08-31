"""Settings dialog — theme, background, language, thumbnail quality, and cache management.

Inherits TabbedDialog for consistent dark theme and widget factories.
"""
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from shiboken6 import Shiboken
from PySide6.QtCore import Qt, Signal, QObject, QSignalBlocker, QSize, QTimer
from PySide6.QtWidgets import (
    QMessageBox, QProgressBar, QVBoxLayout, QHBoxLayout, QWidget,
    QRadioButton, QFrame, QPushButton, QFileDialog, QSlider,
    QInputDialog, QLabel, QComboBox, QListWidget, QListWidgetItem,
    QCheckBox, QSpinBox, QLineEdit,
)
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager.core.constants import (
    ACTIVITY_RETENTION_DAYS,
    AI_TAGGING_MAX_TAGS_LIMIT,
    THUMBNAIL_CACHE_DEFAULT_MAX_BYTES,
)
from AssetsManager.panels._event_bridge import DomainEventSubscription
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core import themes
from AssetsManager.core import icons
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager import i18n
tr = i18n.tr

# H2-b: row cap for the broken-link result list — a pathological library can
# report thousands of orphans, so the card renders the first slice and says so.
_RELINK_ROW_LIMIT = 500


class _RelinkRowWidget(QWidget):
    """One broken-link result row: paths/confidence text + optional action."""

    def __init__(self, text: str, on_relink=None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scaled_px(6))
        self.path_label = QLabel(text)
        layout.addWidget(self.path_label, 1)
        self.relink_button: QPushButton | None = None
        if on_relink is not None:
            self.relink_button = QPushButton(tr("settings.relink_row_action"))
            themes.set_button_variant(self.relink_button, "secondary")
            self.relink_button.clicked.connect(on_relink)
            layout.addWidget(self.relink_button)


class _ThumbnailLoader(Protocol):
    def clear_thumb_cache(self) -> int: ...

    def clear_thumb_cache_async(self, on_progress=None, on_complete=None) -> bool: ...

    def regenerate_all(self, lib_root: str, on_progress=None, on_complete=None) -> bool: ...


class _FileListHost(Protocol):
    _loader: _ThumbnailLoader
    _lib_root: str


@runtime_checkable
class _BackgroundStyleHost(Protocol):
    def _on_bg_style_changed(self) -> None: ...


class _ThumbnailHost(Protocol):
    file_list: _FileListHost


class _ProgressSignals(QObject):
    updated = Signal(int, int)
    finished = Signal(int)
    # Thumbnail cache clear: per-file progress and the (removed, failed) outcome.
    clear_progress = Signal(int, int)
    cleared = Signal(int, int)


class SettingsDialog(TabbedDialog):
    supports_runtime_refresh = True

    def __init__(self, parent=None):
        self._logical_min_size = (460, 520)
        # Created lazily via _maintenance_runner (must exist before the tab
        # builders run inside super().__init__, hence the pre-init default).
        self._maintenance_runner = None
        super().__init__(parent, title=tr("settings.title"),
                         min_size=(scaled_px(460), scaled_px(520)))
        self._maintenance_subscription = None
        self._ensure_maintenance_subscription()

    def _ensure_maintenance_runner(self):
        """Lazily create the shared backup/restore background-task runner."""
        from AssetsManager.dialogs._maintenance_tasks import MaintenanceTaskRunner

        if self._maintenance_runner is None:
            self._maintenance_runner = MaintenanceTaskRunner(self)
        return self._maintenance_runner

    def set_library_settings_adapter(self, adapter) -> None:
        """Attach a UI-neutral library settings adapter for future settings sections."""
        self._library_settings_adapter = adapter
        if hasattr(self, "_maintenance_status"):
            self._refresh_maintenance_status()
        if hasattr(self, "_backup_status"):
            self._refresh_backup_status()

    @property
    def library_settings_adapter(self):
        return getattr(self, "_library_settings_adapter", None)

    def _set_menu_button_presentation(self, button: QPushButton, text: str):
        button.setText(text)
        button.setIcon(icons.icon("chevron_down", color="icon_primary", size=scaled_px(14)))
        button.setIconSize(QSize(scaled_px(14), scaled_px(14)))
        button.setAccessibleName(text)
        button.setToolTip(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        themes.set_button_variant(button, "secondary")

    def _refresh_menu_button_icons(self):
        for button in (
            getattr(self, "_mode_btn", None),
            getattr(self, "_theme_btn", None),
            getattr(self, "_effect_btn", None),
        ):
            if button is not None:
                button.setIcon(
                    icons.icon("chevron_down", color="icon_primary", size=scaled_px(14)))
                button.setIconSize(QSize(scaled_px(14), scaled_px(14)))

    def _on_theme_changed(self, name):
        super()._on_theme_changed(name)
        self._refresh_menu_button_icons()

    def _make_theme_row(self, name):
        """Create a row widget with color swatch and radio button."""
        from AssetsManager.core.ui_scale import scaled_px
        accent = themes.get(name)["accent"]
        row_w = QWidget()
        row_l = QHBoxLayout(row_w)
        row_l.setContentsMargins(0, 0, 0, 0)
        row_l.setSpacing(scaled_px(6))
        swatch = QFrame()
        swatch.setFixedSize(scaled_px(12), scaled_px(12))
        radius_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        swatch.setStyleSheet(
            f"background: {accent}; border: {scaled_px(1)}px solid {accent}; border-radius: {radius_sm}px;")
        row_l.addWidget(swatch)
        rb = QRadioButton(name)
        rb.setMinimumHeight(scaled_px(24))
        if name == themes._current:
            rb.setChecked(True)
        row_l.addWidget(rb)
        row_l.addStretch()
        return row_w, rb

    def _setup_tabs(self):
        self._build_appearance_tab()
        self._build_general_tab()
        self._build_thumbnails_tab()
        self._build_maintenance_tab()
        self._build_backup_tab()
        self._build_plugins_tab()

    # ── Tab 1: Appearance (Theme + Background) ────────────

    def _build_appearance_tab(self):
        from AssetsManager.core.ui_scale import scaled_px
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._appearance_layout = layout
        layout.setSpacing(scaled_px(int(themes.prop("spacing", "md"))))
        layout.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "sm"))),
            scaled_px(int(themes.prop("spacing", "sm"))),
            scaled_px(int(themes.prop("spacing", "sm"))),
            scaled_px(int(themes.prop("spacing", "sm"))))

        self._setup_theme_section(layout)

        # ── Background ─────────────────────────────────

        self._background_heading = self.make_heading(tr("settings.background"))
        layout.addWidget(self._background_heading)
        self._bg_enabled_cb = self.make_checkbox(tr("settings.bg_enabled"),
            themes.bg_enabled())
        self._bg_enabled_cb.toggled.connect(self._on_bg_setting_changed)
        layout.addWidget(self._bg_enabled_cb)

        path_row, self._bg_path_edit = self.make_browse_row(
            tr("settings.bg_image"), tr("settings.bg_placeholder"), callback=self._browse_bg_image)
        bg_image_item = path_row.itemAt(0)
        bg_browse_item = path_row.itemAt(2)
        assert bg_image_item is not None and bg_browse_item is not None
        self._bg_image_label = cast(QLabel, bg_image_item.widget())
        self._bg_browse_btn = cast(QPushButton, bg_browse_item.widget())
        current_path = themes.bg_image()
        if current_path:
            self._bg_path_edit.setText(current_path)
        self._bg_path_edit.textChanged.connect(self._on_bg_setting_changed)
        layout.addLayout(path_row)

        self._bg_panel_slider = self._make_pct_slider(themes.bg_panel_opacity())
        self._bg_panel_slider.valueChanged.connect(self._on_bg_setting_changed)
        self._bg_panel_row = self.make_labeled_row(
            tr("settings.bg_panel_opacity"), self._bg_panel_slider)
        bg_panel_label_item = self._bg_panel_row.itemAt(0)
        assert bg_panel_label_item is not None
        self._bg_panel_label = cast(QLabel, bg_panel_label_item.widget())
        layout.addLayout(self._bg_panel_row)

        self._bg_header_slider = self._make_pct_slider(themes.bg_header_opacity())
        self._bg_header_slider.valueChanged.connect(self._on_bg_setting_changed)
        self._bg_header_row = self.make_labeled_row(
            tr("settings.bg_header_opacity"), self._bg_header_slider)
        bg_header_label_item = self._bg_header_row.itemAt(0)
        assert bg_header_label_item is not None
        self._bg_header_label = cast(QLabel, bg_header_label_item.widget())
        layout.addLayout(self._bg_header_row)

        # ── Image Effects ──────────────────────────────

        self._effects_heading = self.make_heading(tr("settings.bg_effects"))
        layout.addWidget(self._effects_heading)

        btn_row = QHBoxLayout()
        self._effects_layout = btn_row
        btn_row.setSpacing(scaled_px(int(themes.prop("spacing", "sm"))))
        current_effect = themes.bg_effect()
        self._current_effect = current_effect
        effect_label = {"none": tr("settings.bg_effect_none"), "blur": tr("settings.bg_blur"), "mosaic": tr("settings.bg_mosaic"), "kuwahara": tr("settings.bg_kuwahara"), "shader": tr("settings.bg_effect_shader")}.get(current_effect, tr("settings.bg_effect_none"))
        self._effect_btn = QPushButton()
        self._set_menu_button_presentation(self._effect_btn, effect_label)
        self._effect_btn.setMinimumWidth(scaled_px(120))
        self._effect_btn.clicked.connect(self._on_effect_menu)
        btn_row.addWidget(self._effect_btn)

        self._effect_intensity = QSlider(Qt.Orientation.Horizontal)
        self._effect_intensity.setRange(1, 50)
        self._effect_intensity.setValue(themes.bg_effect_intensity())
        self._effect_intensity.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._effect_intensity.setTickInterval(5)
        # Debounce: each drag tick would otherwise trigger a settings save plus
        # a full synchronous re-application of the (potentially expensive)
        # background effect inside the next paintEvent.
        self._effect_intensity_timer = QTimer(self)
        self._effect_intensity_timer.setSingleShot(True)
        self._effect_intensity_timer.setInterval(150)
        self._effect_intensity_timer.timeout.connect(self._on_bg_setting_changed)
        self._effect_intensity.valueChanged.connect(self._effect_intensity_timer.start)
        btn_row.addWidget(self._effect_intensity, 1)
        layout.addLayout(btn_row)

        # ── Shader preset (visible only for the 'shader' effect) ─
        self._shader_preset_combo = QComboBox()
        from AssetsManager.background.gl import presets
        for key in presets.preset_keys():
            self._shader_preset_combo.addItem(presets.display_name(key), userData=key)
        active_preset = presets.resolve(themes.bg_shader_preset())
        idx = self._shader_preset_combo.findData(active_preset)
        if idx >= 0:
            self._shader_preset_combo.setCurrentIndex(idx)
        self._shader_preset_combo.currentIndexChanged.connect(self._on_bg_setting_changed)
        self._shader_preset_row = self.make_labeled_row(
            tr("settings.bg_shader_preset"), self._shader_preset_combo)
        layout.addLayout(self._shader_preset_row)
        self._set_row_visible(self._shader_preset_row, current_effect == "shader")

        self._clear_bg_btn = self.make_secondary_btn(tr("settings.bg_clear"), self._clear_bg)
        layout.addWidget(self._clear_bg_btn)

        layout.addStretch()
        self._add_tab(tab, tr("settings.appearance"), scrollable=True, label_key="settings.appearance")

    def _setup_theme_section(self, layout):
        from AssetsManager.core.ui_scale import scaled_px

        self._theme_heading = self.make_heading(tr("settings.theme"))
        layout.addWidget(self._theme_heading)

        btn_row = QHBoxLayout()
        self._theme_layout = btn_row
        btn_row.setSpacing(scaled_px(int(themes.prop("spacing", "sm"))))

        current_mode = AppSettings.instance().get("appearance_mode", "dark")
        mode_text = tr("settings.dark_mode") if current_mode == "dark" else tr("settings.light_mode")
        self._mode_btn = QPushButton()
        self._set_menu_button_presentation(self._mode_btn, mode_text)
        self._mode_btn.setMinimumWidth(scaled_px(100))
        self._mode_btn.clicked.connect(self._on_mode_menu_requested)
        btn_row.addWidget(self._mode_btn)

        current_theme = themes.name()
        self._theme_btn = QPushButton()
        self._set_menu_button_presentation(self._theme_btn, current_theme)
        self._theme_btn.setMinimumWidth(scaled_px(160))
        self._theme_btn.clicked.connect(self._on_theme_menu_requested)
        btn_row.addWidget(self._theme_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._current_mode = current_mode

    def _on_mode_menu_requested(self):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        dark_action = menu.addAction(tr("settings.dark_mode"))
        light_action = menu.addAction(tr("settings.light_mode"))
        custom_action = menu.addAction(tr("settings.custom_themes"))
        chosen = menu.exec(self._mode_btn.mapToGlobal(self._mode_btn.rect().bottomLeft()))
        if chosen == dark_action:
            self._apply_mode("dark")
        elif chosen == light_action:
            self._apply_mode("light")
        elif chosen == custom_action:
            self._apply_mode("custom")

    def _apply_mode(self, mode: str):
        self._current_mode = mode
        mode_label = {"dark": tr("settings.dark_mode"), "light": tr("settings.light_mode"), "custom": tr("settings.custom_themes")}.get(mode, mode)
        self._set_menu_button_presentation(self._mode_btn, mode_label)
        AppSettings.instance().set("appearance_mode", mode)
        AppSettings.instance().save()
        from AssetsManager.core.themes import _get_loader
        loader = _get_loader()
        groups = loader.list_themes()
        if mode == "custom":
            theme_list = groups.get("User", [])
        else:
            group_name = "Dark" if mode == "dark" else "Light"
            theme_list = groups.get(group_name, [])
        if theme_list:
            first = theme_list[0].get("name", "")
            if first:
                themes.set_theme(first)
                self._set_menu_button_presentation(self._theme_btn, first)

    def _on_theme_menu_requested(self):
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QPixmap, QColor, QIcon
        from AssetsManager.core.themes import _get_loader, theme_mode_for_base
        from AssetsManager.core.ui_scale import scaled_px

        loader = _get_loader()
        groups = loader.list_themes()
        menu = QMenu(self)

        current_theme = themes.name()
        sz = scaled_px(12)

        def _make_icon(accent):
            pixmap = QPixmap(sz, sz)
            pixmap.fill(QColor(accent))
            return QIcon(pixmap)

        if self._current_mode == "custom":
            # Custom mode: show only User themes
            user_themes = groups.get("User", [])
            for td in user_themes:
                name = td.get("name", "")
                accent = td.get("colors", {}).get("accent", "#888")
                action = menu.addAction(_make_icon(accent), name)
                action.setData(name)
                if name == current_theme:
                    action.setCheckable(True)
                    action.setChecked(True)
        else:
            group_name = "Dark" if self._current_mode == "dark" else "Light"
            theme_list = groups.get(group_name, [])
            # Built-in themes
            for td in theme_list:
                name = td.get("name", "")
                accent = td.get("colors", {}).get("accent", "#888")
                action = menu.addAction(_make_icon(accent), name)
                action.setData(name)
                if name == current_theme:
                    action.setCheckable(True)
                    action.setChecked(True)

            # Custom themes for current mode
            user_themes = groups.get("User", [])
            user_in_mode = [
                td for td in user_themes
                if theme_mode_for_base(td.get("colors", {}).get("base", "#1a1a1a")) == self._current_mode
            ]
            if user_in_mode:
                menu.addSeparator()
                for td in user_in_mode:
                    name = td.get("name", "")
                    accent = td.get("colors", {}).get("accent", "#888")
                    action = menu.addAction(_make_icon(accent), name)
                    action.setData(name)
                    if name == current_theme:
                        action.setCheckable(True)
                        action.setChecked(True)

        # Action items
        menu.addSeparator()
        new_action = menu.addAction(tr("settings.new_theme"))
        edit_action = menu.addAction(tr("settings.theme_preview"))
        import_action = menu.addAction(tr("settings.import_theme"))
        delete_action = menu.addAction(tr("settings.delete_theme"))

        is_custom = any(td.get("name") == current_theme for td in user_themes)
        edit_action.setEnabled(is_custom)
        delete_action.setEnabled(is_custom)

        chosen = menu.exec(self._theme_btn.mapToGlobal(self._theme_btn.rect().bottomLeft()))
        if not chosen:
            return

        chosen_name = chosen.data()
        if chosen_name:
            themes.set_theme(chosen_name)
            self._set_menu_button_presentation(self._theme_btn, chosen_name)
        elif chosen == new_action:
            self._on_new_custom_theme_btn()
        elif chosen == edit_action:
            self._on_preview_theme()
        elif chosen == import_action:
            self._import_theme()
        elif chosen == delete_action:
            self._delete_custom_theme_btn()

    def _on_new_custom_theme_btn(self):
        from AssetsManager.core.themes import _get_loader
        loader = _get_loader()

        name, ok = QInputDialog.getText(self, tr("settings.new_theme"), tr("settings.theme_name"))
        if not ok or not name.strip():
            return
        name = name.strip()

        groups = loader.list_themes()
        all_themes = []
        for g in ("Dark", "Light"):
            for td in groups.get(g, []):
                all_themes.append(td.get("name", ""))
        if not all_themes:
            return

        base, ok = QInputDialog.getItem(
            self, tr("settings.base_theme"), tr("settings.select_base"), all_themes, 0, False)
        if not ok:
            return

        if loader.create_custom_theme(name, base):
            themes.reload_themes()
            themes.set_theme(name)
            self._set_menu_button_presentation(self._theme_btn, name)
        else:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.theme_exists"))

    def _on_preview_theme(self):
        from AssetsManager.dialogs.theme_preview_dialog import ThemePreviewDialog
        dlg = ThemePreviewDialog(self)
        dlg.exec()

    def _import_theme(self):
        import json
        import shutil
        from AssetsManager.core.path_resolver import themes_dir
        from AssetsManager.core.themes import _get_loader, theme_mode_for_base

        path, _ = QFileDialog.getOpenFileName(
            self, tr("settings.import_theme"), "",
            "JSON Files (*.json);;All Files (*)")
        if not path:
            return
        try:
            data = json.loads(open(path, encoding="utf-8").read())
            name = data.get("name", "")
            if not name:
                QMessageBox.warning(self, tr("dialog.error"), tr("settings.theme_no_name"))
                return
            loader = _get_loader()
            if loader.get_theme(name):
                QMessageBox.warning(self, tr("dialog.error"), tr("settings.theme_exists"))
                return
            base = data.get("colors", {}).get("base", "#1a1a1a")
            mode = theme_mode_for_base(base)
            prefix = "D_" if mode == "dark" else "L_"
            dest = themes_dir() / f"{prefix}{name.replace(' ', '_')}.json"
            shutil.copy2(path, dest)
            themes.reload_themes()
            themes.set_theme(name)
            self._set_menu_button_presentation(self._theme_btn, name)
        except Exception as e:
            QMessageBox.warning(self, tr("dialog.error"), str(e))

    def _delete_custom_theme_btn(self):
        from PySide6.QtWidgets import QMessageBox
        from AssetsManager.core.themes import _get_loader
        current = themes.name()
        loader = _get_loader()
        if not loader.is_custom_theme(current):
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.cannot_delete_builtin"))
            return
        answer = QMessageBox.question(
            self,
            tr("settings.delete_theme_title"),
            tr("settings.delete_theme_confirm").format(theme=current),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if loader.delete_custom_theme(current):
            themes.reload_themes()
            groups = loader.list_themes()
            group_name = "Dark" if self._current_mode == "dark" else "Light"
            theme_list = groups.get(group_name, [])
            if theme_list:
                first = theme_list[0].get("name", "")
                themes.set_theme(first)
                self._set_menu_button_presentation(self._theme_btn, first)

    def _make_pct_slider(self, start_value):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(30, 100)
        slider.setValue(int(start_value * 100))
        slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        slider.setTickInterval(10)
        return slider

    def _browse_bg_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("settings.bg_browse_title"), "",
            "Media Files (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.mp4 *.webm *.avi);;Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;Videos (*.mp4 *.webm *.avi)")
        if path:
            self._bg_path_edit.setText(path)
            self._on_bg_setting_changed()

    def _clear_bg(self):
        self._bg_path_edit.clear()
        self._bg_enabled_cb.setChecked(False)
        self._on_bg_setting_changed()

    @staticmethod
    def _set_row_visible(row, visible: bool):
        """Toggle visibility of every widget inside a labeled row layout."""
        for i in range(row.count()):
            item = row.itemAt(i)
            if item is not None and item.widget() is not None:
                item.widget().setVisible(visible)

    def _on_bg_setting_changed(self, *_):
        s = AppSettings.instance()
        bg_enabled = self._bg_enabled_cb.isChecked()
        bg_path = self._bg_path_edit.text().strip()

        # If background is enabled but no valid path is set, disable it
        # to prevent black background on next startup
        if bg_enabled and not bg_path:
            bg_enabled = False
            # Block signals to prevent recursion
            from PySide6.QtCore import QSignalBlocker
            with QSignalBlocker(self._bg_enabled_cb):
                self._bg_enabled_cb.setChecked(False)

        s.set("bg_enabled", bg_enabled)
        s.set("bg_image", bg_path)
        s.set("bg_panel_opacity", self._bg_panel_slider.value() / 100.0)
        s.set("bg_header_opacity", self._bg_header_slider.value() / 100.0)
        s.set("bg_effect", self._current_effect)
        s.set("bg_effect_intensity", self._effect_intensity.value())
        s.set("bg_shader_preset", self._shader_preset_combo.currentData() or "plasma")
        s.save()
        themes.invalidate_cache()
        parent = self.parent()
        if isinstance(parent, _BackgroundStyleHost):
            try:
                parent._on_bg_style_changed()
            except Exception:
                pass

    def _on_effect_menu(self):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        none_action = menu.addAction(tr("settings.bg_effect_none"))
        blur_action = menu.addAction(tr("settings.bg_blur"))
        mosaic_action = menu.addAction(tr("settings.bg_mosaic"))
        kuwahara_action = menu.addAction(tr("settings.bg_kuwahara"))
        shader_action = menu.addAction(tr("settings.bg_effect_shader"))
        chosen = menu.exec(self._effect_btn.mapToGlobal(self._effect_btn.rect().bottomLeft()))
        if chosen == none_action:
            self._current_effect = "none"
        elif chosen == blur_action:
            self._current_effect = "blur"
        elif chosen == mosaic_action:
            self._current_effect = "mosaic"
        elif chosen == kuwahara_action:
            self._current_effect = "kuwahara"
        elif chosen == shader_action:
            self._current_effect = "shader"
        else:
            return
        label = {"none": tr("settings.bg_effect_none"), "blur": tr("settings.bg_blur"), "mosaic": tr("settings.bg_mosaic"), "kuwahara": tr("settings.bg_kuwahara"), "shader": tr("settings.bg_effect_shader")}.get(self._current_effect, tr("settings.bg_effect_none"))
        self._set_menu_button_presentation(self._effect_btn, label)
        self._set_row_visible(self._shader_preset_row, self._current_effect == "shader")
        self._on_bg_setting_changed()

    # ── Tab 2: General ────────────────────────────────────

    def _build_general_tab(self):
        from AssetsManager.core.ui_scale import scaled_px
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._general_layout = layout
        layout.setSpacing(scaled_px(int(themes.prop("spacing", "md"))))
        layout.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "sm"))),
            scaled_px(int(themes.prop("spacing", "sm"))),
            scaled_px(int(themes.prop("spacing", "sm"))),
            scaled_px(int(themes.prop("spacing", "sm"))))

        lang_map = i18n.languages()
        lang_opts = {code: lang_map.get(code, code) for code in ("en", "zh", "ja")}
        self._lang_group_box, self._lang_group = self.make_radio_group(
            tr("settings.language"), lang_opts, i18n.current_language(), on_changed=self._on_lang_clicked)
        layout.addWidget(self._lang_group_box)

        # UI Scale
        from AssetsManager.core.ui_scale import get_ui_scale
        self._scale_heading = self.make_heading(tr("settings.ui_scale"))
        layout.addWidget(self._scale_heading)
        self._ui_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._ui_scale_slider.setRange(50, 200)
        self._ui_scale_slider.setValue(int(get_ui_scale() * 100))
        self._ui_scale_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._ui_scale_slider.setTickInterval(25)
        self._ui_scale_slider.valueChanged.connect(self._set_ui_scale)
        layout.addWidget(self._ui_scale_slider)
        self._ui_scale_label = self.make_muted(f"{get_ui_scale() * 100:.0f}%")
        layout.addWidget(self._ui_scale_label)

        self._build_ai_tagging_group(layout)

        layout.addStretch()
        self._add_tab(tab, tr("settings.general"), scrollable=True, label_key="settings.general")

    # ── H2-c: AI tagging group (Ollama local-first) ──────

    def _build_ai_tagging_group(self, layout):
        """Build the "AI Tagging" settings group on the General tab.

        The whole feature stays invisible until ``ai_tagging_enabled`` is
        explicitly switched on; every control persists on change and the
        "Test Connection" button probes the Ollama daemon on a worker
        thread (run_task, the H2-a1 health-card pattern).
        """
        from AssetsManager.core.ui_scale import scaled_px as _px
        settings = AppSettings.instance()

        self._ai_group = self.make_groupbox(tr("settings.ai_group"))
        al = QVBoxLayout(self._ai_group)
        al.setSpacing(_px(6))
        al.setContentsMargins(
            _px(int(themes.prop("spacing", "md"))),
            _px(int(themes.prop("spacing", "md"))),
            _px(int(themes.prop("spacing", "md"))),
            _px(int(themes.prop("spacing", "sm"))))

        self._ai_enable_check = QCheckBox(tr("settings.ai_enable"))
        self._ai_enable_check.setChecked(settings.get_ai_tagging_enabled())
        self._ai_enable_check.toggled.connect(self._on_ai_enabled_toggled)
        al.addWidget(self._ai_enable_check)

        endpoint_row = QHBoxLayout()
        endpoint_row.setSpacing(_px(6))
        self._ai_endpoint_label = QLabel(tr("settings.ai_endpoint"))
        endpoint_row.addWidget(self._ai_endpoint_label)
        self._ai_endpoint_edit = QLineEdit(settings.get_ai_tagging_endpoint())
        self._ai_endpoint_edit.setAccessibleName(tr("settings.ai_endpoint"))
        self._ai_endpoint_edit.editingFinished.connect(self._on_ai_endpoint_edited)
        endpoint_row.addWidget(self._ai_endpoint_edit, 1)
        al.addLayout(endpoint_row)

        model_row = QHBoxLayout()
        model_row.setSpacing(_px(6))
        self._ai_model_label = QLabel(tr("settings.ai_model"))
        model_row.addWidget(self._ai_model_label)
        self._ai_model_edit = QLineEdit(settings.get_ai_tagging_model())
        self._ai_model_edit.setAccessibleName(tr("settings.ai_model"))
        self._ai_model_edit.editingFinished.connect(self._on_ai_model_edited)
        model_row.addWidget(self._ai_model_edit, 1)
        al.addLayout(model_row)

        tags_row = QHBoxLayout()
        tags_row.setSpacing(_px(6))
        self._ai_max_tags_label = QLabel(tr("settings.ai_max_tags"))
        tags_row.addWidget(self._ai_max_tags_label)
        self._ai_max_tags_spin = QSpinBox()
        self._ai_max_tags_spin.setRange(1, AI_TAGGING_MAX_TAGS_LIMIT)
        self._ai_max_tags_spin.setValue(settings.get_ai_tagging_max_tags())
        self._ai_max_tags_spin.setAccessibleName(tr("settings.ai_max_tags"))
        self._ai_max_tags_spin.valueChanged.connect(self._on_ai_max_tags_changed)
        tags_row.addWidget(self._ai_max_tags_spin)
        tags_row.addStretch()
        al.addLayout(tags_row)

        self._ai_force_check = QCheckBox(tr("settings.ai_force_existing"))
        self._ai_force_check.setChecked(settings.get_ai_tagging_force_existing())
        self._ai_force_check.setToolTip(tr("settings.ai_force_existing_tooltip"))
        self._ai_force_check.toggled.connect(self._on_ai_force_toggled)
        al.addWidget(self._ai_force_check)

        action_row = QHBoxLayout()
        action_row.setSpacing(_px(6))
        self._ai_test_btn = self.make_secondary_btn(
            tr("settings.ai_test"), self._on_ai_test_connection)
        action_row.addWidget(self._ai_test_btn)
        action_row.addStretch()
        al.addLayout(action_row)

        self._ai_status = self.make_muted(tr("settings.ai_status_idle"))
        self._ai_status.setWordWrap(True)
        al.addWidget(self._ai_status)

        self._update_ai_rows_enabled()
        layout.addWidget(self._ai_group)

    def _update_ai_rows_enabled(self):
        """Dim the AI controls while the feature is switched off."""
        enabled = self._ai_enable_check.isChecked()
        for widget in (
            self._ai_endpoint_edit, self._ai_model_edit,
            self._ai_max_tags_spin, self._ai_force_check,
            self._ai_test_btn,
        ):
            widget.setEnabled(enabled)

    def _on_ai_enabled_toggled(self, checked: bool) -> None:
        AppSettings.instance().set_ai_tagging_enabled(bool(checked))
        self._update_ai_rows_enabled()

    def _on_ai_endpoint_edited(self) -> None:
        text = self._ai_endpoint_edit.text().strip()
        try:
            AppSettings.instance().set_ai_tagging_endpoint(text)
            self._ai_status.setText(tr("settings.ai_status_saved"))
        except ValueError:
            # Invalid URL: keep the last persisted value in the field and
            # say so — the endpoint must stay an absolute http(s) URL.
            self._ai_endpoint_edit.setText(
                AppSettings.instance().get_ai_tagging_endpoint())
            self._ai_status.setText(tr("settings.ai_endpoint_invalid"))

    def _on_ai_model_edited(self) -> None:
        model = self._ai_model_edit.text().strip() or \
            AppSettings.instance().get_ai_tagging_model()
        AppSettings.instance().set_ai_tagging_model(model)
        self._ai_model_edit.setText(model)
        self._ai_status.setText(tr("settings.ai_status_saved"))

    def _on_ai_max_tags_changed(self, value: int) -> None:
        AppSettings.instance().set_ai_tagging_max_tags(int(value))

    def _on_ai_force_toggled(self, checked: bool) -> None:
        AppSettings.instance().set_ai_tagging_force_existing(bool(checked))

    def _on_ai_test_connection(self) -> None:
        """Probe the Ollama daemon and report the result in the status label."""
        from AssetsManager.panels.file_list._background import run_task
        from AssetsManager.application.ai_tagging.ollama_client import probe
        endpoint = self._ai_endpoint_edit.text().strip() or \
            AppSettings.instance().get_ai_tagging_endpoint()
        self._ai_test_btn.setEnabled(False)
        self._ai_status.setText(tr("settings.ai_status_testing"))

        def _work():
            return probe(endpoint)

        def _done(result, exc):
            self._ai_test_btn.setEnabled(True)
            if exc is not None:
                self._ai_status.setText(tr("settings.ai_test_fail"))
                return
            self._ai_status.setText(
                tr("settings.ai_test_ok") if result else tr("settings.ai_test_fail"))

        run_task(_work, on_done=_done)

    # ── Tab 3: Thumbnails ────────────────────────────────

    def _build_thumbnails_tab(self):
        from AssetsManager.core.ui_scale import scaled_px
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._thumbnails_layout = layout
        layout.setSpacing(scaled_px(int(themes.prop("spacing", "md"))))
        layout.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "sm"))),
            scaled_px(int(themes.prop("spacing", "sm"))),
            scaled_px(int(themes.prop("spacing", "sm"))),
            scaled_px(int(themes.prop("spacing", "sm"))))

        current_quality = AppSettings.instance().get("thumb_quality", "default")
        quality_labels = {
            "fast": tr("settings.thumb_quality_fast"), "default": tr("settings.thumb_quality_default"),
            "high": tr("settings.thumb_quality_high"), "original": tr("settings.thumb_quality_original"),
        }
        thumb_opts = {k: quality_labels[k] for k in ("fast", "default", "high", "original")}
        self._thumb_group_box, self._thumb_group = self.make_radio_group(
            tr("settings.thumb_quality"), thumb_opts, current_quality, on_changed=self._on_thumb_quality_clicked)
        layout.addWidget(self._thumb_group_box)

        self._cache_group = self.make_groupbox(tr("settings.thumb_cache"))

        cl = QVBoxLayout(self._cache_group)
        self._cache_layout = cl
        cl.setSpacing(scaled_px(6))
        cl.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "sm"))))

        self._clear_btn = self.make_secondary_btn(tr("settings.thumb_clear"), self._clear_thumbnails)
        cl.addWidget(self._clear_btn)

        self._regen_btn = self.make_secondary_btn(tr("settings.thumb_regenerate"), self._regenerate_thumbnails)
        cl.addWidget(self._regen_btn)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setTextVisible(True)
        cl.addWidget(self._progress)

        self._progress_signals = _ProgressSignals(self)
        self._progress_signals.updated.connect(self._on_progress)
        self._progress_signals.finished.connect(self._on_regenerate_done)
        self._progress_signals.clear_progress.connect(self._on_clear_progress)
        self._progress_signals.cleared.connect(self._on_clear_done)

        layout.addWidget(self._cache_group)
        layout.addStretch()
        self._add_tab(tab, tr("settings.thumbnails"), scrollable=True, label_key="settings.thumbnails")

    # ── Tab 4: Database maintenance ─────────────────────────

    def _build_maintenance_tab(self):
        from AssetsManager.core.ui_scale import scaled_px
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._maintenance_layout = layout
        layout.setSpacing(scaled_px(int(themes.prop("spacing", "md"))))
        layout.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "sm"))),
            scaled_px(int(themes.prop("spacing", "sm"))),
            scaled_px(int(themes.prop("spacing", "sm"))),
            scaled_px(int(themes.prop("spacing", "sm"))))

        self._maintenance_group = self.make_groupbox(tr("settings.maintenance_title"))
        gl = QVBoxLayout(self._maintenance_group)
        self._maintenance_group_layout = gl
        gl.setSpacing(scaled_px(6))
        gl.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "sm"))))

        self._run_checkpoint_btn = self.make_secondary_btn(
            tr("settings.maintenance_run_checkpoint"), self._on_run_checkpoint)
        gl.addWidget(self._run_checkpoint_btn)

        self._read_size_btn = self.make_secondary_btn(
            tr("settings.maintenance_read_size"), self._on_read_size)
        gl.addWidget(self._read_size_btn)

        self._integrity_btn = self.make_secondary_btn(
            tr("settings.maintenance_run_integrity"), self._on_run_integrity)
        gl.addWidget(self._integrity_btn)

        self._integrity_status = self.make_muted(tr("settings.maintenance_integrity_idle"))
        self._integrity_status.setWordWrap(True)
        gl.addWidget(self._integrity_status)

        self._maintenance_status = self.make_muted(tr("settings.maintenance_idle"))
        self._maintenance_status.setWordWrap(True)
        gl.addWidget(self._maintenance_status)

        layout.addWidget(self._maintenance_group)

        # ── H2-a1: library health card ─────────────────────
        # Scale observation surface: sizes/counts collected on a worker
        # thread (run_task, the same primitive the maintenance runner uses)
        # so a large library never blocks the GUI during a refresh.
        self._health_group = self.make_groupbox(tr("settings.health_title"))
        hl = QVBoxLayout(self._health_group)
        self._health_group_layout = hl
        hl.setSpacing(scaled_px(6))
        hl.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "sm"))))

        self._health_refresh_btn = self.make_secondary_btn(
            tr("settings.health_refresh"), self._on_refresh_health)
        hl.addWidget(self._health_refresh_btn)

        self._health_status = self.make_muted(tr("settings.health_idle"))
        self._health_status.setWordWrap(True)
        hl.addWidget(self._health_status)

        self._health_open_dir_btn = self.make_secondary_btn(
            tr("settings.health_open_data_dir"), self._on_open_data_dir)
        hl.addWidget(self._health_open_dir_btn)

        # H2-a3: manual retention pass over the per-library activity_log.
        self._health_prune_btn = self.make_secondary_btn(
            tr("settings.health_prune"), self._on_prune_activity)
        hl.addWidget(self._health_prune_btn)

        layout.addWidget(self._health_group)

        # ── H2-a2: thumbnail cache capacity cap ────────────
        self._thumb_cap_group = self.make_groupbox(tr("settings.thumb_cap_group"))
        cl = QVBoxLayout(self._thumb_cap_group)
        self._thumb_cap_group_layout = cl
        cl.setSpacing(scaled_px(6))
        cl.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "sm"))))

        cap_row = QHBoxLayout()
        cap_row.setSpacing(scaled_px(6))
        self._thumb_cap_label = QLabel(tr("settings.thumb_cap_label"))
        cap_row.addWidget(self._thumb_cap_label)
        self._thumb_cap_combo = QComboBox()
        for gb in (1, 2, 5, 10):
            self._thumb_cap_combo.addItem(
                tr("settings.thumb_cap_gb", gb=gb), userData=gb * 1024 ** 3)
        self._thumb_cap_combo.addItem(tr("settings.thumb_cap_unlimited"), userData=0)
        current_cap = AppSettings.instance().get_thumbnail_cache_max_bytes()
        cap_index = self._thumb_cap_combo.findData(current_cap)
        if cap_index < 0:
            cap_index = self._thumb_cap_combo.findData(
                THUMBNAIL_CACHE_DEFAULT_MAX_BYTES)
        with QSignalBlocker(self._thumb_cap_combo):
            self._thumb_cap_combo.setCurrentIndex(max(cap_index, 0))
        self._thumb_cap_combo.currentIndexChanged.connect(self._on_thumb_cap_changed)
        cap_row.addWidget(self._thumb_cap_combo, 1)
        cl.addLayout(cap_row)

        self._thumb_evict_btn = self.make_secondary_btn(
            tr("settings.thumb_cap_evict"), self._on_evict_to_cap)
        cl.addWidget(self._thumb_evict_btn)

        self._thumb_cap_status = self.make_muted(tr("settings.thumb_cap_idle"))
        self._thumb_cap_status.setWordWrap(True)
        cl.addWidget(self._thumb_cap_status)

        layout.addWidget(self._thumb_cap_group)

        # ── H2-b: broken-link (relink) card ─────────────────
        # Files moved outside the app leave tags/notes/ratings orphaned on
        # the dead path. The scan walks the library on a worker thread
        # (run_task, the H2-a1 health-card pattern) and pairs lost metadata
        # rows with newcomer files; relinking then runs the same core
        # metadata migration the in-app move uses. Low-confidence pairs are
        # never batch-applied: no "relink all (low)" button exists.
        self._relink_group = self.make_groupbox(tr("settings.relink_title"))
        rl = QVBoxLayout(self._relink_group)
        self._relink_group_layout = rl
        rl.setSpacing(scaled_px(6))
        rl.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "sm"))))

        self._relink_scan_btn = self.make_secondary_btn(
            tr("settings.relink_scan"), self._on_scan_relink)
        rl.addWidget(self._relink_scan_btn)

        self._relink_status = self.make_muted(tr("settings.relink_idle"))
        self._relink_status.setWordWrap(True)
        rl.addWidget(self._relink_status)

        self._relink_all_btn = self.make_secondary_btn(
            tr("settings.relink_relink_all"), self._on_relink_all_high)
        self._relink_all_btn.setVisible(False)
        rl.addWidget(self._relink_all_btn)

        self._relink_list = QListWidget()
        self._relink_list.setVisible(False)
        rl.addWidget(self._relink_list, 1)

        self._relink_suggestions: list = []
        self._relink_last_action = ""

        layout.addWidget(self._relink_group)

        layout.addStretch()
        self._add_tab(tab, tr("settings.maintenance_title"), scrollable=True,
                      label_key="settings.maintenance_title")
        self._refresh_maintenance_status()

    # ── Tab 5: Backup & restore (G6-1 product entry) ────────

    def _build_backup_tab(self):
        from AssetsManager.core.ui_scale import scaled_px
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._backup_layout = layout
        layout.setSpacing(scaled_px(int(themes.prop("spacing", "md"))))
        layout.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "sm"))),
            scaled_px(int(themes.prop("spacing", "sm"))),
            scaled_px(int(themes.prop("spacing", "sm"))),
            scaled_px(int(themes.prop("spacing", "sm"))))

        self._backup_group = self.make_groupbox(tr("settings.backup_title"))
        gl = QVBoxLayout(self._backup_group)
        gl.setSpacing(scaled_px(6))
        gl.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "sm"))))

        self._export_btn = self.make_secondary_btn(
            tr("settings.backup_export_metadata"), self._on_export_metadata)
        gl.addWidget(self._export_btn)

        self._backup_btn = self.make_secondary_btn(
            tr("settings.backup_create"), self._on_create_backup)
        gl.addWidget(self._backup_btn)

        self._restore_btn = self.make_secondary_btn(
            tr("settings.backup_restore"), self._on_restore_backup)
        gl.addWidget(self._restore_btn)

        self._backup_status = self.make_muted(tr("settings.backup_idle"))
        self._backup_status.setWordWrap(True)
        gl.addWidget(self._backup_status)

        layout.addWidget(self._backup_group)

        self._quarantine_group = self.make_groupbox(tr("settings.backup_quarantine"))
        ql = QVBoxLayout(self._quarantine_group)
        ql.setSpacing(scaled_px(6))
        ql.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "sm"))))
        self._quarantine_status = self.make_muted(tr("settings.backup_quarantine_empty"))
        self._quarantine_status.setWordWrap(True)
        ql.addWidget(self._quarantine_status)
        layout.addWidget(self._quarantine_group)

        layout.addStretch()
        self._add_tab(tab, tr("settings.backup_title"), scrollable=True,
                      label_key="settings.backup_title")
        self._refresh_backup_status()

    def _on_export_metadata(self):
        adapter = self.library_settings_adapter
        if adapter is None:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.error_no_library"))
            return
        default = str(adapter.library_root / "metadata-export.json")
        destination, _selected = QFileDialog.getSaveFileName(
            self, tr("settings.backup_export_metadata"), default, "JSON (*.json)")
        if not destination:
            return
        try:
            result = adapter.export_metadata(destination)
            self._backup_status.setText(tr(
                "settings.backup_export_done",
                path=getattr(result, "destination", destination),
            ))
        except Exception as exc:
            QMessageBox.warning(self, tr("dialog.error"), str(exc))

    def _on_create_backup(self):
        adapter = self.library_settings_adapter
        if adapter is None:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.error_no_library"))
            return
        default = str(adapter.library_root / "assetmanager-backup.zip")
        destination, _selected = QFileDialog.getSaveFileName(
            self, tr("backup.choose_destination"), default, tr("backup.file_filter"))
        if not destination:
            return
        # GB-scale IO: run on a worker thread behind the shared busy dialog
        # (same contract as the main-window backup entry point).
        self._ensure_maintenance_runner().run(
            lambda: adapter.create_backup(destination),
            title=tr("backup.title"),
            busy_text=tr("backup.in_progress"),
            reentry_text=tr("maintenance.task_running"),
            disable=(self._export_btn, self._backup_btn, self._restore_btn),
            on_success=self._on_create_backup_success,
            on_error=lambda exc: QMessageBox.critical(
                self, tr("backup.title"), tr("backup.failed").format(error=exc)),
        )

    def _on_create_backup_success(self, result):
        self._backup_status.setText(tr(
            "settings.backup_create_done", path=result.destination))

    def _on_restore_backup(self):
        adapter = self.library_settings_adapter
        if adapter is None:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.error_no_library"))
            return
        vm = adapter.view_model()
        if not vm.restore_allowed:
            QMessageBox.warning(
                self, tr("restore.title"), tr("settings.backup_restore_blocked"))
            return
        archive, _selected = QFileDialog.getOpenFileName(
            self, tr("restore.choose_archive"), str(adapter.library_root.parent),
            tr("restore.file_filter"))
        if not archive:
            return
        answer = QMessageBox.warning(
            self, tr("restore.title"), tr("restore.confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        # Restore replaces the RuntimeData directory on disk; run it on a
        # worker thread.  The session the adapter was built from is already
        # closed (restore_allowed), and settings.backup_restore_done plus
        # the library list are refreshed by the caller reopening it.
        self._ensure_maintenance_runner().run(
            lambda: adapter.restore_backup(archive, overwrite_existing=True),
            title=tr("restore.title"),
            busy_text=tr("restore.in_progress"),
            reentry_text=tr("maintenance.task_running"),
            disable=(self._export_btn, self._backup_btn, self._restore_btn),
            on_success=self._on_restore_backup_success,
            on_error=lambda exc: QMessageBox.critical(
                self, tr("restore.title"), tr("restore.failed").format(error=exc)),
        )

    def _on_restore_backup_success(self, result):
        self._backup_status.setText(tr(
            "settings.backup_restore_done", path=result.data_dir))

    def _refresh_backup_status(self):
        status = self._backup_status
        runner = getattr(self, "_maintenance_runner", None)
        if runner is not None and runner.is_busy:
            # A backup/restore task is in flight: the buttons were disabled
            # by the runner and must not be re-enabled by an event refresh.
            return
        adapter = self.library_settings_adapter
        if adapter is None:
            status.setText(tr("settings.error_no_library"))
            self._export_btn.setEnabled(False)
            self._backup_btn.setEnabled(False)
            self._restore_btn.setEnabled(False)
            self._quarantine_status.setText(tr("settings.backup_quarantine_empty"))
            return
        vm = adapter.view_model()
        self._export_btn.setEnabled(True)
        self._backup_btn.setEnabled(True)
        self._restore_btn.setEnabled(vm.restore_allowed)
        if vm.restore_allowed:
            status.setText(tr("settings.backup_restore_ready"))
        else:
            status.setText(tr("settings.backup_restore_blocked"))
        try:
            entries = adapter.list_restore_quarantine()
        except Exception:
            entries = ()
        if not entries:
            self._quarantine_status.setText(tr("settings.backup_quarantine_empty"))
        else:
            lines = [f"{entry.name or entry.path} — {entry.modified_at}" for entry in entries[:10]]
            self._quarantine_status.setText("\n".join(lines))

    # ── Tab 6: Plugins ─────────────────────────────────────────

    def _build_plugins_tab(self):
        from AssetsManager.dialogs._plugin_manager_widget import PluginManagerWidget

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "sm"))))
        layout.setSpacing(scaled_px(int(themes.prop("spacing", "md"))))

        self._plugin_widget = PluginManagerWidget()
        layout.addWidget(self._plugin_widget, 1)

        self._add_tab(tab, tr("settings.plugins_title", default="Plugins"),
                      scrollable=False, label_key="settings.plugins_title")

    def _on_run_checkpoint(self):
        adapter = self.library_settings_adapter
        if adapter is None:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.error_no_library"))
            return
        try:
            adapter.start_wal_checkpoint()
        except Exception as exc:
            QMessageBox.warning(self, tr("dialog.error"), str(exc))
        self._refresh_maintenance_status()

    def _on_read_size(self):
        adapter = self.library_settings_adapter
        if adapter is None:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.error_no_library"))
            return
        try:
            result = adapter.read_database_size()
        except Exception as exc:
            QMessageBox.warning(self, tr("dialog.error"), str(exc))
            return
        self._maintenance_status.setText(self._format_result_text(result))

    def _on_run_integrity(self):
        adapter = self.library_settings_adapter
        if adapter is None:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.error_no_library"))
            return
        try:
            adapter.start_integrity_check()
        except Exception as exc:
            QMessageBox.warning(self, tr("dialog.error"), str(exc))
        self._refresh_maintenance_status()

    # ── H2-a1: library health card ────────────────────────────

    def _on_refresh_health(self):
        adapter = self.library_settings_adapter
        if adapter is None:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.error_no_library"))
            return
        self._health_refresh_btn.setEnabled(False)
        self._health_status.setText(tr("settings.health_collecting"))
        # Directory walks + read-only counts: collect off the GUI thread and
        # let the queued completion (run_task) deliver the snapshot back.
        from AssetsManager.panels.file_list._background import run_task

        run_task(adapter.collect_health_snapshot, on_done=self._on_health_collected)

    def _on_health_collected(self, result, exc):
        adapter = self.library_settings_adapter
        runner = getattr(self, "_maintenance_runner", None)
        busy = runner is not None and runner.is_busy
        if adapter is not None and not busy:
            self._health_refresh_btn.setEnabled(True)
        if exc is not None:
            self._health_status.setText(tr("settings.health_failed", error=exc))
            return
        self._render_health(result)

    def _render_health(self, snapshot):
        """Render one health snapshot as colored per-metric rows."""
        warning_color = themes.color("warning")
        warnings = tuple(getattr(snapshot, "warnings", ()) or ())

        def row(text: str, warn: bool) -> str:
            if warn:
                return f'<span style="color:{warning_color};">{text}</span>'
            return text

        db_size = (
            self._format_bytes(snapshot.db_bytes)
            if snapshot.db_bytes is not None else "—"
        )
        wal_size = (
            self._format_bytes(snapshot.wal_bytes)
            if snapshot.wal_bytes is not None else "—"
        )
        lines = [
            row(tr("settings.health_db", size=db_size, wal=wal_size),
                "wal" in warnings),
            row(tr("settings.health_thumbs",
                   size=self._format_bytes(snapshot.thumbnail_bytes),
                   files=snapshot.thumbnail_files),
                "thumbnail_cache" in warnings),
            row(tr("settings.health_derivatives",
                   size=self._format_bytes(snapshot.derivatives_bytes),
                   files=snapshot.derivatives_files),
                False),
        ]
        if snapshot.activity_rows is None:
            lines.append(tr(
                "settings.health_activity_empty",
                days=ACTIVITY_RETENTION_DAYS))
        else:
            age = (
                "—"
                if snapshot.activity_oldest_age_days is None
                else f"{snapshot.activity_oldest_age_days:.1f}"
            )
            lines.append(tr(
                "settings.health_activity",
                rows=snapshot.activity_rows, age=age,
                days=ACTIVITY_RETENTION_DAYS))
        if snapshot.favorites_count is not None:
            lines.append(tr("settings.health_favorites", count=snapshot.favorites_count))
        if snapshot.asset_rows is not None:
            lines.append(tr("settings.health_assets", rows=snapshot.asset_rows))
        self._health_status.setText("<br>".join(lines))

    def _on_open_data_dir(self):
        adapter = self.library_settings_adapter
        if adapter is None:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        data_dir = Path(adapter.library_data_dir)
        # The button is enabled only while the directory exists (refreshed
        # with the maintenance status), but re-check before launching: the
        # slot directory can disappear under a restore/switch.
        if not data_dir.is_dir():
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir)))

    # ── H2-a2: thumbnail cache capacity cap ───────────────────

    def _current_thumb_cap_bytes(self) -> int:
        data = self._thumb_cap_combo.currentData()
        return int(data) if isinstance(data, int) else THUMBNAIL_CACHE_DEFAULT_MAX_BYTES

    def _on_thumb_cap_changed(self, _index: int):
        AppSettings.instance().set_thumbnail_cache_max_bytes(
            self._current_thumb_cap_bytes())
        AppSettings.instance().save()
        self._update_thumb_cap_buttons()

    def _update_thumb_cap_buttons(self):
        """The evict button needs an adapter and a configured (non-zero) cap."""
        adapter = self.library_settings_adapter
        self._thumb_evict_btn.setEnabled(
            adapter is not None and self._current_thumb_cap_bytes() > 0)

    def _on_evict_to_cap(self):
        adapter = self.library_settings_adapter
        if adapter is None:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.error_no_library"))
            return
        max_bytes = self._current_thumb_cap_bytes()
        if max_bytes <= 0:
            return
        # Candidate scan + per-artifact unlink is GB-scale IO: reuse the
        # E-C maintenance task async mode (worker thread + busy dialog +
        # re-entry guard).
        self._ensure_maintenance_runner().run(
            lambda: adapter.enforce_thumbnail_capacity(max_bytes),
            title=tr("settings.thumb_cap_group"),
            busy_text=tr("settings.thumb_cap_running"),
            reentry_text=tr("maintenance.task_running"),
            disable=(self._thumb_evict_btn, self._health_refresh_btn),
            on_success=self._on_evict_to_cap_success,
            on_error=lambda exc: QMessageBox.warning(
                self, tr("dialog.error"),
                tr("settings.thumb_cap_error", error=exc)),
        )

    def _on_evict_to_cap_success(self, result):
        evicted, reclaimed = result
        self._thumb_cap_status.setText(tr(
            "settings.thumb_cap_done",
            count=evicted, size=self._format_bytes(reclaimed)))

    # ── H2-a3: activity log retention ─────────────────────────

    def _on_prune_activity(self):
        adapter = self.library_settings_adapter
        if adapter is None:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.error_no_library"))
            return
        # A large log can hold millions of rows: run the delete through the
        # shared maintenance runner (worker thread + busy dialog + re-entry
        # guard) instead of blocking the GUI.
        self._ensure_maintenance_runner().run(
            adapter.prune_activity_log,
            title=tr("settings.health_title"),
            busy_text=tr("settings.health_prune_running"),
            reentry_text=tr("maintenance.task_running"),
            disable=(self._health_prune_btn, self._health_refresh_btn),
            on_success=self._on_prune_activity_success,
            on_error=lambda exc: QMessageBox.warning(
                self, tr("dialog.error"),
                tr("settings.health_prune_error", error=exc)),
        )

    def _on_prune_activity_success(self, deleted):
        self._health_status.setText(
            tr("settings.health_prune_done", count=deleted))

    # ── H2-b: broken-link (relink) card ───────────────────────

    def _on_scan_relink(self):
        adapter = self.library_settings_adapter
        if adapter is None:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.error_no_library"))
            return
        self._set_relink_busy(True)
        self._relink_status.setText(tr("settings.relink_scanning"))
        # Full directory walk + read-only SQL: collect off the GUI thread and
        # let the queued completion (run_task) deliver the report back — the
        # same async mode as the health card refresh above.
        from AssetsManager.panels.file_list._background import run_task

        run_task(adapter.scan_relink, on_done=self._on_relink_scanned)

    def _on_relink_scanned(self, report, exc):
        if exc is not None:
            self._set_relink_busy(False)
            self._relink_status.setText(tr("settings.relink_failed", error=exc))
            return
        self._render_relink_report(report)

    def _render_relink_report(self, report):
        """Render one RelinkReport as capped result rows + status summary."""
        self._set_relink_busy(False)
        self._relink_list.clear()
        self._relink_suggestions = []
        prefix = self._relink_last_action
        self._relink_last_action = ""
        if not report.lost and not report.newcomers:
            self._relink_status.setText(
                (prefix + " " if prefix else "") + tr("settings.relink_clean"))
            self._relink_list.setVisible(False)
            self._relink_all_btn.setVisible(False)
            return

        rows: list[tuple[str, object]] = [
            ("pair", suggestion) for suggestion in report.suggestions
        ]
        rows.extend(("lost", entry) for entry in report.unpaired_lost)
        for kind, payload in rows[:_RELINK_ROW_LIMIT]:
            if kind == "pair":
                suggestion = payload
                badge = (
                    tr("settings.relink_confidence_high")
                    if suggestion.confidence == "high"
                    else tr("settings.relink_confidence_low"))
                text = (f"{suggestion.lost.file_path}  →  "
                        f"{suggestion.newcomer.file_path}  ·  {badge}")
                row = _RelinkRowWidget(
                    text,
                    on_relink=lambda checked=False, s=suggestion:
                        self._on_relink_one(s))
                self._relink_suggestions.append(suggestion)
            else:
                text = f"{payload.file_path}"
                row = _RelinkRowWidget(
                    f"{payload.file_path}  ·  {tr('settings.relink_no_suggestion')}")
            item = QListWidgetItem(text)
            self._relink_list.addItem(item)
            self._relink_list.setItemWidget(item, row)

        parts = [prefix] if prefix else []
        parts.append(tr(
            "settings.relink_summary",
            lost=len(report.lost),
            newcomers=len(report.newcomers),
            pairs=len(report.suggestions)))
        if report.truncated:
            parts.append(tr("settings.relink_truncated"))
        if len(rows) > _RELINK_ROW_LIMIT:
            parts.append(tr("settings.relink_capped", limit=_RELINK_ROW_LIMIT))
        self._relink_status.setText(" ".join(parts))

        high_count = sum(
            1 for suggestion in report.suggestions
            if suggestion.confidence == "high")
        self._relink_all_btn.setVisible(high_count > 0)
        self._relink_all_btn.setEnabled(high_count > 0)
        self._relink_list.setVisible(True)

    def _on_relink_one(self, suggestion):
        adapter = self.library_settings_adapter
        if adapter is None:
            return
        self._set_relink_busy(True)
        from AssetsManager.panels.file_list._background import run_task

        run_task(
            lambda: adapter.relink_file(
                suggestion.lost.file_path, suggestion.newcomer.file_path),
            on_done=lambda result, exc: self._on_relink_done(
                1 if result else 0, exc),
        )

    def _on_relink_all_high(self):
        adapter = self.library_settings_adapter
        if adapter is None:
            return
        # Semantic safety: only high-confidence pairs are batch-applied.
        # Low-confidence suggestions stay per-row and must be confirmed one
        # by one; no "relink all (low)" entry exists anywhere.
        high = [s for s in self._relink_suggestions if s.confidence == "high"]
        if not high:
            return
        self._set_relink_busy(True)

        def _relink_all():
            relinked = 0
            first_error = None
            for suggestion in high:
                try:
                    if adapter.relink_file(
                            suggestion.lost.file_path,
                            suggestion.newcomer.file_path):
                        relinked += 1
                except Exception as exc:  # noqa: BLE001 — reported per batch
                    if first_error is None:
                        first_error = exc
            return relinked, first_error

        from AssetsManager.panels.file_list._background import run_task

        run_task(_relink_all, on_done=self._on_relink_all_done)

    def _on_relink_all_done(self, result, exc):
        if exc is not None:
            self._relink_last_action = ""
            self._set_relink_busy(False)
            self._relink_status.setText(tr("settings.relink_failed", error=exc))
            return
        relinked, first_error = result
        if first_error is not None:
            self._relink_last_action = tr(
                "settings.relink_failed", error=first_error)
        else:
            self._relink_last_action = tr("settings.relink_done", count=relinked)
        # Every applied action re-runs the scan so the list reflects reality.
        self._on_scan_relink()

    def _on_relink_done(self, count, exc):
        if exc is not None:
            self._relink_last_action = ""
            self._set_relink_busy(False)
            self._relink_status.setText(tr("settings.relink_failed", error=exc))
            return
        self._relink_last_action = tr("settings.relink_done", count=count)
        self._on_scan_relink()

    def _set_relink_busy(self, busy: bool):
        """Disable relink affordances while a scan or relink task runs."""
        enabled = self.library_settings_adapter is not None and not busy
        self._relink_scan_btn.setEnabled(enabled)
        # isVisibleTo: the maintenance tab is not necessarily the current
        # tab, plain isVisible() would always be False there.
        self._relink_all_btn.setEnabled(
            enabled and self._relink_all_btn.isVisibleTo(self))
        for row in range(self._relink_list.count()):
            widget = self._relink_list.itemWidget(self._relink_list.item(row))
            button = getattr(widget, "relink_button", None)
            if button is not None:
                button.setEnabled(enabled)

    def _refresh_maintenance_status(self):
        """Pull the adapter view model and render the maintenance state."""
        status = self._maintenance_status
        adapter = self.library_settings_adapter
        if adapter is None:
            status.setText(tr("settings.error_no_library"))
            self._run_checkpoint_btn.setEnabled(False)
            self._read_size_btn.setEnabled(False)
            self._integrity_btn.setEnabled(False)
            self._integrity_status.setText(tr("settings.error_no_library"))
            self._health_refresh_btn.setEnabled(False)
            self._health_open_dir_btn.setEnabled(False)
            self._health_prune_btn.setEnabled(False)
            self._thumb_evict_btn.setEnabled(False)
            self._relink_scan_btn.setEnabled(False)
            self._relink_all_btn.setEnabled(False)
            return
        vm = adapter.view_model()
        self._run_checkpoint_btn.setEnabled(not vm.maintenance_running)
        self._read_size_btn.setEnabled(not vm.maintenance_running)
        self._integrity_btn.setEnabled(not vm.integrity_running)
        if vm.integrity_running:
            self._integrity_status.setText(tr("settings.maintenance_integrity_running"))
        elif vm.integrity_schedule_error:
            self._integrity_status.setText(tr(
                "settings.maintenance_integrity_error", error=vm.integrity_schedule_error))
        elif vm.integrity_error:
            self._integrity_status.setText(tr(
                "settings.maintenance_integrity_error", error=vm.integrity_error))
        elif vm.integrity_report is not None:
            self._integrity_status.setText(tr("settings.maintenance_integrity_ok"))
        else:
            self._integrity_status.setText(tr("settings.maintenance_integrity_idle"))
        if vm.maintenance_running:
            status.setText(tr("settings.maintenance_running"))
        elif vm.maintenance_schedule_error:
            status.setText(tr(
                "settings.maintenance_schedule_error", error=vm.maintenance_schedule_error))
        elif vm.maintenance_error:
            status.setText(tr("settings.maintenance_error", error=vm.maintenance_error))
        elif vm.maintenance_result is not None:
            status.setText(self._format_result_text(vm.maintenance_result))
        else:
            status.setText(tr("settings.maintenance_idle"))
        # Health card affordances: refresh needs a live adapter and the
        # data-dir button additionally requires the directory to still exist.
        self._health_refresh_btn.setEnabled(True)
        self._health_prune_btn.setEnabled(True)
        try:
            data_dir_ok = Path(adapter.library_data_dir).is_dir()
        except OSError:
            data_dir_ok = False
        self._health_open_dir_btn.setEnabled(data_dir_ok)
        # Thumbnail-cap button only makes sense with a configured (non-zero)
        # cap; "unlimited" has nothing to enforce down to.
        self._thumb_evict_btn.setEnabled(self._current_thumb_cap_bytes() > 0)
        # Relink scan affordance follows the live adapter; the batch button
        # stays governed by the last scan result (high-confidence pairs).
        self._relink_scan_btn.setEnabled(True)

    @staticmethod
    def _format_result_text(result) -> str:
        error = getattr(result, "error", None)
        if error:
            return tr("settings.maintenance_error", error=error)
        size_bytes = getattr(result, "size_bytes", None)
        if size_bytes is not None:
            return tr("settings.maintenance_db_size",
                      size=SettingsDialog._format_bytes(size_bytes))
        checkpointed = getattr(result, "checkpointed_frames", None)
        if checkpointed is not None:
            return tr("settings.maintenance_checkpoint_done",
                      checkpointed=checkpointed,
                      log=getattr(result, "log_frames", 0),
                      busy=getattr(result, "busy", 0))
        if getattr(result, "success", True):
            return tr("settings.maintenance_done")
        return tr("settings.maintenance_error", error=str(result))

    @staticmethod
    def _format_bytes(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024:
                if unit == "B":
                    return f"{int(value)} B"
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"

    def _ensure_maintenance_subscription(self):
        if self._maintenance_subscription is not None:
            return
        from AssetsManager.domain.events import MaintenanceChanged
        # Queued Qt bridge: MaintenanceChanged is published from worker
        # threads (integrity-check workers / LAN), so the raw weak
        # subscription would run _on_maintenance_event on the publishing
        # thread. The bridge re-emits through a queued signal so the slot
        # always runs on the dialog's (GUI) thread. Closed via
        # _on_dialog_closed.
        self._maintenance_subscription = DomainEventSubscription(
            MaintenanceChanged, self._on_maintenance_event, self)

    def _on_dialog_closed(self):
        """Unsubscribe from the global event bus on every close path."""
        if self._maintenance_subscription is not None:
            self._maintenance_subscription.close()
            self._maintenance_subscription = None

    def _on_maintenance_event(self, event):
        adapter = self.library_settings_adapter
        if adapter is None:
            return
        if getattr(event, "session_token", "") != adapter.session_token:
            return
        self._refresh_maintenance_status()

    def showEvent(self, event):
        self._ensure_maintenance_subscription()
        super().showEvent(event)

    def _on_lang_clicked(self, key):
        i18n.set_language(key)

    def _set_ui_scale(self, val):
        scale = val / 100.0
        AppSettings.instance().set("ui_scale", scale)
        AppSettings.instance().save()
        self._ui_scale_label.setText(f"{val:.0f}%")
        bus().ui_scale_changed.emit(scale)

    def retranslate_ui(self):
        self.setWindowTitle(tr("settings.title"))
        self._theme_heading.setText(tr("settings.theme"))
        self._background_heading.setText(tr("settings.background"))
        self._effects_heading.setText(tr("settings.bg_effects"))
        self._bg_enabled_cb.setText(tr("settings.bg_enabled"))
        self._bg_image_label.setText(tr("settings.bg_image"))
        self._bg_browse_btn.setText(tr("dialog.browse"))
        self._bg_path_edit.setPlaceholderText(tr("settings.bg_placeholder"))
        self._bg_panel_label.setText(tr("settings.bg_panel_opacity"))
        self._bg_header_label.setText(tr("settings.bg_header_opacity"))
        self._clear_bg_btn.setText(tr("settings.bg_clear"))
        self._lang_group_box.setTitle(tr("settings.language"))
        for button in self._lang_group.buttons():
            key = cast(str, button.property("option_key"))
            button.setText(i18n.languages().get(key, key))
        self._scale_heading.setText(tr("settings.ui_scale"))
        self._thumb_group_box.setTitle(tr("settings.thumb_quality"))
        self._cache_group.setTitle(tr("settings.thumb_cache"))
        self._clear_btn.setText(tr("settings.thumb_clear"))
        self._regen_btn.setText(tr("settings.thumb_regenerate"))
        self._maintenance_group.setTitle(tr("settings.maintenance_title"))
        self._run_checkpoint_btn.setText(tr("settings.maintenance_run_checkpoint"))
        self._read_size_btn.setText(tr("settings.maintenance_read_size"))
        self._health_group.setTitle(tr("settings.health_title"))
        self._health_refresh_btn.setText(tr("settings.health_refresh"))
        self._health_open_dir_btn.setText(tr("settings.health_open_data_dir"))
        self._health_prune_btn.setText(tr("settings.health_prune"))
        self._thumb_cap_group.setTitle(tr("settings.thumb_cap_group"))
        self._thumb_cap_label.setText(tr("settings.thumb_cap_label"))
        self._thumb_evict_btn.setText(tr("settings.thumb_cap_evict"))
        self._relink_group.setTitle(tr("settings.relink_title"))
        self._relink_scan_btn.setText(tr("settings.relink_scan"))
        self._relink_all_btn.setText(tr("settings.relink_relink_all"))
        for _row in range(self._relink_list.count()):
            _widget = self._relink_list.itemWidget(self._relink_list.item(_row))
            _button = getattr(_widget, "relink_button", None)
            if _button is not None:
                _button.setText(tr("settings.relink_row_action"))
        for _i in range(self._thumb_cap_combo.count()):
            data = self._thumb_cap_combo.itemData(_i)
            if isinstance(data, int) and data > 0:
                self._thumb_cap_combo.setItemText(
                    _i, tr("settings.thumb_cap_gb", gb=data // (1024 ** 3)))
            else:
                self._thumb_cap_combo.setItemText(_i, tr("settings.thumb_cap_unlimited"))
        mode_label = {
            "dark": tr("settings.dark_mode"), "light": tr("settings.light_mode"),
            "custom": tr("settings.custom_themes"),
        }.get(self._current_mode, self._current_mode)
        self._set_menu_button_presentation(self._mode_btn, mode_label)
        effect_label = {
            "none": tr("settings.bg_effect_none"), "blur": tr("settings.bg_blur"),
            "mosaic": tr("settings.bg_mosaic"), "kuwahara": tr("settings.bg_kuwahara"),
            "shader": tr("settings.bg_effect_shader"),
        }.get(self._current_effect, tr("settings.bg_effect_none"))
        self._set_menu_button_presentation(self._effect_btn, effect_label)
        preset_item = self._shader_preset_row.itemAt(0)
        preset_label = preset_item.widget() if preset_item is not None else None
        if isinstance(preset_label, QLabel):
            preset_label.setText(tr("settings.bg_shader_preset"))
        quality_keys = ("fast", "default", "high", "original")
        for button in self._thumb_group.buttons():
            key = cast(str, button.property("option_key"))
            if key in quality_keys:
                button.setText(tr(f"settings.thumb_quality_{key}"))

    def refresh_scaled_geometry(self, scale: float | None = None):
        if scale is None:
            configured_scale = AppSettings.instance().get("ui_scale", 1.0)
            scale = configured_scale if isinstance(configured_scale, (int, float)) else 1.0
        percentage = round(scale * 100)
        if self._ui_scale_slider.value() != percentage:
            blocker = QSignalBlocker(self._ui_scale_slider)
            self._ui_scale_slider.setValue(percentage)
            del blocker
        self._ui_scale_label.setText(f"{percentage}%")
        self.setMinimumSize(
            scaled_px(self._logical_min_size[0]), scaled_px(self._logical_min_size[1]))
        for layout in (self._appearance_layout, self._general_layout,
                       self._thumbnails_layout, self._maintenance_layout):
            layout.setSpacing(scaled_px(int(themes.prop("spacing", "md"))))
            layout.setContentsMargins(
                scaled_px(int(themes.prop("spacing", "sm"))),
                scaled_px(int(themes.prop("spacing", "sm"))),
                scaled_px(int(themes.prop("spacing", "sm"))),
                scaled_px(int(themes.prop("spacing", "sm"))))
        self._effects_layout.setSpacing(scaled_px(int(themes.prop("spacing", "sm"))))
        self._theme_layout.setSpacing(scaled_px(int(themes.prop("spacing", "sm"))))
        self._cache_layout.setSpacing(scaled_px(6))
        self._cache_layout.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "sm"))))
        self._maintenance_group_layout.setSpacing(scaled_px(6))
        self._maintenance_group_layout.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "sm"))))
        self._health_group_layout.setSpacing(scaled_px(6))
        self._health_group_layout.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "sm"))))
        self._thumb_cap_group_layout.setSpacing(scaled_px(6))
        self._thumb_cap_group_layout.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "sm"))))
        self._relink_group_layout.setSpacing(scaled_px(6))
        self._relink_group_layout.setContentsMargins(
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "md"))),
            scaled_px(int(themes.prop("spacing", "sm"))))
        self._mode_btn.setMinimumWidth(scaled_px(100))
        self._theme_btn.setMinimumWidth(scaled_px(160))
        self._effect_btn.setMinimumWidth(scaled_px(120))
        self._bg_browse_btn.setFixedWidth(scaled_px(60))
        self._refresh_menu_button_icons()
        self.refresh_radio_group_geometry(self._lang_group_box)
        self.refresh_radio_group_geometry(self._thumb_group_box)
        for group in (self._lang_group, self._thumb_group):
            for button in group.buttons():
                button.setMinimumHeight(scaled_px(24))

    def _on_thumb_quality_clicked(self, key):
        AppSettings.instance().set("thumb_quality", key)
        AppSettings.instance().save()

    def _clear_thumbnails(self):
        reply = QMessageBox.question(
            self, tr("settings.thumb_clear_title"),
            tr("settings.thumb_clear_msg"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        parent = self.parent()
        if parent is None or not hasattr(parent, "file_list"):
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.error_no_library"))
            return
        loader = cast(_ThumbnailHost, parent).file_list._loader
        # Deleting every cached artifact can touch tens of thousands of
        # files: mirror the regenerate flow — worker thread + progress bar
        # + disabled trigger buttons, completion reported via signals.
        signals = self._progress_signals
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._progress.setFormat(tr("settings.thumb_clearing"))
        self._clear_btn.setEnabled(False)
        self._regen_btn.setEnabled(False)
        # Non-admitted tasks still report completion (0, 0) so the UI
        # resets itself instead of waiting forever.
        loader.clear_thumb_cache_async(
            on_progress=lambda done, total: self._emit_clear_progress(signals, done, total),
            on_complete=lambda removed, failed: self._emit_clear_finished(signals, removed, failed),
        )

    @staticmethod
    def _emit_clear_progress(signals, done: int, total: int):
        if Shiboken.isValid(signals):
            signals.clear_progress.emit(done, total)

    @staticmethod
    def _emit_clear_finished(signals, removed: int, failed: int):
        if Shiboken.isValid(signals):
            signals.cleared.emit(removed, failed)

    def _on_clear_progress(self, done: int, total: int):
        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(done)

    def _on_clear_done(self, removed: int, failed: int):
        self._progress.setVisible(False)
        self._clear_btn.setEnabled(True)
        self._regen_btn.setEnabled(True)
        if failed:
            QMessageBox.information(
                self, tr("dialog.done"),
                tr("settings.thumb_clear_done_failed", count=removed, failed=failed))
        else:
            QMessageBox.information(
                self, tr("dialog.done"), tr("settings.thumbnails_deleted", count=removed))

    def _regenerate_thumbnails(self):
        reply = QMessageBox.question(
            self, tr("settings.thumb_regenerate_title"),
            tr("settings.thumb_regenerate_msg"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        parent = self.parent()
        if parent is None or not hasattr(parent, "file_list"):
            return
        fl = cast(_ThumbnailHost, parent).file_list
        loader = fl._loader
        lib_root = fl._lib_root
        if not lib_root:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.error_no_library_path"))
            return
        loader.clear_thumb_cache()
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._clear_btn.setEnabled(False)
        self._regen_btn.setEnabled(False)
        signals = self._progress_signals
        loader.regenerate_all(
            lib_root,
            on_progress=lambda c, t: self._emit_regeneration_progress(signals, c, t),
            on_complete=lambda count: self._emit_regeneration_finished(signals, count),
        )

    @staticmethod
    def _emit_regeneration_progress(signals, current: int, total: int):
        if Shiboken.isValid(signals):
            signals.updated.emit(current, total)

    @staticmethod
    def _emit_regeneration_finished(signals, count: int):
        if Shiboken.isValid(signals):
            signals.finished.emit(count)

    def _on_progress(self, cur: int, total: int):
        self._progress.setRange(0, total)
        self._progress.setValue(cur)

    def _on_regenerate_done(self, count: int):
        self._progress.setVisible(False)
        self._clear_btn.setEnabled(True)
        self._regen_btn.setEnabled(True)
        QMessageBox.information(self, tr("dialog.done"), tr("settings.thumb_regenerate_done", count=count))
