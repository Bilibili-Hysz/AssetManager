"""WebSocket manager for real-time client updates."""
import asyncio
import contextvars
import inspect
import json
import logging
from dataclasses import dataclass
from aiohttp import web

_log = logging.getLogger(__name__)

MAX_WS_CONNECTIONS = 50
WS_HEARTBEAT_INTERVAL = 30
WS_OPERATION_TIMEOUT = 5
HEARTBEAT_PING_TIMEOUT = 10.0
MAX_BROADCAST_FRAME_BYTES = 1024 * 1024


@dataclass
class _AuthorityLease:
    authority: object
    lock: asyncio.Lock
    admission_ready: asyncio.Event
    active: bool = True


@dataclass
class _AuthorityTransition:
    state: str = "ready"
    generation: int = 0

    def __post_init__(self):
        self.ready = asyncio.Event()
        self.ready.set()

    def begin(self):
        self.state = "revoking"
        self.generation += 1
        self.ready.clear()

    def finish(self):
        self.state = "ready"
        self.ready.set()


@dataclass
class _CallbackReservation:
    previous: asyncio.Future | None
    finished: asyncio.Future
    callback: object
    args: tuple
    transferred: bool = False


class WebSocketManager:
    """Manages connected WebSocket clients and broadcasts events.

    Broadcasts whose serialized frame exceeds ``MAX_BROADCAST_FRAME_BYTES``
    are either truncated (payloads carrying a ``paths`` list, keeping the
    first entries until the frame fits) or dropped (everything else).
    ``dropped_broadcast_frames`` / ``truncated_broadcast_frames`` expose
    the resulting counters for status/observability interfaces.
    """

    def __init__(self, on_connection_change=None):
        self._clients: set[web.WebSocketResponse] = set()
        self._on_connection_change = on_connection_change
        self._lock = asyncio.Lock()
        self._connection_change_lock = asyncio.Lock()
        self._callback_queue_lock = asyncio.Lock()
        self._callback_tail = None
        self._in_callback = contextvars.ContextVar(
            "websocket_manager_in_callback", default=False,
        )
        self._heartbeat_task: asyncio.Task | None = None
        self._pong_waiters: dict[web.WebSocketResponse, tuple[bytes, asyncio.Event]] = {}
        self._authorizers = {}
        self._leases = {}
        self._authority_locks = {}
        self._authority_transitions: dict[object, _AuthorityTransition] = {}
        self._on_remove = {}
        self._ping_sequence = 0
        self._accepting = True
        self._close_all_task: asyncio.Task | None = None
        self._dropped_broadcast_frames = 0
        self._truncated_broadcast_frames = 0

    @property
    def dropped_broadcast_frames(self) -> int:
        """Count of broadcasts dropped because they could not be trimmed."""
        return self._dropped_broadcast_frames

    @property
    def truncated_broadcast_frames(self) -> int:
        """Count of broadcasts sent after truncating an oversized ``paths`` list."""
        return self._truncated_broadcast_frames

    async def start_accepting(self) -> None:
        """Open admission for a newly started server lifecycle."""
        async with self._lock:
            self._accepting = True

    async def add(self, ws: web.WebSocketResponse, *, authorize=None,
                  on_admission=None, on_remove=None, authority=None,
                  admission_pending=False) -> bool:
        """Revalidate and register a client under its canonical authority lock."""
        async with self._lock:
            if authority is None:
                authority = ws
                authority_lock = asyncio.Lock()
            else:
                authority_lock = self._authority_locks.setdefault(
                    authority, asyncio.Lock(),
                )
            self._authority_transitions.setdefault(authority, _AuthorityTransition())

        admission_error = None
        accepted = False
        count = 0
        callback_reservation = None
        while True:
            try:
                authorized, generation = await self._authorize_for_authority(
                    authority, authority_lock, authorize,
                )
            except asyncio.TimeoutError:
                await self._close(ws, code=1013, message=b"Admission timed out")
                return False
            retry = False
            async with authority_lock:
                transition = self._authority_transitions[authority]
                if (transition.state != "ready"
                        or transition.generation != generation):
                    retry = True
                else:
                    async with self._connection_change_lock:
                        async with self._lock:
                            accepted = (
                                authorized
                                and self._accepting
                                and len(self._clients) < MAX_WS_CONNECTIONS
                            )
                            if not accepted:
                                count = len(self._clients)
                            else:
                                lease = _AuthorityLease(
                                    authority, authority_lock, asyncio.Event(),
                                )
                                if not admission_pending:
                                    lease.admission_ready.set()
                                self._leases[ws] = lease
                                self._clients.add(ws)
                                if authorize is not None:
                                    self._authorizers[ws] = authorize
                                if on_remove is not None:
                                    self._on_remove[ws] = on_remove
                                count = len(self._clients)
                                _log.debug("WebSocket client connected (%d total)", count)
                                if self._heartbeat_task is None or self._heartbeat_task.done():
                                    self._heartbeat_task = asyncio.create_task(self._heartbeat())
                                callback_reservation = self._reserve_callback(
                                    self._admission_callbacks,
                                    on_admission,
                                    count,
                                )
            if retry:
                try:
                    await self._authority_ready(authority)
                except asyncio.TimeoutError:
                    await self._close(ws, code=1013, message=b"Admission timed out")
                    return False
                continue
            break
        if accepted:
            try:
                await self._run_reserved(callback_reservation)
            except BaseException as error:
                admission_error = error
                if isinstance(error, asyncio.CancelledError):
                    current_task = asyncio.current_task()
                    if current_task is not None:
                        current_task.uncancel()
                self._abandon_reserved(callback_reservation)
            finally:
                self._abandon_reserved(callback_reservation)
        if not accepted:
            if authorized:
                await self._close(ws, code=1013, message=b"Too many connections")
            else:
                await self._close(ws, code=1008, message=b"Authorization revoked")
            return False
        if admission_error is not None:
            cleanup = asyncio.create_task(self.evict(ws))
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    current_task = asyncio.current_task()
                    if current_task is not None:
                        current_task.uncancel()
            await cleanup
            raise admission_error
        return True

    async def _invoke_callback(self, callback, *args):
        if self._in_callback.get():
            result = callback(*args)
            if inspect.isawaitable(result):
                return await result
            return result
        async with self._callback_queue_lock:
            previous = self._callback_tail
            loop = asyncio.get_running_loop()
            finished = loop.create_future()
            self._callback_tail = finished
        try:
            if previous is not None:
                await asyncio.shield(previous)
            token = self._in_callback.set(True)
            try:
                result = callback(*args)
                if inspect.isawaitable(result):
                    return await result
                return result
            finally:
                self._in_callback.reset(token)
        finally:
            if not finished.done():
                finished.set_result(None)

    def _reserve_callback(self, callback, *args):
        previous = self._callback_tail
        finished = asyncio.get_running_loop().create_future()
        self._callback_tail = finished
        reservation = _CallbackReservation(previous, finished, callback, args)
        owner = asyncio.current_task()
        if owner is not None:
            owner.add_done_callback(
                lambda _task: self._abandon_reserved(reservation),
            )
        return reservation

    @staticmethod
    def _abandon_reserved(reservation):
        if reservation is not None and not reservation.transferred:
            if not reservation.finished.done():
                reservation.finished.set_result(None)

    async def _run_reserved(self, reservation):
        if reservation is None:
            return
        reservation.transferred = True
        previous = reservation.previous
        finished = reservation.finished
        callback = reservation.callback
        args = reservation.args
        token = None
        try:
            if self._in_callback.get():
                await callback(*args)
                return
            if previous is not None:
                await asyncio.shield(previous)
            token = self._in_callback.set(True)
            await callback(*args)
        finally:
            if token is not None:
                self._in_callback.reset(token)
            if not finished.done():
                finished.set_result(None)

    async def _admission_callbacks(self, on_admission, count):
        if on_admission is not None:
            result = on_admission()
            if inspect.isawaitable(result):
                await result
        if self._on_connection_change is not None:
            await self._invoke_callback(self._on_connection_change, count)

    async def _notify_connection_change(self, count: int) -> None:
        if self._on_connection_change is None:
            return
        try:
            await self._invoke_callback(self._on_connection_change, count)
        except Exception:
            _log.exception("WebSocket connection-change callback failed")

    async def remove(self, ws: web.WebSocketResponse):
        async with self._lock:
            lease = self._leases.get(ws)
        if lease is not None and lease.active:
            async with lease.lock:
                lease.active = False
                lease.admission_ready.set()
        async with self._connection_change_lock:
            async with self._lock:
                removed = ws in self._clients
                self._clients.discard(ws)
                self._pong_waiters.pop(ws, None)
                self._authorizers.pop(ws, None)
                self._leases.pop(ws, None)
                on_remove = self._on_remove.pop(ws, None)
                _log.debug("WebSocket client disconnected (%d total)", len(self._clients))
                count = len(self._clients)
            callback_reservation = (
                self._reserve_callback(self._removal_callbacks, on_remove, count)
                if removed else None
            )
        try:
            if on_remove is not None:
                await self._run_reserved(callback_reservation)
            elif removed:
                await self._run_reserved(callback_reservation)
        except Exception:
            if on_remove is not None:
                _log.exception("WebSocket removal callback failed")
            else:
                raise
        finally:
            self._abandon_reserved(callback_reservation)
        return removed

    async def _removal_callbacks(self, on_remove, count):
        if on_remove is not None:
            try:
                result = on_remove()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                _log.exception("WebSocket removal callback failed")
        await self._notify_connection_change(count)

    async def revoke_authority(self, authority, revoke) -> bool:
        """Mutate canonical authority and evict its sockets as one boundary."""
        async with self._lock:
            authority_lock = self._authority_locks.setdefault(
                authority, asyncio.Lock(),
            )
            transition = self._authority_transitions.setdefault(
                authority, _AuthorityTransition(),
            )
        async with authority_lock:
            if transition.state != "ready":
                return False
            transition.begin()
        committed = False
        try:
            result = revoke()
            if inspect.isawaitable(result):
                result = await result
            if not result:
                return False
            async with authority_lock:
                async with self._lock:
                    clients = [
                        (ws, lease) for ws, lease in self._leases.items()
                        if lease.authority == authority
                    ]
                    for _ws, lease in clients:
                        lease.active = False
                committed = True
                transition.finish()
        finally:
            if not committed:
                async with authority_lock:
                    transition.finish()
        await asyncio.gather(*(self.evict(ws) for ws, _lease in clients))
        return True

    async def _run_authorizer(self, authorize) -> bool:
        """Run an authorization callback without holding manager locks."""
        try:
            result = authorize()
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        except Exception:
            _log.exception("WebSocket authorization callback failed")
            return False

    async def _authorize_for_authority(self, authority, authority_lock, authorize):
        while True:
            # Establish the pre-callback boundary without invoking user code
            # while holding it.  A revoke that starts after this point marks
            # the transition event, forcing the authorization result to retry.
            async with authority_lock:
                transition = self._authority_transitions[authority]
                transition_in_progress = transition.state != "ready"
            if transition_in_progress:
                await asyncio.wait_for(transition.ready.wait(), WS_OPERATION_TIMEOUT)
                continue
            authorized = True if authorize is None else await self._run_authorizer(authorize)
            async with authority_lock:
                transition = self._authority_transitions[authority]
                if transition.state == "ready":
                    return authorized, transition.generation
            await asyncio.wait_for(transition.ready.wait(), WS_OPERATION_TIMEOUT)

    async def _authority_ready(self, authority):
        transition = self._authority_transitions.get(authority)
        if transition is not None and transition.state != "ready":
            await asyncio.wait_for(transition.ready.wait(), WS_OPERATION_TIMEOUT)

    async def _is_authorized(self, ws: web.WebSocketResponse) -> bool:
        authorize = self._authorizers.get(ws)
        if authorize is None:
            return True
        return await self._run_authorizer(authorize)

    async def evict(self, ws: web.WebSocketResponse, *, code=1008,
                    message=b"Authorization revoked") -> None:
        """Idempotently remove a socket, then close the transport."""
        if await self.remove(ws):
            await self._close(ws, code=code, message=message)

    async def _evict(self, ws: web.WebSocketResponse, *, code=1008,
                     message=b"Authorization revoked") -> None:
        """Backward-compatible internal alias for :meth:`evict`."""
        await self.evict(ws, code=code, message=message)

    async def finish_admission(self, ws: web.WebSocketResponse,
                               payload=None) -> bool:
        """Send the final baseline and release this socket to broadcasts."""
        async with self._lock:
            lease = self._leases.get(ws)
        if lease is None or not lease.active:
            return False
        try:
            async with lease.lock:
                if not lease.active:
                    return False
                if payload is not None:
                    await asyncio.wait_for(
                        ws.send_json(payload), WS_OPERATION_TIMEOUT,
                    )
                lease.admission_ready.set()
                return True
        except Exception:
            lease.admission_ready.set()
            raise

    def acknowledge_pong(self, ws: web.WebSocketResponse, message: bytes):
        waiter = self._pong_waiters.get(ws)
        if waiter is not None and waiter[0] == message:
            waiter[1].set()

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(WS_HEARTBEAT_INTERVAL)
            async with self._lock:
                if not self._clients:
                    self._heartbeat_task = None
                    return
            await self._heartbeat_cycle()

    async def _heartbeat_cycle(self):
        """Check all clients concurrently without holding the client lock."""
        async with self._lock:
            clients = list(self._clients)

        async def check(ws: web.WebSocketResponse):
            waiter: tuple[bytes, asyncio.Event] | None = None
            try:
                if not await self._is_authorized(ws):
                    return ws
                async with self._lock:
                    self._ping_sequence += 1
                    payload = str(self._ping_sequence).encode()
                    waiter = (payload, asyncio.Event())
                    self._pong_waiters[ws] = waiter
                await asyncio.wait_for(ws.ping(payload), HEARTBEAT_PING_TIMEOUT)
                await asyncio.wait_for(waiter[1].wait(), HEARTBEAT_PING_TIMEOUT)
            except Exception:
                return ws
            finally:
                async with self._lock:
                    if self._pong_waiters.get(ws) is waiter:
                        self._pong_waiters.pop(ws, None)
            return None

        results = await asyncio.gather(
            *(check(ws) for ws in clients), return_exceptions=True
        )
        dead = {
            ws
            for ws, result in zip(clients, results)
            if isinstance(result, BaseException) or result is not None
        }
        if dead:
            await asyncio.gather(*(self.evict(ws) for ws in dead))

    def _trim_broadcast_payload(self, event_type: str, data: dict):
        """Trim an oversized broadcast payload, or count it as dropped.

        When ``data`` carries a non-empty ``paths`` list/tuple the paths
        are truncated to the largest leading prefix that serializes within
        95% of ``MAX_BROADCAST_FRAME_BYTES`` (headroom for the truncated
        re-serialization), and the trimmed payload is returned so the
        event reaches clients instead of being silently dropped. Returns
        ``None`` when the frame cannot be safely trimmed (no ``paths``,
        or even an empty ``paths`` list does not fit), in which case the
        drop is counted and logged.

        Only invoked when the original frame already exceeded the limit,
        so normal broadcasts pay no extra cost.
        """
        paths = data.get("paths")
        if not isinstance(paths, (list, tuple)) or not paths:
            return self._count_dropped(event_type)
        budget = int(MAX_BROADCAST_FRAME_BYTES * 0.95)
        total = len(paths)

        def frame_size(keep_count):
            payload = dict(data, paths=list(paths[:keep_count]))
            return len(json.dumps({"type": event_type, **payload}).encode("utf-8"))

        low, high = 0, total
        while low < high:
            mid = (low + high + 1) // 2
            if frame_size(mid) <= budget:
                low = mid
            else:
                high = mid - 1
        keep = low
        if keep == 0:
            # Not even a single path fits: drop rather than send a
            # misleading empty-paths invalidation.
            return self._count_dropped(event_type)
        self._truncated_broadcast_frames += 1
        _log.warning(
            "Broadcast '%s' exceeds %d bytes; truncated paths %d -> %d "
            "(truncated_broadcast_frames=%d)",
            event_type,
            MAX_BROADCAST_FRAME_BYTES,
            total,
            keep,
            self._truncated_broadcast_frames,
        )
        return dict(data, paths=list(paths[:keep]))

    def _count_dropped(self, event_type: str):
        """Count and log a broadcast frame that had to be dropped."""
        self._dropped_broadcast_frames += 1
        _log.warning(
            "Broadcast '%s' exceeds %d bytes; dropping frame "
            "(dropped_broadcast_frames=%d)",
            event_type,
            MAX_BROADCAST_FRAME_BYTES,
            self._dropped_broadcast_frames,
        )
        return None

    async def broadcast(self, event_type: str, data: dict | None = None):
        """Send a JSON event to all connected clients."""
        async with self._lock:
            if not self._clients:
                return
            clients = [
                (ws, self._leases[ws]) for ws in self._clients
            ]

        try:
            message = json.dumps({"type": event_type, **(data or {})})
        except (TypeError, ValueError) as error:
            _log.warning("Failed to serialize broadcast '%s': %s", event_type, error)
            return
        if len(message.encode("utf-8")) > MAX_BROADCAST_FRAME_BYTES:
            data = self._trim_broadcast_payload(event_type, data or {})
            if data is None:
                return
            try:
                message = json.dumps({"type": event_type, **data})
            except (TypeError, ValueError) as error:
                _log.warning(
                    "Failed to serialize truncated broadcast '%s': %s",
                    event_type,
                    error,
                )
                return
        async def send_to(ws, lease):
            if not await self._is_authorized(ws):
                return ws
            try:
                while True:
                    await self._authority_ready(lease.authority)
                    if not lease.admission_ready.is_set():
                        await lease.admission_ready.wait()
                        continue
                    async with lease.lock:
                        if not lease.active:
                            return ws
                        transition = self._authority_transitions.get(lease.authority)
                        if transition is not None and transition.state != "ready":
                            continue
                        await ws.send_str(message)
                        return None
            except Exception:
                return ws

        results = await asyncio.gather(
            *(asyncio.wait_for(send_to(ws, lease), WS_OPERATION_TIMEOUT)
              for ws, lease in clients),
            return_exceptions=True,
        )
        dead = [
            ws for (ws, _lease), result in zip(clients, results)
            if isinstance(result, BaseException) or result is not None
        ]

        if dead:
            await asyncio.gather(*(self.evict(ws) for ws in dead))

    @staticmethod
    async def _close(ws: web.WebSocketResponse, **kwargs):
        try:
            await asyncio.wait_for(ws.close(**kwargs), timeout=WS_OPERATION_TIMEOUT)
        except Exception:
            pass

    def close_all(self):
        """Begin teardown synchronously, then drain it for the caller."""
        # Publish the admission barrier before handing control to the event
        # loop.  This closes the scheduling gap between create_task() and the
        # first statement of _close_all().
        self._accepting = False
        for lease in self._leases.values():
            lease.active = False
        teardown = self._close_all_task
        if teardown is None or teardown.done():
            teardown = asyncio.ensure_future(self._close_all())
            self._close_all_task = teardown
        return self._drain_close_all(teardown)

    async def _drain_close_all(self, teardown):
        """Complete teardown before propagating cancellation from the caller."""
        cancellation = None
        while not teardown.done():
            try:
                await asyncio.shield(teardown)
            except asyncio.CancelledError as error:
                cancellation = cancellation or error
                current_task = asyncio.current_task()
                if current_task is not None:
                    current_task.uncancel()
        await teardown
        if cancellation is not None:
            raise cancellation

    async def _close_all(self):
        """Invalidate every canonical authority lease, then close all clients.

        Server teardown is the real rotation boundary for its immutable
        access-key/password snapshots and process-bound local-UI signing
        secret.  Taking the same locks used by broadcasts prevents a send
        after teardown has invalidated one of those authorities.
        """
        heartbeat = self._heartbeat_task
        self._heartbeat_task = None
        async with self._lock:
            self._accepting = False
            authority_locks = list(dict.fromkeys(
                lease.lock for lease in self._leases.values()
            ))
            for lease in self._leases.values():
                lease.active = False
                lease.admission_ready.set()
        if heartbeat and heartbeat is not asyncio.current_task():
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        acquired_locks = []
        try:
            for authority_lock in authority_locks:
                await authority_lock.acquire()
                acquired_locks.append(authority_lock)
            async with self._connection_change_lock:
                async with self._lock:
                    clients = list(self._clients)
                    self._clients.clear()
                    self._pong_waiters.clear()
                    self._authorizers.clear()
                    self._leases.clear()
                    self._authority_locks.clear()
                    callbacks = [self._on_remove.pop(ws, None) for ws in clients]
            for authority_lock in reversed(acquired_locks):
                authority_lock.release()
            acquired_locks.clear()
            for callback in callbacks:
                if callback is not None:
                    try:
                        await self._invoke_callback(callback)
                    except BaseException:
                        _log.exception("WebSocket removal callback failed")
            if clients:
                try:
                    await self._notify_connection_change(0)
                except BaseException:
                    _log.exception("WebSocket connection-change callback failed")
        finally:
            for authority_lock in reversed(acquired_locks):
                authority_lock.release()
        await asyncio.gather(*(self._close(ws) for ws in clients))
