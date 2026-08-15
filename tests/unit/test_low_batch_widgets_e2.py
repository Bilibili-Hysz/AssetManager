"""Unit tests for the low-priority widget fixes (batch E2).

Covers:
- lan_sharing: start-failure-but-running keeps status/tray consistent (F1)
- lan_sharing: ValueError/TypeError from server.start shows a warning (F2)
- toast: horizontal chrome is computed from fixed widths, not pre-layout 0
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import Mock

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

# The 6-argument QMouseEvent constructor is the simplest way to build
# synthetic click events; PySide6 marks it deprecated, which is fine here.
pytestmark = pytest.mark.filterwarnings(
    "ignore:.*QMouseEvent.*deprecated:DeprecationWarning"
)


# ── lan_sharing F1: start failure while server actually runs ──────

def test_toggle_sharing_start_failure_but_running_keeps_status_and_tray(monkeypatch):
    from AssetsManager import lan
    from AssetsManager.core import settings as settings_module
    from AssetsManager.widgets import lan_sharing
    from AssetsManager.widgets.lan_sharing import LanSharingMixin

    class _Settings:
        def get(self, key, default=None):
            return {
                "lan_bind": "0.0.0.0",
                "lan_share_safety_ack_version": 1,
                "lan_trusted_network_confirmed": True,
            }.get(key, default)

    runtime = type("Runtime", (), {})()
    session = type("Session", (), {"is_closed": False})()
    bootstrap = Mock()
    bootstrap.runtime_for.return_value = runtime
    server = Mock()
    server.start.return_value = {
        "share_state": "failed",
        "failure_reason": "security_post_start_rollback_failed",
        "rollback_failed": True,
        "running": True,
    }
    server.status.return_value = {"url": "http://192.168.1.10:9090"}

    class _Tray:
        def __init__(self):
            self.states = []

        def update_sharing_state(self, running, url=""):
            self.states.append((running, url))

    class _Host(LanSharingMixin):
        _lan_server = None
        _library_session = session
        _bootstrap = bootstrap
        _tray_manager = _Tray()

        @staticmethod
        def _lan_server_factory(**kwargs):
            return lan.LanServer(**kwargs)

        def _dialog_parent(self):
            return None

        def _update_share_status(self, running, port=8080):
            self.status = (running, port)

    warning = Mock()
    monkeypatch.setattr(
        settings_module.AppSettings, "instance", classmethod(lambda cls: _Settings())
    )
    monkeypatch.setattr(lan, "LanServer", Mock(return_value=server))
    monkeypatch.setattr(lan_sharing.QMessageBox, "warning", warning)

    host = _Host()
    host._toggle_sharing()

    # The server is really up: status bar and tray must show "running"
    # even though start() reported a failure (the reason is just a hint).
    assert host._lan_server is server
    assert host.status == (True, 8080)
    assert host._tray_manager.states == [(True, "http://192.168.1.10:9090")]
    warning.assert_called_once()


def test_toggle_sharing_start_failure_not_running_keeps_status_off(monkeypatch):
    from AssetsManager import lan
    from AssetsManager.core import settings as settings_module
    from AssetsManager.widgets import lan_sharing
    from AssetsManager.widgets.lan_sharing import LanSharingMixin

    class _Settings:
        def get(self, key, default=None):
            return {
                "lan_bind": "0.0.0.0",
                "lan_share_safety_ack_version": 1,
                "lan_trusted_network_confirmed": True,
            }.get(key, default)

    runtime = type("Runtime", (), {})()
    session = type("Session", (), {"is_closed": False})()
    bootstrap = Mock()
    bootstrap.runtime_for.return_value = runtime
    server = Mock()
    server.start.return_value = {
        "share_state": "failed",
        "failure_reason": "security_post_start_rollback_failed",
        "running": False,
    }
    server.is_running.return_value = False

    class _Host(LanSharingMixin):
        _lan_server = None
        _library_session = session
        _bootstrap = bootstrap

        @staticmethod
        def _lan_server_factory(**kwargs):
            return lan.LanServer(**kwargs)

        def _dialog_parent(self):
            return None

        def _update_share_status(self, running, port=8080):
            self.status = (running, port)

    warning = Mock()
    monkeypatch.setattr(
        settings_module.AppSettings, "instance", classmethod(lambda cls: _Settings())
    )
    monkeypatch.setattr(lan, "LanServer", Mock(return_value=server))
    monkeypatch.setattr(lan_sharing.QMessageBox, "warning", warning)

    host = _Host()
    host._toggle_sharing()

    # Server is not running: nothing may be marked active.
    assert host._lan_server is None
    assert not hasattr(host, "status")
    warning.assert_called_once()


# ── lan_sharing F2: ValueError/TypeError from server.start ────────

def test_toggle_sharing_start_value_error_shows_warning(monkeypatch):
    from AssetsManager import lan
    from AssetsManager.core import settings as settings_module
    from AssetsManager.widgets import lan_sharing
    from AssetsManager.widgets.lan_sharing import LanSharingMixin

    class _Settings:
        def get(self, key, default=None):
            return {
                "lan_bind": "0.0.0.0",
                "lan_share_safety_ack_version": 1,
                "lan_trusted_network_confirmed": True,
            }.get(key, default)

    runtime = type("Runtime", (), {})()
    session = type("Session", (), {"is_closed": False})()
    bootstrap = Mock()
    bootstrap.runtime_for.return_value = runtime
    server = Mock()
    server.start.side_effect = ValueError("invalid port")

    class _Host(LanSharingMixin):
        _lan_server = None
        _library_session = session
        _bootstrap = bootstrap

        @staticmethod
        def _lan_server_factory(**kwargs):
            return lan.LanServer(**kwargs)

        def _dialog_parent(self):
            return None

        def _update_share_status(self, running, port=8080):
            self.status = (running, port)

    warning = Mock()
    monkeypatch.setattr(
        settings_module.AppSettings, "instance", classmethod(lambda cls: _Settings())
    )
    monkeypatch.setattr(lan, "LanServer", Mock(return_value=server))
    monkeypatch.setattr(lan_sharing.QMessageBox, "warning", warning)

    host = _Host()
    host._toggle_sharing()

    warning.assert_called_once()
    assert host._lan_server is None
    assert not hasattr(host, "status")


def test_toggle_sharing_start_type_error_shows_warning(monkeypatch):
    from AssetsManager import lan
    from AssetsManager.core import settings as settings_module
    from AssetsManager.widgets import lan_sharing
    from AssetsManager.widgets.lan_sharing import LanSharingMixin

    class _Settings:
        def get(self, key, default=None):
            return {
                "lan_bind": "0.0.0.0",
                "lan_share_safety_ack_version": 1,
                "lan_trusted_network_confirmed": True,
            }.get(key, default)

    runtime = type("Runtime", (), {})()
    session = type("Session", (), {"is_closed": False})()
    bootstrap = Mock()
    bootstrap.runtime_for.return_value = runtime
    server = Mock()
    server.start.side_effect = TypeError("bind must be a string")

    class _Host(LanSharingMixin):
        _lan_server = None
        _library_session = session
        _bootstrap = bootstrap

        @staticmethod
        def _lan_server_factory(**kwargs):
            return lan.LanServer(**kwargs)

        def _dialog_parent(self):
            return None

        def _update_share_status(self, running, port=8080):
            self.status = (running, port)

    warning = Mock()
    monkeypatch.setattr(
        settings_module.AppSettings, "instance", classmethod(lambda cls: _Settings())
    )
    monkeypatch.setattr(lan, "LanServer", Mock(return_value=server))
    monkeypatch.setattr(lan_sharing.QMessageBox, "warning", warning)

    host = _Host()
    host._toggle_sharing()

    warning.assert_called_once()
    assert host._lan_server is None


# ── toast E1: chrome width uses fixed widths, not pre-layout 0 ─────

def test_toast_horizontal_chrome_uses_fixed_widths_before_layout():
    from AssetsManager.core.ui_scale import scaled_px
    from AssetsManager.widgets.toast import Toast

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    toasts = []
    try:
        # shadow_margin reserves scaled_px(8) on each side for elevation.
        shadow = 2 * scaled_px(8)
        with_icon = Toast(parent, "Saved", icon="check")
        toasts.append(with_icon)
        assert with_icon._horizontal_chrome == (
            shadow + scaled_px(4) + scaled_px(12) + scaled_px(12) + scaled_px(20)
        )

        no_icon = Toast(parent, "Plain")
        toasts.append(no_icon)
        assert no_icon._horizontal_chrome == (
            shadow + scaled_px(4) + scaled_px(12) + scaled_px(12)
        )
    finally:
        for toast in toasts:
            toast.dismiss_immediately()
        parent.close()
        parent.deleteLater()
        app.processEvents()


def test_toast_deletes_itself_after_fade_out():
    from AssetsManager.widgets.toast import Toast

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    toast = Toast(parent, "hello", duration=100000)
    toast._start_fade_out()  # bypass the dismiss timer, drive the fade directly
    QTest.qWait(800)  # 300ms fade animation + margin for deleteLater
    app.processEvents()
    # After the fade the widget must be destroyed, not merely hidden.
    with pytest.raises(RuntimeError):
        toast.isVisible()
    parent.deleteLater()
    app.processEvents()
