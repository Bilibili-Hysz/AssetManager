import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from AssetsManager.lan.server import _LanServerImpl

# These tests bind a fixed port (8765); under xdist --dist worksteal they
# must never run concurrently on different workers.
pytestmark = pytest.mark.xdist_group(name="serial")


class _ThreadThatStaysAlive:
    def __init__(self):
        self.join_timeouts = []

    def is_alive(self):
        return True

    def join(self, timeout=None):
        self.join_timeouts.append(timeout)


class _ThreadThatStopsOnJoin(_ThreadThatStaysAlive):
    def __init__(self):
        super().__init__()
        self._alive = True

    def is_alive(self):
        return self._alive

    def start(self):
        pass

    def join(self, timeout=None):
        super().join(timeout)
        self._alive = False


class _ThreadThatStopsWhenCleanupCompletes(_ThreadThatStaysAlive):
    def __init__(self):
        super().__init__()
        self._alive = True

    def is_alive(self):
        return self._alive

    def cleanup_completed(self):
        self._alive = False


class _ThreadThatExitsDuringJoin(_ThreadThatStaysAlive):
    def __init__(self, join_started, allow_join):
        super().__init__()
        self._alive = True
        self._join_started = join_started
        self._allow_join = allow_join

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        super().join(timeout)
        self._alive = False
        self._join_started.set()
        assert self._allow_join.wait(timeout=2)


class _ShutdownFuture:
    def __init__(self, error=None):
        self._error = error

    def result(self, timeout=None):
        if self._error is not None:
            raise self._error


def _server_with_thread(thread):
    server = object.__new__(_LanServerImpl)
    server._running = True
    server._lifecycle_state = "running"
    server._loop = object()
    server._thread = thread
    server._cleanup_complete = False
    server._shutdown_future = None
    server._lifecycle_lock = threading.Lock()
    return server


async def _completed():
    pass


def _submit_future(monkeypatch, future):
    def submit(coro, loop):
        coro.close()
        return future

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", submit)


def test_stop_preserves_actionable_state_when_shutdown_future_times_out(monkeypatch):
    thread = _ThreadThatStaysAlive()
    server = _server_with_thread(thread)
    loop = server._loop
    _submit_future(monkeypatch, _ShutdownFuture(TimeoutError("shutdown timed out")))

    with pytest.raises(TimeoutError, match="shutdown timed out"):
        server.stop()

    assert server._thread is thread
    assert server._loop is loop
    assert server._lifecycle_state == "failed"
    assert not server.is_running()


def test_stop_reconciles_pending_shutdown_without_submitting_overlapping_cleanup(
        monkeypatch):
    thread = _ThreadThatStopsWhenCleanupCompletes()
    server = _server_with_thread(thread)
    cleanup_coroutines = []
    result_calls = []

    async def shutdown():
        pass

    server._shutdown = shutdown

    class PendingThenCompleteFuture:
        def result(self, timeout=None):
            result_calls.append(timeout)
            if len(result_calls) == 1:
                raise TimeoutError("shutdown still pending")
            server._cleanup_complete = True
            thread.cleanup_completed()

    future = PendingThenCompleteFuture()

    def submit(coro, loop):
        cleanup_coroutines.append(coro)
        return future

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", submit)

    with pytest.raises(TimeoutError, match="shutdown still pending"):
        server.stop()

    assert server._lifecycle_state == "failed"
    assert not server._cleanup_complete
    assert server._shutdown_future is future

    server.stop()

    assert len(cleanup_coroutines) == 1
    cleanup_coroutines[0].close()
    assert result_calls == [8, 8]
    assert server._cleanup_complete
    assert server._lifecycle_state == "stopped"
    assert server._shutdown_future is None
    assert server._thread is None
    assert server._loop is None


def test_concurrent_stop_submits_one_cleanup_and_reconciles_same_future(monkeypatch):
    thread = _ThreadThatStopsOnJoin()
    server = _server_with_thread(thread)
    callers_ready = threading.Barrier(2)
    submissions = []
    future_results = []
    future = _ShutdownFuture()
    original_stop = server.stop
    second_caller_started = threading.Event()
    result_callers = threading.Event()
    result_count = 0
    result_count_lock = threading.Lock()

    def synchronized_stop():
        callers_ready.wait(timeout=2)
        second_caller_started.set()
        return original_stop()

    server.stop = synchronized_stop

    def submit(coro, loop):
        submissions.append((coro, loop))
        assert second_caller_started.wait(timeout=2)
        return future

    def result(timeout=None):
        nonlocal result_count
        future_results.append((future, timeout))
        with result_count_lock:
            result_count += 1
            if result_count == 2:
                result_callers.set()
        assert result_callers.wait(timeout=2)

    future.result = result
    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", submit)

    errors = []
    workers = [threading.Thread(target=lambda: _stop_and_record(server, errors)) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=2)

    assert not errors
    assert all(not worker.is_alive() for worker in workers)
    assert len(submissions) == 1
    assert len(future_results) == 2
    assert all(observed_future is future for observed_future, _ in future_results)
    assert [timeout for _, timeout in future_results] == [8, 8]
    assert server._shutdown_future is None
    assert server._thread is None
    assert server._loop is None
    submissions[0][0].close()


def _stop_and_record(server, errors):
    try:
        server.stop()
    except BaseException as exc:  # pragma: no cover - assertion reports failures
        errors.append(exc)


def test_stop_preserves_actionable_state_when_thread_join_times_out(monkeypatch):
    thread = _ThreadThatStaysAlive()
    server = _server_with_thread(thread)
    loop = server._loop
    _submit_future(monkeypatch, _ShutdownFuture())

    with pytest.raises(TimeoutError, match="thread did not terminate"):
        server.stop()

    assert server._thread is thread
    assert server._loop is loop
    assert server._lifecycle_state == "failed"
    assert not server.is_running()


def test_start_rejects_restart_while_previous_thread_is_alive(monkeypatch):
    thread = _ThreadThatStaysAlive()
    server = _server_with_thread(thread)
    server._running = False
    server._lifecycle_state = "failed"

    def unexpected_thread(*args, **kwargs):
        raise AssertionError("start attempted to create a second server thread")

    monkeypatch.setattr("AssetsManager.lan.server.threading.Thread", unexpected_thread)

    with pytest.raises(RuntimeError, match="previous server thread is still alive"):
        server.start(port=8765, bind="127.0.0.1")

    assert server._thread is thread


