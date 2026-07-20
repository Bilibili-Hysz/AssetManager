"""Application entry point with startup window -> main window flow."""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from AssetsManager.core import themes
from AssetsManager.core.settings import AppSettings


def main():
    from AssetsManager.core.crash_handler import install as install_crash_handler
    install_crash_handler()

    # ── High-DPI support ─────────────────────────────────
    from PySide6.QtCore import Qt
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    if hasattr(Qt, 'HighDpiScaleFactorRoundingPolicy'):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName("AssetManager")
    app.setStyleSheet(themes.stylesheet())
    font = app.font()
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    # Apply UI scale to application font
    from AssetsManager.core.ui_scale import scaled_pt
    base_pt = font.pointSize()
    app.setProperty("base_font_size", base_pt)
    font.setPointSize(scaled_pt(base_pt))
    app.setFont(font)

    from AssetsManager import i18n
    i18n.init()

    # ── Service Bootstrap ───────────────────────────────────────
    import logging
    _log = logging.getLogger(__name__)

    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.dock_factory import install_dock_refresh_handlers
    from AssetsManager.core.performance import PerformanceRecorder
    telemetry_enabled = AppSettings.instance().get("performance_telemetry_enabled", False)
    bootstrap = ApplicationBootstrap(
        performance_recorder=PerformanceRecorder(enabled=True) if telemetry_enabled else None
    )
    app.setProperty("bootstrap", bootstrap)
    install_dock_refresh_handlers()

    # ── Plugin Discovery ──────────────────────────────────────
    bootstrap.discover_plugins()
    app.setProperty("plugin_host_context", bootstrap.plugin_host_context)

    # ── Eagerly warm up OpenGL context ──────────────────────
    # Prevents main window flicker on first ImageViewer open.
    try:
        from PySide6.QtOpenGLWidgets import QOpenGLWidget
        _gl = QOpenGLWidget()
        _gl.setVisible(False)
        _gl.resize(1, 1)
        _gl.grabFramebuffer()
    except Exception:
        pass

    # ── System Tray ──────────────────────────────────────────
    from AssetsManager.widgets.tray import SystemTrayManager
    icon_path = str(Path(__file__).resolve().parent.parent / "assets" / "icons" / "icon.ico")
    tray = SystemTrayManager(icon_path)
    app.setProperty("has_tray", True)

    # ── Startup Window ───────────────────────────────────────
    from AssetsManager.dialogs.startup import StartupWindow
    startup = StartupWindow()

    window = None  # will be set when a library is opened

    def _on_open(path):
        nonlocal window
        from AssetsManager.window import MainWindow

        # Close previous window if re-opening a library
        if window is not None:
            try:
                window._force_quit = True
                window.close()
                window.deleteLater()
            except Exception:
                pass
            window = None

        window = MainWindow(bootstrap)
        # window.__init__ already restores workspace tabs via _restore_workspace_tabs().
        # If no saved tabs, add the startup-selected path.
        if not window._workspace.tab_paths():
            window._workspace.add_library(path)
        window.show()
        # Expose tray to window for state updates
        window._tray_manager = tray

        # Auto-start sharing if enabled
        auto_start = AppSettings.instance().get("lan_auto_start", False)
        if auto_start:
            from AssetsManager import lan
            if lan.is_available():
                # Delay auto-start to allow window to fully initialize
                from PySide6.QtCore import QTimer
                QTimer.singleShot(1000, window._toggle_sharing)

    # Connect tray signals once (outside _on_open to avoid accumulation)
    def _tray_show():
        if window is not None:
            window.show()
        else:
            startup.show()

    def _open_browser():
        if window is not None and hasattr(window, '_lan_server') and window._lan_server and window._lan_server.is_running():
            status = window._lan_server.status()
            url = status.get("url", "")
            if url:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl(url))

    tray.show_requested.connect(_tray_show)
    tray.open_browser.connect(_open_browser)
    tray.toggle_sharing.connect(lambda: window._toggle_sharing() if window else None)
    def _tray_exit():
        if window is not None:
            window.request_exit()
        app.quit()
    tray.exit_requested.connect(_tray_exit)

    startup.library_opened.connect(_on_open)
    startup.show()
    return app.exec()
