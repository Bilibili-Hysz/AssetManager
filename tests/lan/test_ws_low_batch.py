"""Low-severity WebSocketManager fixes: heartbeat lifecycle (W5), authority
dict cleanup (W6), and PONG/broadcast smoke coverage (W7/W8).

Uses lightweight in-memory socket doubles (no real aiohttp transport),
mirroring the pattern of the heartbeat tests in test_lan_api.py.
"""
import asyncio

import pytest

from AssetsManager.lan import ws as ws_module
from AssetsManager.lan.ws import WebSocketManager


class _Socket:
    """Minimal async websocket double used across the tests below."""

    def __init__(self, name="socket"):
        self.name = name
        self.messages = []
        self.closed = False

    async def send_str(self, message):
        self.messages.append(message)

    async def close(self, **_kwargs):
        self.closed = True

    async def ping(self, _payload):
        pass


# ---------------------------------------------------------------------------
# W5: heartbeat task lifecycle — no lingering task after the last close, and
# add()/remove() cycles never leave more than one live heartbeat.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_heartbeat_task_cancelled_when_last_client_removed():
    manager = WebSocketManager()
    socket = _Socket()
    assert await manager.add(socket) is True
    heartbeat = manager._heartbeat_task
    assert heartbeat is not None and not heartbeat.done()

    assert await manager.remove(socket) is True
    # Reference dropped synchronously under _lock...
    assert manager._heartbeat_task is None
    # ...and the task actually terminates (cancellation delivered).
    await asyncio.gather(heartbeat, return_exceptions=True)
    assert heartbeat.done()


@pytest.mark.anyio
async def test_heartbeat_task_survives_removal_while_clients_remain():
    manager = WebSocketManager()
    first = _Socket("first")
    second = _Socket("second")
    await manager.add(first)
    await manager.add(second)
    heartbeat = manager._heartbeat_task
    assert heartbeat is not None and not heartbeat.done()

    await manager.remove(first)
    assert manager._heartbeat_task is heartbeat
    assert not heartbeat.done()

    await manager.remove(second)
    assert manager._heartbeat_task is None
    await asyncio.gather(heartbeat, return_exceptions=True)
    assert heartbeat.done()


@pytest.mark.anyio
async def test_heartbeat_restarts_after_add_remove_cycles():
    manager = WebSocketManager()
    previous = None
    for index in range(5):
        socket = _Socket(f"cycle-{index}")
        assert await manager.add(socket) is True
        heartbeat = manager._heartbeat_task
        assert heartbeat is not None and not heartbeat.done()
        if previous is not None:
            # Each new cycle owns a fresh, distinct heartbeat task; the old
            # one was cancelled by remove() and has fully terminated.
            assert heartbeat is not previous
            assert previous.done()

        assert await manager.remove(socket) is True
        assert manager._heartbeat_task is None
        await asyncio.gather(heartbeat, return_exceptions=True)
        assert heartbeat.done()
        previous = heartbeat


# ---------------------------------------------------------------------------
# W6: _authority_locks / _authority_transitions must not grow without bound.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_authority_dicts_cleaned_when_last_connection_removed():
    manager = WebSocketManager()
    authority = ("user", 7)
    first = _Socket("first")
    second = _Socket("second")
    await manager.add(first, authority=authority)
    await manager.add(second, authority=authority)
    assert authority in manager._authority_locks
    assert authority in manager._authority_transitions

    # One connection of two remains: entries must be retained.
    await manager.remove(first)
    assert authority in manager._authority_locks
    assert authority in manager._authority_transitions

    # Last connection for the authority is gone: entries are dropped.
    await manager.remove(second)
    assert authority not in manager._authority_locks
    assert authority not in manager._authority_transitions
    assert manager._authority_locks == {}
    assert manager._authority_transitions == {}