def test_start_cannot_cross_final_stop_reconciliation(monkeypatch):
    join_started = threading.Event()
    allow_join = threading.Event()
    old_thread = _ThreadThatExitsDuringJoin(join_started, allow_join)
    server = _server_with_thread(old_thread)
    server._shutdown_future = _ShutdownFuture()
    server._cleanup_complete = True
    server._port = 8080
    server._build_app = lambda: None
    new_thread = _ThreadThatStopsOnJoin()
    new_thread.start = lambda: (
        setattr(server, "_running", True),
        setattr(server, "_lifecycle_state", "running"),
        setattr(server, "_loop", object()),
    )
    new_thread.join = lambda timeout=None: None
    stop_errors = []
    stopper = threading.Thread(target=lambda: _stop_and_record(server, stop_errors))
    monkeypatch.setattr(threading, "Thread", lambda *args, **kwargs: new_thread)
    _submit_future(monkeypatch, _ShutdownFuture())
    stopper.start()
    assert join_started.wait(timeout=2)

    with pytest.raises(RuntimeError, match="stop is still finalizing"):
        server.start(port=8765, bind="127.0.0.1")

    allow_join.set()
    stopper.join(timeout=2)
    assert not stop_errors

    server.start(port=8765, bind="127.0.0.1")
    assert server._thread is new_thread
    new_thread.is_alive = lambda: False
    server._cleanup_complete = True
    server.stop()
    assert server._thread is None
    assert server._loop is None


def test_start_rejects_until_mixed_concurrent_stop_callers_finish(monkeypatch):
    join_started = threading.Event()
    allow_join = threading.Event()
    old_thread = _ThreadThatExitsDuringJoin(join_started, allow_join)
    server = _server_with_thread(old_thread)
    server._cleanup_complete = True
    server._port = 8080
    server._build_app = lambda: None
    result_callers_ready = threading.Barrier(2)
    timeout_returned = threading.Event()

    class MixedResultFuture:
        def result(self, timeout=None):
            result_callers_ready.wait(timeout=2)
            if threading.current_thread().name == "timing-out-stopper":
                timeout_returned.set()
                raise TimeoutError("shared future wait timed out")
            assert timeout_returned.wait(timeout=2)

        def done(self):
            return False

    future = MixedResultFuture()
    _submit_future(monkeypatch, future)
    errors = []
    timing_out_stopper = threading.Thread(
        name="timing-out-stopper",
        target=lambda: _stop_and_record(server, errors),
    )
    successful_stopper = threading.Thread(
        name="successful-stopper",
        target=lambda: _stop_and_record(server, errors),
    )
    timing_out_stopper.start()
    successful_stopper.start()

    timing_out_stopper.join(timeout=2)
    assert not timing_out_stopper.is_alive()
    assert join_started.wait(timeout=2)
    assert server._lifecycle_state == "failed"
    assert errors and isinstance(errors[0], TimeoutError)

    with pytest.raises(RuntimeError, match="stop is still finalizing"):
        server.start(port=8765, bind="127.0.0.1")

    allow_join.set()
    successful_stopper.join(timeout=2)
    assert not successful_stopper.is_alive()
    assert len(errors) == 1
    assert server._lifecycle_state == "stopped"

    new_thread = _ThreadThatStopsOnJoin()
    new_thread.start = lambda: (
        setattr(server, "_running", True),
        setattr(server, "_lifecycle_state", "running"),
        setattr(server, "_loop", object()),
    )
    new_thread.join = lambda timeout=None: None
    monkeypatch.setattr(threading, "Thread", lambda *args, **kwargs: new_thread)

    server.start(port=8765, bind="127.0.0.1")

    assert server._thread is new_thread
    new_thread.is_alive = lambda: False
    server._cleanup_complete = True
    server.stop()


def test_start_rolls_back_when_thread_start_fails_before_worker_creation(monkeypatch):
    server = object.__new__(_LanServerImpl)
    server._running = False
    server._lifecycle_state = "stopped"
    server._cleanup_complete = True
    server._shutdown_future = None
    server._lifecycle_lock = threading.Lock()
    server._loop = None
    server._thread = None
    server._build_app = lambda: None

    def fail_start(_thread):
        raise RuntimeError("controlled thread start failure")

    monkeypatch.setattr(threading.Thread, "start", fail_start)

    with pytest.raises(RuntimeError, match="controlled thread start failure"):
        server.start(port=8765, bind="127.0.0.1")

    assert server._thread is None
    assert server._loop is None
    assert server._lifecycle_state == "stopped"
    assert server._cleanup_complete
    assert server._shutdown_future is None


def test_start_does_not_mask_preexisting_cleanup_incomplete_state(monkeypatch):
    server = object.__new__(_LanServerImpl)
    server._running = False
    server._lifecycle_state = "failed"
    server._cleanup_complete = False
    server._shutdown_future = object()
    server._loop = None
    server._thread = None
    server._lifecycle_lock = threading.Lock()
    server._build_app = lambda: None

    def unexpected_thread(*args, **kwargs):
        raise AssertionError("start attempted to replace incomplete cleanup state")

    monkeypatch.setattr("AssetsManager.lan.server.threading.Thread", unexpected_thread)

    with pytest.raises(RuntimeError, match="previous server cleanup incomplete"):
        server.start(port=8765, bind="127.0.0.1")

    assert server._thread is None
    assert server._loop is None
    assert server._lifecycle_state == "failed"
    assert not server._cleanup_complete


def test_successful_stop_clears_references_and_remains_idempotent(monkeypatch):
    thread = _ThreadThatStopsOnJoin()
    server = _server_with_thread(thread)
    _submit_future(monkeypatch, _ShutdownFuture())

    server.stop()


def test_successful_stop_without_runtime_remains_idempotent(monkeypatch):
    thread = _ThreadThatStopsOnJoin()
    server = _server_with_thread(thread)
    _submit_future(monkeypatch, _ShutdownFuture())

    server.stop()


def test_stop_calls_runtime_unregister_outside_server_lifecycle_lock():
    server = object.__new__(_LanServerImpl)
    thread = _ThreadThatStopsOnJoin()
    thread._alive = False
    server._running = False
    server._lifecycle_state = "running"
    server._cleanup_complete = True
    server._shutdown_future = None
    server._lifecycle_lock = threading.Lock()
    server._thread = thread
    server._loop = object()
    server._runtime_adapter_registered = True
    server._runtime_adapter_lock = threading.Lock()
    unregister_acquired = threading.Event()

    def unregister(_adapter):
        def acquire_server_lock():
            with server._lifecycle_lock:
                unregister_acquired.set()

        waiter = threading.Thread(target=acquire_server_lock)
        waiter.start()
        waiter.join(1)
        assert unregister_acquired.is_set()

    server.runtime = SimpleNamespace(unregister_lifecycle_adapter=unregister)

    server.stop()

    assert unregister_acquired.is_set()

    assert server._thread is None
    assert server._loop is None
    assert server._lifecycle_state == "stopped"
    assert not server.is_running()

    server.stop()


