"""Main window — QDockWidget-based docking layout with workspace tab bar."""
import logging
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, QSize, Signal
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QApplication,
    QLabel,
    QPushButton,
    QStatusBar,
    QProgressDialog,
)

from AssetsManager import dock_factory as dock
from AssetsManager.core import themes
from AssetsManager.core import icons
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_pt, scaled_px
from AssetsManager.core.settings import AppSettings
from AssetsManager import i18n
from AssetsManager.dialogs.startup import StartupWindow
from AssetsManager.core.database import clean_orphan_dirs
from AssetsManager.widgets.workspace_bar import WorkspaceSection
from AssetsManager.widgets.lan_sharing import LanSharingMixin
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager.lan.ports import LanDesktopAdapter, build_lan_server

_log = logging.getLogger(__name__)
tr = i18n.tr


try:
    import shiboken6
    _shiboken6 = shiboken6
except ImportError:
    _shiboken6 = None


def _alive(widget) -> bool:
    """True while a C++-backed widget has not yet been destroyed."""
    try:
        if widget is None:
            return False
        if _shiboken6 is not None:
            return _shiboken6.isValid(widget)
        return widget.winId() is not None
    except Exception:
        return False


def _save_window_geometry(window: QWidget) -> None:
    """Persist window geometry and maximized state to AppSettings.

    A maximized window is temporarily restored to its normal size before
    saveGeometry() so the persisted rect is the windowed geometry; the
    maximized state is saved separately and re-applied on restore.
    """
    settings = AppSettings.instance()
    try:
        was_maximized = window.isMaximized()
        if was_maximized:
            window.showNormal()
        settings.set("window_geometry", bytes(window.saveGeometry().data()).hex())
        settings.set("window_maximized", was_maximized)
        settings.save()
    except Exception:
        _log.exception("Failed to save window geometry")


class _ImportProgressDialog(QProgressDialog):
    """Progress dialog that treats window dismissal as import cancellation."""

    user_closed = Signal()

    def closeEvent(self, event):
        if not self.property("import_finished") and not self.property(
            "import_cancel_requested"
        ):
            self.user_closed.emit()
        super().closeEvent(event)


def _restore_window_geometry(window: QWidget) -> None:
    """Restore window geometry and maximized state saved last session.

    Malformed persisted data is ignored so a hand-edited settings file
    cannot prevent the window from starting.
    """
    try:
        settings = AppSettings.instance()
        geom = settings.get("window_geometry")
        if isinstance(geom, str) and geom:
            window.restoreGeometry(bytes.fromhex(geom))
        if settings.get("window_maximized"):
            window.showMaximized()
    except (TypeError, ValueError):
        _log.warning("Ignoring malformed saved window geometry", exc_info=True)


