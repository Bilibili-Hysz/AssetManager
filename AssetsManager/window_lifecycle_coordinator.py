"""Window-level library switch and exit resource orchestration."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from AssetsManager.window_scoped_panels import (
    SHUTDOWN_BEFORE_SAVE_PANELS as _SHUTDOWN_BEFORE_SAVE,
    SWITCH_PANELS as _SWITCH_PANELS,
)

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
    tabs = getattr(workspace, "_tabs", None)
    add_library = getattr(workspace, "add_library", None)
    if workspace is None or not callable(add_library):
        return
    try:
        if tabs is None:
            add_library(str(root))
            return
        # ``WorkspaceBar.add_library`` emits ``library_switched`` itself.
        # A rollback has already installed the target session, so a recursive
        # switch from that signal could close it again.
        was_blocked = workspace.blockSignals(True)
        try:
            add_library(str(root))
        finally:
            workspace.blockSignals(was_blocked)
    except Exception:
        _log.exception("Failed to restore workspace tab selection for %s", root)


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


def _rollback_open_failure(
    window: Any,
    old_session: Any,
    bind_and_navigate: Callable[[Any], None],
) -> None:
    """Restore the previous library after opening the replacement failed.

    Re-open the previous root (the old session was already closed), fully
    bind it, and reset the workspace tab selection. A failed restore leaves
    no live session and keeps the selected target tab available for retry.
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
            bind_and_navigate(restored)
        except Exception as restore_error:
            window._switch_recovery_pending = True
            _select_workspace_tab(window, restored.root)
            raise RuntimeError(
                "Library switch failed and the restored session is only partially bound; "
                "retry the selected library"
            ) from restore_error
        window._switch_recovery_pending = False
        _select_workspace_tab(window, restored.root)
    else:
        window._library_session = None
        window._switch_recovery_pending = True


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
          the previous library; if that also fails, the target tab remains
          selected as the explicit retry entry point while no live session is
          claimed.
        """
        window = self._window
        old_session = window._library_session
        if (
            old_session is not None
            and Path(path).resolve() == old_session.root
            and window._library_service().owns_live_session(old_session)
            and not getattr(window, "_switch_recovery_pending", False)
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

        self._prepare_switch_panels(run_window_step)

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
        # teardown). Restore the old root when possible; otherwise retain
        # the target tab as the explicit retry entry point.
        try:
            session = window._open_library_session(path)
        except Exception:
            self._set_scoped_panels_enabled(False)
            _rollback_open_failure(window, old_session, self._bind_and_navigate)
            raise

        try:
            self._bind_and_navigate(session)
        except Exception as exc:
            self._set_scoped_panels_enabled(False)
            self._rollback_post_open_failure(old_session, session, exc)
            raise
        window._switch_recovery_pending = False

    def _prepare_switch_panels(self, run_step: Callable[[Callable[[], Any]], None]) -> None:
        """Ask every scoped panel to stop work before a session is closed."""
        window = self._window
        for name in _SWITCH_PANELS:
            def prepare_panel(name=name) -> None:
                panel = getattr(window, name, None)
                prepare = getattr(panel, "prepare_library_switch", None)
                if self._is_alive(panel) and callable(prepare):
                    prepare()

            run_step(prepare_panel)

    def _bind_and_navigate(self, session: Any) -> None:
        """Apply session services and establish both navigation roots."""
        window = self._window
        window._apply_scoped_services(session)
        sidebar = getattr(window, "sidebar", None)
        navigate_sidebar = getattr(sidebar, "navigate_to", None)
        if self._is_alive(sidebar) and callable(navigate_sidebar):
            navigate_sidebar(session.root_str)
        file_list = getattr(window, "file_list", None)
        navigate_file_list = getattr(file_list, "navigate_to", None)
        if self._is_alive(file_list) and callable(navigate_file_list):
            navigate_file_list(session.root_str, set_root=True)
        self._set_scoped_panels_enabled(True)

    def _set_scoped_panels_enabled(self, enabled: bool) -> None:
        """Prevent interaction with panels whose session binding is incomplete."""
        window = self._window
        for name in _SWITCH_PANELS:
            panel = getattr(window, name, None)
            set_enabled = getattr(panel, "setEnabled", None)
            if self._is_alive(panel) and callable(set_enabled):
                set_enabled(enabled)

    def _rollback_post_open_failure(
        self, old_session: Any, new_session: Any, original_error: Exception
    ) -> None:
        """Restore a coherent session after bind/navigation failed post-open."""
        window = self._window
        prepare_error: Exception | None = None

        def record_prepare_error(thunk: Callable[[], Any]) -> None:
            nonlocal prepare_error
            try:
                thunk()
            except Exception as exc:
                if prepare_error is None:
                    prepare_error = exc

        self._prepare_switch_panels(record_prepare_error)
        if prepare_error is not None:
            window._switch_recovery_pending = True
            _select_workspace_tab(window, new_session.root)
            raise RuntimeError(
                "Library switch failed after opening the replacement session; "
                "panel cleanup failed, so the replacement session remains available for retry"
            ) from prepare_error

        try:
            window._library_service().close_session(new_session)
        except Exception as close_error:
            window._switch_recovery_pending = True
            _select_workspace_tab(window, new_session.root)
            raise RuntimeError(
                "Library switch failed after opening the replacement session; "
                "it could not be closed and remains available for retry"
            ) from close_error

        if old_session is None:
            window._library_session = None
            window._switch_recovery_pending = True
            raise RuntimeError(
                "Library switch failed after opening the replacement session; "
                "no previous session is available to restore"
            ) from original_error

        try:
            restored = window._open_library_session(old_session.root)
        except Exception as restore_error:
            window._library_session = None
            window._switch_recovery_pending = True
            raise RuntimeError(
                "Library switch failed and the previous session could not be restored; "
                "select a library tab to retry"
            ) from restore_error

        try:
            self._bind_and_navigate(restored)
        except Exception as restore_error:
            window._switch_recovery_pending = True
            _select_workspace_tab(window, restored.root)
            raise RuntimeError(
                "Library switch failed and the restored session is only partially bound; "
                "retry the selected library"
            ) from restore_error

        window._switch_recovery_pending = False
        _select_workspace_tab(window, restored.root)

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
        for name in _SHUTDOWN_BEFORE_SAVE:
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
