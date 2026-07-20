"""Window-level library switch and exit resource orchestration."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


class WindowLifecycleCoordinator:
    """Preserve resource ordering without exposing panel internals to the window."""

    def __init__(self, window: Any, is_alive: Callable[[Any], bool]):
        self._window = window
        self._is_alive = is_alive

    def switch_library(self, path: str) -> None:
        window = self._window
        old_session = window._library_session
        if (
            old_session is not None
            and Path(path).resolve() == old_session.root
            and window._library_service().owns_live_session(old_session)
        ):
            return

        lan_server = getattr(window, "_lan_server", None)
        if lan_server and lan_server.is_running():
            lan_server.stop()
            update_status = getattr(window, "_update_share_status", None)
            if callable(update_status):
                update_status(False)
            tray = getattr(window, "_tray_manager", None)
            if tray is not None:
                tray.update_sharing_state(False)

        for name in ("info", "file_list", "sidebar", "tag_tree"):
            panel = getattr(window, name, None)
            prepare = getattr(panel, "prepare_library_switch", None)
            if self._is_alive(panel) and callable(prepare):
                prepare()

        if old_session is not None:
            old_root = old_session.root_str
            window._library_service().close_session(old_session)
            window._bootstrap.cleanup_library(old_root)

        session = window._open_library_session(path)
        window._apply_scoped_services(session)
        sidebar = getattr(window, "sidebar", None)
        navigate_sidebar = getattr(sidebar, "navigate_to", None)
        if self._is_alive(sidebar) and callable(navigate_sidebar):
            navigate_sidebar(session.root_str)
        file_list = getattr(window, "file_list", None)
        navigate_file_list = getattr(file_list, "navigate_to", None)
        if self._is_alive(file_list) and callable(navigate_file_list):
            navigate_file_list(session.root_str, set_root=True)

    def shutdown_resources(self) -> None:
        """Stop panel-owned work before MainWindow closes library sessions."""
        window = self._window
        lan_server = getattr(window, "_lan_server", None)
        if lan_server and lan_server.is_running():
            lan_server.stop()
        for name in ("info", "sidebar", "tag_tree"):
            panel = getattr(window, name, None)
            shutdown = getattr(panel, "shutdown", None)
            if self._is_alive(panel) and callable(shutdown):
                shutdown()
        window._save_dock_layout()
        window._save_workspace_tabs()
        file_list = getattr(window, "file_list", None)
        shutdown_file_list = getattr(file_list, "shutdown", None)
        if self._is_alive(file_list) and callable(shutdown_file_list):
            shutdown_file_list()
