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
    from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer
    from AssetsManager.core.tag_library import get_library
    from AssetsManager.dock_factory import install_dock_refresh_handlers
    from AssetsManager.core.performance import PerformanceRecorder
    install_tag_canonicalizer(get_library().canonical)
    telemetry_enabled = AppSettings.instance().get("performance_telemetry_enabled", False)
    bootstrap = ApplicationBootstrap(
        performance_recorder=PerformanceRecorder(enabled=True) if telemetry_enabled else None
    )
    app.setProperty("bootstrap", bootstrap)
    install_dock_refresh_handlers()

    # ── Plugin Discovery / GL warm-up (deferred) ──────────────
    # Both are heavy but only needed before the first library window opens.
    # They run in a zero-delay timer AFTER the startup window is shown, so
    # the picker appears without waiting for plugin disk scans or GL
    # context creation.  Ordering guarantee: the timer is queued before
    # app.exec() starts and its callback runs synchronously to completion;
    # Qt cannot deliver user input while a slot is executing, so discovery
    # always finishes before _on_open (the only consumer of the plugin host
    # context, via MainWindow._bind_plugin_host) can fire.
    from PySide6.QtCore import QTimer

    def _deferred_startup():
        bootstrap.discover_plugins()
        app.setProperty("plugin_host_context", bootstrap.plugin_host_context)
        _warm_up_gl()

    def _warm_up_gl():
        # Eagerly warm up the OpenGL context: prevents main window flicker
        # on first ImageViewer open.
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
    app.setProperty("has_tray", tray.is_available)

    # ── Startup Window ───────────────────────────────────────
    from AssetsManager.dialogs.startup import StartupWindow
    startup = StartupWindow()

    window = None  # will be set when a library is opened

    def _on_open(path):
        nonlocal window
        from AssetsManager.i18n import tr
        from AssetsManager.window import MainWindow

        # Close previous window if re-opening a library.  A failed close
        # leaves a half-torn-down window behind; abort the reopen instead of
        # stacking a new window on top of it.
        if window is not None:
            try:
                window._force_quit = True
                window.close()
                window.deleteLater()
            except Exception:
                _log.exception("Failed to close previous window; aborting reopen")
                return
            window = None

        window = MainWindow(bootstrap)
        # A direct Startup selection is the user's current intent and takes
        # precedence over restored workspace history.
        try:
            window._workspace.add_library(path)
        except Exception as exc:
            _log.exception("Failed to open library %s", path)
            try:
                window._force_quit = True
                window.close()
                window.deleteLater()
            except Exception:
                _log.exception("Failed to discard failed library window")
            window = None
            state = bootstrap.library_service.restore_intent_status(path)
            if state is None:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.critical(
                    startup, tr("restore_marker.open_failed_title"), str(exc)
                )
                return
            from PySide6.QtWidgets import QMessageBox

            dialog = QMessageBox(startup)
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setWindowTitle(tr("restore_marker.title"))
            dialog.setText(tr("restore_marker.body"))
            retry_button = dialog.addButton(
                tr("restore_marker.retry_button"), QMessageBox.ButtonRole.AcceptRole
            )
            acknowledge_button = dialog.addButton(
                tr("restore_marker.ack_button"), QMessageBox.ButtonRole.DestructiveRole
            )
            dialog.addButton(QMessageBox.StandardButton.Cancel)
            dialog.exec()
            clicked = dialog.clickedButton()
            try:
                if clicked is retry_button:
                    bootstrap.library_service.retry_interrupted_restore(path)
                    startup._accept(path)
                elif clicked is acknowledge_button:
                    token = state.get("token")
                    if not token:
                        raise RuntimeError("Restore marker has no acknowledgement token")
                    bootstrap.library_service.acknowledge_restore_intent(path, token)
                    startup._accept(path)
            except Exception as recovery_error:
                _log.exception("Restore recovery action failed for %s", path)
                QMessageBox.critical(
                    startup, tr("restore_marker.failed_title"), str(recovery_error)
                )
            return
        window.show()
        # Surface a crash from a previous session now that a window is on
        # screen.  Deferred past show() so the dialog does not steal the
        # first paint; the crash log stays on disk for inspection either way.
        def _notify_pending_crash(owner) -> None:
            from AssetsManager.core.crash_handler import consume_pending_crash
            if not consume_pending_crash():
                return
            QMessageBox.warning(
                owner,
                tr("crash.recovered_title"),
                tr("crash.recovered_body"),
            )

        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: _notify_pending_crash(window))
        # Surface plugin load failures collected during discovery (there is no
        # GUI consumer otherwise): status-bar message for 20s + log entry.
        # Deliberately no modal dialog — a broken plugin must not block open.
        plugin_failures = bootstrap.plugin_load_failures
        if plugin_failures:
            _log.warning(
                "Plugin load failures (%d): %s",
                len(plugin_failures), ", ".join(plugin_failures))
            window.statusBar().showMessage(
                tr("app.plugin_load_failures", count=len(plugin_failures)), 20000)
        # Expose tray to window for state updates
        window._tray_manager = tray
        # The startup picker is no longer needed once a library is open.
        startup.close()

        # Auto-start sharing if enabled
        auto_start = AppSettings.instance().get("lan_auto_start", False)
        if auto_start:
            from AssetsManager import lan
            if lan.is_available():
                # Delay auto-start to allow window to fully initialize.
                # The window can be destroyed before the timer fires (user
                # re-opens another library); guard against a deleted object.
                from PySide6.QtCore import QTimer

                def _start_sharing_later(target=window):
                    if target is None:
                        return
                    try:
                        import shiboken6
                        if not shiboken6.isValid(target):
                            return
                    except ImportError:
                        pass
                    try:
                        target._toggle_sharing()
                    except Exception:
                        _log.exception("Failed to auto-start LAN sharing")

                QTimer.singleShot(1000, _start_sharing_later)

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
    # Deferred heavy work runs once the event loop is running (see the
    # ordering guarantee above the _deferred_startup definition).
    QTimer.singleShot(0, _deferred_startup)
    return app.exec()
