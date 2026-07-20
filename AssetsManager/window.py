"""Main window — QDockWidget-based docking layout with workspace tab bar."""
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtWidgets import QMainWindow, QWidget, QApplication, QLabel, QPushButton, QStatusBar

from AssetsManager import dock_factory as dock
from AssetsManager.core import themes
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_pt, scaled_px
from AssetsManager.core.settings import AppSettings
from AssetsManager import i18n
from AssetsManager.dialogs.startup import StartupWindow
from AssetsManager.core.database import clean_orphan_dirs
from AssetsManager.widgets.workspace_bar import WorkspaceSection
from AssetsManager.widgets.lan_sharing import LanSharingMixin

_log = logging.getLogger(__name__)
tr = i18n.tr


try:
    import shiboken6
    def _alive(widget):
        try:
            return widget is not None and shiboken6.isValid(widget)
        except Exception:
            return False
except ImportError:
    def _alive(widget):
        try:
            return widget is not None and widget.winId() is not None
        except Exception:
            return False


class MainWindow(LanSharingMixin, QMainWindow):
    def __init__(self, bootstrap, library_session=None):
        super().__init__()
        from AssetsManager.window_coordinator import WindowCoordinator
        from AssetsManager.window_lifecycle_coordinator import WindowLifecycleCoordinator
        self._coordinator = WindowCoordinator(self)
        self.setWindowTitle(tr("app.name"))
        self.resize(1200, 800)
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
        # Must be set before UI setup because workspace restore can switch libraries.
        self._library_session = library_session
        self._setup_ui()
        self._connect_bus()
        self._startup_anim_done = False
        self._force_quit = False

    def _library_service(self):
        return self._bootstrap.library_service

    def _open_library_session(self, path):
        session = self._library_service().open_session(path)
        self._library_session = session
        return session

    def _scoped_services_for_session(self, session):
        return self._bootstrap.for_library(session)

    def _apply_scoped_services(self, session):
        scoped = self._scoped_services_for_session(session)
        if scoped is None:
            return
        for panel in (
            getattr(self, "file_list", None),
            getattr(self, "info", None),
            getattr(self, "sidebar", None),
        ):
            set_services = getattr(panel, "set_scoped_services", None)
            if _alive(panel) and callable(set_services):
                set_services(scoped)
        tag_tree = getattr(self, "tag_tree", None)
        set_tag_services = getattr(tag_tree, "set_scoped_services", None)
        if _alive(tag_tree) and callable(set_tag_services):
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
            app.setStyleSheet(themes.stylesheet())
        self._apply_menu_theme()
        from AssetsManager import dock_factory as dk
        for dock_widget, (i18n_key, title, extra_buttons) in dk._DOCK_TITLES.items():
            bar = dock_widget.titleBarWidget()
            if bar and bar.property("is_custom_title"):
                bar.setStyleSheet(
                    f"background: {themes.header_for_dock()}; "
                    f"border: 1px solid {themes.get()['border']}; "
                    f"border-top-left-radius: {scaled_px(7)}px; border-top-right-radius: {scaled_px(7)}px; ")
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
        self._menu_lib.addAction(tr("menu.exit"), self.close)
        self._menu_act_settings = bar.addAction(tr("menu.settings"), self._open_settings)

        # Tools menu
        self._setup_tools_menu(bar)

        # Hide native menu bar since we have our own in the menu widget
        self.menuBar().hide()

    def _setup_tools_menu(self, bar):
        from AssetsManager.core.tool_scheduler import list_tools, run_tool
        self._menu_tools = bar.addMenu(tr("menu.tools"))
        tools_menu = self._menu_tools

        # External tools
        tools = list_tools()
        for t in tools:
            icon = t.get("icon", "") or "🔧"
            name = t.get("name", "Tool")
            text = f"{icon}  {name}"
            tools_menu.addAction(text,
                lambda checked, tool=t: run_tool(tool,
                    file_path=getattr(self.file_list, '_current', str(Path.home()))))

        # Plugin Manager
        tools_menu.addSeparator()
        tools_menu.addAction(tr("menu.plugin_manager"), self._open_plugin_manager)

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
                            tools_menu.addAction(f"🧩  {title}",
                                lambda checked, cid=cmd_id: self._run_plugin_command(cid))

        # LAN Sharing
        tools_menu.addSeparator()
        from AssetsManager import lan
        if lan.is_available():
            self._menu_act_share = tools_menu.addAction(tr('menu.share_system'), self._open_sharing_settings)
        else:
            a = tools_menu.addAction(tr("menu.sharing_unavailable"))
            a.setEnabled(False)
            a.setToolTip(tr("menu.sharing_install_hint"))

        # Keyboard Shortcuts
        tools_menu.addSeparator()
        tools_menu.addAction(tr("menu.keyboard_shortcuts"), self._show_shortcuts)

        self._lan_server = None

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
        self._share_toggle_btn = QPushButton("🌐")
        self._share_toggle_btn.setToolTip(tr("sharing.toggle_tooltip"))
        self._share_toggle_btn.setFixedSize(scaled_px(28), scaled_px(28))
        self._share_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._share_toggle_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; font-size: {scaled_pt(14)}px; }}"
            f"QPushButton:hover {{ background: {alpha('#ffffff', 0.1)}; border-radius: {scaled_px(4)}px; }}"
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

    @staticmethod
    def _create_file_list_panel():
        from AssetsManager.panels.file_list import QWidgetFileListPanel
        return QWidgetFileListPanel()

    def _setup_status_bar(self):
        """Setup status bar with share indicator."""
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        # Share status indicator
        self._share_status_label = QLabel(tr("sharing.off"))
        t = themes.get()
        self._share_status_label.setStyleSheet(f"color: {t['muted']}; padding: 0 8px;")
        self._share_status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._share_status_label.mousePressEvent = self._on_share_status_clicked
        status_bar.addPermanentWidget(self._share_status_label)

        # Apply theme
        status_bar.setStyleSheet(
            f"QStatusBar {{ background: {t['header']}; color: {t['body']}; "
            f"border-top: 1px solid {t['border']}; font-size: {scaled_pt(11)}px; }}"
            f"QStatusBar::item {{ border: none; }}"
        )

    def _apply_status_bar_theme(self):
        t = themes.get()
        self._share_status_label.setStyleSheet(f"color: {t['muted']}; padding: 0 8px;")
        self.statusBar().setStyleSheet(
            f"QStatusBar {{ background: {t['header']}; color: {t['body']}; "
            f"border-top: 1px solid {t['border']}; font-size: {scaled_pt(11)}px; }}"
            f"QStatusBar::item {{ border: none; }}"
        )

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
            QTimer.singleShot(2000, lambda: self._share_status_label.setToolTip(tr("sharing.click_to_copy")))
        else:
            # Open sharing settings
            self._open_sharing_settings()

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
        self._lifecycle_coordinator.switch_library(path)

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
        t = themes.get()
        self._menu_widget.setStyleSheet(f"background: {t['header']};")
        self._menu_bar.setStyleSheet(
            f"QMenuBar {{ background: transparent; color: {t['heading']}; "
            f"border: none; padding: 2px 8px; font-size: {scaled_pt(12)}px; }}"
            f"QMenuBar::item {{ padding: 3px 10px; border-radius: {scaled_px(4)}px; }}"
            f"QMenuBar::item:selected {{ background: {alpha(t['accent'], 0.313)}; }}"
            f"QMenu {{ background: {t['panel']}; color: {t['heading']}; "
            f"border: 1px solid {t['border']}; border-radius: {scaled_px(6)}px; padding: 4px; }}"
            f"QMenu::item {{ padding: 5px 28px 5px 12px; border-radius: {scaled_px(4)}px; }}"
            f"QMenu::item:selected {{ background: {t['accent']}; }}"
        )

    def _on_theme_refresh(self):
        self._coordinator.on_theme_refresh()

    def _refresh_language(self, _code: str = ""):
        self.setWindowTitle(tr("app.name"))
        self._menu_lib.setTitle(tr("menu.library"))
        self._menu_act_open.setText(tr("menu.open_library"))
        self._recent_menu.setTitle(tr("menu.recent_libraries"))
        self._menu_act_refresh.setText(tr("menu.refresh"))
        self._menu_act_settings.setText(tr("menu.settings"))
        if hasattr(self, '_menu_tools'):
            self._menu_tools.setTitle(tr("menu.tools"))
        if hasattr(self, '_menu_act_share'):
            self._menu_act_share.setText(tr('menu.share_system'))

    def _save_dock_layout(self):
        """Save dock sizes to AppSettings for session restore."""
        sizes = []
        for d in (self.sidebar_dock, self.info_dock):
            if _alive(d):
                panel = d.widget()
                if _alive(panel):
                    sizes.append(panel.width())
        AppSettings.instance().set("dock_widths", sizes)
        AppSettings.instance().save()

    def _save_workspace_tabs(self):
        paths = self._workspace.tab_paths()
        AppSettings.instance().set("workspace_tabs", paths)
        AppSettings.instance().save()

    def _restore_workspace_tabs(self):
        paths = AppSettings.instance().get("workspace_tabs")
        if isinstance(paths, list):
            self._workspace.restore_tabs(paths)

    def _restore_dock_layout(self):
        """Restore dock sizes from previous session."""
        sizes = AppSettings.instance().get("dock_widths")
        if isinstance(sizes, list) and len(sizes) == 2:
            docks = [self.sidebar_dock, self.info_dock]
            for d, w in zip(docks, sizes):
                panel = d.widget() if _alive(d) else None
                if not isinstance(panel, QWidget) or not _alive(panel):
                    continue
                panel.setMinimumWidth(max(100, w // 2))
                panel.resize(w, panel.height())

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
            if os.path.isdir(path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            else:
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
        open_image_viewer(self, path)

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
        from AssetsManager.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            themes.apply_to(self)

    def _on_ui_scale_changed(self, scale: float):
        """Re-apply stylesheet and update font when UI scale changes."""
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        from AssetsManager.core.ui_scale import scaled_pt
        themes.apply_to(self)
        font = app.font()
        base_pt = app.property("base_font_size")
        if base_pt is None:
            base_pt = font.pointSize()
        font.setPointSize(scaled_pt(base_pt))
        app.setFont(font)

    def _run_plugin_command(self, command_id: str):
        """Execute a plugin command by ID."""
        import logging
        _log = logging.getLogger(__name__)
        app = QApplication.instance()
        if not app:
            return
        plugin_ctx = app.property("plugin_host_context")
        if not plugin_ctx:
            return
        for cmd in plugin_ctx.commands():
            if getattr(cmd, 'id', None) == command_id:
                plugin_id = getattr(cmd, 'plugin_id', 'unknown')
                _log.info("Running plugin command: %s (plugin: %s)", command_id, plugin_id)
                try:
                    handler = getattr(cmd, 'handler', None)
                    if handler and callable(handler):
                        handler()
                except Exception:
                    _log.exception("Plugin command failed: %s (plugin: %s)", command_id, plugin_id)
                return

    # ── Close ───────────────────────────────────────────────────

    def request_exit(self):
        """Close for real even when tray minimize-on-close is enabled."""
        self._force_quit = True
        self.close()

    def _shutdown_resources(self):
        """Persist UI state and stop background resources before process exit."""
        self._lifecycle_coordinator.shutdown_resources()

    def closeEvent(self, event):
        # If system tray is available, hide to tray instead of quitting
        app = QApplication.instance()
        if app and app.property("has_tray") and not self._force_quit:
            self.hide()
            event.ignore()
            return
        # True exit: clean up everything
        self._shutdown_resources()
        super().closeEvent(event)
        self._library_service().close()
