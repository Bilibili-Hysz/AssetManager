import asyncio
import multiprocessing
import os
import sqlite3
import sys
import threading
import time
import traceback
from pathlib import Path

import pytest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from aiohttp import ClientSession, WSMsgType
from AssetsManager.window import MainWindow
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.lan.auth import generate_token
from AssetsManager.lan.server import _LanServerImpl
from AssetsManager.window_lifecycle_coordinator import WindowLifecycleCoordinator


class _Tray:
    def __init__(self):
        self.states = []

    def update_sharing_state(self, running):
        self.states.append(running)


class _Window:
    def __init__(self, bootstrap, session, server):
        self._bootstrap = bootstrap
        self._library_session = session
        self._lan_server = server
        self.info = None
        self.file_list = None
        self.sidebar = None
        self.tag_tree = None
        self._tray_manager = _Tray()
        self.share_states = []
        self.replacement_opened = threading.Event()

    def _library_service(self):
        return self._bootstrap.library_service

    def _update_share_status(self, running):
        self.share_states.append(running)

    def _open_library_session(self, _path):
        self.replacement_opened.set()
        raise AssertionError("replacement library must not open")

    def _apply_scoped_services(self, _session):
        raise AssertionError("scoped services must not be applied")


class _RecordingPanel(QWidget):
    def __init__(self, events):
        super().__init__()
        self.events = events

    def shutdown(self):
        self.events.append("panel.shutdown")


class _RealExitWindow(MainWindow):
    def __init__(self, bootstrap, session, server, events):
        QMainWindow.__init__(self)
        self._bootstrap = bootstrap
        self._library_session = session
        self._lan_server = server
        self._lifecycle_coordinator = WindowLifecycleCoordinator(self, lambda panel: panel is not None)
        self._force_quit = True
        self._events = events
        self.info = _RecordingPanel(events)
        self.sidebar = _RecordingPanel(events)
        self.tag_tree = _RecordingPanel(events)
        self.file_list = _RecordingPanel(events)

    def _save_dock_layout(self):
        self._events.append("save.dock")

    def _save_workspace_tabs(self):
        self._events.append("save.tabs")


def _assert_exit_teardown(bootstrap, session, runtime, server, window, events, attempts):
    assert attempts == 2
    assert session.is_closed
    assert not bootstrap.library_service.owns_live_session(session)
    assert id(session) not in bootstrap._runtimes
    assert not server.is_running()
    assert server._thread is None
    assert server._runtime_adapter_registered is False
    assert server._runtime_subscription is None
    assert runtime._lifecycle_adapters == []
    assert server._ws_manager._clients == set()
    assert events == [
        "panel.shutdown",
        "panel.shutdown",
        "panel.shutdown",
        "save.dock",
        "save.tabs",
        "panel.shutdown",
    ]
    with pytest.raises(sqlite3.ProgrammingError):
        session.context.db_conn.execute("SELECT 1")


async def _run_managed_async(callable_, timeout=10):
    completed = threading.Event()
    result = []
    error = []

    def worker():
        try:
            result.append(callable_())
        except BaseException as exc:  # transfer the worker result to the test loop
            error.append(exc)
        finally:
            completed.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while not completed.is_set():
        if time.monotonic() >= deadline:
            return thread, None, TimeoutError(
                "managed lifecycle worker is still pending; it was not cancelled"
            )
        await asyncio.sleep(0.01)

    thread.join(timeout=1)
    assert not thread.is_alive(), "managed lifecycle worker leaked"
    return thread, result[0] if result else None, error[0] if error else None