class MainWindow(LanSharingMixin, QMainWindow):
    def __init__(
        self, bootstrap, library_session=None, *,
        lan_server_factory=None, sharing_port=None,
    ):
        super().__init__()
        from AssetsManager.window_coordinator import WindowCoordinator
        from AssetsManager.window_lifecycle_coordinator import WindowLifecycleCoordinator
        self._coordinator = WindowCoordinator(self)
        self.setWindowTitle(tr("app.name"))
        self.resize(1200, 800)
        _restore_window_geometry(self)
        self.setDockNestingEnabled(True)
        self._bg_cache: tuple = ("", None, None)  # (path, processed_raw, scaled)
        self._bg_effects_cache_key: str = ""  # effect:intensity string
        self._bg_dirty = False
        self._bg_resize_timer = QTimer(self)
        self._bg_resize_timer.setSingleShot(True)
        self._bg_resize_timer.setInterval(150)
        self._bg_resize_timer.timeout.connect(self._on_bg_resize_done)
        themes.apply_to(self)
        self._bootstrap = bootstrap
        self._lifecycle_coordinator = WindowLifecycleCoordinator(self, _alive)
        self._import_generation = 0
        self._import_token = None
        self._import_pool = None
        self._import_task = None
        self._import_dialog = None
        # Must be set before UI setup because workspace restore can switch libraries.
        self._library_session = library_session
        self._setup_ui()
        self._bind_plugin_host()
        self._connect_bus()
        self._startup_anim_done = False
        self._force_quit = False
        self._lan_server = None
        # G2: the window is the composition root for presentation LAN ports.
        # Widgets/dialogs only see these injected boundaries, never lan.*.
        self._lan_server_factory = (
            lan_server_factory if lan_server_factory is not None else build_lan_server
        )
        self._sharing_port = (
            sharing_port if sharing_port is not None else LanDesktopAdapter()
        )

    def _library_service(self):
        return self._bootstrap.library_service

    def _open_library_session(self, path):
        session = self._library_service().open_session(path)
        self._library_session = session
        return session

    def _scoped_services_for_session(self, session):
        return self._bootstrap.runtime_for(session).services

    def _cleanup_import(self, generation=None, *, close_dialog=True, timeout_ms=3_000):
        """Cancel and terminally release the current import worker resources."""
        current_generation = self._import_generation
        if generation is not None and generation != current_generation:
            return False
        self._import_generation = current_generation + 1
        token = self._import_token
        pool = self._import_pool
        dialog = self._import_dialog
        self._import_token = None
        self._import_pool = None
        self._import_task = None
        self._import_dialog = None
        if token is not None:
            token.cancel()
        if pool is not None:
            try:
                pool.close(timeout_ms, owner_label="MainWindow import")
            except Exception:
                _log.exception("Failed to close import worker pool")
        if close_dialog and _alive(dialog):
            try:
                dialog.close()
            except RuntimeError:
                pass
        return True

    def _apply_scoped_services(self, session):
        runtime = self._bootstrap.runtime_for(session)
        scoped = runtime.services
        if scoped is None:
            return
        integrity_service = getattr(scoped, "integrity_service", None)
        if integrity_service is not None:
            if integrity_service.schedule() is False:
                _log.warning(
                    "Automatic library integrity check was not scheduled for %s: %s",
                    getattr(session, "root", session),
                    getattr(integrity_service, "last_schedule_error", "unknown"),
                )
        for panel in (
            getattr(self, "file_list", None),
            getattr(self, "info", None),
            getattr(self, "sidebar", None),
        ):
            set_services = getattr(panel, "set_scoped_services", None)
            if _alive(panel) and callable(set_services):
                set_services(scoped)
        tag_tree = getattr(self, "tag_tree", None)
        set_runtime = getattr(type(tag_tree), "set_runtime", None) if tag_tree is not None else None
        set_tag_services = getattr(tag_tree, "set_scoped_services", None)
        if _alive(tag_tree):
            if callable(set_runtime):
                set_runtime(tag_tree, runtime)
            elif callable(set_tag_services):
                set_tag_services(scoped)

    def showEvent(self, event):
        """Override to add startup fade-in animation."""
        super().showEvent(event)
        if not self._startup_anim_done:
            self._startup_anim_done = True
            self.setWindowOpacity(0.0)
            anim = QPropertyAnimation(self, b"windowOpacity")
            anim.setDuration(300)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start()
            self._startup_anim = anim

    # ── Background image ───────────────────────────────────

    def paintEvent(self, event):
        if themes.bg_enabled():
            path = themes.bg_image()
            opacity = themes.bg_overall_opacity()
            if path and Path(path).is_file():
                effect = themes.bg_effect()
                intensity = themes.bg_effect_intensity()
                effects_key = f"{effect}:{intensity}"
                # Load raw pixmap once per path change
                if self._bg_cache[0] != path or not self._bg_cache[1]:
                    pm = QPixmap(path)
                    if pm.isNull():
                        self._bg_cache = ("", None, None)
                    else:
                        processed = self._apply_bg_effects(pm, effect, intensity)
                        self._bg_cache = (path, processed, None)
                        self._bg_effects_cache_key = effects_key
                elif self._bg_effects_cache_key != effects_key:
                    pm = QPixmap(path)
                    if not pm.isNull():
                        processed = self._apply_bg_effects(pm, effect, intensity)
                        self._bg_cache = (path, processed, None)
                        self._bg_effects_cache_key = effects_key
                processed = self._bg_cache[1]
                scaled = self._bg_cache[2]
                w, h = self.width(), self.height()
                # M6: while a resize drag is in flight (_bg_dirty), skip the
                # expensive smooth scale and draw the raw pixmap each frame;
                # the final scale is computed once when the resize timer fires.
                if processed and scaled is None and not self._bg_dirty:
                    scaled = processed.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    self._bg_cache = (self._bg_cache[0], processed, scaled)
                if processed:
                    p = QPainter(self)
                    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                    p.setOpacity(opacity)
                    src = scaled if scaled else processed
                    p.drawPixmap((w - src.width()) // 2, (h - src.height()) // 2, src)
                    p.end()
        super().paintEvent(event)

    @staticmethod
    def _apply_bg_effects(pixmap, effect, intensity):
        """Apply a single effect to a pixmap."""
        result = pixmap
        if effect == "blur" and intensity > 0:
            from AssetsManager.core.bg_effects import apply_blur
            result = apply_blur(result, intensity)
        elif effect == "mosaic" and intensity > 1:
            from AssetsManager.core.bg_effects import apply_mosaic
            result = apply_mosaic(result, intensity)
        return result

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._bg_dirty = True
        self._bg_cache = (self._bg_cache[0], self._bg_cache[1], None)
        self._bg_resize_timer.start()

    def _on_bg_resize_done(self):
        self._bg_dirty = False
        self._bg_cache = (self._bg_cache[0], self._bg_cache[1], None)
        self.update()

    def refresh_bg(self):
        self._bg_cache = ("", None, None)
        self._bg_dirty = False
        self.update()

    def _on_bg_style_changed(self):
        """Re-apply stylesheet and refresh title-bars when bg opacity changes."""
        app = QApplication.instance()
        if isinstance(app, QApplication):
            themes.apply_to(app)
        self._apply_menu_theme()
        from AssetsManager import dock_factory as dk
        for dock_widget, (_i18n_key, _title, _extra_buttons) in dk._DOCK_TITLES.items():
            try:
                bar = dock_widget.titleBarWidget()
                if bar and bar.property("is_custom_title"):
                    bar.setStyleSheet(
                        f"background: {themes.header_for_dock()}; "
                        f"border: 1px solid {themes.get()['border']}; "
                        f"border-top-left-radius: {scaled_px(7)}px; border-top-right-radius: {scaled_px(7)}px; ")
            except RuntimeError:
                # L10: the dock was deleted while the theme change propagated.
                continue
        self._workspace._apply_style()
        refresh_header = getattr(self.file_list, "refresh_header", None)
        if callable(refresh_header):
            refresh_header()
        self.refresh_bg()

    def _setup_menu(self):
        bar = self._menu_bar
        self._menu_lib = bar.addMenu(tr("menu.library"))
        self._menu_act_open = self._menu_lib.addAction(tr("menu.open_library"), self._open_library)
        self._menu_lib.addSeparator()
        self._recent_menu = self._menu_lib.addMenu(tr("menu.recent_libraries"))
        self._recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        self._menu_lib.addSeparator()
        self._menu_act_refresh = self._menu_lib.addAction(tr("menu.refresh"), self._refresh_all)
        self._menu_lib.addSeparator()
        self._menu_act_backup = self._menu_lib.addAction(tr("menu.backup_library"), self._backup_library)
        self._menu_act_restore = self._menu_lib.addAction(tr("menu.restore_library"), self._restore_library)
        self._menu_act_import = self._menu_lib.addAction(tr("menu.import_assets"), self._import_assets)
        self._menu_lib.addSeparator()
        # A real exit even when the system tray makes close() hide instead.
        self._menu_act_exit = self._menu_lib.addAction(tr("menu.exit"), self.request_exit)
        self._menu_act_settings = bar.addAction(tr("menu.settings"), self._open_settings)

        # Tools menu
        self._setup_tools_menu(bar)

        # Hide native menu bar since we have our own in the menu widget
        self.menuBar().hide()

    def _setup_tools_menu(self, bar):
        from AssetsManager.core.tool_scheduler import list_tools, run_tool
        self._menu_tools = bar.addMenu(tr("menu.tools"))
        tools_menu = self._menu_tools
        self._tools_menu_icon_specs: list[tuple] = []

        # External tools
        tools = list_tools()
        for t in tools:
            name = t.get("name", "Tool")
            action = tools_menu.addAction(name,
                lambda checked, tool=t: run_tool(tool,
                    file_path=getattr(self.file_list, '_current', str(Path.home()))))
            icon_name = t.get("icon_name") or t.get("icon")
            action.setIcon(icons.icon(icon_name, color="icon_primary", size=scaled_px(16), fallback="wrench"))
            self._tools_menu_icon_specs.append((action, icon_name, "wrench"))

        # Plugin Manager
        tools_menu.addSeparator()
        self._menu_act_plugin_manager = tools_menu.addAction(
            tr("menu.plugin_manager"), self._open_plugin_manager)
        self._menu_act_plugin_manager.setIcon(
            icons.icon("puzzle", color="icon_primary", size=scaled_px(16)))
        self._tools_menu_icon_specs.append((self._menu_act_plugin_manager, "puzzle", "puzzle"))

        # Plugin contributions
        app = QApplication.instance()
        if isinstance(app, QApplication):
            plugin_ctx = app.property("plugin_host_context")
            if plugin_ctx:
                contributions = plugin_ctx.menu_contributions("tools")
                if contributions:
                    tools_menu.addSeparator()
                    for contrib in contributions:
                        title = getattr(contrib, 'title', None) or getattr(contrib, 'id', 'Plugin')
                        cmd_id = getattr(contrib, 'command_id', None)
                        if isinstance(cmd_id, str):
                            action = tools_menu.addAction(title,
                                lambda checked, cid=cmd_id: self._run_plugin_command(cid))
                            action.setIcon(icons.icon("puzzle", color="icon_primary", size=scaled_px(16)))
                            available = getattr(plugin_ctx, "command_available", None)
                            if callable(available):
                                action.setEnabled(bool(available(cmd_id)))
                            self._tools_menu_icon_specs.append((action, "puzzle", "puzzle"))

        # LAN Sharing
        tools_menu.addSeparator()
        from AssetsManager import lan
        if lan.is_available():
            self._menu_act_share = tools_menu.addAction(tr('menu.share_system'), self._open_sharing_settings)
        else:
            self._menu_act_share_unavailable = tools_menu.addAction(tr("menu.sharing_unavailable"))
            self._menu_act_share_unavailable.setEnabled(False)
            self._menu_act_share_unavailable.setToolTip(tr("menu.sharing_install_hint"))

        # Keyboard Shortcuts
        tools_menu.addSeparator()
        self._menu_act_shortcuts = tools_menu.addAction(tr("menu.keyboard_shortcuts"), self._show_shortcuts)

    def _setup_ui(self):
        from PySide6.QtWidgets import QMenuBar, QHBoxLayout, QSpacerItem, QSizePolicy
        self._menu_widget = QWidget()
        layout = QHBoxLayout(self._menu_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._menu_bar = QMenuBar()
        self._menu_bar.setNativeMenuBar(False)
        self._apply_menu_theme()
        layout.addWidget(self._menu_bar)

        # Spacers for dynamic workspace positioning
        self._ws_left = QSpacerItem(10, 1, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        layout.addSpacerItem(self._ws_left)

        self._workspace = WorkspaceSection()
        self._workspace.library_switched.connect(self._on_switch_library)
        self._workspace.add_requested.connect(self._open_library)
        self._workspace.setMinimumWidth(scaled_px(80))
        layout.addWidget(self._workspace)

        self._ws_right = QSpacerItem(10, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addSpacerItem(self._ws_right)

        # Share toggle button in menu bar
        self._share_toggle_btn = QPushButton()
        self._share_toggle_btn.setIcon(icons.icon("share", color="icon_primary", size=scaled_px(16)))
        self._share_toggle_btn.setIconSize(QSize(scaled_px(16), scaled_px(16)))
        self._share_toggle_btn.setToolTip(tr("sharing.toggle_tooltip"))
        self._share_toggle_btn.setAccessibleName(tr("sharing.toggle_tooltip"))
        self._share_toggle_btn.setFixedSize(scaled_px(28), scaled_px(28))
        self._share_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        themes.set_button_variant(self._share_toggle_btn, "ghost")
        btn_radius = scaled_px(int(themes.prop("border_radius", "sm")))
        btn_hover = alpha(themes.get()["hover_overlay"], themes.prop("opacity", "hover"))
        self._share_toggle_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; }}"
            f"QPushButton:hover {{ background: {btn_hover}; border-radius: {btn_radius}px; }}"
            f"QPushButton:pressed {{ background: {alpha(themes.get()['accent'], 0.18)}; border-radius: {btn_radius}px; }}"
        )
        self._share_toggle_btn.clicked.connect(self._toggle_sharing)
        layout.addWidget(self._share_toggle_btn)
        self._setup_menu()
        self.setMenuWidget(self._menu_widget)
        self._menu_widget.resizeEvent = self._on_menu_row_resize

        # ── Central panel ────────────────────────────────────────
        self.file_list = self._create_file_list_panel()
        self.setCentralWidget(self.file_list)

        # ── Docks ───────────────────────────────────────────────
        self.sidebar_dock = dock.create(tr("dock.sidebar"), self, Qt.DockWidgetArea.LeftDockWidgetArea,
                                         panel_type="sidebar")
        from AssetsManager.panels.sidebar import SidebarPanel
        self.sidebar = self.sidebar_dock.widget()
        if not isinstance(self.sidebar, SidebarPanel):
            raise RuntimeError("Sidebar dock did not create SidebarPanel")

        self.info_dock = dock.create(tr("dock.info"), self, Qt.DockWidgetArea.RightDockWidgetArea,
                                       panel_type="info")
        from AssetsManager.panels.info import InfoPanel
        self.info = self.info_dock.widget()
        if not isinstance(self.info, InfoPanel):
            raise RuntimeError("Info dock did not create InfoPanel")

        # ── Status bar ──────────────────────────────────────────
        self._setup_status_bar()

        self._restore_dock_layout()
        self._restore_workspace_tabs()

        self.sidebar.directory_selected.connect(self._on_sidebar_navigate)
        self.file_list.file_double_clicked.connect(self._on_file_double_clicked)
        self.info.open_requested.connect(self._on_file_double_clicked)
        self.info.copy_path_requested.connect(self._copy_to_clipboard)
        self.info.view_fullscreen.connect(self._switch_to_viewer)
        self.info.navigate_requested.connect(self._on_sidebar_navigate)

    @staticmethod
    def _create_file_list_panel():
        from AssetsManager.panels.file_list import FileListPanel
        return FileListPanel()

    def _setup_status_bar(self):
        """Setup status bar with share indicator."""
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        # Share status indicator
        self._share_status_label = QLabel(tr("sharing.off"))
        t = themes.get()
        self._share_status_label.setStyleSheet(f"color: {t['muted']}; padding: 0 {scaled_px(8)}px;")
        self._share_status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._share_status_label.mousePressEvent = self._on_share_status_clicked
        status_bar.addPermanentWidget(self._share_status_label)

        # Tooltip-reset timer: restores the click-to-copy tooltip after the
        # URL-copied hint expires.  A member QTimer (instead of a bare
        # QTimer.singleShot lambda) so the timeout can never fire against a
        # destroyed window, and the shutdown path can stop it explicitly.
        self._share_status_timer = QTimer(self)
        self._share_status_timer.setSingleShot(True)
        self._share_status_timer.setInterval(2000)
        self._share_status_timer.timeout.connect(self._reset_share_status_tooltip)

        # Apply theme
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        status_bar.setStyleSheet(sk.status_bar_css())

    def _apply_status_bar_theme(self):
        t = themes.get()
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self._share_status_label.setStyleSheet(f"color: {t['muted']}; padding: 0 {scaled_px(8)}px;")
        self.statusBar().setStyleSheet(sk.status_bar_css())

    def _on_share_status_clicked(self, event):
        """Handle click on share status indicator."""
        if self._lan_server and self._lan_server.is_running():
            # Copy URL to clipboard
            from PySide6.QtWidgets import QApplication
            from AssetsManager.lan.server import get_local_ip
            ip = get_local_ip()
            port = self._lan_server._port
            url = f"http://{ip}:{port}"
            QApplication.clipboard().setText(url)
            self._share_status_label.setToolTip(tr("sharing.url_copied_tooltip"))
            self._share_status_timer.start()
        else:
            # Open sharing settings
            self._open_sharing_settings()

    def _reset_share_status_tooltip(self):
        """Restore the default share-status tooltip after the hint expires."""
        if not _alive(self._share_status_label):
            return
        self._share_status_label.setToolTip(tr("sharing.click_to_copy"))

    def _connect_bus(self):
        b = bus()
        b.directory_changed.connect(self._on_dir_selected)
        b.file_focused.connect(self._on_file_focused_safe)
        b.theme_changed.connect(lambda _: self._on_theme_refresh())
        b.language_changed.connect(self._refresh_language)
        b.ui_scale_changed.connect(self._on_ui_scale_changed)

    # ── Workspace switching ────────────────────────────────────

    def _on_switch_library(self, path):
        """Switch all panels to a different library root."""
        workspace = getattr(self, "_workspace", None)
        previous = workspace.current_library() if workspace is not None else None
        try:
            self._lifecycle_coordinator.switch_library(path)
        except Exception as exc:
            # The coordinator rolls back library sessions itself; also
            # re-point the workspace tab bar at the previous library so the
            # UI does not stay on a tab whose session failed to open.
            _log.exception("Library switch to %s failed", path)
            self._reselect_workspace_tab(previous)
            from AssetsManager.window_lifecycle_coordinator import _notify_switch_failed
            _notify_switch_failed(self, f"The library switch failed: {exc}")

    def _reselect_workspace_tab(self, path):
        """Re-select the workspace tab for ``path`` if it is still present."""
        if not path:
            return
        tabs = getattr(getattr(self, "_workspace", None), "_tabs", None)
        if tabs is None:
            return
        idx = tabs.find_tab(path)
        if idx >= 0 and idx != tabs.currentIndex():
            tabs.setCurrentIndex(idx)

    def _open_library(self):
        startup = StartupWindow(self)
        def _on_open(path):
            # Workspace switching owns session creation. add_library emits
            # synchronously, so opening a session here would double-open it.
            self._workspace.add_library(path)
            clean_orphan_dirs([path])
            # Save recent
            settings = AppSettings.instance()
            settings.prepend_list("recent_libraries", str(Path(path).resolve()), max_items=10)
            settings.save()
            from AssetsManager.core.library_manager import record_visit
            record_visit(str(Path(path).resolve()))
            startup.close()
        startup.library_opened.connect(_on_open)
        startup.show()

    def _open_path(self, path):
        self._workspace.add_library(path)

    def _rebuild_recent_menu(self):
        self._recent_menu.clear()
        settings = AppSettings.instance()
        recents = settings.get_list("recent_libraries", [])
        if not recents:
            self._recent_menu.addAction(tr("menu.recent_empty")).setEnabled(False)
            return
        for p in recents:
            path = Path(p)
            label = f"{path.name} — {p}"
            if len(label) > 60:
                label = label[:57] + "..."
            self._recent_menu.addAction(label,
                                         lambda checked, p=p: self._open_path(p))

    def _on_sidebar_navigate(self, path):
        if _alive(self.file_list):
            self.file_list.navigate_to(path)

    # ── Events ─────────────────────────────────────────────────

    def _on_menu_row_resize(self, event):
        """Position workspace between menus and right edge.

        Left:  max(20% width, last menu right + 20px) — never overlap menus.
        Right: min(80% width, width - 40px) — leave right margin.
        When squeezed, clip workspace rather than hide.
        """
        QWidget.resizeEvent(self._menu_widget, event)
        w = self._menu_widget.width()
        if w <= 0:
            return
        menu_w = self._menu_bar.sizeHint().width() + 10
        left_bound = max(int(w * 0.20), menu_w + 20)
        right_bound = min(int(w * 0.80), w - 40)
        avail = max(right_bound - left_bound, 0)
        self._workspace.setVisible(avail > 0)
        self._ws_left.changeSize(left_bound - menu_w, 1)
        self._workspace.setFixedWidth(max(avail, 0))
        menu_layout = self._menu_widget.layout()
        if menu_layout is not None:
            menu_layout.activate()

    def _apply_menu_theme(self):
        self._coordinator.apply_menu_theme()

    def _on_theme_refresh(self):
        self._coordinator.on_theme_refresh()

    def _refresh_ui_icons(self):
        if hasattr(self, "_share_toggle_btn"):
            server = getattr(self, "_lan_server", None)
            running = bool(server is not None and server.is_running())
            icon_name = "close" if running else "share"
            self._share_toggle_btn.setIcon(
                icons.icon(icon_name, color="icon_primary", size=scaled_px(16)))
            self._share_toggle_btn.setIconSize(QSize(scaled_px(16), scaled_px(16)))
        self._refresh_tools_menu_icons()

    def _refresh_tools_menu_icons(self):
        """Retint tools-menu action icons after a theme change."""
        tint = "icon_primary"
        for action, icon_name, fallback in getattr(self, "_tools_menu_icon_specs", ()):
            if action is None or not _alive(action):
                continue
            action.setIcon(
                icons.icon(icon_name, color=tint, size=scaled_px(16), fallback=fallback))


    def _refresh_language(self, _code: str = ""):
        self.setWindowTitle(tr("app.name"))
        self._menu_lib.setTitle(tr("menu.library"))
        self._menu_act_open.setText(tr("menu.open_library"))
        self._recent_menu.setTitle(tr("menu.recent_libraries"))
        self._menu_act_refresh.setText(tr("menu.refresh"))
        self._menu_act_exit.setText(tr("menu.exit"))
        self._menu_act_settings.setText(tr("menu.settings"))
        if hasattr(self, '_menu_tools'):
            self._menu_tools.setTitle(tr("menu.tools"))
        if hasattr(self, '_menu_act_plugin_manager'):
            self._menu_act_plugin_manager.setText(tr("menu.plugin_manager"))
        if hasattr(self, '_menu_act_share'):
            self._menu_act_share.setText(tr('menu.share_system'))
        if hasattr(self, '_menu_act_share_unavailable'):
            self._menu_act_share_unavailable.setText(tr("menu.sharing_unavailable"))
            self._menu_act_share_unavailable.setToolTip(tr("menu.sharing_install_hint"))
        if hasattr(self, '_menu_act_shortcuts'):
            self._menu_act_shortcuts.setText(tr("menu.keyboard_shortcuts"))
        if hasattr(self, '_menu_act_backup'):
            self._menu_act_backup.setText(tr("menu.backup_library"))
        if hasattr(self, '_menu_act_restore'):
            self._menu_act_restore.setText(tr("menu.restore_library"))
        if hasattr(self, '_menu_act_import'):
            self._menu_act_import.setText(tr("menu.import_assets"))
        if hasattr(self, '_share_toggle_btn'):
            self._share_toggle_btn.setToolTip(tr("sharing.toggle_tooltip"))
            self._share_toggle_btn.setAccessibleName(tr("sharing.toggle_tooltip"))

    @staticmethod
    def _dock_widths_state(ctx) -> dict:
        """Snapshot sidebar/info dock widths for PanelState."""
        sizes = []
        for d in (ctx.sidebar_dock, ctx.info_dock):
            if _alive(d):
                panel = d.widget()
                if _alive(panel):
                    sizes.append(panel.width())
        return {"sizes": sizes}

    @staticmethod
    def _restore_dock_widths(ctx, state: dict) -> None:
        """Apply persisted dock widths."""
        sizes = state.get("sizes") if isinstance(state, dict) else None
        if isinstance(sizes, list) and len(sizes) == 2:
            docks = [ctx.sidebar_dock, ctx.info_dock]
            for d, w in zip(docks, sizes, strict=True):
                panel = d.widget() if _alive(d) else None
                if not isinstance(panel, QWidget) or not _alive(panel):
                    continue
                # L9: a fixed minimum keeps narrow restores usable without
                # pinning the panel to half the saved width; the saved width
                # is applied directly via resize().
                qpanel = cast(QWidget, panel)
                qpanel.setMinimumWidth(scaled_px(120))
                qpanel.resize(w, qpanel.height())

    def _save_dock_layout(self):
        """Save dock sizes and panel view state for session restore."""
        from AssetsManager.panels.panel_state import PanelState

        PanelState("dock_widths", save=self._dock_widths_state,
                   restore=self._restore_dock_widths).persist(self)
        persist = getattr(self.file_list, "persist_panel_state", None)
        if callable(persist):
            persist()
        persist_sidebar = getattr(self.sidebar, "persist_panel_state", None)
        if callable(persist_sidebar):
            persist_sidebar()

    def _save_workspace_tabs(self):
        from AssetsManager.panels.panel_state import PanelState

        PanelState("workspace_tabs").persist(self._workspace)

    def _restore_workspace_tabs(self):
        from AssetsManager.panels.panel_state import PanelState

        PanelState("workspace_tabs").load(self._workspace)

    def _restore_dock_layout(self):
        """Restore dock sizes and panel view state from previous session."""
        from AssetsManager.panels.panel_state import PanelState

        PanelState("dock_widths", save=self._dock_widths_state,
                   restore=self._restore_dock_widths).load(self)
        restore = getattr(self.file_list, "restore_panel_state", None)
        if callable(restore):
            restore()

    def _on_dir_selected(self, path):
        self.setWindowTitle(f"{tr('app.name')} — {path}")

    def _on_file_focused_safe(self, info):
        update_info = getattr(self.info, "update_info", None)
        if _alive(self.info) and callable(update_info):
            update_info(info)

    def _on_file_double_clicked(self, path):
        import os
        if os.path.exists(path):
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _switch_to_viewer(self, path):
        """Open image in floating overlay viewer."""
        from AssetsManager.panels.image_viewer import open_image_viewer
        from AssetsManager.core.constants import IMAGE_EXTS
        if not Path(path).is_file():
            return
        if Path(path).suffix.lower() not in IMAGE_EXTS:
            return
        flush_pending = getattr(self.info, "flush_pending_changes", None)
        if _alive(self.info) and callable(flush_pending):
            flush_pending()
        session = getattr(self, "_library_session", None)
        library_root = getattr(session, "root_str", None) if session is not None else None
        open_image_viewer(self, path, library_root=library_root)

    def _refresh_all(self):
        populate = getattr(self.sidebar, "_populate", None)
        if _alive(self.sidebar) and callable(populate):
            populate()
        refresh_contents = getattr(self.file_list, "refresh_contents", None)
        if _alive(self.file_list) and callable(refresh_contents):
            refresh_contents()

    @staticmethod
    def _copy_to_clipboard(path: str):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(path)

    def _open_plugin_manager(self):
        from AssetsManager.dialogs.plugin_manager_dialog import PluginManagerDialog
        dlg = PluginManagerDialog(self)
        dlg.exec()

    def _show_shortcuts(self):
        from PySide6.QtWidgets import QMessageBox
        lines = [
            f"<b>{tr('shortcuts.group_global')}</b>",
            f"Ctrl+Tab — {tr('shortcuts.next_tab')}",
            f"Ctrl+Shift+Tab — {tr('shortcuts.prev_tab')}",
            "",
            f"<b>{tr('shortcuts.group_sidebar')}</b>",
            f"Ctrl+F — {tr('shortcuts.sidebar_search')}",
            f"Ctrl+Shift+F — {tr('shortcuts.sidebar_add_fav')}",
            f"Escape — {tr('shortcuts.sidebar_clear')}",
            f"Delete — {tr('shortcuts.sidebar_delete')}",
            "",
            f"<b>{tr('shortcuts.group_filelist')}</b>",
            f"Ctrl+F — {tr('shortcuts.filelist_filter')}",
            f"Ctrl+C — {tr('shortcuts.filelist_copy')}",
            f"Ctrl+X — {tr('shortcuts.filelist_cut')}",
            f"Ctrl+V — {tr('shortcuts.filelist_paste')}",
            f"Ctrl+Z — {tr('shortcuts.filelist_undo')}",
            f"Delete — {tr('shortcuts.filelist_delete')}",
            f"F2 — {tr('shortcuts.filelist_rename')}",
        ]
        QMessageBox.information(self, tr("shortcuts.title"), "<br>".join(lines))

    def _open_settings(self):
        from AssetsManager.application.library_settings_adapter import LibrarySettingsAdapter
        from AssetsManager.dialogs.settings_dialog import SettingsDialog

        dlg = SettingsDialog(self)
        session = getattr(self, "_library_session", None)
        if session is not None:
            scoped = self._scoped_services_for_session(session)
            dlg.set_library_settings_adapter(LibrarySettingsAdapter(scoped))
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            themes.apply_to(self)

    def _backup_library(self):
        """Back up the current library's RuntimeData to a portable archive."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        session = getattr(self, "_library_session", None)
        if session is None:
            QMessageBox.information(self, tr("backup.title"), tr("backup.no_library"))
            return
        scoped = self._scoped_services_for_session(session)
        service = scoped.export_service
        default_name = service.backup_filename(session.root)
        destination, _selected = QFileDialog.getSaveFileName(
            self,
            tr("backup.choose_destination"),
            str(Path(session.root) / default_name),
            tr("backup.file_filter"),
        )
        if not destination:
            return
        try:
            result = service.create_backup(session.root, destination)
        except Exception as exc:
            QMessageBox.critical(
                self, tr("backup.title"), tr("backup.failed").format(error=exc)
            )
            return
        QMessageBox.information(
            self,
            tr("backup.title"),
            tr("backup.success").format(
                path=result.destination,
                files=result.file_count,
                size=result.bytes_written,
            ),
        )

    def _restore_library(self):
        """Restore the current library's RuntimeData from a backup archive."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        session = getattr(self, "_library_session", None)
        if session is None:
            QMessageBox.information(self, tr("restore.title"), tr("restore.no_library"))
            return
        archive, _selected = QFileDialog.getOpenFileName(
            self,
            tr("restore.choose_archive"),
            str(Path.home()),
            tr("restore.file_filter"),
        )
        if not archive:
            return
        answer = QMessageBox.warning(
            self,
            tr("restore.title"),
            tr("restore.confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        scoped = self._scoped_services_for_session(session)
        try:
            result = scoped.export_service.restore_backup(
                archive, session.root, overwrite_existing=True
            )
        except Exception as exc:
            QMessageBox.critical(
                self, tr("restore.title"), tr("restore.failed").format(error=exc)
            )
            return
        QMessageBox.information(
            self,
            tr("restore.title"),
            tr("restore.success").format(path=result.data_dir),
        )

    def _import_assets(self):
        """Import files/folders into the current library via a background task."""
        from PySide6.QtCore import QObject, Signal
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        session = getattr(self, "_library_session", None)
        if session is None:
            QMessageBox.information(self, tr("import.title"), tr("import.no_library"))
            return
        scoped = self._scoped_services_for_session(session)
        file_operations = scoped.file_operation_service

        current_dir = getattr(self.file_list, "_current", None)
        default_dir = str(Path(current_dir) if current_dir else session.root)

        sources, _selected = QFileDialog.getOpenFileNames(
            self,
            tr("import.choose_sources"),
            str(Path.home()),
        )
        sources = cast(list[str | Path], sources)
        if not sources:
            return
        destination = QFileDialog.getExistingDirectory(
            self,
            tr("import.choose_destination"),
            default_dir,
        )
        if not destination:
            return

        from AssetsManager.application.import_service import ImportCancelled, ImportService
        from AssetsManager.core.workers import BoundedPool, CancellationToken, CancellableRunnable
        if self._import_pool is not None or self._import_token is not None:
            self._cleanup_import()
        service = ImportService(session, file_operations)
        import_token = CancellationToken()
        self._import_generation += 1
        generation = self._import_generation
        self._import_token = import_token
        self._import_pool = BoundedPool(1)

        # Cancellation is cooperative: an active copy2 call finishes, then no
        # additional files are scheduled and copied files remain on disk.
        class _ImportDone(QObject):
            finished = Signal(object)
            progress = Signal(int, int)

        class _ImportTask(CancellableRunnable):
            def __init__(self, done):
                super().__init__(cancel_token=import_token)
                self._done = done

            def run(self):
                try:
                    result = service.import_sources(
                        sources,
                        destination,
                        progress=self._done.progress.emit,
                        should_cancel=import_token.is_cancelled,
                    )
                except ImportCancelled as exc:
                    self._done.finished.emit(("cancelled", exc.partial_result))
                    return
                except Exception as exc:
                    self._done.finished.emit(("error", exc))
                    return
                self._done.finished.emit(("ok", result))

        done = _ImportDone()
        task = _ImportTask(done)
        progress_dialog = _ImportProgressDialog(
            tr("import.in_progress"),
            tr("dialog.cancel"),
            0,
            0,
            self,
        )
        progress_dialog.setWindowTitle(tr("import.title"))
        progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dialog.setMinimumDuration(500)
        self._import_dialog = progress_dialog

        def _request_cancel():
            progress_dialog.setProperty("import_cancel_requested", True)
            import_token.cancel()

        def _on_dialog_closed():
            progress_dialog.setProperty("import_dismissed", True)
            import_token.cancel()
            self._cleanup_import(generation, close_dialog=False)

        def _on_progress(done_count, total):
            if generation != self._import_generation or progress_dialog.property(
                "import_dismissed"
            ):
                return
            if total > 0:
                progress_dialog.setRange(0, total)
                progress_dialog.setValue(done_count)

        def _on_finished(payload):
            if generation != self._import_generation:
                return
            dismissed = bool(progress_dialog.property("import_dismissed"))
            progress_dialog.setProperty("import_finished", True)
            self._cleanup_import(generation, close_dialog=True)
            if dismissed:
                return
            progress_dialog.close()
            status, value = payload
            if status == "cancelled":
                if value is not None:
                    QMessageBox.information(
                        self,
                        tr("import.title"),
                        tr("import.cancelled").format(
                            copied=value.copied,
                            skipped=value.skipped,
                            failed=len(value.failed),
                        ),
                    )
                return
            if status == "error":
                QMessageBox.critical(
                    self, tr("import.title"), tr("import.failed").format(error=value)
                )
                return
            result = value
            message_key = "import.partial" if result.degraded else "import.success"
            QMessageBox.information(
                self,
                tr("import.title"),
                tr(message_key).format(
                    copied=result.copied,
                    skipped=result.skipped,
                    failed=len(result.failed),
                ),
            )

        progress_dialog.canceled.connect(_request_cancel)
        progress_dialog.user_closed.connect(_on_dialog_closed)
        done.finished.connect(_on_finished)
        done.progress.connect(_on_progress)
        self._import_task = task
        try:
            self._import_pool.start(task)
        except Exception:
            self._cleanup_import(generation, close_dialog=True)
            raise
        progress_dialog.exec()
        if generation == self._import_generation and not progress_dialog.property(
            "import_cancel_requested"
        ) and not progress_dialog.property("import_finished"):
            _on_dialog_closed()

    def _on_ui_scale_changed(self, scale: float):
        """Re-apply stylesheet and update font when UI scale changes."""
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        from AssetsManager.core import icons
        from AssetsManager.core.ui_scale import scaled_pt
        icons.clear_cache()
        themes.apply_to(self)
        font = app.font()
        base_pt = app.property("base_font_size")
        if base_pt is None:
            base_pt = font.pointSize()
        font.setPointSize(scaled_pt(base_pt))
        app.setFont(font)

    def _plugin_host(self):
        app = QApplication.instance()
        host = None
        if isinstance(app, QApplication):
            host = app.property("plugin_host_context")
        if host is None:
            host = getattr(self._bootstrap, "plugin_host_context", None)
        return host

    def _bind_plugin_host(self) -> None:
        """Point the process-wide plugin host at this live window."""
        host = self._plugin_host()
        binder = getattr(host, "bind_window", None)
        if callable(binder):
            binder(self)
        setter = getattr(host, "set_param_prompt", None)
        if callable(setter):
            setter(self._prompt_plugin_params)
        self._mount_plugin_docks()

    def _prompt_plugin_params(self, operator_cls, defaults):
        from AssetsManager.dialogs.plugin_operator_dialog import prompt_operator_params

        return prompt_operator_params(operator_cls, defaults, parent=self)

    def _mount_plugin_docks(self) -> None:
        """Create docks for registered PanelContributor / tool_windows()."""
        host = self._plugin_host()
        if host is None:
            return
        windows = getattr(host, "tool_windows", None)
        if not callable(windows):
            return
        mounted = getattr(self, "_plugin_docks", None)
        if mounted is None:
            mounted = {}
            self._plugin_docks = mounted
        areas = {
            "left": Qt.DockWidgetArea.LeftDockWidgetArea,
            "right": Qt.DockWidgetArea.RightDockWidgetArea,
            "top": Qt.DockWidgetArea.TopDockWidgetArea,
            "bottom": Qt.DockWidgetArea.BottomDockWidgetArea,
        }
        seen: set[str] = set()
        # ``callable()`` narrows the duck-typed accessor to a return of
        # ``object``, which is not iterable; the host returns a sequence.
        contributions: Any = windows() or []
        for contrib in contributions:
            cid = str(getattr(contrib, "id", "") or "").strip()
            if not cid:
                continue
            seen.add(cid)
            if cid in mounted:
                continue
            factory = getattr(contrib, "factory", None)
            if not callable(factory):
                continue
            try:
                widget = factory()
            except Exception:
                _log.exception("Plugin tool window '%s' failed to build", cid)
                continue
            if not isinstance(widget, QWidget):
                _log.warning("Plugin tool window '%s' did not return a QWidget", cid)
                continue
            title = str(getattr(contrib, "title", "") or cid)
            area_name = str(getattr(contrib, "area", "right") or "right").lower()
            area = areas.get(area_name, Qt.DockWidgetArea.RightDockWidgetArea)
            mounted[cid] = dock.create(title, self, area, widget=widget)
        for cid in list(mounted):
            if cid not in seen:
                leftover = mounted.pop(cid)
                try:
                    self.removeDockWidget(leftover)
                    leftover.deleteLater()
                except RuntimeError:
                    pass

    def _run_plugin_command(self, command_id: str):
        """Execute a plugin command by ID through the shared host path."""
        import logging
        _log = logging.getLogger(__name__)
        app = QApplication.instance()
        if not app:
            return
        plugin_ctx = app.property("plugin_host_context")
        if not plugin_ctx:
            return
        execute = getattr(plugin_ctx, "execute_command", None)
        try:
            if callable(execute):
                execute(command_id)
                return
            for cmd in plugin_ctx.commands():
                if getattr(cmd, 'id', None) == command_id:
                    handler = getattr(cmd, 'handler', None)
                    if handler and callable(handler):
                        handler()
                    return
        except Exception:
            _log.exception("Plugin command failed: %s", command_id)

    # ── Close ───────────────────────────────────────────────────

    def request_exit(self):
        """Close for real even when tray minimize-on-close is enabled."""
        self._force_quit = True
        self.close()

    def _shutdown_resources(self):
        """Persist UI state and stop background resources before process exit."""
        timer = getattr(self, "_share_status_timer", None)
        if timer is not None:
            timer.stop()
        self._lifecycle_coordinator.shutdown_resources()
        _save_window_geometry(self)

    def closeEvent(self, event):
        # If system tray is available, hide to tray instead of quitting
        app = QApplication.instance()
        if app and app.property("has_tray") and not self._force_quit:
            self.hide()
            event.ignore()
            return
        # True exit: clean up everything.  A teardown failure must not hang
        # the process: log it, still let the window close, and then make
        # sure the event loop exits.
        teardown_failed = False
        try:
            self._shutdown_resources()
        except Exception:
            _log.exception("Resource shutdown failed during window close")
            teardown_failed = True
        try:
            super().closeEvent(event)
        except Exception:
            _log.exception("Base closeEvent failed during window close")
            teardown_failed = True
        try:
            self._library_service().close()
        except Exception:
            _log.exception("Library service close failed during window close")
            teardown_failed = True
        if teardown_failed:
            # The normal last-window-closed quit may have been bypassed by
            # the raised teardown error; quit explicitly.  On the clean path
            # the app exits through the standard mechanism, which keeps
            # programmatic re-open (close old window, open new one) working.
            app = QApplication.instance()
            if app is not None:
                app.quit()
