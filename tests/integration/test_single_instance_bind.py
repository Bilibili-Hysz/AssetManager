"""Single-instance ping/echo contract (N1 product fix regression).

The old probe treated "pipe connects" as "instance alive" — a pipe handle
outliving its crashed owner (inherited by a child process) answered forever
and blocked every subsequent launch behind the "Already Running" dialog.
The fix: probes must complete a ping/echo handshake; a silent pipe is stale
and startup fails open.  Pinned here:

  1. a live instance's server echoes probes → the next bind reports
     already-running;
  2. a listener that never echoes (stale-pipe simulation) → bind fails OPEN
     and takes over the name;
  3. after a fail-open takeover, the new instance's own server answers
     probes (the lock works again).
"""
import importlib.util
import sys
import time
import uuid
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="QLocalServer named-pipe semantics on Windows")

spec = importlib.util.spec_from_file_location(
    "appmod", Path(__file__).resolve().parents[2] / "AssetsManager" / "app.py")
appmod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(appmod)

KEY = appmod._SINGLE_INSTANCE_KEY


@pytest.fixture
def key(qapp, monkeypatch):
    """A unique pipe key per test: the production key may be shadowed by a
    leaked phantom pipe from an earlier crashed instance on this machine."""
    unique = f"{KEY}.test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(appmod, "_SINGLE_INSTANCE_KEY", unique)
    return unique


def _probe_echoes(key: str = KEY) -> bool:
    probe = QLocalSocket()
    probe.connectToServer(key)
    deadline = time.monotonic() + 2.0
    while not probe.waitForConnected(50):
        QCoreApplication.processEvents()
        if time.monotonic() > deadline:
            return False
    probe.write(b"ping\n")
    probe.flush()
    deadline = time.monotonic() + 2.0
    echoed = False
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if probe.waitForReadyRead(50):
            if bytes(probe.readAll()).startswith(b"ping"):
                echoed = True
                break
    probe.abort()
    return echoed


def _teardown_server(server) -> None:
    server.close()
    server.deleteLater()


@pytest.fixture
def qapp():
    # QApplication (not QCoreApplication): the bind signature takes the real
    # app, and a core-only instance poisons later desktop tests in the same
    # xdist worker (their conftest expects QApplication).
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_live_server_echoes_and_next_bind_reports_running(qapp, key):
    """Cross-process live instance: a real subprocess runs an echo server in
    its own event loop — the in-process synchronous variant cannot dispatch
    the server accept and is not production-realistic."""
    from tests.test_support.single_instance_echo import (
        start_echo_server,
        stop_echo_server,
    )

    server_proc = start_echo_server(key)
    try:
        bound = appmod._bind_single_instance(qapp)
        assert bound is False, (
            "bind must report already-running against a live echo server")
    finally:
        stop_echo_server(server_proc)


def test_silent_pipe_is_stale_and_bind_fails_open(qapp, key):
    server = QLocalServer()
    assert server.listen(key)  # simulates a leaked handle: never echoes
    bound = appmod._bind_single_instance(qapp)
    assert bound is True, "a silent pipe is stale; startup must fail open"
    _teardown_server(server)
    # Realistic post-crash state: the dead owner's pipe instance is gone, so
    # the takeover's own server must answer later probes.
    assert _probe_echoes(key), "the fail-open takeover must answer later probes"


def test_takeover_server_remains_answerable(qapp, key):
    bound = appmod._bind_single_instance(qapp)
    assert bound is True
    assert _probe_echoes(key), "post-takeover lock must keep answering probes"
