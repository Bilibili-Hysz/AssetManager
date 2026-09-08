import logging
import uuid
import pytest

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

import AssetsManager.app as app_mod
from AssetsManager.app import _SINGLE_INSTANCE_KEY, _bind_single_instance
from AssetsManager.i18n import tr
from AssetsManager.window import maybe_show_tray_hide_hint


@pytest.fixture(autouse=True)
def _isolate_pipe_key(monkeypatch):
    test_key = f"AssetsManager_TestPipe_{uuid.uuid4().hex}"
    monkeypatch.setattr(app_mod, "_SINGLE_INSTANCE_KEY", test_key)
    monkeypatch.setattr("tests.desktop.test_single_instance_and_tray_hint._SINGLE_INSTANCE_KEY", test_key)
    yield test_key
    QLocalServer.removeServer(test_key)


class _FakeSettings:
    """In-memory stand-in for AppSettings (get/set/save surface only)."""

    def __init__(self, stored=None):
        self._stored = dict(stored or {})
        self.saved = 0

    def get(self, key, default=False):
        return self._stored.get(key, default)

    def set(self, key, value):
        self._stored[key] = value

    def save(self):
        self.saved += 1


class _FakeTray:
    def __init__(self, available=True):
        self.is_available = available
        self.messages: list[tuple[str, str]] = []

    def show_message(self, title, message):
        self.messages.append((title, message))


def _qapp():
    return QApplication.instance() or QApplication([])


def test_single_instance_second_probe_sees_live_lock():
    _qapp()
    QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    server.close()
    QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)
    # N1: a live instance ECHOES probes — a connect-only probe cannot
    # distinguish a live instance from a leaked pipe handle.  The live
    # instance is simulated with a real subprocess echo server: an
    # in-process server cannot dispatch its accept during bind's
    # synchronous handshake.
    from tests.test_support.single_instance_echo import (
        start_echo_server,
        stop_echo_server,
    )

    echo_proc = start_echo_server(_SINGLE_INSTANCE_KEY)
    try:
        assert _bind_single_instance(QCoreApplication.instance()) is False
    finally:
        stop_echo_server(echo_proc)
        QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)


def test_single_instance_bind_succeeds_when_no_instance_runs():
    import AssetsManager.app as app_mod

    _qapp()
    QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)
    app = QCoreApplication.instance()
    try:
        assert _bind_single_instance(app) is True
        # The server is retained for the process lifetime via the module
        # keep-alive (a parentless local QLocalServer would otherwise be
        # garbage collected and its socket closed).
        assert app_mod._single_instance_server is not None
        assert app.property("single_instance_server") is not None
    finally:
        server = app_mod._single_instance_server
        if server is not None:
            server.close()
            app_mod._single_instance_server = None
        QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)


def test_single_instance_fails_open_on_listen_error(monkeypatch, tmp_path):
    _qapp()
    QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)
    monkeypatch.setattr(QLocalServer, "listen", lambda self, name: False)

    # A listen failure must not block startup (fail-open, log only).
    assert _bind_single_instance(QCoreApplication.instance()) is True


def test_single_instance_fails_open_on_exception(monkeypatch):
    _qapp()

    def boom(_self, _path):
        raise RuntimeError("qt network unavailable")

    monkeypatch.setattr(QLocalSocket, "connectToServer", boom)

    assert _bind_single_instance(QCoreApplication.instance()) is True


def test_tray_hide_hint_shows_once_and_persists_flag():
    settings = _FakeSettings()
    tray = _FakeTray()

    shown = maybe_show_tray_hide_hint(tray, settings=settings, sharing_running=False)

    assert shown is True
    assert len(tray.messages) == 1
    title, body = tray.messages[0]
    assert title and body
    # "Only once" is remembered through the persisted flag, and the flag is
    # written before the balloon so a crash cannot loop the nag.
    assert settings._stored["tray_hide_hint_shown"] is True
    assert settings.saved == 1

    assert maybe_show_tray_hide_hint(tray, settings=settings, sharing_running=False) is False
    assert len(tray.messages) == 1


def test_tray_hide_hint_mentions_sharing_when_server_runs():
    settings = _FakeSettings()
    tray = _FakeTray()

    shown = maybe_show_tray_hide_hint(tray, settings=settings, sharing_running=True)

    assert shown is True
    # The sharing variant text is used when the LAN server is still running.
    assert tray.messages[0][0] == tr("tray.hide_hint_title")
    assert tray.messages[0][1] == tr("tray.hide_hint_body_sharing")


def test_tray_hide_hint_skipped_when_unavailable_or_already_shown():
    settings = _FakeSettings({"tray_hide_hint_shown": True})
    assert maybe_show_tray_hide_hint(_FakeTray(), settings=settings, sharing_running=False) is False

    assert maybe_show_tray_hide_hint(None, settings=_FakeSettings(), sharing_running=False) is False
    assert maybe_show_tray_hide_hint(_FakeTray(available=False), settings=_FakeSettings(), sharing_running=False) is False


def test_tray_hide_hint_survives_settings_save_failure(caplog):
    class _BrokenSettings(_FakeSettings):
        def save(self):
            raise OSError("disk full")

    tray = _FakeTray()
    with caplog.at_level(logging.ERROR):
        shown = maybe_show_tray_hide_hint(tray, settings=_BrokenSettings(), sharing_running=False)

    # Fail-open: the persistence error is logged but the hint still shows.
    assert shown is True
    assert len(tray.messages) == 1