async def _scenario(tmp_path):
    bootstrap = ApplicationBootstrap()
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    session = bootstrap.library_service.open_session(old_root)
    runtime = bootstrap.runtime_for(session)
    server = _LanServerImpl(runtime=runtime, password="window-test-password")
    server.start(port=0, bind="127.0.0.1")
    token = generate_token(server.password_hash)

    ws = None
    worker = None
    cleanup_error = None
    original_shutdown = server._shutdown
    shutdown_attempts = []
    production_teardown_verified = False
    try:
        async with ClientSession() as client:
            ws = await client.ws_connect(
                f"ws://127.0.0.1:{server._port}/ws",
                headers={"Cookie": f"lan_token={token}"},
            )
            assert (await ws.receive()).type == WSMsgType.TEXT
            assert server._ws_manager._clients

            async def fail_once_then_shutdown():
                shutdown_attempts.append(threading.get_ident())
                if len(shutdown_attempts) == 1:
                    raise RuntimeError("explicit window stop failed")
                await original_shutdown()

            server._shutdown = fail_once_then_shutdown
            window = _Window(bootstrap, session, server)
            coordinator = WindowLifecycleCoordinator(window, lambda panel: panel is not None)

            worker, _, worker_error = await _run_managed_async(
                lambda: coordinator.switch_library(str(new_root))
            )
            if isinstance(worker_error, TimeoutError):
                cleanup_error = worker_error
            elif worker_error is not None:
                with pytest.raises(RuntimeError, match="explicit window stop failed"):
                    raise worker_error

            try:
                close_message = await asyncio.wait_for(ws.receive(), timeout=2)
            except asyncio.TimeoutError:
                close_message = None
            assert close_message is not None, (
                f"old websocket was not closed; stop attempts={len(shutdown_attempts)}, "
                f"session_closed={session.is_closed}"
            )
            assert close_message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED}
            await ws.close()

            assert len(shutdown_attempts) == 2
            assert session.is_closed
            assert not bootstrap.library_service.owns_live_session(session)
            assert id(session) not in bootstrap._runtimes
            assert not server.is_running()
            assert server._thread is None
            assert server._runtime_adapter_registered is False
            assert server._runtime_subscription is None
            assert runtime._lifecycle_adapters == []
            assert server._ws_manager._clients == set()
            assert window.share_states == [False]
            assert window._tray_manager.states == [False]
            with pytest.raises(sqlite3.ProgrammingError):
                session.context.db_conn.execute("SELECT 1")
            production_teardown_verified = True
    finally:
        active_error = sys.exc_info()[1]
        if ws is not None and not ws.closed:
            await ws.close()
        if worker is not None:
            worker.join(timeout=1)
        if worker is None or not worker.is_alive():
            server._shutdown = original_shutdown
        if server.is_running() and (worker is None or not worker.is_alive()):
            try:
                _, _, server_cleanup_error = await _run_managed_async(server.stop)
            except BaseException:
                if active_error is None:
                    raise
            else:
                if cleanup_error is None and active_error is None:
                    cleanup_error = server_cleanup_error
        if not session.is_closed and (worker is None or not worker.is_alive()):
            try:
                bootstrap.library_service.close_session(session)
            except BaseException:
                if active_error is None:
                    raise

    if cleanup_error is not None:
        raise cleanup_error

    assert production_teardown_verified

    # Idempotent cleanup must not require another worker or resurrect a server.
    _, _, cleanup_error = await _run_managed_async(server.stop)
    assert cleanup_error is None


async def _exit_scenario(tmp_path):
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "exit")
    runtime = bootstrap.runtime_for(session)
    server = _LanServerImpl(runtime=runtime, password="window-test-password")
    server.start(port=0, bind="127.0.0.1")
    token = generate_token(server.password_hash)
    events = []
    attempts = []
    original_shutdown = server._shutdown
    ws = None
    production_teardown_verified = False
    try:
        async with ClientSession() as client:
            ws = await client.ws_connect(
                f"ws://127.0.0.1:{server._port}/ws",
                headers={"Cookie": f"lan_token={token}"},
            )
            assert (await ws.receive()).type == WSMsgType.TEXT
            assert server._ws_manager._clients

            async def fail_once_then_shutdown():
                attempts.append(threading.get_ident())
                if len(attempts) == 1:
                    raise RuntimeError("explicit window stop failed")
                await original_shutdown()

            server._shutdown = fail_once_then_shutdown
            window = _RealExitWindow(bootstrap, session, server, events)
            close_event = QCloseEvent()
            with pytest.raises(RuntimeError, match="explicit window stop failed"):
                MainWindow.closeEvent(window, close_event)
            assert close_event.isAccepted()
            close_message = await asyncio.wait_for(ws.receive(), timeout=2)
            assert close_message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED}
            await ws.close()
            _assert_exit_teardown(
                bootstrap,
                session,
                runtime,
                server,
                window,
                events,
                len(attempts),
            )
            production_teardown_verified = True
    finally:
        active_error = sys.exc_info()[1]
        if ws is not None and not ws.closed:
            await ws.close()
        if server.is_running():
            try:
                _, _, cleanup_error = await _run_managed_async(server.stop)
            except BaseException:
                if active_error is None:
                    raise
            else:
                if cleanup_error is not None and active_error is None:
                    raise cleanup_error
        if not session.is_closed:
            try:
                bootstrap.library_service.close_session(session)
            except BaseException:
                if active_error is None:
                    raise
        server._shutdown = original_shutdown
        app.quit()

    assert production_teardown_verified