@pytest.mark.anyio
async def test_authority_dicts_cleaned_for_per_socket_authority():
    """authority=None keys the transition by the ws object; remove must drop
    it.  (The per-socket admission lock is local-only and never registered.)"""
    manager = WebSocketManager()
    socket = _Socket()
    assert await manager.add(socket) is True
    assert socket not in manager._authority_locks
    assert socket in manager._authority_transitions

    await manager.remove(socket)
    assert socket not in manager._authority_locks
    assert socket not in manager._authority_transitions


@pytest.mark.anyio
async def test_authority_dicts_cleaned_on_failed_admission():
    """Rejected admissions create entries; they must not accumulate."""
    manager = WebSocketManager()
    rejected = _Socket("rejected")
    assert await manager.add(
        rejected, authorize=lambda: False, authority=("user", 99),
    ) is False
    assert ("user", 99) not in manager._authority_locks
    assert ("user", 99) not in manager._authority_transitions
    assert manager._authority_locks == {}
    assert manager._authority_transitions == {}


@pytest.mark.anyio
async def test_authority_entries_recreated_on_reconnect():
    """A reconnect after cleanup transparently re-creates the entries."""
    manager = WebSocketManager()
    authority = ("user", 12)
    socket = _Socket()
    await manager.add(socket, authority=authority)
    await manager.remove(socket)
    assert authority not in manager._authority_locks

    again = _Socket("again")
    assert await manager.add(again, authority=authority) is True
    assert authority in manager._authority_locks
    assert again in manager._clients

    await manager.remove(again)
    assert authority not in manager._authority_locks


@pytest.mark.anyio
async def test_close_all_clears_authority_dicts_and_heartbeat():
    manager = WebSocketManager()
    socket = _Socket()
    await manager.add(socket, authority=("user", 5))
    heartbeat = manager._heartbeat_task
    assert heartbeat is not None

    await manager.close_all()

    assert manager._authority_locks == {}
    assert manager._authority_transitions == {}
    assert manager._clients == set()
    assert manager._heartbeat_task is None
    await asyncio.gather(heartbeat, return_exceptions=True)
    assert heartbeat.done()


# ---------------------------------------------------------------------------
# W7/W8: smoke coverage — no behavior change, calls must not raise.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_pong_acknowledgement_smoke():
    manager = WebSocketManager()
    socket = _Socket()
    await manager.add(socket)

    # No waiter registered: must be a no-op.
    manager.acknowledge_pong(socket, b"1")
    # Unrelated payload must not satisfy a pending waiter.
    waiter = (b"7", asyncio.Event())
    manager._pong_waiters[socket] = waiter
    manager.acknowledge_pong(socket, b"other")
    assert not waiter[1].is_set()
    # Matching payload satisfies it.
    manager.acknowledge_pong(socket, b"7")
    assert waiter[1].is_set()
    # Removing the socket clears the waiter registry.
    await manager.remove(socket)
    assert socket not in manager._pong_waiters


@pytest.mark.anyio
async def test_broadcast_smoke_single_client_and_teardown():
    manager = WebSocketManager()
    socket = _Socket()
    await manager.add(socket, authority=("user", 3))

    await manager.broadcast("asset_changed", {"path": "hero.png"})
    assert socket.messages == ['{"type": "asset_changed", "path": "hero.png"}']

    # Teardown keeps the manager usable and consistent.
    await manager.close_all()
    await manager.broadcast("asset_changed", {"path": "ghost.png"})
    assert len(socket.messages) == 1
    assert manager._leases == {}


@pytest.mark.anyio
async def test_heartbeat_loop_self_terminates_on_empty_clients(monkeypatch):
    """The heartbeat singleton still exits when it observes an empty set."""
    monkeypatch.setattr(ws_module, "WS_HEARTBEAT_INTERVAL", 0.01)
    manager = WebSocketManager()
    socket = _Socket()
    assert await manager.add(socket) is True
    heartbeat = manager._heartbeat_task
    assert await manager.remove(socket) is True
    assert manager._heartbeat_task is None
    await asyncio.gather(heartbeat, return_exceptions=True)
    assert heartbeat.done()
