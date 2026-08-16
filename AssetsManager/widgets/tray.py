"""System tray manager — background operation with quick controls.

When the main window is closed, the app hides to the system tray.
The tray icon provides a context menu for quick access to sharing
controls and window restoration.
"""
import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import QSystemTrayIcon, QMenu

from AssetsManager import i18n
from AssetsManager.core import themes
from AssetsManager.core.signal_bus import get as bus

_log = logging.getLogger(__name__)
tr = i18n.tr


class SystemTrayManager(QObject):
    """Manages the system tray icon and context menu."""

    show_requested = Signal()
    toggle_sharing = Signal()
    open_browser = Signal()
    exit_requested = Signal()

    def __init__(self, icon_path: str | None = None, parent=None):
        super().__init__(parent)
        self._generated_icon = False
        self._icon = self._load_icon(icon_path)
        self._tray = QSystemTrayIcon(self._icon, self)
        # The tray does not take ownership of its context menu and the
        # manager is a QObject (QMenu requires a QWidget parent), so the
        # menu is released explicitly when the manager is destroyed.
        self._menu = QMenu()
        self.destroyed.connect(self._menu.deleteLater)
        self._sharing_running = False

        self._setup_menu()
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)
        self._tray.setToolTip(tr("app.name"))
        self._available = QSystemTrayIcon.isSystemTrayAvailable()
        if self._available:
            self._tray.show()
        self._bus_theme_conn = bus().theme_changed.connect(self._on_theme_changed)

    @property
    def is_available(self) -> bool:
        return self._available

    def _load_icon(self, icon_path: str | None) -> QIcon:
        """Load icon from file or generate a fallback."""
        if icon_path and Path(icon_path).exists():
            icon = QIcon(icon_path)
            if not icon.isNull():
                self._generated_icon = False
                return icon
        self._generated_icon = True
        # Fallback: generate a simple 'A' icon
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(themes.color("accent")))
        painter.setPen(QColor(0, 0, 0, 0))
        painter.drawRoundedRect(2, 2, 28, 28, 6, 6)
        painter.setPen(QColor(themes.color("on_accent")))
        font = painter.font()
        font.setPixelSize(20)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), 0x0084, "A")
        painter.end()
        return QIcon(pixmap)

    def _on_theme_changed(self, _name: str = ""):
        if not self._generated_icon:
            return
        self._tray.setIcon(self._load_icon(None))

    def _setup_menu(self):
        """Build the context menu."""
        self._show_action = self._menu.addAction(tr("tray.show"))

        self._show_action.triggered.connect(self.show_requested.emit)

        self._menu.addSeparator()

        self._share_action = self._menu.addAction(tr("tray.start_sharing"))

        self._share_action.triggered.connect(self.toggle_sharing.emit)

        self._open_action = self._menu.addAction(tr("tray.open_browser"))
        self._open_action.triggered.connect(self.open_browser.emit)
        self._open_action.setEnabled(False)

        self._menu.addSeparator()

        exit_action = self._menu.addAction(tr("tray.exit"))
        exit_action.triggered.connect(self.exit_requested.emit)

    def _on_activated(self, reason):
        """Handle tray icon activation (double-click to show window)."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_requested.emit()

    def update_sharing_state(self, running: bool, url: str = ""):
        """Update menu items based on sharing state."""
        self._sharing_running = running
        if running:
            self._share_action.setText(tr("tray.stop_sharing"))
            self._open_action.setEnabled(True)
            self._tray.setToolTip(tr("tray.sharing_tooltip", url=url))
        else:
            self._share_action.setText(tr("tray.start_sharing"))
            self._open_action.setEnabled(False)
            self._tray.setToolTip(tr("app.name"))

    def show_message(self, title: str, message: str):
        """Show a system notification."""
        self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)
