"""Settings dialog — theme, background, language, thumbnail quality, and cache management.

Inherits TabbedDialog for consistent dark theme and widget factories.
"""
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QMessageBox, QProgressBar, QVBoxLayout, QHBoxLayout, QWidget,
    QRadioButton, QFrame, QButtonGroup, QFileDialog, QSlider,
    QListWidget, QListWidgetItem, QInputDialog,
)
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core import themes
from AssetsManager import i18n
tr = i18n.tr


class _ProgressSignals(QObject):
    updated = Signal(int, int)
    finished = Signal(int)


class SettingsDialog(TabbedDialog):
    def __init__(self, parent=None):
        super().__init__(parent, title=tr("settings.title"), min_size=(460, 520))

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
        swatch.setStyleSheet(
            f"background: {accent}; border: 1px solid {accent}; border-radius: {scaled_px(3)}px;")
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

    # ── Tab 1: Appearance (Theme + Background) ────────────

    def _build_appearance_tab(self):
        from AssetsManager.core.ui_scale import scaled_px
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(scaled_px(12))
        layout.setContentsMargins(scaled_px(8), scaled_px(8), scaled_px(8), scaled_px(8))

        self._setup_theme_section(layout)

        # ── Background ─────────────────────────────────

        layout.addWidget(self.make_heading(tr("settings.background")))
        self._bg_enabled_cb = self.make_checkbox(tr("settings.bg_enabled"),
            themes.bg_enabled())
        self._bg_enabled_cb.clicked.connect(self._on_bg_setting_changed)
        layout.addWidget(self._bg_enabled_cb)

        path_row, self._bg_path_edit = self.make_browse_row(
            tr("settings.bg_image"), tr("settings.bg_placeholder"), callback=self._browse_bg_image)
        current_path = themes.bg_image()
        if current_path:
            self._bg_path_edit.setText(current_path)
        layout.addLayout(path_row)

        self._bg_panel_slider = self._make_pct_slider(themes.bg_panel_opacity())
        self._bg_panel_slider.valueChanged.connect(self._on_bg_setting_changed)
        layout.addLayout(self.make_labeled_row(tr("settings.bg_panel_opacity"), self._bg_panel_slider))

        self._bg_header_slider = self._make_pct_slider(themes.bg_header_opacity())
        self._bg_header_slider.valueChanged.connect(self._on_bg_setting_changed)
        layout.addLayout(self.make_labeled_row(tr("settings.bg_header_opacity"), self._bg_header_slider))

        clear_btn = self.make_secondary_btn(tr("settings.bg_clear"), self._clear_bg)
        layout.addWidget(clear_btn)

        layout.addStretch()
        self._add_tab(tab, "  " + tr("settings.appearance") + "  ", scrollable=True)

    def _setup_theme_section(self, layout):
        from AssetsManager.core.ui_scale import scaled_px
        from AssetsManager.core.themes import _get_loader

        loader = _get_loader()
        groups = loader.list_themes()

        layout.addWidget(self.make_heading(tr("settings.theme")))

        # Section 1: Appearance Mode
        mode_group = self.make_groupbox(tr("settings.appearance_mode"))
        mode_layout = QVBoxLayout(mode_group)
        mode_layout.setSpacing(scaled_px(2))
        mode_layout.setContentsMargins(scaled_px(12), scaled_px(16), scaled_px(12), scaled_px(8))

        self._mode_btn_group = QButtonGroup(self)
        self._mode_dark = QRadioButton(tr("settings.dark_mode"))
        self._mode_light = QRadioButton(tr("settings.light_mode"))
        self._mode_system = QRadioButton(tr("settings.follow_system"))

        self._mode_btn_group.addButton(self._mode_dark)
        self._mode_btn_group.addButton(self._mode_light)
        self._mode_btn_group.addButton(self._mode_system)

        mode_layout.addWidget(self._mode_dark)
        mode_layout.addWidget(self._mode_light)
        mode_layout.addWidget(self._mode_system)

        current_mode = AppSettings.instance().get("appearance_mode", "dark")
        if current_mode == "light":
            self._mode_light.setChecked(True)
        elif current_mode == "system":
            self._mode_system.setChecked(True)
        else:
            self._mode_dark.setChecked(True)

        self._mode_btn_group.buttonClicked.connect(self._on_appearance_mode_changed)
        layout.addWidget(mode_group)

        # Section 2: Theme Selection
        theme_group = self.make_groupbox(tr("settings.theme"))
        theme_layout = QVBoxLayout(theme_group)
        theme_layout.setSpacing(scaled_px(4))
        theme_layout.setContentsMargins(scaled_px(12), scaled_px(16), scaled_px(12), scaled_px(8))

        self._theme_list = QListWidget()
        self._theme_list.setMinimumHeight(scaled_px(120))

        dark_themes = groups.get("Dark", [])
        if dark_themes:
            header = QListWidgetItem(tr("settings.dark_mode"))
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setData(Qt.ItemDataRole.UserRole, "__header__")
            f = header.font()
            f.setBold(True)
            header.setFont(f)
            self._theme_list.addItem(header)

            for theme_data in dark_themes:
                name = theme_data.get("name", "")
                item = QListWidgetItem(f"  {name}")
                item.setData(Qt.ItemDataRole.UserRole, name)
                self._theme_list.addItem(item)

        light_themes = groups.get("Light", [])
        if light_themes:
            header = QListWidgetItem(tr("settings.light_mode"))
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setData(Qt.ItemDataRole.UserRole, "__header__")
            f = header.font()
            f.setBold(True)
            header.setFont(f)
            self._theme_list.addItem(header)

            for theme_data in light_themes:
                name = theme_data.get("name", "")
                item = QListWidgetItem(f"  {name}")
                item.setData(Qt.ItemDataRole.UserRole, name)
                self._theme_list.addItem(item)

        current_theme = themes.name()
        for i in range(self._theme_list.count()):
            item = self._theme_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == current_theme:
                self._theme_list.setCurrentItem(item)
                break

        self._theme_list.currentItemChanged.connect(self._on_theme_selected)
        theme_layout.addWidget(self._theme_list)
        layout.addWidget(theme_group)

        # Section 3: Custom Themes
        custom_group = self.make_groupbox(tr("settings.custom_themes"))
        custom_layout = QVBoxLayout(custom_group)
        custom_layout.setSpacing(scaled_px(4))
        custom_layout.setContentsMargins(scaled_px(12), scaled_px(16), scaled_px(12), scaled_px(8))

        self._custom_list = QListWidget()
        self._custom_list.setMinimumHeight(scaled_px(80))

        user_themes = groups.get("User", [])
        for theme_data in user_themes:
            name = theme_data.get("name", "")
            self._add_custom_theme_item(name)

        custom_layout.addWidget(self._custom_list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(scaled_px(6))
        new_btn = self.make_secondary_btn(tr("settings.new_theme"), self._on_new_theme)
        export_btn = self.make_secondary_btn(tr("settings.export_theme"), self._on_export_theme)
        delete_btn = self.make_secondary_btn("Delete", self._on_delete_theme)
        btn_row.addWidget(new_btn)
        btn_row.addWidget(export_btn)
        btn_row.addWidget(delete_btn)
        custom_layout.addLayout(btn_row)

        layout.addWidget(custom_group)

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
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if path:
            self._bg_path_edit.setText(path)
            self._on_bg_setting_changed()

    def _clear_bg(self):
        self._bg_path_edit.clear()
        self._bg_enabled_cb.setChecked(False)
        self._on_bg_setting_changed()

    def _on_bg_setting_changed(self, *_):
        s = AppSettings.instance()
        s.set("bg_enabled", self._bg_enabled_cb.isChecked())
        s.set("bg_image", self._bg_path_edit.text())
        s.set("bg_panel_opacity", self._bg_panel_slider.value() / 100.0)
        s.set("bg_header_opacity", self._bg_header_slider.value() / 100.0)
        s.save()
        themes.invalidate_cache()
        parent = self.parent()
        if parent and hasattr(parent, '_on_bg_style_changed'):
            parent._on_bg_style_changed()

    # ── Tab 2: General ────────────────────────────────────

    def _build_general_tab(self):
        from AssetsManager.core.ui_scale import scaled_px
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(scaled_px(12))
        layout.setContentsMargins(scaled_px(8), scaled_px(8), scaled_px(8), scaled_px(8))

        lang_map = i18n.languages()
        lang_opts = {code: lang_map.get(code, code) for code in ("en", "zh", "ja")}
        lang_group, self._lang_group = self.make_radio_group(
            tr("settings.language"), lang_opts, i18n.current_language(), on_changed=self._on_lang_clicked)
        layout.addWidget(lang_group)

        # UI Scale
        from AssetsManager.core.ui_scale import get_ui_scale
        layout.addWidget(self.make_heading(tr("settings.ui_scale")))
        self._ui_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._ui_scale_slider.setRange(50, 200)
        self._ui_scale_slider.setValue(int(get_ui_scale() * 100))
        self._ui_scale_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._ui_scale_slider.setTickInterval(25)
        self._ui_scale_slider.valueChanged.connect(self._on_ui_scale_changed)
        layout.addWidget(self._ui_scale_slider)
        self._ui_scale_label = self.make_muted(f"{get_ui_scale() * 100:.0f}%")
        layout.addWidget(self._ui_scale_label)

        layout.addStretch()
        self._add_tab(tab, "  " + tr("settings.general") + "  ", scrollable=True)

    # ── Tab 3: Thumbnails ────────────────────────────────

    def _build_thumbnails_tab(self):
        from AssetsManager.core.ui_scale import scaled_px
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(scaled_px(12))
        layout.setContentsMargins(scaled_px(8), scaled_px(8), scaled_px(8), scaled_px(8))

        current_quality = AppSettings.instance().get("thumb_quality", "default")
        quality_labels = {
            "fast": tr("settings.thumb_quality_fast"), "default": tr("settings.thumb_quality_default"),
            "high": tr("settings.thumb_quality_high"), "original": tr("settings.thumb_quality_original"),
        }
        thumb_opts = {k: quality_labels[k] for k in ("fast", "default", "high", "original")}
        thumb_group, self._thumb_group = self.make_radio_group(
            tr("settings.thumb_quality"), thumb_opts, current_quality, on_changed=self._on_thumb_quality_clicked)
        layout.addWidget(thumb_group)

        cache_group = self.make_groupbox(tr("settings.thumb_cache"))

        cl = QVBoxLayout(cache_group)
        cl.setSpacing(scaled_px(6))
        cl.setContentsMargins(scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(8))

        self._clear_btn = self.make_secondary_btn(tr("settings.thumb_clear"), self._clear_thumbnails)
        cl.addWidget(self._clear_btn)

        self._regen_btn = self.make_secondary_btn(tr("settings.thumb_regenerate"), self._regenerate_thumbnails)
        cl.addWidget(self._regen_btn)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setTextVisible(True)
        cl.addWidget(self._progress)

        self._progress_signals = _ProgressSignals()
        self._progress_signals.updated.connect(self._on_progress)
        self._progress_signals.finished.connect(self._on_regenerate_done)

        layout.addWidget(cache_group)
        layout.addStretch()
        self._add_tab(tab, "  " + tr("settings.thumbnails") + "  ", scrollable=True)

    # ── Handlers ─────────────────────────────────────────

    def _on_appearance_mode_changed(self, btn):
        if btn == self._mode_dark:
            mode = "dark"
        elif btn == self._mode_light:
            mode = "light"
        else:
            mode = "system"
        AppSettings.instance().set("appearance_mode", mode)
        AppSettings.instance().save()

    def _on_theme_selected(self, current, _previous):
        if current is None:
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        if name and name != "__header__":
            themes.set_theme(name)

    def _on_new_theme(self):
        from AssetsManager.core.themes import _get_loader
        loader = _get_loader()

        name, ok = QInputDialog.getText(self, tr("settings.new_theme"), tr("settings.theme_name"))
        if not ok or not name.strip():
            return

        name = name.strip()
        groups = loader.list_themes()
        all_themes = []
        for theme_data in groups.get("Dark", []):
            all_themes.append(theme_data.get("name", ""))
        for theme_data in groups.get("Light", []):
            all_themes.append(theme_data.get("name", ""))

        if not all_themes:
            return

        base, ok = QInputDialog.getItem(self, tr("settings.base_theme"), tr("settings.select_base"), all_themes, 0, False)
        if not ok:
            return

        if loader.create_custom_theme(name, base):
            self._add_custom_theme_item(name)
            themes.reload_themes()
        else:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.theme_exists"))

    def _add_custom_theme_item(self, name: str):
        item = QListWidgetItem(f"  {name}")
        item.setData(Qt.ItemDataRole.UserRole, name)
        self._custom_list.addItem(item)

    def _on_export_theme(self):
        from AssetsManager.core.themes import _get_loader
        loader = _get_loader()

        current = self._custom_list.currentItem()
        if current is None:
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        if not name:
            return

        path, _ = QFileDialog.getSaveFileName(self, tr("settings.export_theme"), f"{name}.json", "JSON (*.json)")
        if path:
            if loader.export_theme(name, path):
                QMessageBox.information(self, tr("dialog.done"), tr("settings.export_theme"))
            else:
                QMessageBox.warning(self, tr("dialog.error"), tr("dialog.error"))

    def _on_delete_theme(self):
        from AssetsManager.core.themes import _get_loader
        loader = _get_loader()

        current = self._custom_list.currentItem()
        if current is None:
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        if not name:
            return

        reply = QMessageBox.question(
            self, tr("dialog.confirm"),
            f"Delete theme '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        if loader.delete_custom_theme(name):
            row = self._custom_list.row(current)
            self._custom_list.takeItem(row)
            themes.reload_themes()

    def _on_lang_clicked(self, key):
        i18n.set_language(key)

    def _on_ui_scale_changed(self, val):
        scale = val / 100.0
        AppSettings.instance().set("ui_scale", scale)
        AppSettings.instance().save()
        self._ui_scale_label.setText(f"{val:.0f}%")
        bus().ui_scale_changed.emit(scale)

    def _on_thumb_quality_clicked(self, key):
        AppSettings.instance().set("thumb_quality", key)
        AppSettings.instance().save()

    def _clear_thumbnails(self):
        reply = QMessageBox.question(
            self, tr("settings.thumb_clear_title"),
            tr("settings.thumb_clear_msg"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        parent = self.parent()
        if parent and hasattr(parent, 'file_list') and hasattr(parent.file_list, '_loader'):
            count = parent.file_list._loader.clear_thumb_cache()
            QMessageBox.information(self, tr("dialog.done"), tr("settings.thumbnails_deleted", count=count))
        else:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.error_no_library"))

    def _regenerate_thumbnails(self):
        reply = QMessageBox.question(
            self, tr("settings.thumb_regenerate_title"),
            tr("settings.thumb_regenerate_msg"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        parent = self.parent()
        if not parent or not hasattr(parent, 'file_list'):
            return
        fl = parent.file_list
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
        loader.regenerate_all(lib_root, on_progress=lambda c, t: self._progress_signals.updated.emit(c, t))

    def _on_progress(self, cur: int, total: int):
        self._progress.setRange(0, total)
        self._progress.setValue(cur)

    def _on_regenerate_done(self, count: int):
        self._progress.setVisible(False)
        self._clear_btn.setEnabled(True)
        self._regen_btn.setEnabled(True)
        QMessageBox.information(self, tr("dialog.done"), tr("settings.thumb_regenerate_done", count=count))
