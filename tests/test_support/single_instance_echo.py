"""Shared subprocess echo server for single-instance contract tests.

A live instance must ECHO single-instance probes: a connect-only probe
cannot distinguish a live instance from a leaked pipe handle whose owner
crashed (N1 product fix).  An in-process QLocalServer cannot deterministically
dispatch its accept during another bind's synchronous handshake, so these
tests simulate the live instance with a real subprocess running its own
event loop.
"""
import os
import subprocess
import sys
import time

ECHO_SERVER_SCRIPT = """
import sys
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalServer

app = QCoreApplication(sys.argv)
server = QLocalServer()
assert server.listen(sys.argv[1])


def handle():
    while server.hasPendingConnections():
        conn = server.nextPendingConnection()

        def echo(c=conn):
            data = bytes(c.readAll())
            if data:
                c.write(data)

        conn.readyRead.connect(echo)
        data = bytes(conn.readAll())
        if data:
            conn.write(data)


server.newConnection.connect(handle)
app.exec()
"""


def start_echo_server(key: str) -> subprocess.Popen:
    """Start an echo-server subprocess on ``key`` and wait until it answers."""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    proc = subprocess.Popen(
        [sys.executable, "-c", ECHO_SERVER_SCRIPT, key],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    from PySide6.QtNetwork import QLocalSocket

    probe = QLocalSocket()
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        probe.connectToServer(key)
        if probe.waitForConnected(100):
            probe.abort()
            return proc
        probe.abort()
        if proc.poll() is not None:
            raise RuntimeError("echo server died before answering")
        time.sleep(0.1)
    proc.terminate()
    raise RuntimeError("echo server never answered probes")


def stop_echo_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