def test_server_registers_each_successful_generation_only_after_start(
        monkeypatch, tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    server = _LanServerImpl(runtime=runtime)

    class _ImmediateThread:
        def __init__(self, target, daemon=False):
            self._target = target
            self._alive = False

        def start(self):
            self._alive = True
            self._target()
            self._alive = False

        def is_alive(self):
            return self._alive

        def join(self, timeout=None):
            self._alive = False

    def run_generation():
        server._running = True
        server._lifecycle_state = "running"
        server._cleanup_complete = True
        assert server._register_runtime_adapter() is True

    server._build_app = lambda: None
    server._run = run_generation
    monkeypatch.setattr("AssetsManager.lan.server.threading.Thread", _ImmediateThread)

    from AssetsManager.application.security_preflight import SecurityPreflight
    preflight = SecurityPreflight()
    preflight.confirm_authenticated_lan()
    try:
        baseline_adapters = list(runtime._lifecycle_adapters)
        assert server not in baseline_adapters

        server.start(port=8765, bind="127.0.0.1", preflight=preflight)
        assert runtime._lifecycle_adapters == [*baseline_adapters, server]

        server.stop()
        assert runtime._lifecycle_adapters == baseline_adapters

        server.start(port=8765, bind="127.0.0.1", preflight=preflight)
        assert runtime._lifecycle_adapters == [*baseline_adapters, server]

        server.stop()
        assert runtime._lifecycle_adapters == baseline_adapters
    finally:
        if server._thread is not None:
            server.stop()
        bootstrap.library_service.close()


def test_server_registration_race_with_stop_cannot_leave_stale_runtime_adapter():
    registered = []
    registration_entered = threading.Event()
    release_registration = threading.Event()
    unregister_done = threading.Event()

    server = object.__new__(_LanServerImpl)
    server._runtime_adapter_registered = False
    server._runtime_adapter_lock = threading.Lock()

    def register(adapter):
        registered.append(adapter)
        registration_entered.set()
        assert release_registration.wait(5)
        return True

    def unregister(adapter):
        registered.remove(adapter)
        unregister_done.set()

    server.runtime = SimpleNamespace(
        register_lifecycle_adapter=register,
        unregister_lifecycle_adapter=unregister,
    )

    registration_thread = threading.Thread(target=server._register_runtime_adapter)
    registration_thread.start()
    assert registration_entered.wait(5)
    stop_thread = threading.Thread(target=server._unregister_runtime_adapter)
    stop_thread.start()
    release_registration.set()
    registration_thread.join(5)
    stop_thread.join(5)

    assert not registration_thread.is_alive()
    assert not stop_thread.is_alive()
    assert unregister_done.is_set()
    assert registered == []
    assert server._runtime_adapter_registered is False


def test_start_rejects_generation_that_runtime_does_not_retain():
    runtime = SimpleNamespace(register_lifecycle_adapter=Mock(return_value=False))
    server = object.__new__(_LanServerImpl)
    server.runtime = runtime
    server._runtime_adapter_registered = False
    server._runtime_adapter_lock = threading.Lock()
    server._running = False
    server._lifecycle_state = "stopped"
    server._cleanup_complete = True
    server._shutdown_future = None
    server._lifecycle_lock = threading.Lock()
    server._loop = None
    server._thread = None
    server._build_app = lambda: None

    def run_generation():
        server._running = True
        server._lifecycle_state = "running"
        server._cleanup_complete = True
        retained = server._register_runtime_adapter()
        if retained is False:
            server._running = False
            server._lifecycle_state = "failed"
            server._publish_startup_result("failure")

    class _ImmediateThread:
        def __init__(self, target, daemon=False):
            self._target = target
            self._alive = False

        def start(self):
            self._alive = True
            self._target()
            self._alive = False

        def is_alive(self):
            return self._alive

        def join(self, timeout=None):
            self._alive = False

    server._run = run_generation
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("AssetsManager.lan.server.threading.Thread", _ImmediateThread)
        with pytest.raises(OSError, match="Failed to start server"):
            server.start(port=8765, bind="127.0.0.1")

    assert server._lifecycle_state == "stopped"
    assert not server._running
    assert server._runtime_adapter_registered is False


def test_startup_registration_does_not_hold_server_lifecycle_lock(
        monkeypatch, tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    server = _LanServerImpl(runtime=runtime)
    lock_acquired = threading.Event()
    registration_finished = threading.Event()
    registration_errors = []

    async def start_accepting():
        pass

    class _Runner:
        async def setup(self):
            pass

        async def cleanup(self):
            pass

    class _Site:
        async def start(self):
            pass

    monkeypatch.setattr(server._ws_manager, "start_accepting", start_accepting)
    monkeypatch.setattr(server._auth_service, "init_tables", lambda: None)
    monkeypatch.setattr(server._share_service, "init_table", lambda: None)
    monkeypatch.setattr(server._scanner, "start_background_scan", lambda: None)
    monkeypatch.setattr("AssetsManager.lan.server.web.AppRunner", lambda *args, **kwargs: _Runner())
    monkeypatch.setattr("AssetsManager.lan.server.web.TCPSite", lambda *args, **kwargs: _Site())
    server._lifecycle_generation = 1
    server._startup_cancel_generation = None
    server._startup_result_event = threading.Event()
    server._startup_result = None
    server._cleanup_complete = False
    server._lifecycle_state = "starting"
    server._lifecycle_lock = threading.Lock()

    def register(adapter):
        assert adapter is server
        # The event only proves the lock was free once the waiter thread has
        # been *scheduled*; under CPU contention that can lag a 1s wait even
        # with the lock unheld.  The timeout exists only to bound a hang, so
        # keep it generous and report the observable fact (no acquisition
        # within the window) rather than asserting the lock was held.
        lock_wait_timeout = 10

        def acquire_lock():
            try:
                with server._lifecycle_lock:
                    lock_acquired.set()
            except BaseException as exc:  # pragma: no cover - diagnostic transfer
                registration_errors.append(exc)

        waiter = threading.Thread(target=acquire_lock)
        waiter.start()
        try:
            assert lock_acquired.wait(lock_wait_timeout), (
                f"lifecycle lock not acquired within {lock_wait_timeout}s "
                "during startup registration"
            )
        finally:
            waiter.join(lock_wait_timeout)
        server._cleanup_complete = True
        registration_finished.set()
        return True

    monkeypatch.setattr(runtime, "try_register_lifecycle_adapter", register)
    try:
        asyncio.run(server._startup())
        assert registration_finished.is_set()
        assert not registration_errors
    finally:
        server._unregister_runtime_adapter()
        bootstrap.library_service.close()


@pytest.mark.parametrize("failing_stage", ["close_all", "site_stop", "runner_cleanup"])
def test_stop_preserves_cleanup_handles_when_shutdown_stage_fails(
        monkeypatch, failing_stage):
    thread = _ThreadThatStopsOnJoin()
    server = _server_with_thread(thread)
    loop = server._loop
    _submit_future(monkeypatch, _ShutdownFuture(RuntimeError(failing_stage)))

    with pytest.raises(RuntimeError, match=failing_stage):
        server.stop()

    assert server._thread is thread
    assert server._loop is loop
    assert server._lifecycle_state == "failed"
    assert not server.is_running()

    with pytest.raises(RuntimeError, match="previous server"):
        server.start(port=8765, bind="127.0.0.1")


@pytest.mark.parametrize("failing_stage", ["close_all", "site_stop", "runner_cleanup"])
def test_shutdown_exercises_each_cleanup_stage_after_running_is_cleared(
        monkeypatch, failing_stage):
    calls = []
    server = object.__new__(_LanServerImpl)
    server._running = True

    async def stage(name):
        calls.append((name, server._running))
        if name == failing_stage:
            raise RuntimeError(name)

    server._ws_manager = SimpleNamespace(close_all=lambda: stage("close_all"))
    server._site = SimpleNamespace(stop=lambda: stage("site_stop"))
    server._runner = SimpleNamespace(cleanup=lambda: stage("runner_cleanup"))
    monkeypatch.setattr("AssetsManager.lan.server_lifecycle.stop_runtime_realtime", lambda _server: None)

    with pytest.raises(RuntimeError, match=failing_stage):
        asyncio.run(server._shutdown())

    assert calls[-1] == (failing_stage, False)


def test_real_thread_retries_failed_cleanup_and_closes_loop_on_owner_thread(monkeypatch):
    ready = threading.Event()
    close_thread_ids = []
    original_new_event_loop = asyncio.new_event_loop

    def new_event_loop():
        loop = original_new_event_loop()
        original_close = loop.close

        def close():
            close_thread_ids.append(threading.get_ident())
            original_close()

        loop.close = close
        return loop

    monkeypatch.setattr(asyncio, "new_event_loop", new_event_loop)

    server = object.__new__(_LanServerImpl)
    server._running = True
    server._lifecycle_state = "running"
    server._cleanup_complete = False
    server._shutdown_future = None
    server._lifecycle_lock = threading.Lock()
    server._loop = None
    attempts = 0

    async def startup():
        ready.set()
        while not server._cleanup_complete:
            await asyncio.sleep(0.01)

    async def shutdown():
        nonlocal attempts
        attempts += 1
        server._running = False
        if attempts == 1:
            raise RuntimeError("controlled cleanup failure")
        server._cleanup_complete = True

    server._startup = startup
    server._shutdown = shutdown
    thread = threading.Thread(target=server._run)
    server._thread = thread
    thread.start()
    assert ready.wait(timeout=2)
    loop = server._loop

    with pytest.raises(RuntimeError, match="controlled cleanup failure"):
        server.stop()

    assert thread.is_alive()
    assert server._thread is thread
    assert server._loop is loop
    assert close_thread_ids == []

    server.stop()

    assert not thread.is_alive()
    assert loop is not None and loop.is_closed()
    assert close_thread_ids == [thread.ident]
    assert server._thread is None
    assert server._loop is None


@pytest.mark.parametrize("retry_succeeds", [True, False])
def test_explicit_cleanup_retries_normal_stop_failure_once(retry_succeeds, monkeypatch):
    """A normal stop failure is retryable by the next lifecycle caller only once."""

    thread = _ThreadThatStopsWhenCleanupCompletes()
    server = object.__new__(_LanServerImpl)
    server._running = True
    server._lifecycle_state = "running"
    server._cleanup_complete = False
    server._shutdown_future = None
    server._lifecycle_lock = threading.Lock()
    server._loop = object()
    server._thread = thread
    server._lifecycle_generation = 1
    server._stop_reservation_generation = 1
    server._stop_reservations = 0
    server._cleanup_attempt_event = threading.Event()
    server._cleanup_attempt_state = "idle"
    server._cleanup_attempt_owner = None
    server._cleanup_attempt_error = None
    server._cleanup_retry_used = False
    server._startup_cleanup_failed = False
    server._startup_cleanup_retry_used = False
    server._unregister_runtime_adapter = lambda: None
    submitted = []

    async def shutdown():
        return None

    server._shutdown = shutdown

    def submit(coro, loop):
        submitted.append(coro)
        coro.close()
        if len(submitted) == 1 or not retry_succeeds:
            server._publish_cleanup_attempt("failed", RuntimeError("controlled stop failure"))
        else:
            server._cleanup_complete = True
            thread.cleanup_completed()
            server._publish_cleanup_attempt("succeeded")
        return _ShutdownFuture()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", submit)

    with pytest.raises(RuntimeError, match="controlled stop failure"):
        server.stop()
    assert len(submitted) == 1
    assert server._cleanup_retry_used is False

    if retry_succeeds:
        server.stop()
        assert server._cleanup_complete is True
        assert server._lifecycle_state == "stopped"
        assert not thread.is_alive()
        server.stop()
    else:
        with pytest.raises(RuntimeError, match="controlled stop failure"):
            server.stop()
        assert server._cleanup_retry_used is True
        assert server._cleanup_complete is False
        assert server._lifecycle_state == "failed"
        with pytest.raises(RuntimeError, match="controlled stop failure"):
            server.stop()

    assert len(submitted) == 2


@pytest.mark.parametrize("startup_error", [RuntimeError("startup failed after runner initialization")])
def test_startup_exception_retains_owner_thread_until_cleanup_retry(monkeypatch, startup_error):
    cleanup_thread_ids = []
    resource_initialized = threading.Event()
    server = object.__new__(_LanServerImpl)
    runtime = SimpleNamespace(unregister_lifecycle_adapter=Mock())
    server.runtime = runtime
    server._runtime_adapter_registered = True
    server._runtime_adapter_lock = threading.Lock()
    server._running = False
    server._lifecycle_state = "stopped"
    server._cleanup_complete = True
    server._shutdown_future = None
    server._lifecycle_lock = threading.Lock()
    server._loop = None
    server._thread = None
    server._runner = None
    server._build_app = lambda: None

    async def startup():
        server._runner = object()
        resource_initialized.set()
        raise startup_error

    cleanup_attempts = 0

    async def shutdown():
        nonlocal cleanup_attempts
        cleanup_attempts += 1
        cleanup_thread_ids.append(threading.get_ident())
        server._running = False
        if cleanup_attempts == 1:
            raise RuntimeError("controlled startup cleanup failure")
        server._cleanup_complete = True

    server._startup = startup
    server._shutdown = shutdown

    with pytest.raises(OSError, match="Failed to start server"):
        server.start(port=8765, bind="127.0.0.1")

    assert resource_initialized.is_set()
    failed_thread = server._thread
    failed_loop = server._loop
    assert failed_thread is not None and failed_thread.is_alive()
    assert failed_loop is not None and not failed_loop.is_closed()
    assert server._runner is not None
    assert server._lifecycle_state == "failed"
    assert not server._cleanup_complete
    for _ in range(100):
        if cleanup_thread_ids:
            break
        threading.Event().wait(0.01)
    assert cleanup_thread_ids == [failed_thread.ident]
    assert runtime.unregister_lifecycle_adapter.call_count == 0

    with pytest.raises(RuntimeError, match="previous server thread is still alive"):
        server.start(port=8765, bind="127.0.0.1")

    server.stop()

    assert cleanup_attempts == 2
    assert cleanup_thread_ids == [failed_thread.ident, failed_thread.ident]
    assert not failed_thread.is_alive()
    assert failed_loop.is_closed()
    assert server._cleanup_complete
    runtime.unregister_lifecycle_adapter.assert_called_once_with(server)
    assert server._runtime_adapter_registered is False
    assert server._lifecycle_state == "stopped"
    assert server._thread is None
    assert server._loop is None
    assert server._shutdown_future is None


def test_startup_system_exit_rolls_back_and_publishes_terminal_cleanup(monkeypatch):
    resource_initialized = threading.Event()
    cleanup_thread_ids = []
    server = object.__new__(_LanServerImpl)
    runtime = SimpleNamespace(unregister_lifecycle_adapter=Mock())
    server.runtime = runtime
    server._runtime_adapter_registered = True
    server._runtime_adapter_lock = threading.Lock()
    server._running = False
    server._lifecycle_state = "stopped"
    server._cleanup_complete = True
    server._shutdown_future = None
    server._lifecycle_lock = threading.Lock()
    server._loop = None
    server._thread = None
    server._runner = None
    server._build_app = lambda: None

    async def startup():
        server._runner = object()
        resource_initialized.set()
        raise SystemExit("startup base failure")

    async def shutdown():
        cleanup_thread_ids.append(threading.get_ident())
        server._running = False
        server._cleanup_complete = True

    server._startup = startup
    server._shutdown = shutdown

    with pytest.raises(OSError, match="Failed to start server"):
        server.start(port=8765, bind="127.0.0.1")

    failed_thread = server._thread
    failed_loop = server._loop
    assert resource_initialized.is_set()
    for _ in range(100):
        if cleanup_thread_ids:
            break
        threading.Event().wait(0.01)
    assert cleanup_thread_ids == [failed_thread.ident]
    assert not failed_thread.is_alive()
    assert failed_loop.is_closed()
    assert server._cleanup_complete
    assert server._startup_result[0] == "failure"
    runtime.unregister_lifecycle_adapter.assert_called_once_with(server)
    assert server._runtime_adapter_registered is False


@pytest.mark.parametrize("cleanup_error", [RuntimeError("controlled startup cleanup failure"), SystemExit("controlled startup cleanup failure")])
def test_startup_cleanup_base_exception_retains_owner_thread_until_stop_retry(
        monkeypatch, cleanup_error):
    resource_initialized = threading.Event()
    cleanup_thread_ids = []
    server = object.__new__(_LanServerImpl)
    runtime = SimpleNamespace(unregister_lifecycle_adapter=Mock())
    server.runtime = runtime
    server._runtime_adapter_registered = True
    server._runtime_adapter_lock = threading.Lock()
    server._running = False
    server._lifecycle_state = "stopped"
    server._cleanup_complete = True
    server._shutdown_future = None
    server._lifecycle_lock = threading.Lock()
    server._loop = None
    server._thread = None
    server._runner = None
    server._build_app = lambda: None

    async def startup():
        server._runner = object()
        resource_initialized.set()
        raise RuntimeError("startup failed after runner initialization")

    cleanup_attempts = 0

    async def shutdown():
        nonlocal cleanup_attempts
        cleanup_attempts += 1
        cleanup_thread_ids.append(threading.get_ident())
        server._running = False
        if cleanup_attempts == 1:
            raise cleanup_error
        server._cleanup_complete = True

    server._startup = startup
    server._shutdown = shutdown

    with pytest.raises(OSError, match="Failed to start server"):
        server.start(port=8765, bind="127.0.0.1")

    failed_thread = server._thread
    failed_loop = server._loop
    assert resource_initialized.is_set()
    for _ in range(100):
        if cleanup_thread_ids:
            break
        threading.Event().wait(0.01)
    assert failed_thread.is_alive()
    assert not failed_loop.is_closed()
    assert not server._cleanup_complete
    assert cleanup_thread_ids == [failed_thread.ident]
    assert runtime.unregister_lifecycle_adapter.call_count == 0

    server.stop()

    assert cleanup_attempts == 2
    assert cleanup_thread_ids == [failed_thread.ident, failed_thread.ident]
    assert failed_loop.is_closed()
    assert server._cleanup_complete
    runtime.unregister_lifecycle_adapter.assert_called_once_with(server)
    assert server._runtime_adapter_registered is False


def test_startup_cancellation_cleanup_base_exception_retains_owner_loop_until_stop_retry():
    cleanup_attempted = threading.Event()
    cleanup_attempts = []
    server = object.__new__(_LanServerImpl)
    runtime = SimpleNamespace(unregister_lifecycle_adapter=Mock())
    server.runtime = runtime
    server._runtime_adapter_registered = True
    server._runtime_adapter_lock = threading.Lock()
    server._running = False
    server._lifecycle_state = "starting"
    server._cleanup_complete = False
    server._shutdown_future = None
    server._startup_cleanup_failed = False
    server._lifecycle_generation = 1
    server._startup_cancel_generation = 1
    server._cleanup_started_event = None
    server._startup_result_event = threading.Event()
    server._startup_result = None
    server._lifecycle_lock = threading.Lock()
    server._loop = None
    server._thread = None

    async def startup():
        server._running = True

    async def shutdown():
        cleanup_attempts.append(threading.get_ident())
        cleanup_attempted.set()
        server._running = False
        if len(cleanup_attempts) == 1:
            raise SystemExit("cancel cleanup failed")
        server._cleanup_complete = True

    server._startup = startup
    server._shutdown = shutdown
    thread = threading.Thread(target=server._run)
    server._thread = thread
    thread.start()

    assert cleanup_attempted.wait(timeout=2)
    assert thread.is_alive()
    loop = server._loop
    assert loop is not None and not loop.is_closed()
    assert server._startup_cleanup_failed is True
    assert server._cleanup_complete is False
    assert runtime.unregister_lifecycle_adapter.call_count == 0

    server.stop()

    assert cleanup_attempts == [thread.ident, thread.ident]
    assert not thread.is_alive()
    assert loop.is_closed()
    assert server._cleanup_complete is True
    assert server._lifecycle_state == "stopped"
    assert server._thread is None
    assert server._loop is None
    runtime.unregister_lifecycle_adapter.assert_called_once_with(server)
    assert server._runtime_adapter_registered is False


@pytest.mark.parametrize("startup_cancelled", [False, True])
def test_startup_shared_cleanup_failure_marks_stop_retry_state(startup_cancelled, monkeypatch):
    shared_cleanup = _ShutdownFuture(RuntimeError("shared cleanup failed"))
    server = object.__new__(_LanServerImpl)
    server._running = False
    server._lifecycle_state = "starting"
    server._cleanup_complete = False
    server._shutdown_future = shared_cleanup
    server._startup_cleanup_failed = False
    server._lifecycle_generation = 1
    server._startup_cancel_generation = 1 if startup_cancelled else None
    server._cleanup_started_event = None
    server._startup_result_event = threading.Event()
    server._startup_result = None
    server._lifecycle_lock = threading.Lock()
    server._loop = None
    server._thread = None

    async def startup():
        if startup_cancelled:
            server._running = True
            return
        raise RuntimeError("startup failed")

    server._startup = startup
    async def shutdown():
        return None

    server._shutdown = shutdown
    thread = threading.Thread(target=server._run)
    server._thread = thread
    thread.start()

    for _ in range(200):
        if server._startup_cleanup_failed:
            break
        threading.Event().wait(0.01)
    assert server._startup_cleanup_failed is True
    assert server._shutdown_future is shared_cleanup
    assert server._cleanup_complete is False

    thread_ident = thread.ident
    assert thread_ident is not None
    assert server._loop is not None and not server._loop.is_closed()
    class RetryFuture:
        def result(self, timeout):
            server._cleanup_complete = True

    submitted = []

    def submit(coro, loop):
        submitted.append(coro)
        coro.close()
        return RetryFuture()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", submit)
    server.stop()

    # The shared future is deliberately left to stop() to reconcile.  The
    # startup owner must not submit a second cleanup coroutine itself.
    assert len(submitted) == 1
    thread.join(timeout=2)
    assert not thread.is_alive()


@pytest.mark.parametrize(
    "cleanup_error",
    [RuntimeError("shared cleanup failed"), SystemExit("shared cleanup stopped"),
     TimeoutError("shared cleanup wait timed out")],
)
def test_stop_retries_shared_startup_cleanup_when_future_fails_during_result(
        cleanup_error, monkeypatch):
    class PendingThenFailedFuture:
        def __init__(self, error):
            self.error = error
            self._done = False

        def done(self):
            return self._done

        def exception(self):
            return self.error if self._done else None

        def result(self, timeout):
            self._done = True
            raise self.error

    class RetryFuture:
        def result(self, timeout):
            server._cleanup_complete = True
            server._thread.cleanup_completed()

    server = object.__new__(_LanServerImpl)
    server._running = False
    server._lifecycle_state = "starting"
    server._cleanup_complete = False
    server._shutdown_future = PendingThenFailedFuture(cleanup_error)
    server._startup_cleanup_failed = True
    server._lifecycle_generation = 1
    server._startup_cancel_generation = 1
    server._lifecycle_lock = threading.Lock()
    server._loop = object()

    async def shutdown():
        return None

    server._shutdown = shutdown
    server._thread = _ThreadThatStopsWhenCleanupCompletes()
    submitted = []

    def submit(coro, loop):
        submitted.append(coro)
        coro.close()
        return RetryFuture()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", submit)

    server.stop()

    assert len(submitted) == 1
    assert server._cleanup_complete
    assert server._shutdown_future is None


def test_stop_retries_startup_cleanup_that_fails_after_reconciliation(monkeypatch):
    class FakeThread:
        def __init__(self):
            self.ident = 4242
            self._alive = True

        def is_alive(self):
            return self._alive

        def join(self, timeout):
            self._alive = False

    class FailedBetweenCheckAndResult:
        def __init__(self):
            self._failed = False

        def done(self):
            return self._failed

        def exception(self):
            return RuntimeError("controlled startup cleanup failure") if self._failed else None

        def result(self, timeout):
            self._failed = True
            raise RuntimeError("controlled startup cleanup failure")

    class RetryFuture:
        def result(self, timeout):
            server._cleanup_complete = True

    server = object.__new__(_LanServerImpl)
    server._running = False
    server._lifecycle_state = "failed"
    server._cleanup_complete = False
    server._startup_cleanup_failed = True
    server._shutdown_future = FailedBetweenCheckAndResult()
    server._lifecycle_lock = threading.Lock()
    server._lifecycle_generation = 1
    server._stop_reservation_generation = 1
    server._stop_reservations = 0
    server._loop = object()
    server._thread = FakeThread()

    async def shutdown():
        return None

    server._shutdown = shutdown
    submitted = []

    def submit(coro, loop):
        submitted.append(coro)
        coro.close()
        return RetryFuture()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", submit)

    server.stop()

    assert len(submitted) == 1
    assert server._cleanup_complete
    assert server._shutdown_future is None


def test_stop_reconciles_owner_failure_published_at_future_timeout_boundary(monkeypatch):
    """A terminal owner publication wins even while the future is still pending."""

    publication_order = []
    result_calls = []
    retry_submissions = []
    thread = _ThreadThatStopsWhenCleanupCompletes()
    server = object.__new__(_LanServerImpl)
    server._running = False
    server._lifecycle_state = "failed"
    server._cleanup_complete = False
    server._lifecycle_generation = 1
    server._stop_reservation_generation = 1
    server._stop_reservations = 0
    server._startup_cleanup_failed = False
    server._startup_cleanup_retry_used = False
    server._cleanup_attempt_state = "running"
    server._cleanup_attempt_owner = "startup"
    server._cleanup_attempt_error = None
    server._lifecycle_lock = threading.Lock()
    server._loop = object()
    server._thread = thread
    server._unregister_runtime_adapter = lambda: None

    class PendingFuture:
        def done(self):
            return False

        def result(self, timeout=None):
            result_calls.append(timeout)
            raise AssertionError("stop must use the cleanup-attempt publication")

    owner_future = PendingFuture()
    server._shutdown_future = owner_future

    class BoundaryEvent:
        def __init__(self):
            self._event = threading.Event()
            self._published = False

        def clear(self):
            self._event.clear()

        def set(self):
            self._event.set()

        def wait(self, timeout=None):
            if not self._published:
                self._published = True
                publication_order.append("owner-failed")
                server._publish_cleanup_attempt(
                    "failed", RuntimeError("owner cleanup failed at timeout boundary")
                )
            return self._event.is_set()

    server._cleanup_attempt_event = BoundaryEvent()

    def submit(coro, loop):
        retry_submissions.append(coro)
        coro.close()
        server._cleanup_complete = True
        thread.cleanup_completed()
        publication_order.append("retry-succeeded")
        server._publish_cleanup_attempt("succeeded")
        return _ShutdownFuture()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", submit)

    server.stop()

    assert publication_order == ["owner-failed", "retry-succeeded"]
    assert len(retry_submissions) == 1
    assert result_calls == []
    assert server._cleanup_complete is True
    assert server._cleanup_attempt_state == "succeeded"


def test_start_waits_for_definitive_delayed_startup_success():
    startup_finished = threading.Event()
    cleanup_finished = threading.Event()
    server = object.__new__(_LanServerImpl)
    server._running = False
    server._lifecycle_state = "stopped"
    server._cleanup_complete = True
    server._shutdown_future = None
    server._lifecycle_lock = threading.Lock()
    server._loop = None
    server._thread = None
    server._build_app = lambda: None

    async def startup():
        await asyncio.sleep(2.1)
        server._running = True
        server._lifecycle_state = "running"
        server._publish_startup_result("success")
        startup_finished.set()
        await asyncio.to_thread(cleanup_finished.wait)

    async def shutdown():
        server._running = False
        server._cleanup_complete = True
        cleanup_finished.set()

    server._startup = startup
    server._shutdown = shutdown

    server.start(port=8765, bind="127.0.0.1")

    assert startup_finished.is_set()
    assert server._lifecycle_state == "running"
    server.stop()


def test_stop_reconciles_startup_rollback_future_without_overlapping_shutdown():
    startup_failed = threading.Event()
    rollback_started = threading.Event()
    release_rollback = threading.Event()
    cleanup_finished = threading.Event()
    server = object.__new__(_LanServerImpl)
    server._running = False
    server._lifecycle_state = "stopped"
    server._cleanup_complete = True
    server._shutdown_future = None
    server._lifecycle_lock = threading.Lock()
    server._loop = None
    server._thread = None
    server._runner = object()
    server._build_app = lambda: None

    async def startup():
        startup_failed.set()
        raise RuntimeError("controlled startup failure")

    shutdown_calls = 0

    async def shutdown():
        nonlocal shutdown_calls
        shutdown_calls += 1
        rollback_started.set()
        await asyncio.to_thread(release_rollback.wait)
        server._cleanup_complete = True
        cleanup_finished.set()

    server._startup = startup
    server._shutdown = shutdown

    with pytest.raises(OSError, match="Failed to start server"):
        server.start(port=8765, bind="127.0.0.1")

    assert startup_failed.is_set()
    assert rollback_started.wait(timeout=2)
    stop_thread = threading.Thread(target=server.stop)
    stop_thread.start()
    assert stop_thread.is_alive()
    assert shutdown_calls == 1

    release_rollback.set()
    stop_thread.join(timeout=2)
    assert not stop_thread.is_alive()
    assert cleanup_finished.is_set()
    assert shutdown_calls == 1


def test_startup_running_publication_is_atomic_against_cancellation(monkeypatch):
    publication_paused = threading.Event()
    release_publication = threading.Event()
    cancellation_finished = threading.Event()
    server = object.__new__(_LanServerImpl)
    server._running = False
    server._lifecycle_state = "starting"
    server._cleanup_complete = False
    server._lifecycle_generation = 1
    server._startup_cancel_generation = None
    server._lifecycle_lock = threading.Lock()
    server._port = 8765
    server._bind = "127.0.0.1"
    server._runner = None
    server._site = None
    server._app = {}
    server._ssl_cert = None
    server._ssl_key = None
    server._ws_manager = SimpleNamespace(start_accepting=lambda: _completed(), close_all=lambda: _completed())
    server._auth_service = SimpleNamespace(init_tables=lambda: None)
    server._share_service = SimpleNamespace(init_table=lambda: None)
    server._scanner = SimpleNamespace(start_background_scan=lambda: None)
    server._startup_result_event = threading.Event()
    server._startup_result = None

    class Runner:
        async def setup(self):
            pass

        async def cleanup(self):
            pass

    class Site:
        async def start(self):
            pass

    monkeypatch.setattr("AssetsManager.lan.server.web.AppRunner", lambda *args, **kwargs: Runner())
    monkeypatch.setattr("AssetsManager.lan.server.web.TCPSite", lambda *args, **kwargs: Site())
    class PausingLock:
        def __init__(self):
            self._lock = threading.Lock()

        def __enter__(self):
            self._lock.acquire()
            return self

        def __exit__(self, *args):
            publication_paused.set()
            release_publication.wait(timeout=2)
            self._lock.release()

    server._lifecycle_lock = PausingLock()

    def cancel_startup():
        with server._lifecycle_lock:
            server._startup_cancel_generation = server._lifecycle_generation
            server._running = False
            server._lifecycle_state = "failed"
        cancellation_finished.set()

    async def _startup_wrapper():
        task = asyncio.create_task(server._startup())
        await asyncio.to_thread(publication_paused.wait, 2)
        assert server._running is True
        canceller = threading.Thread(target=cancel_startup)
        canceller.start()
        assert not cancellation_finished.wait(timeout=0.1)
        release_publication.set()
        canceller.join(timeout=2)
        assert cancellation_finished.is_set()
        server._cleanup_complete = True
        await task

    async def _completed():
        pass

    asyncio.run(_startup_wrapper())

    assert server._running is False
    assert server._lifecycle_state == "failed"


def test_bind_failure_returns_without_waiting_for_rollback_timeout(monkeypatch):
    server = object.__new__(_LanServerImpl)
    runtime = SimpleNamespace(unregister_lifecycle_adapter=Mock())
    server.runtime = runtime
    server._runtime_adapter_registered = True
    server._runtime_adapter_lock = threading.Lock()
    server._running = False
    server._lifecycle_state = "stopped"
    server._cleanup_complete = True
    server._shutdown_future = None
    server._lifecycle_lock = threading.Lock()
    server._loop = None
    server._thread = None
    server._runner = None
    server._site = None
    server._app = {}
    server._ssl_cert = None
    server._ssl_key = None
    server._ws_manager = SimpleNamespace(start_accepting=lambda: _completed(), close_all=lambda: _completed())
    server._auth_service = SimpleNamespace(init_tables=lambda: None)
    server._share_service = SimpleNamespace(init_table=lambda: None)
    server._scanner = SimpleNamespace(start_background_scan=lambda: None)
    server._build_app = lambda: None

    class Runner:
        async def setup(self):
            pass

        async def cleanup(self):
            pass

    class Site:
        async def start(self):
            raise OSError("address already in use")

    async def _completed():
        pass

    monkeypatch.setattr("AssetsManager.lan.server.web.AppRunner", lambda *args, **kwargs: Runner())
    monkeypatch.setattr("AssetsManager.lan.server.web.TCPSite", lambda *args, **kwargs: Site())
    server._startup = _LanServerImpl._startup.__get__(server, _LanServerImpl)

    started = time.monotonic()
    with pytest.raises(OSError, match="Failed to start server"):
        server.start(port=8765, bind="127.0.0.1")
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    if server._thread is not None:
        server._thread.join(timeout=1)
    assert server._running is False
    assert server._lifecycle_state == "stopped"
    assert server._cleanup_complete is True
    server._port = 8765
    server._started_at = None
    server._share_name = "test"
    server._library_root = Path(".")
    server._access_key_hash = None
    server._password_hash = None
    server._auth_mode = "none"
    server._has_users_cache = False
    server._has_users_cache_time = 0
    server._connections = 0
    server._requests = 0
    server._bytes_transferred = 0
    assert server.is_running() is False
    assert server.status()["restart_ready"] is True
    runtime.unregister_lifecycle_adapter.assert_called_once_with(server)
    assert server._runtime_adapter_registered is False


def test_explicit_tls_load_failure_does_not_downgrade_to_http(monkeypatch):
    server = object.__new__(_LanServerImpl)
    server._ssl_cert = "missing-cert.pem"
    server._ssl_key = "missing-key.pem"
    server._ssl_active = False
    server._app = {}
    server._running = False
    server._cleanup_complete = False
    server._lifecycle_state = "starting"
    server._lifecycle_generation = 1
    server._startup_cancel_generation = None
    server._lifecycle_lock = threading.Lock()
    server._runner = None
    server._site = None
    server._ws_manager = SimpleNamespace(start_accepting=lambda: _completed())
    server._auth_service = SimpleNamespace()
    server._port = 8765
    server._bind = "127.0.0.1"

    class Runner:
        async def setup(self):
            pass

    def unexpected_site(*args, **kwargs):
        raise AssertionError("explicit TLS failure must not continue to HTTP site creation")

    monkeypatch.setattr("AssetsManager.lan.server.web.AppRunner", lambda *args, **kwargs: Runner())
    monkeypatch.setattr("AssetsManager.lan.server.web.TCPSite", unexpected_site)

    with pytest.raises((FileNotFoundError, OSError)):
        asyncio.run(_LanServerImpl._startup(server))

    assert server._ssl_active is False


def _server_with_users_cache():
    server = object.__new__(_LanServerImpl)
    server._auth_mode = "user"
    server._has_users_cache = None
    server._has_users_cache_time = 0.0
    server._has_users_cache_ttl = 30.0
    server._has_users_cache_lock = threading.Lock()
    probes = []

    class _AuthService:
        def has_active_users(self, raise_on_error=True):
            probes.append(time.monotonic())
            return True

    server._auth_service = _AuthService()
    return server, probes


def test_has_users_cache_serves_ttl_and_invalidate_forces_reprobe():
    """The cache satisfies repeated reads; invalidation re-probes the DB."""
    server, probes = _server_with_users_cache()

    assert server._has_active_users() is True
    assert server._has_active_users() is True
    assert len(probes) == 1

    server.invalidate_user_cache()
    assert server._has_active_users() is True
    assert len(probes) == 2


def test_has_users_cache_fails_closed_and_caches_the_negative_result():
    server = object.__new__(_LanServerImpl)
    server._auth_mode = "user"
    server._has_users_cache = None
    server._has_users_cache_time = 0.0
    server._has_users_cache_ttl = 30.0
    server._has_users_cache_lock = threading.Lock()

    class _BrokenAuthService:
        def has_active_users(self, raise_on_error=True):
            raise RuntimeError("database unavailable")

    server._auth_service = _BrokenAuthService()
    assert server._has_active_users() is True
    # Fail-closed result stays cached for the TTL: no re-probe, no re-log.
    assert server._has_active_users() is True


def test_has_users_cache_survives_cross_thread_hammering():
    """The cache is read by the event-loop thread (middleware) and the UI
    thread (status/auth_status); concurrent probes and invalidations must
    neither raise nor leave an inconsistent cached state."""
    server, probes = _server_with_users_cache()
    errors = []

    def hammer():
        try:
            for _ in range(300):
                if server._has_active_users() is not True:
                    errors.append(AssertionError("unexpected cache result"))
                server.invalidate_user_cache()
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    with server._has_users_cache_lock:
        if server._has_users_cache is not None:
            assert server._has_users_cache is True
            assert server._has_users_cache_time > 0.0


def _server_with_revocation(conn):
    from AssetsManager.application.auth_service import AuthService

    server = object.__new__(_LanServerImpl)
    server._revoked_tokens = {}
    server._revoked_loaded = False
    server._TOKEN_REVOCATION_TTL = 86400
    server._TOKEN_REVOCATION_MAX = 10000
    server._auth_service = AuthService(conn, "test-secret")
    return server


def test_revocation_survives_server_restart(schema_db):
    """A revoked token stays revoked across an app restart: the revocation
    is persisted in the library DB, not just the in-memory table."""
    token = "1234567890.nonce.deadbeef"

    server_a = _server_with_revocation(schema_db)
    server_a.revoke_auth_token(token)
    assert server_a.is_auth_token_revoked(token) is True
    assert server_a.is_auth_token_revoked("1234567890.nonce.other") is False

    # A brand-new server instance over the same library DB simulates an app
    # restart; the persisted revocation must still hold.
    server_b = _server_with_revocation(schema_db)
    assert server_b.is_auth_token_revoked(token) is True
