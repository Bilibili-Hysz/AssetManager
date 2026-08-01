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

        stop_error: Exception | None = None
        lan_stopped = False
        window_error: Exception | None = None

        def run_window_step(thunk: Callable[[], Any]) -> None:
            nonlocal window_error
            try:
                thunk()
            except Exception as exc:
                if window_error is None:
                    window_error = exc

        def stop_lan() -> None:
            nonlocal lan_stopped, stop_error
            lan_server = getattr(window, "_lan_server", None)
            if lan_server and lan_server.is_running():
                try:
                    lan_server.stop()
                except Exception as exc:
                    stop_error = exc
                    raise
                else:
                    lan_stopped = True

        run_window_step(stop_lan)

        def notify_status() -> None:
            update_status = getattr(window, "_update_share_status", None)
            if callable(update_status):
                update_status(False)

        def notify_tray() -> None:
            tray = getattr(window, "_tray_manager", None)
            if tray is not None:
                tray.update_sharing_state(False)

        if lan_stopped:
            run_window_step(notify_status)
            run_window_step(notify_tray)

        for name in ("info", "file_list", "sidebar", "tag_tree"):
            def prepare_panel(name=name) -> None:
                panel = getattr(window, name, None)
                prepare = getattr(panel, "prepare_library_switch", None)
                if self._is_alive(panel) and callable(prepare):
                    prepare()

            run_window_step(prepare_panel)

        if old_session is not None:
            window._library_service().close_session(old_session)

        if stop_error is not None:
            run_window_step(notify_status)
            run_window_step(notify_tray)

        if window_error is not None:
            raise window_error

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
        first_error: Exception | None = None

        def run_cleanup(callback: Callable[[], Any]) -> None:
            nonlocal first_error
            try:
                callback()
            except Exception as exc:
                if first_error is None:
                    first_error = exc

        def cleanup_lan() -> None:
            lan_server = getattr(window, "_lan_server", None)
            if lan_server and lan_server.is_running():
                lan_server.stop()

        run_cleanup(cleanup_lan)
        for name in ("info", "sidebar", "tag_tree"):
            def cleanup_panel(name=name) -> None:
                panel = getattr(window, name, None)
                shutdown = getattr(panel, "shutdown", None)
                if self._is_alive(panel) and callable(shutdown):
                    shutdown()

            run_cleanup(cleanup_panel)
        run_cleanup(lambda: window._save_dock_layout())
        run_cleanup(lambda: window._save_workspace_tabs())

        def cleanup_file_list() -> None:
            file_list = getattr(window, "file_list", None)
            shutdown_file_list = getattr(file_list, "shutdown", None)
            if self._is_alive(file_list) and callable(shutdown_file_list):
                shutdown_file_list()

        run_cleanup(cleanup_file_list)
        if first_error is not None:
            raise first_error