def _run_scenario_process(root_str, send_conn, scenario="switch"):
    try:
        scenario_runner = _scenario if scenario == "switch" else _exit_scenario
        asyncio.run(scenario_runner(Path(root_str)))
    except BaseException as exc:
        send_conn.send(("error", type(exc).__name__, str(exc), traceback.format_exc()))
    else:
        send_conn.send(("success",))
    finally:
        send_conn.close()


def _wait_for_process_result(process, receive_conn, timeout=30):
    deadline = time.monotonic() + timeout
    result = None

    while process.is_alive() and time.monotonic() < deadline:
        if result is None and receive_conn.poll(0.01):
            try:
                result = receive_conn.recv()
            except EOFError as exc:
                pytest.fail(f"真实scenario子进程关闭Pipe但未返回结果: {exc}")
        process.join(timeout=0.05)
        if result is None and receive_conn.poll(0):
            try:
                result = receive_conn.recv()
            except EOFError as exc:
                pytest.fail(f"真实scenario子进程关闭Pipe但未返回结果: {exc}")

    return result


def test_window_switch_drains_session_after_explicit_lan_stop_failure(tmp_path):
    context = multiprocessing.get_context("spawn")
    receive_conn, send_conn = context.Pipe(duplex=False)
    process = context.Process(
        target=_run_scenario_process,
        args=(str(tmp_path), send_conn),
    )
    started = False
    try:
        process.start()
        started = True
        send_conn.close()

        result = _wait_for_process_result(process, receive_conn)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(timeout=5)
            pytest.fail("真实scenario超时：spawn子进程无法在30秒内完成并退出")

        process.join(timeout=5)
        assert process.exitcode == 0, f"真实scenario子进程异常退出，exitcode={process.exitcode}"
        if result is None:
            assert receive_conn.poll(1), "真实scenario子进程未通过Pipe返回结果"
            try:
                result = receive_conn.recv()
            except EOFError as exc:
                pytest.fail(f"真实scenario子进程关闭Pipe但未返回结果: {exc}")
        if result[0] == "error":
            _, error_type, error_message, error_traceback = result
            pytest.fail(
                "真实scenario子进程失败 "
                f"{error_type}: {error_message}\n完整traceback:\n{error_traceback}"
            )
        assert result == ("success",)
    finally:
        if started:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
                if process.is_alive() and hasattr(process, "kill"):
                    process.kill()
                    process.join(timeout=5)
            else:
                process.join(timeout=5)
        send_conn.close()
        receive_conn.close()


def test_window_exit_drains_session_after_explicit_lan_stop_failure(tmp_path):
    context = multiprocessing.get_context("spawn")
    receive_conn, send_conn = context.Pipe(duplex=False)
    process = context.Process(
        target=_run_scenario_process,
        args=(str(tmp_path), send_conn, "exit"),
    )
    started = False
    try:
        process.start()
        started = True
        send_conn.close()
        result = _wait_for_process_result(process, receive_conn)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(timeout=5)
            pytest.fail("真实exit scenario超时：spawn子进程无法在30秒内完成并退出")
        process.join(timeout=5)
        assert process.exitcode == 0, f"真实exit scenario子进程异常退出，exitcode={process.exitcode}"
        if result is None:
            assert receive_conn.poll(1), "真实exit scenario子进程未通过Pipe返回结果"
            result = receive_conn.recv()
        if result[0] == "error":
            _, error_type, error_message, error_traceback = result
            pytest.fail(
                "真实exit scenario子进程失败 "
                f"{error_type}: {error_message}\n完整traceback:\n{error_traceback}"
            )
        assert result == ("success",)
    finally:
        if started:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
                if process.is_alive() and hasattr(process, "kill"):
                    process.kill()
                    process.join(timeout=5)
            else:
                process.join(timeout=5)
        send_conn.close()
        receive_conn.close()
