"""LAN server lifecycle machinery — split out of ``lan/server.py``.

Hosts the stop/cleanup "single-owner" protocol and the startup worker-loop
state machine for ``_LanServerImpl``: ``stop``, the ``_cleanup_attempt_*``
attempt state machine, ``_shutdown`` and its cleanup helpers, ``_run``'s
startup-failure fallback cleanup, the startup-result publication and the
runtime lifecycle-adapter helpers.  Auth/middleware/route building and
WS/scan orchestration remain in ``lan/server.py``.

This is a pure mixin: it defines no ``__init__`` and holds no state of its
own — every attribute lives on the ``_LanServerImpl`` instance, so the
attribute access paths (including tests that poke ``_cleanup_attempt_*``
directly) are unchanged.
"""
import asyncio
import concurrent.futures
import logging
import threading
from typing import TYPE_CHECKING, Any

from AssetsManager.lan.api import stop_runtime_realtime

_log = logging.getLogger(__name__)


class LanServerLifecycleMixin:
    """Lifecycle-protocol methods for the LAN server (see module docstring)."""

    if TYPE_CHECKING:
        from aiohttp import web

        from AssetsManager.lan.ws import WebSocketManager

        # Attributes owned by _LanServerImpl (plus the two host methods
        # called below); declared here — the house mixin pattern, cf.
        # panels/file_list/_navigation.py — so static analysis resolves
        # attribute access on this pure mixin.  Declarations only: no
        # runtime state, no behaviour.
        _lifecycle_lock: threading.Lock
        _lifecycle_state: str
        _running: bool
        _cleanup_complete: bool
        _loop: asyncio.AbstractEventLoop | None
        _thread: threading.Thread | None
        _shutdown_future: concurrent.futures.Future[Any] | None
        _stop_reservations: int
        _stop_reservation_generation: int
        _cleanup_retry_used: bool
        _startup_cleanup_retry_used: bool
        _startup_cleanup_failed: bool
        _startup_result: tuple[str, int] | None
        _cleanup_attempt_event: threading.Event | None
        _cleanup_attempt_future: concurrent.futures.Future[Any] | None
        _cleanup_attempt_state: str
        _cleanup_attempt_owner: str | None
        _cleanup_attempt_error: BaseException | None
        _gallery_prewarm_thread: threading.Thread | None
        _zip_executor_shutdown: bool
        _ws_manager: WebSocketManager
        _site: web.TCPSite | None
        _runner: web.AppRunner | None
        _site_started: bool
        _ssl_active: bool
        _runtime_adapter_lock: threading.Lock | None
        _runtime_adapter_condition_lock: threading.Condition | None
        _runtime_adapter_state: str
        _runtime_adapter_registered: bool
        _runtime_adapter_registration_thread: int | None

        def stop_tunnel(self) -> None: ...
        async def _startup(self) -> None: ...

    def stop(self):
        """Stop the server gracefully.

        The server owns its tunnel process.  A tunnel cleanup failure is
        part of the same retryable lifecycle and must not be hidden by clearing
        the LAN owner handles.
        """
        # ``stop()`` can be called before the worker loop exists (or after a
        # failed startup).  Keep the auth boundary fail-closed even on those
        tunnel = getattr(self, "_tunnel", None)
        if tunnel is not None:
            tunnel_process = getattr(tunnel, "_process", None)
            try:
                tunnel_running = bool(tunnel.is_running)
            except Exception:
                tunnel_running = tunnel_process is not None
            if tunnel_process is not None or tunnel_running:
                self.stop_tunnel()

        unregister_after_lock = False
        submit_cleanup = False
        explicit_cleanup_protocol = False
        with self._lifecycle_lock:
            thread = self._thread
            generation = getattr(self, "_lifecycle_generation", 0)
            if thread is None:
                self._running = False
                self._lifecycle_state = "stopped"
                self._loop = None
                self._thread = None
                self._shutdown_future = None
                unregister_after_lock = True
            elif not thread.is_alive():
                if not self._cleanup_complete:
                    self._lifecycle_state = "failed"
                    raise RuntimeError("Server thread terminated with cleanup incomplete")
                self._running = False
                self._lifecycle_state = "stopped"
                self._loop = None
                self._thread = None
                self._shutdown_future = None
                unregister_after_lock = True
            if self._loop is None:
                if unregister_after_lock:
                    pass
                else:
                    self._lifecycle_state = "failed"
                    raise RuntimeError("Cannot stop live server thread without its event loop")
            elif unregister_after_lock:
                pass
            else:
                self._lifecycle_state = "stopping"
                explicit_cleanup_protocol = getattr(self, "_cleanup_attempt_event", None) is not None
                future = self._shutdown_future
                if explicit_cleanup_protocol:
                    state = getattr(self, "_cleanup_attempt_state", "idle")
                    retry_startup_cleanup = (
                        state == "failed"
                        and getattr(self, "_startup_cleanup_failed", False)
                        and not getattr(self, "_startup_cleanup_retry_used", False)
                        and not self._cleanup_complete
                    )
                    retry_failed_cleanup = (
                        state == "failed"
                        and not getattr(self, "_cleanup_retry_used", False)
                        and not self._cleanup_complete
                    )
                    if retry_failed_cleanup:
                        self._cleanup_retry_used = True
                        if retry_startup_cleanup:
                            self._startup_cleanup_retry_used = True
                        future = self._reset_cleanup_attempt_locked("stop-retry")
                        submit_cleanup = True
                    elif state == "running" and future is not None:
                        pass
                    elif future is None or state in {"idle", "succeeded"}:
                        future = self._reset_cleanup_attempt_locked("stop")
                        submit_cleanup = True
                    elif state == "failed":
                        # A failed cleanup has already consumed its one retry.
                        # Keep the failed attempt available for the bounded wait
                        # below; do not overlap another cleanup coroutine.
                        pass
                else:
                    if future is not None and getattr(future, "done", lambda: False)():
                        future_failed = False
                        try:
                            future_failed = future.exception() is not None
                        except concurrent.futures.CancelledError:
                            future_failed = True
                        except Exception:
                            pass
                        if future_failed and not self._cleanup_complete:
                            self._shutdown_future = None
                            future = None
                    if future is None:
                        loop = self._loop
                        assert loop is not None
                        future = asyncio.run_coroutine_threadsafe(self._shutdown(), loop)
                        self._shutdown_future = future
                reservation_generation = generation
                if getattr(self, "_stop_reservation_generation", generation) != generation:
                    self._stop_reservations = 0
                self._stop_reservation_generation = generation
                self._stop_reservations = getattr(self, "_stop_reservations", 0) + 1

        if unregister_after_lock:
            self._unregister_runtime_adapter()
            return

        if submit_cleanup:
            loop = self._loop
            assert loop is not None
            future = self._submit_cleanup_attempt(loop, future)

        try:
            if explicit_cleanup_protocol:
                while True:
                    attempt_event = self._cleanup_attempt_event
                    assert attempt_event is not None
                    if not attempt_event.wait(timeout=8):
                        shutdown_error = TimeoutError(
                            "Server shutdown timed out or cleanup attempt did not finish"
                        )
                        _log.warning("Server shutdown timed out or failed: %s", shutdown_error)
                        break
                    with self._lifecycle_lock:
                        attempt_state = self._cleanup_attempt_state
                        retry_startup_cleanup = (
                            attempt_state == "failed"
                            and self._shutdown_future is future
                            and getattr(self, "_startup_cleanup_failed", False)
                            and not getattr(self, "_startup_cleanup_retry_used", False)
                            and not self._cleanup_complete
                        )
                        if retry_startup_cleanup:
                            self._cleanup_retry_used = True
                            self._startup_cleanup_retry_used = True
                            retry_placeholder = self._reset_cleanup_attempt_locked("stop-retry")
                        else:
                            retry_placeholder = None
                    if retry_startup_cleanup:
                        loop = self._loop
                        assert loop is not None
                        assert retry_placeholder is not None
                        future = self._submit_cleanup_attempt(loop, retry_placeholder)
                        continue
                    if attempt_state == "failed":
                        shutdown_error = self._cleanup_attempt_error or RuntimeError(
                            "LAN cleanup attempt failed"
                        )
                    else:
                        shutdown_error = None
                    break
            else:
                while True:
                    shutdown_error = None
                    try:
                        future.result(timeout=8)
                    except TimeoutError as exc:
                        with self._lifecycle_lock:
                            future_done = getattr(future, "done", lambda: False)()
                            retry_startup_cleanup = (
                                self._shutdown_future is future
                                and future_done
                                and getattr(self, "_startup_cleanup_failed", False)
                                and not self._cleanup_complete
                            )
                            if self._shutdown_future is future and (future_done or retry_startup_cleanup):
                                self._shutdown_future = None
                            if retry_startup_cleanup:
                                self._startup_cleanup_failed = False
                        if retry_startup_cleanup:
                            with self._lifecycle_lock:
                                loop = self._loop
                                assert loop is not None
                                future = asyncio.run_coroutine_threadsafe(
                                    self._shutdown(), loop
                                )
                                self._shutdown_future = future
                            continue
                        shutdown_error = exc
                        _log.warning("Server shutdown timed out or failed: %s", exc)
                    except BaseException as exc:
                        with self._lifecycle_lock:
                            retry_startup_cleanup = (
                                self._shutdown_future is future
                                and getattr(self, "_startup_cleanup_failed", False)
                                and not self._cleanup_complete
                            )
                            if self._shutdown_future is future:
                                self._shutdown_future = None
                            if retry_startup_cleanup:
                                self._startup_cleanup_failed = False
                        if retry_startup_cleanup:
                            with self._lifecycle_lock:
                                loop = self._loop
                                assert loop is not None
                                future = asyncio.run_coroutine_threadsafe(
                                    self._shutdown(), loop
                                )
                                self._shutdown_future = future
                            continue
                        shutdown_error = exc
                        _log.warning("Server shutdown timed out or failed: %s", exc)
                    break

            if shutdown_error is not None:
                with self._lifecycle_lock:
                    self._lifecycle_state = "failed"
                raise shutdown_error

            assert thread is not None
            if thread is not threading.current_thread():
                thread.join(timeout=8)

            if thread.is_alive():
                with self._lifecycle_lock:
                    self._lifecycle_state = "failed"
                raise TimeoutError("Server thread did not terminate after shutdown")

            with self._lifecycle_lock:
                if (self._thread is not thread
                        or getattr(self, "_lifecycle_generation", 0) != generation):
                    return
                self._running = False
                self._cleanup_complete = True
                self._lifecycle_state = "stopped"
                self._loop = None
                self._thread = None
                self._shutdown_future = None
                self._startup_cleanup_failed = False
            self._unregister_runtime_adapter()
        finally:
            with self._lifecycle_lock:
                if (getattr(self, "_stop_reservation_generation", None)
                        == reservation_generation):
                    self._stop_reservations = max(
                        0, getattr(self, "_stop_reservations", 0) - 1
                    )

    def _unregister_runtime_adapter(self):
        runtime = getattr(self, "runtime", None)
        unregister_adapter = getattr(runtime, "unregister_lifecycle_adapter", None)
        if not callable(unregister_adapter):
            return
        condition = self._runtime_adapter_condition()
        with condition:
            while getattr(self, "_runtime_adapter_state", "unregistered") == "registering":
                if getattr(self, "_runtime_adapter_registration_thread", None) == threading.get_ident():
                    return
                condition.wait()
            if getattr(self, "_runtime_adapter_state", "unregistered") != "registered":
                return
            self._runtime_adapter_state = "unregistering"
            self._runtime_adapter_registered = False
        try:
            unregister_adapter(self)
        except BaseException:
            with condition:
                self._runtime_adapter_state = "registered"
                self._runtime_adapter_registered = True
                condition.notify_all()
            raise
        with condition:
            self._runtime_adapter_state = "unregistered"
            condition.notify_all()

    def _register_runtime_adapter(self):
        runtime = getattr(self, "runtime", None)
        register_adapter = getattr(runtime, "try_register_lifecycle_adapter", None)
        if not callable(register_adapter):
            register_adapter = getattr(runtime, "register_lifecycle_adapter", None)
        if not callable(register_adapter):
            return True
        condition = self._runtime_adapter_condition()
        with condition:
            state = getattr(self, "_runtime_adapter_state", "unregistered")
            if state == "registered":
                return True
            if state == "registering":
                if getattr(self, "_runtime_adapter_registration_thread", None) == threading.get_ident():
                    return False
                while getattr(self, "_runtime_adapter_state", "unregistered") == "registering":
                    condition.wait()
                if getattr(self, "_runtime_adapter_state", "unregistered") == "registered":
                    return True
            self._runtime_adapter_state = "registering"
            self._runtime_adapter_registration_thread = threading.get_ident()
        try:
            retained = register_adapter(self)
        except BaseException:
            with condition:
                self._runtime_adapter_state = "unregistered"
                self._runtime_adapter_registration_thread = None
                condition.notify_all()
            raise
        with condition:
            self._runtime_adapter_registration_thread = None
            self._runtime_adapter_state = "registered" if retained is not False else "unregistered"
            self._runtime_adapter_registered = retained is not False
            condition.notify_all()
            return retained is not False

    def _runtime_adapter_condition(self):
        condition = getattr(self, "_runtime_adapter_condition_lock", None)
        if condition is None:
            lock = getattr(self, "_runtime_adapter_lock", None)
            if lock is None:
                lock = threading.Lock()
                self._runtime_adapter_lock = lock
            condition = threading.Condition(lock)
            self._runtime_adapter_condition_lock = condition
        if not hasattr(self, "_runtime_adapter_state"):
            self._runtime_adapter_state = (
                "registered"
                if getattr(self, "_runtime_adapter_registered", False)
                else "unregistered"
            )
        if not hasattr(self, "_runtime_adapter_registration_thread"):
            self._runtime_adapter_registration_thread = None
        return condition

    def _run(self):
        """Run the asyncio event loop in a background thread."""
        self._loop = asyncio.new_event_loop()
        loop = self._loop
        assert loop is not None
        asyncio.set_event_loop(loop)
        try:
            try:
                loop.run_until_complete(self._startup())
            except BaseException:
                self._running = False
                self._lifecycle_state = "failed"
                _log.exception("LAN server startup failed")
                with self._lifecycle_lock:
                    cleanup_future = self._shutdown_future
                    cleanup_owned_here = cleanup_future is None
                    if cleanup_owned_here:
                        cleanup_future = self._reset_cleanup_attempt_locked("startup")
                    elif not self._cleanup_complete:
                        # A concurrent stop owns cleanup.  The owner remains
                        # responsible for publishing the attempt result; this
                        # flag records that a failed startup needs one retry.
                        self._startup_cleanup_failed = True
                assert cleanup_future is not None
                if cleanup_owned_here and not cleanup_future.done():
                    cleanup_started = getattr(self, "_cleanup_started_event", None)
                    if cleanup_started is not None:
                        cleanup_started.set()
                    self._publish_startup_result("failure")
                    try:
                        loop.run_until_complete(self._run_cleanup_attempt())
                    except BaseException as exc:
                        if not cleanup_future.done():
                            cleanup_future.set_exception(exc)
                        _log.exception("LAN server startup cleanup failed")
                    else:
                        if not cleanup_future.done():
                            cleanup_future.set_result(None)
                self._publish_startup_result("failure")
                while not self._cleanup_complete:
                    loop.run_until_complete(asyncio.sleep(0.01))
            else:
                with self._lifecycle_lock:
                    startup_cancelled = (
                        getattr(self, "_startup_cancel_generation", None)
                        == getattr(self, "_lifecycle_generation", 0)
                    )
                if startup_cancelled and self._running:
                    self._running = False
                    with self._lifecycle_lock:
                        cleanup_future = self._shutdown_future
                        cleanup_owned_here = cleanup_future is None
                        if cleanup_owned_here:
                            cleanup_future = self._reset_cleanup_attempt_locked("startup")
                        elif not self._cleanup_complete:
                            self._startup_cleanup_failed = True
                    assert cleanup_future is not None
                    if cleanup_owned_here and not cleanup_future.done():
                        try:
                            cleanup_started = getattr(self, "_cleanup_started_event", None)
                            if cleanup_started is not None:
                                cleanup_started.set()
                            loop.run_until_complete(self._run_cleanup_attempt())
                        except BaseException as exc:
                            if not cleanup_future.done():
                                cleanup_future.set_exception(exc)
                        else:
                            if not cleanup_future.done():
                                cleanup_future.set_result(None)
                self._publish_startup_result(
                    "failure" if startup_cancelled else ("success" if self._running else "failure")
                )
                while not self._cleanup_complete:
                    loop.run_until_complete(asyncio.sleep(0.01))
        finally:
            loop = self._loop
            assert loop is not None
            loop.close()
            with self._lifecycle_lock:
                if self._cleanup_complete and not self._running:
                    self._lifecycle_state = "stopped"
            if self._cleanup_complete and not self._running:
                try:
                    self._unregister_runtime_adapter()
                except BaseException:
                    _log.exception("Failed to unregister LAN runtime lifecycle adapter")

    def _join_gallery_prewarm(self, timeout: float = 10.0) -> None:
        """Join the tracked gallery prewarm thread after closing the service.

        gallery.close() sets ``_closed``, which the build loop checks on every
        directory visit; the join therefore normally returns quickly. The
        bounded timeout keeps shutdown responsive if a pathological walk is
        stuck inside a single syscall.
        """
        thread = getattr(self, "_gallery_prewarm_thread", None)
        if thread is None:
            return
        if thread is threading.current_thread():
            return
        thread.join(timeout)
        if thread.is_alive():
            _log.warning(
                "Gallery prewarm thread did not stop within %.1fs during shutdown",
                timeout,
            )
            return
        self._gallery_prewarm_thread = None

    async def _shutdown(self):
        self._running = False
        scanner = getattr(self, "_scanner", None)
        if scanner is not None and callable(getattr(scanner, "stop", None)):
            try:
                scanner.stop()
            except Exception:
                _log.exception("Failed to stop background scanner during LAN shutdown")
        # Stop gallery background builds (prewarm / full walks): without
        # this a daemon build thread keeps traversing the library for tens
        # of seconds after sharing stops, and a prewarm thread waiting on
        # the scanner would still start one last full walk. The service is
        # rebuilt on the next start(), so closing it here is safe.
        services = getattr(self, "services", None)
        gallery = getattr(services, "gallery_service", None)
        if gallery is not None and callable(getattr(gallery, "close", None)):
            try:
                drained = gallery.close()
            except Exception:
                _log.exception("Failed to stop gallery service during LAN shutdown")
            else:
                if drained is False:
                    # The bounded join timed out with live workers. Their
                    # handles stay tracked and the database gated close is
                    # the hard safety boundary; the pending state is
                    # recorded for shutdown observability.
                    _log.warning(
                        "Gallery service close left background workers running "
                        "after the bounded join; the database gated close "
                        "remains the hard safety boundary"
                    )
        # L3: after closing the gallery service (which signals its build
        # loops), join the server-tracked prewarm thread so shutdown never
        # leaves a daemon traversal running past the request teardown.
        self._join_gallery_prewarm()
        zip_executor = getattr(self, "_zip_executor", None)
        if zip_executor is not None:
            try:
                # wait=False keeps the event loop responsive; in-flight ZIP
                # work observes the same request teardown as every other
                # route resource and is cancelled via cancel_futures.
                zip_executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                _log.exception("Failed to shutdown LAN zip executor")
            finally:
                # Mark the executor dead even if shutdown() itself raised:
                # the next start() must rebuild a usable one, never republish
                # this handle (H1 stop→start regression).
                self._zip_executor_shutdown = True
        try:
            stop_runtime_realtime(self)
            await self._ws_manager.close_all()
            if self._site and getattr(self, "_site_started", True):
                await self._site.stop()
            if self._runner:
                await self._runner.cleanup()
        except BaseException:
            self._cleanup_complete = False
            raise
        self._site = None
        self._runner = None
        self._site_started = False
        self._ssl_active = False
        self._cleanup_complete = True
        _log.info("LAN sharing stopped")

    async def _run_cleanup_attempt(self):
        """Run one cleanup attempt and publish its terminal state first.

        The attempt event/state is the cross-thread lifecycle contract.  It is
        deliberately published before the asyncio/concurrent future becomes
        done, so a waiter cannot infer a stale state from a timeout boundary.
        """
        try:
            await self._shutdown()
        except BaseException as exc:
            self._publish_cleanup_attempt("failed", exc)
            raise
        self._publish_cleanup_attempt("succeeded")

    def _publish_cleanup_attempt(self, state: str, error: BaseException | None = None) -> None:
        event = getattr(self, "_cleanup_attempt_event", None)
        if event is None:
            return
        with self._lifecycle_lock:
            self._cleanup_attempt_state = state
            self._cleanup_attempt_error = error
            if state == "failed" and self._cleanup_attempt_owner == "startup":
                self._startup_cleanup_failed = True
            event.set()

    def _reset_cleanup_attempt_locked(self, owner: str) -> concurrent.futures.Future[Any]:
        event = getattr(self, "_cleanup_attempt_event", None)
        if event is None:
            event = threading.Event()
            self._cleanup_attempt_event = event
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        self._cleanup_attempt_future = future
        self._shutdown_future = future
        event.clear()
        self._cleanup_attempt_state = "running"
        self._cleanup_attempt_owner = owner
        self._cleanup_attempt_error = None
        return future

    def _submit_cleanup_attempt(
        self,
        loop: asyncio.AbstractEventLoop,
        placeholder: concurrent.futures.Future[Any],
    ) -> concurrent.futures.Future[Any]:
        try:
            future = asyncio.run_coroutine_threadsafe(self._run_cleanup_attempt(), loop)
        except BaseException as exc:
            self._publish_cleanup_attempt("failed", exc)
            if not placeholder.done():
                placeholder.set_exception(exc)
            return placeholder
        with self._lifecycle_lock:
            if self._shutdown_future is placeholder:
                self._shutdown_future = future
            self._cleanup_attempt_future = future
        return future

    def _publish_startup_result(self, status: str) -> None:
        event = getattr(self, "_startup_result_event", None)
        if event is None or event.is_set():
            return
        self._startup_result = (status, getattr(self, "_lifecycle_generation", 0))
        event.set()
