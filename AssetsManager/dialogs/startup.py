"""Startup window — library launcher with integrated menu bar.

Two-column layout:
  Left  — selected library detail card (name, path, status, actions)
  Right — scrollable history list with folder cards
  Top   — menu bar (Settings for theme switching)

Visual: card-based with theme gradients, property-based styling, snapshot diffing.
"""
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, QSize
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QFrame, QWidget, QScrollArea, QSizePolicy,
    QMenuBar, QMainWindow,
)
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.color_utils import alpha
from AssetsManager.core import icons
from AssetsManager.widgets.elevation import apply_elevation, refresh_elevation
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager import i18n
tr = i18n.tr


def _interpolate_color(hex_color: str, factor: float) -> str:
    """Lighten or darken a hex color by blending toward white/black."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if factor > 0:
        r += int((255 - r) * factor)
        g += int((255 - g) * factor)
        b += int((255 - b) * factor)
    else:
        r += int(r * factor)
        g += int(g * factor)
        b += int(b * factor)
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def _font(key: str) -> int:
    """Scaled semantic font size resolved from theme tokens."""
    return scaled_pt(themes.font_size(key))


# ── Detail panel (left column) ────────────────────────────────

class _DetailPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("detailPanel")
        self.setMinimumWidth(scaled_px(220))
        self.setMaximumWidth(scaled_px(300))
        self._t = themes.get()
        self._setup()

    def _setup(self):
        self.setStyleSheet(self._card_qss("detailPanel"))
        apply_elevation(self, level=1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scaled_px(16), scaled_px(14), scaled_px(16), scaled_px(14))
        layout.setSpacing(scaled_px(8))

        self._header = QLabel(tr("startup.selected_header"))
        self._header.setStyleSheet(
            f"font-size: {_font('xxs')}px; font-weight: bold; color: {self._t['muted']}; "
            f"letter-spacing: 1px; padding: 0; background: transparent; border: none;")
        self._header.hide()
        layout.addWidget(self._header)

        self._name = QLabel()
        self._name.setWordWrap(True)
        self._name.setStyleSheet(
            f"font-size: {_font('xl')}px; font-weight: bold; color: {self._t['heading']}; "
            f"padding: 0; line-height: 1.3; background: transparent; border: none;")
        self._name.hide()
        layout.addWidget(self._name)

        self._path = QLabel()
        self._path.setWordWrap(True)
        self._path.setStyleSheet(
            f"font-size: {_font('xs')}px; color: {self._t['muted']}; "
            f"padding: 0; background: transparent; border: none;")
        self._path.hide()
        layout.addWidget(self._path)

        self._status = QLabel()
        self._status.hide()
        layout.addWidget(self._status)

        layout.addStretch()

        self._open_btn = QPushButton(tr("startup.open_btn"))
        self._open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_btn.setStyleSheet(self._primary_btn_qss())
        self._open_btn.clicked.connect(self._emit_open)
        self._open_btn.hide()
        self._open_btn.setDefault(True)
        layout.addWidget(self._open_btn)

        self._remove_btn = QPushButton(tr("startup.remove_btn"))
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.setStyleSheet(self._ghost_btn_qss())
        self._remove_btn.clicked.connect(self._emit_remove)
        self._remove_btn.hide()
        layout.addWidget(self._remove_btn)

        self._refresh_button_icons()

        self._path_data = ""
        self._open_cb = None
        self._remove_cb = None

    def _refresh_button_icons(self):
        icon_size = QSize(scaled_px(15), scaled_px(15))
        self._open_btn.setIcon(icons.icon("folder", color="icon_on_accent", size=scaled_px(15)))
        self._remove_btn.setIcon(icons.icon("close", color="icon_muted", size=scaled_px(15)))
        self._open_btn.setIconSize(icon_size)
        self._remove_btn.setIconSize(icon_size)
        self._open_btn.setAccessibleName(tr("startup.open_btn"))
        self._remove_btn.setAccessibleName(tr("startup.remove_btn"))
        self._open_btn.setToolTip(tr("startup.open_btn"))
        self._remove_btn.setToolTip(tr("startup.remove_btn"))

    def refresh_theme(self):
        t = themes.get()
        self.setStyleSheet(self._card_qss("detailPanel"))
        self._header.setStyleSheet(
            f"font-size: {_font('xxs')}px; font-weight: bold; color: {t['muted']}; "
            f"letter-spacing: 1px; padding: 0; background: transparent; border: none;")
        self._name.setStyleSheet(
            f"font-size: {_font('xl')}px; font-weight: bold; color: {t['heading']}; "
            f"padding: 0; line-height: 1.3; background: transparent; border: none;")
        self._path.setStyleSheet(
            f"font-size: {_font('xs')}px; color: {t['muted']}; "
            f"padding: 0; background: transparent; border: none;")
        self._refresh_button_icons()
        self._open_btn.setStyleSheet(self._primary_btn_qss())
        self._remove_btn.setStyleSheet(self._ghost_btn_qss())
        if self._path_data:
            self.show_detail(self._name.text(), self._path_data,
                           Path(self._path_data).exists())

    def show_detail(self, name: str, path: str, exists: bool):
        t = themes.get()
        self._path_data = path
        self._header.show()
        self._name.setText(name)
        self._name.show()
        self._path.setText(path)
        self._path.show()

        radius_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        if exists:
            self._status.setText(tr("startup.ready"))
            self._status.setStyleSheet(
                f"font-size: {_font('caption')}px; font-weight: bold; padding: 2px 8px; "
                f"border-radius: {radius_sm}px; color: {t['success']}; "
                f"background: {_interpolate_color(t['success'], -0.75)};")
        else:
            self._status.setText(tr("startup.missing"))
            self._status.setStyleSheet(
                f"font-size: {_font('caption')}px; font-weight: bold; padding: 2px 8px; "
                f"border-radius: {radius_sm}px; color: {t['danger']}; "
                f"background: {_interpolate_color(t['danger'], -0.75)};")
        self._status.show()

        self._open_btn.setEnabled(exists)
        self._open_btn.show()
        self._remove_btn.show()
        self.setStyleSheet(self._card_qss("detailPanel"))

    def clear_detail(self):
        self._path_data = ""
        self._header.hide()
        self._name.hide()
        self._path.hide()
        self._status.hide()
        self._open_btn.hide()
        self._remove_btn.hide()

    def set_callbacks(self, open_cb, remove_cb):
        self._open_cb = open_cb
        self._remove_cb = remove_cb

    def _emit_open(self):
        if self._open_cb and self._path_data:
            self._open_cb(self._path_data)

    def _emit_remove(self):
        if self._remove_cb and self._path_data:
            self._remove_cb(self._path_data)

    def _card_qss(self, name: str) -> str:
        t = themes.get()
        return (
            f"#{name} {{"
            f"  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"    stop:0 {t['panel']}, stop:1 {t['base']}); "
            f"  border: 1px solid {t['border_subtle']}; "
            f"  border-radius: {scaled_px(int(themes.prop('border_radius', 'md')))}px; "
            f"}}")

    def _primary_btn_qss(self) -> str:
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        return sk.button_css("primary", font_size_key="md",
                             padding_y=scaled_px(9), padding_x=0)

    def _ghost_btn_qss(self) -> str:
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        return sk.button_css("ghost", font_size_key="caption",
                             padding_y=scaled_px(6), padding_x=0)


# ── Library card row (right column list item) ──────────────────

class _LibraryCard(QFrame):
    clicked = Signal(str)
    double_clicked = Signal(str)

    def __init__(self, name: str, path: str, exists: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("libraryCard")
        self._path = path
        self._selected = False
        self._exists = exists
        self._setup(name)

    def _setup(self, name: str):
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(scaled_px(54))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(scaled_px(12), scaled_px(6), scaled_px(12), scaled_px(6))
        layout.setSpacing(scaled_px(10))

        self._dot = QLabel()
        self._dot.setFixedSize(scaled_px(10), scaled_px(10))
        self._dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._dot)

        info = QVBoxLayout()
        info.setSpacing(0)
        self._name_label = QLabel(name)
        info.addWidget(self._name_label)
        self._path_label = QLabel(self._path)
        self._path_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        info.addWidget(self._path_label)
        layout.addLayout(info, 1)

        self.setAccessibleName(name)
        self.setToolTip(self._path)

        self._apply_style()

    def set_selected(self, sel: bool):
        self._selected = sel
        self._apply_style()

    def _apply_style(self):
        t = themes.get()
        radius_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        hover_bg = alpha(t["hover_overlay"], themes.prop("opacity", "hover"))
        # Dot indicator
        dot_fg = t["success"] if self._exists else t["danger"]
        dot_bg = alpha(dot_fg, 0.25) if self._exists else alpha(dot_fg, 0.13)
        self._dot.setAccessibleName(
            tr("startup.ready" if self._exists else "startup.missing"))
        self._dot.setStyleSheet(
            f"background: {dot_bg}; border: 2px solid {dot_fg}; "
            f"border-radius: {radius_sm}px; padding: 0;")
        # Name and path labels
        self._name_label.setStyleSheet(
            f"font-size: {_font('md')}px; font-weight: bold; color: {t['heading']}; "
            f"background: transparent; border: none;")
        self._path_label.setStyleSheet(
            f"font-size: {_font('xs')}px; color: {t['muted']}; "
            f"background: transparent; border: none;")
        # Card background
        if self._selected:
            bg = alpha(t["accent"], 0.25)
            border = alpha(t["accent"], 0.30)
        else:
            bg = "transparent"
            border = "transparent"
        self.setStyleSheet(
            f"#libraryCard {{"
            f"  background: {bg}; "
            f"  border: 1px solid {border}; border-radius: {radius_sm}px; "
            f"}}"
            f"#libraryCard:hover {{"
            f"  background: {hover_bg}; "
            f"}}")

    def mousePressEvent(self, event):
        self.clicked.emit(self._path)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit(self._path)


# ── Main window ────────────────────────────────────────────────

class StartupWindow(QMainWindow):
    library_opened = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("startup.title"))
        self.resize(scaled_px(740), scaled_px(500))
        self.setMinimumSize(scaled_px(600), scaled_px(400))
        self._settings = AppSettings.instance()
        self._settings.load()
        self._cards: list[_LibraryCard] = []
        self._truncation_indicator: QLabel | None = None
        self._selected_path: str = ""

        self._setup_ui()
        self._populate()
        self._theme_connection = bus().theme_changed.connect(self.refresh_theme)
        self._language_connection = bus().language_changed.connect(self._refresh_language)
        self._center_on_parent(parent)

    def closeEvent(self, event):
        """Disconnect bus signals on close."""
        try:
            QObject.disconnect(self._theme_connection)
        except (RuntimeError, TypeError):
            pass
        try:
            QObject.disconnect(self._language_connection)
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(event)

    def _center_on_parent(self, parent):
        if parent:
            pg = parent.geometry()
            self.move(pg.center() - self.rect().center())

    # ── UI ──────────────────────────────────────────────────────

    def _setup_ui(self):
        t = themes.get()
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)

        # ── Menu bar ──────────────────────────────────────────
        self._menu_bar = QMenuBar()
        self._menu_bar.setNativeMenuBar(False)
        self._apply_menu_theme()

        self._menu_lib = self._menu_bar.addMenu(tr("menu.library"))
        self._menu_act_browse = self._menu_lib.addAction(tr("menu.browse"), self._browse)
        self._menu_lib.addSeparator()
        self._menu_act_exit = self._menu_lib.addAction(tr("menu.exit"), self.close)

        self._menu_settings = self._menu_bar.addMenu(tr("menu.settings"))
        self._menu_act_settings = self._menu_settings.addAction(tr("menu.settings"), self._open_settings)

        self.setMenuBar(self._menu_bar)

        # ── Central widget ────────────────────────────────────
        self._central = QWidget()
        self._central.setStyleSheet(f"background: {sk.token('base')};")
        self.setCentralWidget(self._central)
        root = QVBoxLayout(self._central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._hero_card = QFrame()
        self._hero_card.setObjectName("heroCard")
        self._hero_card.setStyleSheet(
            f"#heroCard {{"
            f"  background: qlineargradient(x1:0, y1:0, x2:1, y2:0.7, "
            f"    stop:0 {_interpolate_color(t['panel'], 0.06)}, "
            f"    stop:0.5 {t['panel']}, "
            f"    stop:1 {t['panel']}); "
            f"  border-bottom: 1px solid {t['border_subtle']}; "
            f"}}")
        hero_layout = QVBoxLayout(self._hero_card)
        hero_layout.setContentsMargins(scaled_px(28), scaled_px(14), scaled_px(28), scaled_px(12))
        hero_layout.setSpacing(2)

        self._hero_title = QLabel(tr("startup.hero_title"))
        self._hero_title.setStyleSheet(
            f"font-size: {_font('xxl')}px; font-weight: bold; color: {t['heading']}; "
            f"background: transparent; border: none;")
        hero_layout.addWidget(self._hero_title)

        self._hero_sub = QLabel(tr("startup.hero_sub"))
        self._hero_sub.setStyleSheet(
            f"font-size: {_font('sm')}px; color: {t['muted']}; "
            f"background: transparent; border: none;")
        hero_layout.addWidget(self._hero_sub)

        hero_layout.addSpacing(scaled_px(6))
        self._hero_count = QLabel()
        self._hero_count.setStyleSheet(
            f"font-size: {_font('caption')}px; color: {_interpolate_color(t['muted'], 0.4)}; "
            f"background: transparent; border: none;")
        hero_layout.addWidget(self._hero_count)

        root.addWidget(self._hero_card)

        # ── Content row ───────────────────────────────────────
        content = QHBoxLayout()
        content.setContentsMargins(scaled_px(20), scaled_px(16), scaled_px(20), scaled_px(14))
        content.setSpacing(scaled_px(16))

        self._detail = _DetailPanel()
        self._detail.set_callbacks(self._accept, self._remove_selected)
        content.addWidget(self._detail)

        self._list_panel = QFrame()
        self._list_panel.setObjectName("listPanel")
        self._list_panel.setStyleSheet(
            f"#listPanel {{"
            f"  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"    stop:0 {_interpolate_color(t['panel'], 0.03)}, stop:1 {t['base']}); "
            f"  border: 1px solid {t['border_subtle']}; "
            f"  border-radius: {scaled_px(int(themes.prop('border_radius', 'md')))}px; "
            f"}}")
        apply_elevation(self._list_panel, level=1)
        right_layout = QVBoxLayout(self._list_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._list_header = QLabel(tr("startup.recent_header"))
        self._list_header.setStyleSheet(
            f"font-size: {_font('xxs')}px; font-weight: bold; color: {t['muted']}; "
            f"letter-spacing: 1px; padding: 10px 0 4px 12px; "
            f"background: transparent; border: none;")
        right_layout.addWidget(self._list_header)

        self._card_container = QWidget()
        self._card_container.setStyleSheet("background: transparent;")
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(scaled_px(8), scaled_px(4), scaled_px(8), scaled_px(4))
        self._card_layout.setSpacing(scaled_px(4))
        self._card_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._card_container)
        right_layout.addWidget(scroll)

        bot = QHBoxLayout()
        bot.setContentsMargins(scaled_px(8), scaled_px(4), scaled_px(8), scaled_px(6))

        self._browse_btn = QPushButton(tr("startup.browse_btn"))
        self._browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._browse_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent; color: {t['body']}; "
            f"  border: 1px solid {alpha(t['border'], 0.375)}; "
            f"  border-radius: {scaled_px(int(themes.prop('border_radius', 'sm')))}px; "
            f"  padding: 6px 14px; font-size: {_font('sm')}px; "
            f"}}"
            f"QPushButton:hover {{ background: {alpha(t['hover_overlay'], themes.prop('opacity', 'hover'))}; }}")
        self._browse_btn.setIcon(icons.icon("folder", color="icon_secondary", size=scaled_px(15)))
        self._browse_btn.setIconSize(QSize(scaled_px(15), scaled_px(15)))
        self._browse_btn.setAccessibleName(tr("startup.browse_btn"))
        self._browse_btn.setToolTip(tr("startup.browse_btn"))
        self._browse_btn.clicked.connect(self._browse)
        bot.addWidget(self._browse_btn)
        bot.addStretch()
        right_layout.addLayout(bot)
        content.addWidget(self._list_panel, 1)

        root.addLayout(content)
        root.addSpacing(scaled_px(4))

    def _refresh_language(self, _code: str = ""):
        """Re-set all translatable text after language change."""
        self._menu_lib.setTitle(tr("menu.library"))
        self._menu_act_browse.setText(tr("menu.browse"))
        self._menu_act_exit.setText(tr("menu.exit"))
        self._menu_settings.setTitle(tr("menu.settings"))
        self._menu_act_settings.setText(tr("menu.settings"))
        self.setWindowTitle(tr("startup.title"))
        self._hero_title.setText(tr("startup.hero_title"))
        self._hero_sub.setText(tr("startup.hero_sub"))
        self._list_header.setText(tr("startup.recent_header"))
        self._detail._header.setText(tr("startup.selected_header"))
        self._detail._open_btn.setText(tr("startup.open_btn"))
        self._detail._remove_btn.setText(tr("startup.remove_btn"))
        self._browse_btn.setText(tr("startup.browse_btn"))
        self._detail._refresh_button_icons()
        self._browse_btn.setIcon(icons.icon("folder", color="icon_secondary", size=scaled_px(15)))
        self._browse_btn.setIconSize(QSize(scaled_px(15), scaled_px(15)))
        self._browse_btn.setAccessibleName(tr("startup.browse_btn"))
        self._browse_btn.setToolTip(tr("startup.browse_btn"))
        self._populate()

    # ── Menu theming ───────────────────────────────────────────

    def _apply_menu_theme(self):
        t = themes.get()
        radius_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        self._menu_bar.setStyleSheet(
            f"QMenuBar {{ background: {t['header']}; color: {t['heading']}; "
            f"border-bottom: 1px solid {alpha(t['border'], 0.25)}; "
            f"padding: 2px 0; font-size: {_font('sm')}px; }}"
            f"QMenuBar::item {{ padding: 4px 10px; border-radius: {radius_sm}px; }}"
            f"QMenuBar::item:selected {{ background: {alpha(t['accent'], 0.313)}; }}"
            f"QMenu {{ background: {t['panel']}; color: {t['heading']}; "
            f"border: 1px solid {t['border']}; "
            f"border-radius: {radius_sm}px; padding: 4px; }}"
            f"QMenu::item {{ padding: 5px 28px 5px 12px; border-radius: {radius_sm}px; }}"
            f"QMenu::item:selected {{ background: {t['accent']}; }}")

    def _open_settings(self):
        from AssetsManager.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec()

    # ── Data ───────────────────────────────────────────────────

    def _populate(self):
        # Drop non-string entries: Path(p) raises TypeError on them and
        # would otherwise crash the whole startup window.
        paths = [p for p in self._settings.get_list("recent_libraries", []) if isinstance(p, str)]
        valid = [p for p in paths if Path(p).exists()]
        missing = [p for p in paths if p not in valid]
        recent = valid + missing

        for c in self._cards:
            self._card_layout.removeWidget(c)
            c.deleteLater()
        self._cards.clear()
        if self._truncation_indicator is not None:
            self._card_layout.removeWidget(self._truncation_indicator)
            self._truncation_indicator.deleteLater()
            self._truncation_indicator = None

        if not paths:
            self._hero_count.setText(tr("startup.hero_empty"))
            self._detail.clear_detail()
            return

        count = len(recent)
        ready = len(valid)
        self._hero_count.setText(
            tr("startup.hero_count", count=count, y="y" if count == 1 else "ies", ready=ready))

        for p in recent[:30]:
            path = Path(p)
            card = _LibraryCard(path.name, p, path.exists())
            card.clicked.connect(self._on_card_clicked)
            card.double_clicked.connect(self._accept)
            self._cards.append(card)
            self._card_layout.insertWidget(len(self._cards) - 1, card)

        if len(recent) > 30:
            t = themes.get()
            indicator = QLabel(tr("startup.hero_truncated", shown=30, total=len(recent)))
            indicator.setStyleSheet(
                f"font-size: {_font('xs')}px; color: {t['muted']}; "
                f"padding: {scaled_px(4)}px {scaled_px(12)}px; background: transparent; border: none;")
            self._truncation_indicator = indicator
            self._card_layout.insertWidget(len(self._cards), indicator)

        if self._cards:
            # Preserve the previous selection across repopulation (e.g. a
            # language refresh); fall back to the first card.
            selected = self._selected_path
            target = next(
                (c for c in self._cards if c._path == selected),
                self._cards[0],
            )
            self._on_card_clicked(target._path)

    def _on_card_clicked(self, path_str: str):
        self._selected_path = path_str
        path = Path(path_str)
        self._detail.show_detail(path.name, path_str, path.exists())
        for c in self._cards:
            c.set_selected(c._path == path_str)

    def _accept(self, path_str: str = ""):
        p = path_str or self._selected_path
        if p and Path(p).exists():
            self._save_recent(p)
            self.library_opened.emit(p)
            self.close()

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, tr("startup.browse_dialog_title"),
                                                 str(Path.home()))
        if path:
            self._save_recent(path)
            self.library_opened.emit(path)
            self.close()

    def _remove_selected(self, path_str: str):
        self._settings.remove_from_list("recent_libraries", path_str)
        self._settings.save()
        self._detail.clear_detail()
        self._populate()

    def _save_recent(self, path):
        self._settings.prepend_list("recent_libraries", path, max_items=30)
        self._settings.save()
        from AssetsManager.core.library_manager import record_visit
        record_visit(path)

    # ── Theme refresh ──────────────────────────────────────────

    def refresh_theme(self, _name: str = ""):
        """Re-apply all theme-dependent styles on startup window."""
        themes.apply_to(self)
        t = themes.get()
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self._central.setStyleSheet(f"background: {sk.token('base')};")
        self._apply_menu_theme()

        # Hero card
        self._hero_card.setStyleSheet(
            f"#heroCard {{"
            f"  background: qlineargradient(x1:0, y1:0, x2:1, y2:0.7, "
            f"    stop:0 {_interpolate_color(t['panel'], 0.06)}, "
            f"    stop:0.5 {t['panel']}, "
            f"    stop:1 {t['panel']}); "
            f"  border-bottom: 1px solid {t['border_subtle']}; "
            f"}}")

        # List panel
        self._list_panel.setStyleSheet(
            f"#listPanel {{"
            f"  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"    stop:0 {_interpolate_color(t['panel'], 0.03)}, stop:1 {t['base']}); "
            f"  border: 1px solid {t['border_subtle']}; "
            f"  border-radius: {scaled_px(int(themes.prop('border_radius', 'md')))}px; "
            f"}}")

        # Detail panel
        self._detail.refresh_theme()
        refresh_elevation(self._detail, level=1)
        refresh_elevation(self._list_panel, level=1)
        self._browse_btn.setIcon(icons.icon("folder", color="icon_secondary", size=scaled_px(15)))
        self._browse_btn.setIconSize(QSize(scaled_px(15), scaled_px(15)))

        # Hero text
        self._hero_title.setStyleSheet(
            f"font-size: {_font('xxl')}px; font-weight: bold; color: {t['heading']}; "
            f"background: transparent; border: none;")
        self._hero_sub.setStyleSheet(
            f"font-size: {_font('sm')}px; color: {t['muted']}; "
            f"background: transparent; border: none;")
        self._hero_count.setStyleSheet(
            f"font-size: {_font('caption')}px; color: {_interpolate_color(t['muted'], 0.4)}; "
            f"background: transparent; border: none;")
        self._list_header.setStyleSheet(
            f"font-size: {_font('xxs')}px; font-weight: bold; color: {t['muted']}; "
            f"letter-spacing: 1px; padding: 10px 0 4px 12px; "
            f"background: transparent; border: none;")

        # Browse button
        self._browse_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent; color: {t['body']}; "
            f"  border: 1px solid {alpha(t['border'], 0.375)}; "
            f"  border-radius: {scaled_px(int(themes.prop('border_radius', 'sm')))}px; "
            f"  padding: 6px 14px; font-size: {_font('sm')}px; "
            f"}}"
            f"QPushButton:hover {{ background: {alpha(t['hover_overlay'], themes.prop('opacity', 'hover'))}; }}")

        # Library cards
        for c in self._cards:
            c._apply_style()
