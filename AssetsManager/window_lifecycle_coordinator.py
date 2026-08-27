"""Window-level library switch and exit resource orchestration."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


def _restore_lan_state(window: Any) -> None:
    """Best-effort restart of LAN sharing after an aborted library switch."""
    toggle = getattr(window, "_toggle_sharing", None)
    if not callable(toggle):
        return
    try:
        toggle()
    except Exception:
        _log.exception("Failed to restore LAN sharing after aborted library switch")


def _select_workspace_tab(window: Any, root: str | Path) -> None:
    """Re-select (or re-add) the workspace tab for ``root`` after a rollback."""
    workspace = getattr(window, "_workspace", None)
    add_library = getattr(workspace, "add_library", None)
    if not callable(add_library):
        return
    try:
        add_library(str(root))
    except Exception:
        _log.exception("Failed to restore workspace tab selection for %s", root)


def _remove_workspace_tab(window: Any, path: str) -> None:
    """Drop the tab for ``path`` after a switch that cannot be rolled back."""
    workspace = getattr(window, "_workspace", None)
    tabs = getattr(workspace, "_tabs", None)
    remove_library = getattr(tabs, "remove_library", None)
    if not callable(remove_library):
        return
    try:
        remove_library(path)
    except Exception:
        _log.exception("Failed to remove workspace tab for %s", path)


def _notify_switch_failed(window: Any, message: str) -> None:
    """Surface a failed library switch to the user (best-effort).

    The warning is deferred to the event loop: switch failures can be
    reported while the main window is still being constructed (workspace
    tab restore during the constructor), where a modal box would block
    startup before the window is shown.
    """
    def _show() -> None:
        try:
            from PySide6.QtWidgets import QMessageBox, QWidget
            if not isinstance(window, QWidget):
                return
            try:
                import shiboken6
                if not shiboken6.isValid(window):
                    return
            except Exception:
                pass
            from AssetsManager import i18n
            QMessageBox.warning(window, i18n.tr("dialog.error"), message)
        except Exception:
            _log.exception("Failed to notify about a failed library switch")

    try:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, _show)
    except Exception:
        _log.exception("Failed to notify about a failed library switch")


def _rollback_open_failure(window: Any, old_session: Any, path: str, error: Exception) -> None:
    """Restore the previous library after opening the replacement failed.

    Re-open the previous root (the old session was already closed) and reset
    the workspace tab selection so the window keeps a usable session.  When
    the restore also fails, drop the new tab and notify the user.
    """
    restored = None
    if old_session is not None:
        try:
            restored = window._open_library_session(old_session.root)
        except Exception:
            _log.exception(
                "Failed to restore previous library %s after switch failure",
                old_session.root,
            )
            restored = None
    if restored is not None:
        try:
            window._apply_scoped_services(restored)
        except Exception:
            _log.exception("Failed to re-apply scoped services after switch rollback")
        _select_workspace_tab(window, restored.root)
    else:
        _remove_workspace_tab(window, path)
        _notify_switch_failed(
            window,
            "The library switch failed and the previous library could not be "
            f"restored: {error}",
        )


class WindowLifecycleCoordinator:
    """Preserve resource ordering without exposing panel internals to the window."""

    def __init__(self, window: Any, is_alive: Callable[[Any], bool]):
        self._window = window
        self._is_alive = is_alive

    def switch_library(self, path: str) -> None:
        """Switch the window to another library root.

        Failure handling:
        - A failed LAN stop that leaves the server running aborts the switch
          before any window state is touched; the old session stays live and
          the UI is not told the server stopped.
        - A failed LAN stop that actually took the server down proceeds with
          the drain: the old session is closed (its runtime close retries the
          LAN stop), the off state is reported to the UI, and the LAN error
          is raised to the caller.
        - Any other failure before ``close_session`` (panel preparation or
          status updates) keeps the old session alive, restores the LAN
          state that was stopped for this attempt, and raises the error.
        - ``close_session`` itself is a window step: its failure sets
          ``window_error`` and leaves ``_library_session`` pointing at the
          old session so the caller can retry the switch.
        - A failure to open the replacement session rolls back by re-opening
          the previous library; if that also fails, the new tab is removed
          and the user is notified.
        """
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

        def stop_import() -> None:
            cleanup = getattr(window, "_cleanup_import", None)
            if callable(cleanup):
                cleanup()
                return
            token = getattr(window, "_import_token", None)
            if token is not None:
                token.cancel()
            pool = getattr(window, "_import_pool", None)
            if pool is not None:
                pool.cancel_all()
                pool.drain(3_000)

        run_window_step(stop_lan)
        run_window_step(stop_import)

        # M4: a failed LAN stop must not silently continue the switch while
        # the server is still up — the UI would misreport it as stopped and
        # the old session would be torn down for a switch that never happens.
        if stop_error is not None:
            lan_server = getattr(window, "_lan_server", None)
            if lan_server is not None and lan_server.is_running():
                if window_error is None:
                    window_error = stop_error
                raise window_error

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

        # H1: a window step failed before the old session was closed.  Abort
        # the switch instead of destroying the session the window still
        # points at; restore the LAN state stopped for this attempt.
        if window_error is not None and stop_error is None:
            if lan_stopped:
                _restore_lan_state(window)
            raise window_error

        # H2: closing the old session is a window step — its failure sets
        # window_error and leaves ``_library_session`` pointing at the old
        # session so the caller can retry the switch.
        if old_session is not None:
            def close_old() -> None:
                try:
                    window._library_service().close_session(old_session)
                except Exception as exc:
                    try:
                        exc.add_note(
                            "Session close failed during library switch; "
                            "retry the switch to finish teardown."
                        )
                    except (AttributeError, TypeError):
                        pass
                    raise

            run_window_step(close_old)

        if stop_error is not None:
            # The LAN server is actually down (verified above): report the
            # off state to the UI before surfacing the stop error.
            run_window_step(notify_status)
            run_window_step(notify_tray)

        if window_error is not None:
            raise window_error

        # H3: opening the replacement session can fail (DB lock, pending
        # teardown).  Roll back to the previous library instead of leaving
        # the window without any usable session.
        try:
            session = window._open_library_session(path)
        except Exception as exc:
            _rollback_open_failure(window, old_session, path, exc)
            raise

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

        def cleanup_import() -> None:
            cleanup = getattr(window, "_cleanup_import", None)
            if callable(cleanup):
                cleanup()
                return
            token = getattr(window, "_import_token", None)
            if token is not None:
                token.cancel()
            pool = getattr(window, "_import_pool", None)
            if pool is not None:
                pool.cancel_all()
                pool.drain(3_000)

        run_cleanup(cleanup_lan)
        run_cleanup(cleanup_import)
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
