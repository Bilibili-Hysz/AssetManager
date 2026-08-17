"""Shutdown-coordination load/concurrency stress tests (audit task D1).

These tests exercise the *stability* dimension of the window-lifecycle
close coordination that
``tests/integration/test_window_lifecycle_lan_failure.py`` covers for
correctness and fault recovery.  They run entirely inside a single
process: the coordinator's library-switch/exit orchestration runs on a
worker thread (as the real Qt UI thread would), while the LAN server's
aiohttp event loop runs on its own thread, and the concurrent WebSocket
clients + browse requests run on the driving asyncio loop.

Sandbox note: ``multiprocessing`` named pipes are denied in this
environment, so the scenarios here use ``asyncio`` + ``threading``
exclusively and never spawn a child process.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
import time
import traceback
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from aiohttp import ClientSession, WSMsgType

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.lan.auth import generate_token
from AssetsManager.lan.server import _LanServerImpl
from AssetsManager.window_lifecycle_coordinator import WindowLifecycleCoordinator

# ── Tunable load parameters ───────────────────────────────────────
# 默认轮数小（15 轮，秒级），保证普通集成套件可承受；CI/本地可用
# 环境变量 AM_STRESS_ROUNDS 覆盖为更高值做更充分的负载验证。
DEFAULT_ROUNDS = int(os.environ.get("AM_STRESS_ROUNDS", "15"))
WS_CLIENTS_PER_ROUND = int(os.environ.get("AM_STRESS_WS_CLIENTS", "5"))
BROWSE_REQUESTS_PER_ROUND = int(os.environ.get("AM_STRESS_BROWSE_REQUESTS", "20"))
# 每轮整体超时（秒）。超时即认为该轮死锁/卡住。
PER_ROUND_TIMEOUT = float(os.environ.get("AM_STRESS_ROUND_TIMEOUT", "30"))
# 泄漏检测抖动阈值：连续 N 轮后允许的相对/绝对增长。
# EventBus handler 总数允许 +2 抖动（各 runtime 关闭是同步的，理论应回基线）。
EVENTBUS_LEAK_TOLERANCE = 2
# 存活线程数允许 +2 抖动（应用命名线程；框架线程池不计入，见 _app_thread_count）。
THREAD_LEAK_TOLERANCE = 2
# sqlite 打开连接数允许 +0（所有连接必须显式关闭；仅在测量瞬间统计打开数）。

#: 浏览请求每轮打的目标（skip-scoped，无需认证）与并发方式：gather 同时发出。
_BROWSE_PATH = "/api/files"
_WS_PATH = "/ws"


class _Tray:
    def __init__(self):
        self.states = []

    def update_sharing_state(self, running):
        self.states.append(running)


class _RecordingPanel:
    """Minimal panel that supports both prepare_library_switch and shutdown."""

    def __init__(self, events):
        self.events = events

    def prepare_library_switch(self):
        self.events.append("panel.prepare")

    def shutdown(self):
        self.events.append("panel.shutdown")

    def navigate_to(self, *_args, **_kwargs):
        self.events.append("panel.navigate")


class _Window:
    """Minimal fake window that can complete a library switch end-to-end.

    Copied/adapted from ``test_window_lifecycle_lan_failure._Window``; the
    key difference is that ``_open_library_session`` / ``_apply_scoped_services``
    really open the replacement session (the failure test asserts they are
    never called).
    """

    def __init__(self, bootstrap, session, server):
        self._bootstrap = bootstrap
        self._library_session = session
        self._lan_server = server
        self.info = _RecordingPanel([])
        self.file_list = _RecordingPanel([])
        self.sidebar = _RecordingPanel([])
        self.tag_tree = _RecordingPanel([])
        self._tray_manager = _Tray()
        self.share_states = []

    def _library_service(self):
        return self._bootstrap.library_service

    def _update_share_status(self, running):
        self.share_states.append(running)

    def _open_library_session(self, path):
        session = self._library_service().open_session(Path(path))
        self._library_session = session
        return session

    def _apply_scoped_services(self, _session):
        # Scoped services are bound to the runtime by the coordinator's
        # caller in production; nothing needed for the stress harness.
        return None

    def _save_dock_layout(self):
        self._tray_manager.states.append("save.dock")

    def _save_workspace_tabs(self):
        self._tray_manager.states.append("save.tabs")


async def _run_managed_async(callable_, timeout=PER_ROUND_TIMEOUT):
    """Run ``callable_`` on a worker thread, bounded by ``timeout``.

    Returns ``(thread, result, error)``; ``error`` is a ``TimeoutError`` when
    the worker is still pending at the deadline (the worker thread is left
    running and reported so the caller can diagnose where it blocked).
    """
    completed = threading.Event()
    result = []
    error = []

    def worker():
        try:
            result.append(callable_())
        except BaseException as exc:
            error.append(exc)
        finally:
            completed.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while not completed.is_set():
        if time.monotonic() >= deadline:
            return thread, None, TimeoutError(
                f"managed lifecycle worker still pending after {timeout}s "
                "(possible deadlock); thread alive="
                f"{thread.is_alive()}"
            )
        await asyncio.sleep(0.01)

    thread.join(timeout=1)
    assert not thread.is_alive(), "managed lifecycle worker leaked"
    return thread, result[0] if result else None, error[0] if error else None


def _active_sqlite_connections():
    """Count sqlite3 connections that are still open (via ``gc``).

    sqlite3 does not expose a global connection registry.  We instead walk
    ``gc.get_objects()`` for ``sqlite3.Connection`` and count those that can
    still execute (closed connections raise ``sqlite3.ProgrammingError``).
    A connection created on another thread may raise a different error on
    ``SELECT 1``; we conservatively count it as open.
    """
    import gc

    count = 0
    for obj in gc.get_objects():
        if isinstance(obj, sqlite3.Connection):
            try:
                obj.execute("SELECT 1")
                count += 1
            except sqlite3.ProgrammingError:
                # closed connection: does not count
                continue
            except Exception:
                # live connection created in another thread: count as open
                count += 1
    return count


def _eventbus_handler_total():
    from AssetsManager.domain.event_bus import get_event_bus

    bus = get_event_bus()
    with bus._lock:
        return sum(len(handlers) for handlers in bus._handlers.values())


def _app_thread_count():
    """Count application-owned named threads, excluding framework pools.

    Qt's global QThreadPool and aiohttp's executor legitimately keep idle
    worker threads alive across rounds, so ``threading.active_count()`` is
    not a leak signal.  Application threads carry a ``library-`` name prefix
    (e.g. the resident library watcher) and must return to zero on teardown.
    """
    return sum(1 for t in threading.enumerate() if t.name.startswith("library-"))


async def _connect_ws(base_url, token):
    """Connect one authenticated WebSocket and prime it with the hello frame."""
    client = ClientSession()
    ws = await client.ws_connect(
        f"ws://{base_url}{_WS_PATH}",
        headers={"Cookie": f"lan_token={token}"},
    )
    first = await ws.receive()
    assert first.type == WSMsgType.TEXT, f"unexpected first WS frame: {first.type}"
    return client, ws


async def _browse(client, base_url, _idx):
    """Issue one browse request; tolerate server-side teardown races."""
    async with client.get(f"http://{base_url}{_BROWSE_PATH}") as resp:
        return resp.status


async def _wait_all_ws_closed(ws_list, timeout=5.0):
    """Return the close/error frame received per socket (or None if not closed)."""
    loop = asyncio.get_running_loop()
    received = {}

    async def observe(ws):
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            except Exception:
                return "error"
            if msg.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                return msg.type

    ws_objs = [ws for _, ws in ws_list]
    results = await asyncio.gather(*(observe(ws) for ws in ws_objs))
    for (_, ws), res in zip(ws_list, results, strict=True):
        received[id(ws)] = res
    return received


async def _round(round_idx, tmp_path):
    """Run one full stress round; returns a stage-marked outcome dict on failure."""
    stage = {"name": "init", "round": round_idx}
    from AssetsManager.application.security_preflight import SecurityPreflight
    from AssetsManager.application.undo_service import UndoService

    UndoService._startup_cleanup_done = True
    bootstrap = ApplicationBootstrap()

    server = None
    ws_list = []
    clients = []
    worker = None
    window = None

    try:
        stage.update(name="open_session")
        root_a = tmp_path / f"lib-a-{round_idx}"
        root_b = tmp_path / f"lib-b-{round_idx}"
        # Materialize the roots up front so the LAN scanner's background walk
        # never races a directory that does not exist yet.
        root_a.mkdir(parents=True, exist_ok=True)
        root_b.mkdir(parents=True, exist_ok=True)
        session = bootstrap.library_service.open_session(root_a)
        runtime = bootstrap.runtime_for(session)

        stage.update(name="start_server")
        server = _LanServerImpl(runtime=runtime, password="stress-password")
        preflight = SecurityPreflight()
        preflight.confirm_authenticated_lan()
        server.start(port=0, bind="127.0.0.1", preflight=preflight)
        token = generate_token(server.password_hash)
        base_url = f"127.0.0.1:{server._port}"

        stage.update(name="connect_ws")
        client_pool = ClientSession()
        clients.append(client_pool)
        for _ in range(WS_CLIENTS_PER_ROUND):
            client, ws = await _connect_ws(base_url, token)
            clients.append(client)
            ws_list.append((client, ws))

        stage.update(name="requests")
        statuses = await asyncio.gather(
            *(_browse(client_pool, base_url, i) for i in range(BROWSE_REQUESTS_PER_ROUND)),
            return_exceptions=True,
        )
        # The request fan-out must not crash the server; every browse attempt
        # should return an HTTP status (exceptions are tolerated only if they
        # are connection errors from a concurrent teardown, which is not the
        # case here since close happens after the fan-out completes).
        request_failures = [s for s in statuses if not isinstance(s, int)]
        if request_failures:
            return {
                "stage": dict(stage),
                "phase": "assert_requests",
                "error": AssertionError(
                    f"round {round_idx}: {len(request_failures)} browse "
                    f"request(s) raised: {request_failures[0]!r}"
                ),
            }

        # Build the coordinator against the *live* window and run the switch
        # (close the old session, open the replacement) concurrently with
        # a concurrent exit attempt is intentionally NOT done: the coordinator
        # is not re-entrant by design (single UI thread).  Stress the close
        # path via rapid switch then shutdown on the same worker.
        window = _Window(bootstrap, session, server)
        coordinator = WindowLifecycleCoordinator(window, lambda panel: True)

        stage.update(name="switch")
        worker, _, switch_error = await _run_managed_async(
            lambda: coordinator.switch_library(str(root_b))
        )
        if switch_error is not None:
            if isinstance(switch_error, TimeoutError):
                return {"stage": dict(stage), "phase": "switch", "error": switch_error}
            raise switch_error

        stage.update(name="shutdown")
        worker, _, shutdown_error = await _run_managed_async(
            coordinator.shutdown_resources
        )
        if shutdown_error is not None:
            if isinstance(shutdown_error, TimeoutError):
                return {"stage": dict(stage), "phase": "shutdown", "error": shutdown_error}
            raise shutdown_error

        stage.update(name="assert")
        # b) all WS clients saw a close/error frame, none left dangling.
        closed = await _wait_all_ws_closed(ws_list)
        dangling = [id(ws) for id_, res in closed.items() if res is None]
        if dangling:
            return {
                "stage": dict(stage),
                "phase": "assert_ws_closed",
                "error": AssertionError(
                    f"round {round_idx}: {len(dangling)} WebSocket(s) not closed; "
                    f"server running={server.is_running()}"
                ),
            }

        # c) runtime closed, adapters cleared, server down.
        if runtime.is_open:
            return {
                "stage": dict(stage),
                "phase": "assert_runtime_closed",
                "error": AssertionError(f"round {round_idx}: runtime still open"),
            }
        if runtime._lifecycle_adapters:
            return {
                "stage": dict(stage),
                "phase": "assert_adapters",
                "error": AssertionError(
                    f"round {round_idx}: {len(runtime._lifecycle_adapters)} "
                    "lifecycle adapters retained"
                ),
            }
        if server.is_running() or server._ws_manager._clients:
            return {
                "stage": dict(stage),
                "phase": "assert_server_down",
                "error": AssertionError(
                    f"round {round_idx}: server running={server.is_running()}, "
                    f"ws_clients={len(server._ws_manager._clients)}"
                ),
            }

        return None
    finally:
        for client, ws in ws_list:
            if not ws.closed:
                try:
                    await ws.close()
                except Exception:
                    pass
            try:
                await client.close()
            except Exception:
                pass
        for client in clients:
            try:
                await client.close()
            except Exception:
                pass
        if server is not None and server.is_running():
            try:
                await _run_managed_async(server.stop, timeout=10)
            except Exception:
                pass
        # Ensure the session is torn down even if a step above raised.
        try:
            live = getattr(window, "_library_session", None)
        except Exception:
            live = None
        if live is not None and not live.is_closed:
            try:
                bootstrap.library_service.close_session(live)
            except Exception:
                pass


@pytest.mark.stress
def test_shutdown_stress_no_deadlock_no_leak(tmp_path):
    """Loop N quick switch+shutdown rounds under LAN/WS/browse load.

    Asserts per-round: no deadlock (per-round timeout), every WebSocket
    closed, runtime closed + adapters cleared, server down.  Across all
    rounds: no background-thread exceptions, and the process-wide EventBus
    handler count / thread count / open sqlite connection count do not grow
    relative to the first-round baseline (leak detection with slack).
    """
    threading_excepthook_holder = {"errors": []}

    def hook(args):
        threading_excepthook_holder["errors"].append(
            (args.exc_type.__name__ if args.exc_type else None, str(args.exc_value))
        )
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_tb)

    threading.excepthook = hook

    baseline = None
    final = None

    try:
        for r in range(DEFAULT_ROUNDS):
            print(
                f"[stress] round {r + 1}/{DEFAULT_ROUNDS} "
                f"(stage marks: open/start/connect/requests/switch/shutdown/assert)"
            )
            # Bind `r` as a default so the closure captures its value, not the
            # loop variable; asyncio.run() completes before the next iteration.
            async def run_round(current_round: int = r):
                return await _round(current_round, Path(tmp_path))

            failure = asyncio.run(run_round())
            if failure is not None:
                pytest.fail(
                    f"[stress] round {r + 1} failed at phase "
                    f"{failure['phase']} (stage={failure['stage']}): "
                    f"{failure['error']}"
                )
            if r == 0:
                baseline = (
                    _eventbus_handler_total(),
                    _app_thread_count(),
                    _active_sqlite_connections(),
                )
            final = (
                _eventbus_handler_total(),
                _app_thread_count(),
                _active_sqlite_connections(),
            )
    finally:
        # restore default hook
        pass

    assert baseline is not None and final is not None
    bus_base, thread_base, sqlite_base = baseline
    bus_final, thread_final, sqlite_final = final

    # d) no uncaught background-thread exceptions.
    assert threading_excepthook_holder["errors"] == [], (
        f"background thread exceptions detected: {threading_excepthook_holder['errors']}"
    )

    # e) leak detection with explicit slack thresholds.
    assert bus_final <= bus_base + EVENTBUS_LEAK_TOLERANCE, (
        f"EventBus handler total grew: baseline={bus_base} final={bus_final} "
        f"(tolerance=+{EVENTBUS_LEAK_TOLERANCE})"
    )
    assert thread_final <= thread_base + THREAD_LEAK_TOLERANCE, (
        f"thread count grew: baseline={thread_base} final={thread_final} "
        f"(tolerance=+{THREAD_LEAK_TOLERANCE})"
    )
    assert sqlite_final <= sqlite_base, (
        f"open sqlite connections grew: baseline={sqlite_base} final={sqlite_final}"
    )
