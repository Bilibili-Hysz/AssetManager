"""Settings dialog — theme, background, language, thumbnail quality, and cache management.

Inherits TabbedDialog for consistent dark theme and widget factories.
"""
from typing import Protocol, cast, runtime_checkable

from shiboken6 import Shiboken
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QMessageBox, QProgressBar, QVBoxLayout, QHBoxLayout, QWidget,
    QRadioButton, QFrame, QPushButton, QFileDialog, QSlider,
    QInputDialog,
)
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core import themes
from AssetsManager import i18n
tr = i18n.tr


class _ThumbnailLoader(Protocol):
    def clear_thumb_cache(self) -> int: ...

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
        self._bg_enabled_cb.toggled.connect(self._on_bg_setting_changed)
        layout.addWidget(self._bg_enabled_cb)

        path_row, self._bg_path_edit = self.make_browse_row(
            tr("settings.bg_image"), tr("settings.bg_placeholder"), callback=self._browse_bg_image)
        current_path = themes.bg_image()
        if current_path:
            self._bg_path_edit.setText(current_path)
        self._bg_path_edit.textChanged.connect(self._on_bg_setting_changed)
        layout.addLayout(path_row)

        self._bg_panel_slider = self._make_pct_slider(themes.bg_panel_opacity())
        self._bg_panel_slider.valueChanged.connect(self._on_bg_setting_changed)
        layout.addLayout(self.make_labeled_row(tr("settings.bg_panel_opacity"), self._bg_panel_slider))

        self._bg_header_slider = self._make_pct_slider(themes.bg_header_opacity())
        self._bg_header_slider.valueChanged.connect(self._on_bg_setting_changed)
        layout.addLayout(self.make_labeled_row(tr("settings.bg_header_opacity"), self._bg_header_slider))

        # ── Image Effects ──────────────────────────────

        layout.addWidget(self.make_heading(tr("settings.bg_effects")))

        btn_row = QHBoxLayout()
        btn_row.setSpacing(scaled_px(8))
        current_effect = themes.bg_effect()
        effect_label = {"none": tr("settings.bg_effect_none"), "blur": tr("settings.bg_blur"), "mosaic": tr("settings.bg_mosaic")}.get(current_effect, tr("settings.bg_effect_none"))
        self._effect_btn = QPushButton(effect_label + " \u25be")
        self._effect_btn.setMinimumWidth(scaled_px(120))
        self._effect_btn.clicked.connect(self._on_effect_menu)
        btn_row.addWidget(self._effect_btn)

        self._effect_intensity = QSlider(Qt.Orientation.Horizontal)
        self._effect_intensity.setRange(1, 50)
        self._effect_intensity.setValue(themes.bg_effect_intensity())
        self._effect_intensity.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._effect_intensity.setTickInterval(5)
        self._effect_intensity.valueChanged.connect(self._on_bg_setting_changed)
        btn_row.addWidget(self._effect_intensity, 1)
        layout.addLayout(btn_row)
        self._current_effect = current_effect

        clear_btn = self.make_secondary_btn(tr("settings.bg_clear"), self._clear_bg)
        layout.addWidget(clear_btn)

        layout.addStretch()
        self._add_tab(tab, "  " + tr("settings.appearance") + "  ", scrollable=True)

    def _setup_theme_section(self, layout):
        from AssetsManager.core.ui_scale import scaled_px

        layout.addWidget(self.make_heading(tr("settings.theme")))

        btn_row = QHBoxLayout()
        btn_row.setSpacing(scaled_px(8))

        current_mode = AppSettings.instance().get("appearance_mode", "dark")
        mode_text = tr("settings.dark_mode") if current_mode == "dark" else tr("settings.light_mode")
        self._mode_btn = QPushButton(mode_text + " \u25be")
        self._mode_btn.setMinimumWidth(scaled_px(100))
        self._mode_btn.clicked.connect(self._on_mode_menu_requested)
        btn_row.addWidget(self._mode_btn)

        current_theme = themes.name()
        self._theme_btn = QPushButton(current_theme + " \u25be")
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
        self._mode_btn.setText(mode_label + " \u25be")
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
                self._theme_btn.setText(first + " \u25be")

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
            self._theme_btn.setText(chosen_name + " \u25be")
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
            self._theme_btn.setText(name + " \u25be")
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
            self._theme_btn.setText(name + " \u25be")
        except Exception as e:
            QMessageBox.warning(self, tr("dialog.error"), str(e))

    def _delete_custom_theme_btn(self):
        from PySide6.QtWidgets import QMessageBox
        from AssetsManager.core.themes import _get_loader
        current = themes.name()
        loader = _get_loader()
        if loader.delete_custom_theme(current):
            themes.reload_themes()
            groups = loader.list_themes()
            group_name = "Dark" if self._current_mode == "dark" else "Light"
            theme_list = groups.get(group_name, [])
            if theme_list:
                first = theme_list[0].get("name", "")
                themes.set_theme(first)
                self._theme_btn.setText(first + " \u25be")
        else:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.cannot_delete_builtin"))

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

    def _on_bg_setting_changed(self, *_):
        s = AppSettings.instance()
        s.set("bg_enabled", self._bg_enabled_cb.isChecked())
        s.set("bg_image", self._bg_path_edit.text())
        s.set("bg_panel_opacity", self._bg_panel_slider.value() / 100.0)
        s.set("bg_header_opacity", self._bg_header_slider.value() / 100.0)
        s.set("bg_effect", self._current_effect)
        s.set("bg_effect_intensity", self._effect_intensity.value())
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
        chosen = menu.exec(self._effect_btn.mapToGlobal(self._effect_btn.rect().bottomLeft()))
        if chosen == none_action:
            self._current_effect = "none"
        elif chosen == blur_action:
            self._current_effect = "blur"
        elif chosen == mosaic_action:
            self._current_effect = "mosaic"
        else:
            return
        label = {"none": tr("settings.bg_effect_none"), "blur": tr("settings.bg_blur"), "mosaic": tr("settings.bg_mosaic")}.get(self._current_effect, tr("settings.bg_effect_none"))
        self._effect_btn.setText(label + " \u25be")
        self._on_bg_setting_changed()

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

        self._progress_signals = _ProgressSignals(self)
        self._progress_signals.updated.connect(self._on_progress)
        self._progress_signals.finished.connect(self._on_regenerate_done)

        layout.addWidget(cache_group)
        layout.addStretch()
        self._add_tab(tab, "  " + tr("settings.thumbnails") + "  ", scrollable=True)

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
        if parent is not None and hasattr(parent, "file_list"):
            host = cast(_ThumbnailHost, parent)
            count = host.file_list._loader.clear_thumb_cache()
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
