"""Deterministic regression for ``lan.utils._enumerate_private_ips``.

Round-3 recheck F2: the single-flight reused the worker thread but every
call read its OWN local results list, so followers lost the interfaces the
shared worker had collected.  These tests gate the fake resolver with Events
so no real network is touched, and pin the three required behaviors:

  1. a follower that waits long enough sees the shared worker's results;
  2. an in-flight enumeration is reused (no second worker thread);
  3. a finished flight is replaced by a fresh one (results never go stale).
"""
import socket
import threading

import pytest

from AssetsManager.lan import utils as lan_utils


@pytest.fixture
def fake_resolver(monkeypatch):
    """Two synthetic adapters; eth0's lookup gates on an Event."""
    calls: list[str] = []
    gate = threading.Event()

    def fake_if_nameindex():
        return [(1, "eth0"), (2, "eth1")]

    def fake_gethostbyname(name):
        calls.append(name)
        if name == "eth0":
            if not gate.wait(timeout=10):
                raise OSError("resolver stuck (gate not released)")
            return "192.168.1.10"
        return "10.0.0.5"

    monkeypatch.setattr(socket, "if_nameindex", fake_if_nameindex)
    monkeypatch.setattr(socket, "gethostbyname", fake_gethostbyname)
    monkeypatch.setattr(lan_utils, "_current_flight", lan_utils._EnumerationFlight())
    return calls, gate


_BOTH = [("eth0", "192.168.1.10"), ("eth1", "10.0.0.5")]


def test_follower_waits_and_reads_shared_results(fake_resolver):
    calls, gate = fake_resolver
    first = lan_utils._enumerate_private_ips(timeout=0.2)
    assert first == [], "gated resolver must yield an empty snapshot, not a hang"
    flight = lan_utils._current_flight
    assert flight.worker is not None and flight.worker.is_alive()

    gate.set()
    second = lan_utils._enumerate_private_ips(timeout=5.0)
    assert second == _BOTH, "follower must observe the shared worker's results"
    assert lan_utils._current_flight is flight
    assert lan_utils._current_flight.worker is flight.worker


def test_inflight_call_reuses_the_same_worker_thread(fake_resolver):
    _calls, gate = fake_resolver
    lan_utils._enumerate_private_ips(timeout=0.1)
    worker = lan_utils._current_flight.worker
    assert worker is not None
    threads_before = threading.active_count()

    lan_utils._enumerate_private_ips(timeout=0.1)
    lan_utils._enumerate_private_ips(timeout=0.1)
    assert lan_utils._current_flight.worker is worker
    assert threading.active_count() == threads_before, "no extra worker per call"

    gate.set()
    assert lan_utils._enumerate_private_ips(timeout=5.0) == _BOTH


def test_finished_flight_is_replaced_by_fresh_enumeration(fake_resolver):
    calls, gate = fake_resolver
    gate.set()
    first = lan_utils._enumerate_private_ips(timeout=5.0)
    assert first == _BOTH
    stale_worker = lan_utils._current_flight.worker
    assert stale_worker is not None
    assert not stale_worker.is_alive()
    calls_after_first = len(calls)

    # A finished flight must NOT be reused for the next call: a fresh worker
    # re-runs the lookups so results never go stale.
    second = lan_utils._enumerate_private_ips(timeout=5.0)
    assert second == _BOTH
    assert lan_utils._current_flight.worker is not stale_worker
    assert len(calls) > calls_after_first, "fresh flight must re-run the lookups"
