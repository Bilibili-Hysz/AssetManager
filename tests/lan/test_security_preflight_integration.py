"""G6-6 security-preflight integration contract tests.

These tests document the expected shared start-preflight interface because the
contract report says that the interface is not implemented yet. The minimum proposed interface is ``preflight: SecurityPreflight | None`` on
``ShareManager.start`` and ``LanServer.start``. The desktop mixin must construct
or obtain the same preflight object from persisted settings before creating a
server. Missing API failures are intentional blockers.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def _preflight(*, ack_version=0, trusted_network_confirmed=False, decision=None):
    from AssetsManager.application.security_preflight import SecurityPreflight

    preflight = SecurityPreflight(
        ack_version=ack_version,
        trusted_network_confirmed=trusted_network_confirmed,
    )
    if decision == "authenticated":
        preflight.confirm_authenticated_lan()
    elif decision == "trusted_lan":
        preflight.confirm_trusted_lan()
    elif decision == "cancel":
        preflight.cancel()
    return preflight


class _Runtime:
    def __init__(self):
        self.session = SimpleNamespace(is_closed=False)


def _runtime():
    return _Runtime()


def _call_expected_start(start, **kwargs):
    try:
        return start(**kwargs)
    except TypeError as exc:
        if "preflight" in str(exc) or "unexpected keyword" in str(exc):
            pytest.fail(f"G6-6 expected start(preflight=...) API is missing: {exc}")
        raise


def test_missing_confirmation_blocks_first_start_without_creating_or_starting_server(monkeypatch):
    from AssetsManager import lan
    from AssetsManager.lan.manager import ShareManager

    server_factory = Mock()
    monkeypatch.setattr(lan, "LanServer", server_factory)

    manager = ShareManager()
    result = _call_expected_start(
        manager.start, runtime=_runtime(), preflight=_preflight()
    )

    assert result["share_state"] == "confirmation_required"
    server_factory.assert_not_called()


def test_cancel_keeps_sharing_off_and_does_not_create_or_start_server(monkeypatch):
    from AssetsManager import lan
    from AssetsManager.lan.manager import ShareManager

    server_factory = Mock()
    monkeypatch.setattr(lan, "LanServer", server_factory)

    manager = ShareManager()
    result = _call_expected_start(
        manager.start,
        runtime=_runtime(),
        preflight=_preflight(decision="cancel"),
    )

    assert result["share_state"] == "off"
    server_factory.assert_not_called()


def test_authenticated_lan_starts_but_trusted_confirmation_cannot_authorize_tunnel(monkeypatch):
    from AssetsManager import lan
    from AssetsManager.lan.manager import ShareManager

    server = Mock()
    server.auth_status.return_value = (True, "password")
    monkeypatch.setattr(lan, "LanServer", Mock(return_value=server))

    manager = ShareManager()
    result = _call_expected_start(
        manager.start,
        runtime=_runtime(),
        password="correct horse battery staple",
        preflight=_preflight(decision="authenticated"),
    )

    assert result["share_state"] == "local_active"
    server.start.assert_called_once()
    manager._state["trusted_network_confirmed"] = True
    manager._server.auth_status.return_value = (False, "none")
    assert manager.start_tunnel(timeout=3) is None


def test_trusted_lan_starts_but_public_tunnel_remains_blocked(monkeypatch):
    from AssetsManager import lan
    from AssetsManager.lan.manager import ShareManager

    server = Mock()
    server.auth_status.return_value = (False, "none")
    monkeypatch.setattr(lan, "LanServer", Mock(return_value=server))

    manager = ShareManager()
    result = _call_expected_start(
        manager.start,
        runtime=_runtime(),
        preflight=_preflight(
            trusted_network_confirmed=True,
            decision="trusted_lan",
        ),
    )

    assert result["share_state"] == "local_active"
    assert manager.start_tunnel(timeout=3) is None


def test_direct_lan_server_cancel_uses_same_gate_and_never_starts(monkeypatch):
    from AssetsManager import lan

    impl = Mock()
    monkeypatch.setattr("AssetsManager.lan.server._LanServerImpl", Mock(return_value=impl))
    server = lan.LanServer(runtime=_runtime())

    result = _call_expected_start(
        server.start,
        port=8765,
        bind="0.0.0.0",
        preflight=_preflight(decision="cancel"),
    )

    assert result["share_state"] == "off"
    impl.start.assert_not_called()


def test_desktop_lan_sharing_mixin_cannot_bypass_missing_confirmation(monkeypatch):
    from AssetsManager import lan
    from AssetsManager.core.settings import AppSettings
    from AssetsManager.widgets.lan_sharing import LanSharingMixin

    server_factory = Mock()
    monkeypatch.setattr(lan, "LanServer", server_factory)

    class _Settings:
        def get(self, key, default=None):
            return {
                "lan_port": 8765,
                "lan_bind": "0.0.0.0",
                "lan_auth_mode": "none",
            }.get(key, default)

    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: _Settings()))

    class _Host(LanSharingMixin):
        _lan_server = None
        _library_session = SimpleNamespace(is_closed=False)
        _bootstrap = SimpleNamespace(runtime_for=lambda session: _runtime())

        @staticmethod
        def _lan_server_factory(**kwargs):
            return lan.LanServer(**kwargs)

        def _dialog_parent(self):
            return None

        def _update_share_status(self, running, port=8080):
            self.status = (running, port)

    monkeypatch.setattr("AssetsManager.widgets.lan_sharing.QMessageBox.warning", Mock())
    monkeypatch.setattr(
        "AssetsManager.widgets.lan_sharing.QMessageBox.question",
        Mock(return_value=0),
    )
    host = _Host()
    host._toggle_sharing()

    assert host._lan_server is None
    server_factory.assert_not_called()


def test_effective_auth_status_recognizes_password_access_key_and_active_user():
    from AssetsManager.lan.server import _LanServerImpl

    server = _LanServerImpl.__new__(_LanServerImpl)
    for attrs, expected in (
        ({"_access_key_hash": "hash", "_password_hash": None, "_auth_mode": "none"}, (True, "key")),
        ({"_access_key_hash": None, "_password_hash": "hash", "_auth_mode": "none"}, (True, "password")),
        ({"_access_key_hash": None, "_password_hash": None, "_auth_mode": "users"}, (True, "user")),
        ({"_access_key_hash": None, "_password_hash": None, "_auth_mode": "none"}, (False, "none")),
    ):
        server.__dict__.update(attrs)
        server._has_active_users = lambda: server._auth_mode == "users"
        assert server.auth_status() == expected


def test_share_manager_tunnel_is_fail_closed_when_auth_status_is_missing(monkeypatch):
    from AssetsManager.lan.manager import ShareManager

    tunnel = Mock()
    tunnel.start.return_value = "https://public.example"
    monkeypatch.setattr("AssetsManager.lan.manager.TunnelManager", Mock(return_value=tunnel))

    manager = ShareManager()
    manager._state["running"] = True
    manager._server = object()

    assert manager.start_tunnel(timeout=3) is None
    tunnel.start.assert_not_called()


class _PersistedSecuritySettings:
    def get(self, key, default=None):
        return {
            "lan_share_safety_ack_version": 1,
            "lan_trusted_network_confirmed": True,
        }.get(key, default)

    def get_share_security_history(self):
        return "127.0.0.1", {"enabled": True, "mode": "password"}


def test_direct_lan_server_entry_uses_persisted_history_before_impl_start(monkeypatch):
    from AssetsManager import lan
    from AssetsManager.core.settings import AppSettings

    class _Impl:
        def __init__(self, **_kwargs):
            self.started = False

        def auth_status(self):
            return True, "password"

        def start(self, **_kwargs):
            self.started = True

    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: _PersistedSecuritySettings()))
    impl = _Impl()
    monkeypatch.setattr("AssetsManager.lan.server._LanServerImpl", lambda **_kwargs: impl)

    server = lan.LanServer(runtime=_runtime())
    result = _call_expected_start(server.start, port=8765, bind="0.0.0.0")

    assert result["share_state"] == "confirmation_required"
    assert result["failure_reason"] == "bind_scope_expanded"
    assert impl.started is False


def test_independent_share_manager_entry_uses_persisted_history_before_server_factory(monkeypatch):
    from AssetsManager import lan
    from AssetsManager.core.settings import AppSettings
    from AssetsManager.lan.manager import ShareManager

    server_factory = Mock()
    monkeypatch.setattr(lan, "LanServer", server_factory)
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: _PersistedSecuritySettings()))

    manager = ShareManager()
    result = manager.start(runtime=_runtime())

    assert result["share_state"] == "confirmation_required"
    assert result["failure_reason"] == "bind_scope_expanded"
    server_factory.assert_not_called()


def test_share_manager_reuses_explicit_preflight_for_constructor_and_start(monkeypatch):
    from AssetsManager.application.security_preflight import SecurityPreflight
    from AssetsManager.lan.manager import ShareManager

    class _Server:
        def __init__(self):
            self.start_kwargs = None

        def start(self, **kwargs):
            self.start_kwargs = kwargs

        def auth_status(self):
            return True, "password"

        def is_running(self):
            return True

        def status(self):
            return {}

    server = _Server()
    captured = {}

    class _Lan:
        @staticmethod
        def is_available():
            return True

        class LanServer:
            def __new__(cls, **kwargs):
                captured.update(kwargs)
                return server

    monkeypatch.setattr("AssetsManager.lan.manager.lan", _Lan, raising=False)
    # ShareManager resolves the package-level module from AssetsManager at call time.
    import AssetsManager as package
    monkeypatch.setattr(package, "lan", _Lan)

    preflight = SecurityPreflight(ack_version=1)
    result = ShareManager().start(runtime=_runtime(), password="secret", preflight=preflight)

    assert result["share_state"] == "local_active"
    assert captured["preflight"] is preflight
    assert server.start_kwargs["preflight"] is preflight


class _WritableSecuritySettings(_PersistedSecuritySettings):
    def __init__(self, save_result=True):
        self.history = None
        self.save_result = save_result
        self.save_calls = 0

    def get_share_security_history(self):
        return None, None

    def set_share_security_history(self, bind, auth_status):
        self.history = (bind, auth_status)

    def save(self):
        self.save_calls += 1
        return self.save_result


def test_lan_server_records_real_post_start_security_history_only_after_active(monkeypatch):
    from AssetsManager import lan
    from AssetsManager.application.security_preflight import security_preflight_from_settings
    from AssetsManager.core.settings import AppSettings

    class _Impl:
        def __init__(self, **_kwargs):
            self.started = False
            self._bind = "localhost"

        def auth_status(self):
            return True, "key"

        def start(self, **_kwargs):
            self.started = True

        def stop(self):
            self.started = False

    settings = _WritableSecuritySettings()
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))
    impl = _Impl()
    monkeypatch.setattr("AssetsManager.lan.server._LanServerImpl", lambda **_kwargs: impl)

    preflight = security_preflight_from_settings(settings)
    preflight.confirm_authenticated_lan()
    server = lan.LanServer(runtime=_runtime(), preflight=preflight)

    assert server.start(port=8765, bind="0.0.0.0") is None
    assert impl.started is True
    assert settings.history == (
        "0.0.0.0",
        {"enabled": True, "mode": "key"},
    )
    assert settings.save_calls == 1
