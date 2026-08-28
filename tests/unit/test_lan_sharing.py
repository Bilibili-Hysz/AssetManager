from unittest.mock import Mock
import asyncio
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from aiohttp import web

from PySide6.QtWidgets import QApplication

from AssetsManager.dialogs.sharing_settings_dialog import (
    SharingSettingsDialog,
    _endpoint_primary_action,
    _endpoint_state,
)
from AssetsManager.widgets.lan_sharing import HOT_SHARING_SETTINGS, LanSharingMixin, RESTART_SHARING_SETTINGS


class _Server:
    _port = 9090
    token_secret = "secret"

    def is_running(self):
        return True

    def status(self):
        return {"url": "http://192.168.1.10:9090"}


def test_active_share_url_prefers_server_status_endpoint():
    class _Host(LanSharingMixin):
        _lan_server = _Server()

    assert _Host()._active_share_url(9090) == "http://192.168.1.10:9090"


def test_active_share_url_preserves_https_endpoint():
    class _HttpsServer(_Server):
        def status(self):
            return {"url": "https://192.168.1.10:9090"}

    class _Host(LanSharingMixin):
        _lan_server = _HttpsServer()

    assert _Host()._active_share_url(9090) == "https://192.168.1.10:9090"


def test_endpoint_state_and_primary_action_distinguish_local_and_public_scope():
    assert _endpoint_state({}) == "off"
    assert _endpoint_state({"state": "starting"}) == "starting"
    assert _endpoint_state({"running": True}) == "local"
    assert _endpoint_state({"running": True}, tunnel_running=True) == "public"
    assert _endpoint_state({"state": "failed"}) == "failed"

    assert _endpoint_primary_action("off") == "start"
    assert _endpoint_primary_action("starting") == "busy"
    assert _endpoint_primary_action("local") == "stop_server"
    assert _endpoint_primary_action("public") == "stop_tunnel"
    assert _endpoint_primary_action("failed") == "retry"


def test_sharing_dialog_uses_stable_auth_mode_key():
    dialog = SharingSettingsDialog.__new__(SharingSettingsDialog)
    dialog._auth_combo = type("_Combo", (), {"currentData": lambda _self: "password"})()

    assert dialog._auth_mode() == "password"


def test_sharing_configuration_impact_keys_match_reload_contract():
    assert HOT_SHARING_SETTINGS == {
        "lan_share_name": "share_name",
        "lan_blur_tags": "blur_tags",
        "lan_theme_color": "theme_color",
        "lan_welcome_msg": "welcome_msg",
        "lan_footer_text": "footer_text",
        "lan_show_hidden": "show_hidden",
        "lan_max_depth": "max_depth",
        "lan_include_types": "include_types",
        "lan_exclude_patterns": "exclude_patterns",
    }
    assert {"lan_port", "lan_bind", "lan_auth_mode", "lan_password", "lan_rate_limit", "lan_ip_whitelist", "lan_ssl_cert"} <= RESTART_SHARING_SETTINGS


def test_sharing_configuration_summary_counts_hot_and_restart_changes():
    dialog = SharingSettingsDialog.__new__(SharingSettingsDialog)
    dialog._configuration_snapshot = {"lan_share_name": "AssetManager", "lan_port": 8080}
    dialog._configuration_values = lambda: {"lan_share_name": "Shared", "lan_port": 9090}

    changes = dialog._configuration_changes()

    assert changes == {"lan_share_name", "lan_port"}
    assert len(changes & HOT_SHARING_SETTINGS.keys()) == 1
    assert len(changes - HOT_SHARING_SETTINGS.keys()) == 1


def test_sharing_configuration_impact_excludes_persisted_only_settings():
    dialog = SharingSettingsDialog.__new__(SharingSettingsDialog)
    dialog._configuration_snapshot = {"lan_enable_log": False}
    dialog._configuration_values = lambda: {"lan_enable_log": True}

    changes = dialog._configuration_changes()

    assert changes == {"lan_enable_log"}
    assert not changes & HOT_SHARING_SETTINGS.keys()
    assert not changes & RESTART_SHARING_SETTINGS


def test_clean_configuration_apply_still_emits_lifecycle_update():
    dialog = SharingSettingsDialog.__new__(SharingSettingsDialog)
    dialog._configuration_changes = lambda: set()
    dialog._save_settings = Mock()
    dialog._sync_configuration_snapshot = Mock()
    dialog._update_configuration_summary = Mock()
    dialog.settings_changed = Mock()

    dialog._apply_configuration_changes(force=True)

    dialog._save_settings.assert_called_once()
    dialog._sync_configuration_snapshot.assert_called_once()
    dialog.settings_changed.emit.assert_called_once()


def test_clean_configuration_apply_without_force_remains_a_noop():
    dialog = SharingSettingsDialog.__new__(SharingSettingsDialog)
    dialog._configuration_changes = lambda: set()
    dialog._save_settings = Mock()

    dialog._apply_configuration_changes()

    dialog._save_settings.assert_not_called()


def test_sharing_configuration_navigation_and_dirty_summary():
    app = QApplication.instance() or QApplication([])
    dialog = SharingSettingsDialog()
    try:
        assert dialog._configuration_stack.count() >= 5
        assert dialog._configuration_nav_buttons[0].isChecked()
        assert dialog._configuration_summary_label.text() == "No unsaved changes"

        dialog._name_edit.setText("Changed")
        app.processEvents()
        assert "apply now" in dialog._configuration_summary_label.text()

        dialog._port_spin.setValue(9090)
        app.processEvents()
        assert "require restart" in dialog._configuration_summary_label.text()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_toggle_sharing_uses_injected_library_session(monkeypatch, tmp_path):
    from AssetsManager import lan
    from AssetsManager.core.settings import AppSettings

    class _Settings:
        def get(self, key, default=None):
            return {
                "lan_share_safety_ack_version": 1,
                "lan_trusted_network_confirmed": True,
            }.get(key, default)

    class _Session:
        root_str = str(tmp_path)
        thumb_dir_str = str(tmp_path / "thumbs")
        is_closed = False

        def __init__(self):
            self.connection_for = Mock(return_value=object())
            self.root = tmp_path

    class _Host(LanSharingMixin):
        def __init__(self):
            self._lan_server = None
            self._lan_server_factory = lambda **kwargs: lan.LanServer(**kwargs)
            self._library_session = _Session()
            self._bootstrap = Mock()
            self._bootstrap.runtime_for.return_value = object()
            self.status_updates = []

        def _update_share_status(self, running, port=8080):
            self.status_updates.append((running, port))

    server = Mock()
    lan_facade = Mock(return_value=server)
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: _Settings()))
    monkeypatch.setattr(lan, "LanServer", lan_facade)
    host = _Host()

    host._toggle_sharing()

    host._bootstrap.runtime_for.assert_called_once_with(host._library_session)
    assert lan_facade.call_args.kwargs["runtime"] is host._bootstrap.runtime_for.return_value
    server.start.assert_called_once_with(port=8080, bind="0.0.0.0")


def test_toggle_sharing_injects_bootstrap_runtime(monkeypatch, tmp_path):
    from AssetsManager import lan
    from AssetsManager.core.settings import AppSettings

    class _Settings:
        def get(self, key, default=None):
            return {
                "lan_share_safety_ack_version": 1,
                "lan_trusted_network_confirmed": True,
            }.get(key, default)

    session = type("Session", (), {"is_closed": False})()
    runtime = object()
    bootstrap = Mock()
    bootstrap.runtime_for.return_value = runtime

    class _Host(LanSharingMixin):
        _library_session = session
        _bootstrap = bootstrap
        _lan_server = None

        @staticmethod
        def _lan_server_factory(**kwargs):
            return lan.LanServer(**kwargs)

        def _update_share_status(self, running, port=8080):
            pass

    server = Mock()
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: _Settings()))
    monkeypatch.setattr(lan, "LanServer", Mock(return_value=server))
    host = _Host()
    host._toggle_sharing()

    bootstrap.runtime_for.assert_called_once_with(session)
    assert lan.LanServer.call_args.kwargs["runtime"] is runtime
    assert lan.LanServer.call_args.kwargs["auth_mode"] == "none"


def test_open_share_link_dialog_uses_runtime_service_without_starting_lan(
    monkeypatch,
):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QMessageBox

    from AssetsManager.core.settings import AppSettings
    from AssetsManager.dialogs import share_link_dialog

    share_service = object()
    runtime = SimpleNamespace(
        sharing_services=SimpleNamespace(share_service=share_service)
    )
    session = SimpleNamespace(is_closed=False)
    bootstrap = Mock()
    bootstrap.runtime_for.return_value = runtime
    captured = {}

    class _Settings:
        def get(self, key, default=None):
            return {
                "lan_port": 9095,
                "lan_ssl_cert": "configured.crt",
                "lan_ssl_key": "configured.key",
                "lan_access_key": "configured-key",
            }.get(key, default)

    class _Dialog:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def exec(self):
            captured["executed"] = True
            return 0

    class _Port:
        def local_ip(self):
            return "192.0.2.10"

    class _Host(LanSharingMixin):
        _lan_server = None
        _library_session = session
        _bootstrap = bootstrap
        _sharing_port = _Port()

        def _dialog_parent(self):
            return None

    question = Mock(return_value=QMessageBox.StandardButton.No)
    monkeypatch.setattr(QMessageBox, "question", question)
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: _Settings()))
    monkeypatch.setattr(share_link_dialog, "ShareLinkDialog", _Dialog)

    _Host()._open_share_link_dialog(paths=["asset.txt"])

    question.assert_not_called()
    bootstrap.runtime_for.assert_called_once_with(session)
    assert captured["executed"] is True
    assert captured["kwargs"]["paths"] == ["asset.txt"]
    assert captured["kwargs"]["share_service"] is share_service
    assert captured["kwargs"]["base_url"] == "http://192.0.2.10:9095"
    assert captured["kwargs"]["requires_key"] is True


def test_runtime_service_providers_are_isolated_across_lan_servers(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.lan.server import _LanServerImpl

    bootstrap = ApplicationBootstrap()
    session_a = bootstrap.library_service.open_session(tmp_path / "library-a")
    session_b = bootstrap.library_service.open_session(tmp_path / "library-b")
    runtime_a = bootstrap.runtime_for(session_a)
    runtime_b = bootstrap.runtime_for(session_b)

    server_a = _LanServerImpl(runtime=runtime_a)
    provider_a = runtime_a.services.thumbnail_service._connection_provider
    server_b = _LanServerImpl(runtime=runtime_b)

    assert runtime_a.services.thumbnail_service is not runtime_b.services.thumbnail_service
    assert runtime_a.services.search_service is not runtime_b.services.search_service
    assert provider_a is runtime_a.services.search_service._connection_provider
    assert provider_a.__self__ is session_a
    assert runtime_b.services.thumbnail_service._connection_provider.__self__ is session_b
    assert runtime_b.services.search_service._connection_provider.__self__ is session_b
    assert server_a.services.thumbnail_service is runtime_a.services.thumbnail_service
    assert server_b.services.thumbnail_service is runtime_b.services.thumbnail_service
    assert runtime_a.services.thumbnail_service._connection_provider is provider_a


def test_toggle_sharing_requires_bootstrap_runtime(monkeypatch):
    from AssetsManager.core.settings import AppSettings
    from AssetsManager.widgets import lan_sharing

    class _Settings:
        def get(self, key, default=None):
            return default

    session = type("Session", (), {
        "is_closed": False,
        "root": "library",
        "root_str": "library",
        "thumb_dir_str": "thumbs",
        "connection_for": Mock(return_value=object()),
    })()
    class _Host(LanSharingMixin):
        _library_session = session
        _bootstrap = None
        _lan_server = None

        def _update_share_status(self, running, port=8080):
            pass

    warning = Mock()
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: _Settings()))
    monkeypatch.setattr(lan_sharing.QMessageBox, "warning", warning)

    _Host()._toggle_sharing()

    warning.assert_called_once()


def test_lan_server_runtime_constructor_is_only_public_constructor(monkeypatch):
    from AssetsManager import lan

    runtime = Mock()
    runtime.session.is_closed = False
    runtime.services.session = runtime.session
    impl = Mock()
    monkeypatch.setattr("AssetsManager.lan.server._LanServerImpl", impl)
    monkeypatch.setattr(lan, "_HAS_AIOHTTP", True)

    lan.LanServer(runtime=runtime)
    assert impl.call_args.kwargs["runtime"] is runtime
    assert not hasattr(lan.LanServer, "from_legacy_connection")


def test_lan_server_stop_does_not_close_runtime_or_session(monkeypatch):
    from AssetsManager import lan

    runtime = Mock()
    runtime.session.is_closed = False
    runtime.services.session = runtime.session
    impl = Mock()
    monkeypatch.setattr("AssetsManager.lan.server._LanServerImpl", impl)
    monkeypatch.setattr(lan, "_HAS_AIOHTTP", True)
    server = lan.LanServer(runtime=runtime)
    server.stop()

    impl.return_value.stop.assert_called_once_with()
    runtime.close.assert_not_called()
    runtime.session.close.assert_not_called()


def test_share_manager_stop_retains_server_for_retry_after_stop_failure():
    from AssetsManager.lan.manager import ShareManager

    class _FlakyServer:
        def __init__(self):
            self.stop_calls = 0

        def stop(self):
            self.stop_calls += 1
            if self.stop_calls == 1:
                raise RuntimeError("server stop failed")

    manager = ShareManager()
    server = _FlakyServer()
    manager._server = server
    manager._state["running"] = True

    # A failing server stop must not raise: the manager records the failure,
    # keeps the handle for a later retry, and marks the state failed.
    manager.stop()

    assert server.stop_calls == 1
    assert manager._server is server
    assert manager._state["running"] is False
    assert manager._state["share_state"] == "failed"
    assert manager._state["failure_reason"] == "server_stop_failed"

    # A second stop retries the retained handle and clears it on success.
    manager.stop()

    assert server.stop_calls == 2
    assert manager._server is None
    assert manager._state["running"] is False
    assert manager._state["share_state"] == "off"
    assert manager._state["failure_reason"] is None


def test_lan_server_restart_keeps_one_runtime_subscription_and_one_broadcast(monkeypatch):
    from AssetsManager.lan.api import setup_routes
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    class _Subscription:
        def __init__(self, router, callback):
            self.router = router
            self.callback = callback
            self.closed = False

        def close(self):
            if not self.closed:
                self.closed = True
                self.router.subscriptions.remove(self)

    class _Router:
        def __init__(self):
            self.subscriptions = []

        def subscribe(self, callback):
            subscription = _Subscription(self, callback)
            self.subscriptions.append(subscription)
            return subscription

        def emit(self, event):
            for subscription in tuple(self.subscriptions):
                subscription.callback(event)

    class _Manager:
        def __init__(self):
            self.broadcasts = []

        async def broadcast(self, event_type, payload):
            self.broadcasts.append((event_type, payload))

        async def close_all(self):
            pass

    runtime = type("Runtime", (), {
        "epoch": "epoch", "revision": 0, "event_router": _Router(),
    })()
    lan = type("Lan", (), {"runtime": runtime, "ws_manager": _Manager()})()
    app = web.Application()
    app[LAN_APP_KEY] = lan
    setup_routes(app)
    loop = asyncio.new_event_loop()
    try:
        app.freeze()
        loop.run_until_complete(app.startup())
        assert len(runtime.event_router.subscriptions) == 1
        loop.run_until_complete(app.cleanup())
        assert len(runtime.event_router.subscriptions) == 0
        loop.run_until_complete(app.startup())
        assert len(runtime.event_router.subscriptions) == 1
        event = type("Event", (), {
            "epoch": "epoch", "revision": 1, "domains": ("files",), "paths": ("x",),
        })()
        loop.call_soon(runtime.event_router.emit, event)
        loop.run_until_complete(asyncio.sleep(0))
        assert len(lan.ws_manager.broadcasts) == 1
        loop.run_until_complete(app.cleanup())
        assert len(runtime.event_router.subscriptions) == 0
    finally:
        loop.close()


class _RestartServer:
    _port = 8080
    _bind = "0.0.0.0"
    _rate_limit_value = 1000
    _blocked_ips = []
    _ip_whitelist = []
    _ssl_cert = None
    _ssl_key = None
    password_hash = None
    access_key_hash = None

    def __init__(self):
        self.stopped = False
        self.reloads = []

    def is_running(self):
        return True

    def stop(self):
        self.stopped = True

    def reload_settings(self, settings):
        self.reloads.append(settings)


class _RestartWindow(LanSharingMixin):
    def __init__(self):
        self._lan_server = _RestartServer()
        self.restarted = False
        self.status_updates = []

    def _update_share_status(self, running, port=8080):
        self.status_updates.append((running, port))

    def _toggle_sharing(self):
        self.restarted = True


def test_apply_sharing_settings_restarts_for_rate_limit_change(monkeypatch):
    from AssetsManager.core.settings import AppSettings

    class _Settings:
        def get(self, name, default=None):
            values = {
                "lan_port": 8080,
                "lan_bind": "0.0.0.0",
                "lan_rate_limit": 2000,
            }
            return values.get(name, default)

    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: _Settings()))

    window = _RestartWindow()
    window._apply_sharing_settings()

    assert window._lan_server.stopped is True
    assert window.restarted is True


class _DialogButton:
    def __init__(self):
        self.enabled = True
        self.text = ""

    def setEnabled(self, enabled):
        self.enabled = enabled

    def setText(self, text):
        self.text = text


class _DialogTimer:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class _DialogSignal:
    def __init__(self):
        self.emitted = False

    def emit(self):
        self.emitted = True


class _DialogTable:
    def __init__(self):
        self.rows = None

    def setRowCount(self, rows):
        self.rows = rows


class _DialogLabel:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


class _DialogServer:
    _port = 8080

    def is_running(self):
        return True

    def status(self):
        return {"running": True, "url": "http://127.0.0.1:8080", "port": 8080}


class _StoppedDialogServer(_DialogServer):
    def is_running(self):
        return False

    def status(self):
        return {"running": False, "port": 8080}


class _DialogHost:
    def __init__(self):
        self._lan_server = None
        self.toggles = 0

    def _toggle_sharing(self):
        self.toggles += 1
        self._lan_server = _DialogServer()


class _RunningDialogHost:
    def __init__(self):
        self._lan_server = _DialogServer()
        self.toggles = 0

    def _toggle_sharing(self):
        self.toggles += 1
        self._lan_server = None


def test_sharing_dialog_toggle_syncs_server_from_parent(monkeypatch):
    from AssetsManager.dialogs import sharing_settings_dialog

    monkeypatch.setattr(sharing_settings_dialog.Toast, "instance", lambda *args, **kwargs: None)
    dialog = SharingSettingsDialog.__new__(SharingSettingsDialog)
    host = _DialogHost()
    dialog._host = host
    dialog._server = None
    dialog._server_status = {}
    dialog._toggle_btn = _DialogButton()
    dialog._status_timer = _DialogTimer()
    dialog.settings_changed = _DialogSignal()
    dialog.refreshed = False
    dialog.status_updates = []
    dialog._save_settings = lambda: None
    dialog._update_status = lambda: dialog.status_updates.append(dialog._server_status.copy())
    dialog._refresh_all_tabs = lambda: setattr(dialog, "refreshed", True)

    dialog._on_toggle_server()

    assert host.toggles == 1
    assert dialog._server is host._lan_server
    assert dialog._server_status["running"] is True
    assert dialog._status_timer.started is True
    assert dialog.refreshed is True
    assert dialog.settings_changed.emitted is True


def test_sharing_dialog_stop_syncs_status_from_parent(monkeypatch):
    from AssetsManager.dialogs import sharing_settings_dialog

    monkeypatch.setattr(sharing_settings_dialog.Toast, "instance", lambda *args, **kwargs: None)
    dialog = SharingSettingsDialog.__new__(SharingSettingsDialog)
    host = _RunningDialogHost()
    dialog._host = host
    dialog._server = host._lan_server
    dialog._server_status = host._lan_server.status()
    dialog._toggle_btn = _DialogButton()
    dialog._status_timer = _DialogTimer()
    dialog.settings_changed = _DialogSignal()
    dialog.status_updates = []
    dialog._save_settings = lambda: None
    dialog._update_status = lambda: dialog.status_updates.append(dialog._server_status.copy())
    dialog._refresh_all_tabs = lambda: None

    dialog._on_toggle_server()

    assert host.toggles == 1
    assert dialog._server is None
    assert dialog._server_status == {}
    assert dialog._status_timer.stopped is True
    assert dialog.settings_changed.emitted is False


def test_sharing_dialog_api_base_requires_running_server():
    dialog = SharingSettingsDialog.__new__(SharingSettingsDialog)
    dialog._server = _StoppedDialogServer()

    assert dialog._get_api_base() is None

    dialog._server = _DialogServer()
    # 127.0.0.1, not localhost: the server binds IPv4 only and Windows
    # resolves localhost to ::1 first, which requests never falls back from.
    assert dialog._get_api_base() == "http://127.0.0.1:8080"


def test_sharing_dialog_refresh_clears_runtime_data_when_stopped():
    dialog = SharingSettingsDialog.__new__(SharingSettingsDialog)
    dialog._server = _StoppedDialogServer()
    dialog._shares = [{"id": "s1"}]
    dialog._invite_codes = ["code"]
    dialog._online_users = [{"name": "alice"}]
    dialog._activity_items = ["activity"]
    dialog._links_table = _DialogTable()
    dialog._codes_table = _DialogTable()
    dialog._online_table = _DialogTable()
    dialog._links_status = _DialogLabel()
    dialog._codes_status = _DialogLabel()
    dialog._online_status = _DialogLabel()
    dialog._activity_list = _DialogLabel()

    dialog._refresh_all_tabs()

    assert dialog._shares == []
    assert dialog._invite_codes == []
    assert dialog._online_users == []
    assert dialog._activity_items == []
    assert dialog._links_table.rows == 0
    assert dialog._codes_table.rows == 0
    assert dialog._online_table.rows == 0


def test_desktop_preflight_uses_runtime_active_user_auth(monkeypatch):
    from AssetsManager import lan
    from AssetsManager.core.settings import AppSettings

    class _Settings:
        def get(self, key, default=None):
            return {
                "lan_bind": "0.0.0.0",
                "lan_auth_mode": "users",
                "lan_share_safety_ack_version": 1,
                "lan_trusted_network_confirmed": False,
            }.get(key, default)

    auth_service = type("AuthService", (), {
        "has_active_users": lambda _self, **_kwargs: True,
    })()
    runtime = type(
        "Runtime",
        (),
        {"sharing_services": type("Sharing", (), {"auth_service": auth_service})()},
    )()
    session = type("Session", (), {"is_closed": False})()
    bootstrap = Mock()
    bootstrap.runtime_for.return_value = runtime
    server = Mock()

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

    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: _Settings()))
    monkeypatch.setattr(lan, "LanServer", Mock(return_value=server))

    host = _Host()
    host._toggle_sharing()

    assert host._share_security_snapshot.effective_auth == {"enabled": True, "mode": "user"}
    assert host._lan_server is server
    server.start.assert_called_once_with(port=8080, bind="0.0.0.0")


def test_desktop_retains_server_reference_when_start_rollback_failed(monkeypatch):
    from AssetsManager import lan
    from AssetsManager.core import settings as settings_module
    from AssetsManager.widgets import lan_sharing

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
    server.is_running.return_value = True

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

    monkeypatch.setattr(settings_module.AppSettings, "instance", classmethod(lambda cls: _Settings()))
    monkeypatch.setattr(lan, "LanServer", Mock(return_value=server))
    monkeypatch.setattr(lan_sharing.QMessageBox, "warning", Mock())

    host = _Host()
    host._toggle_sharing()

    assert host._lan_server is server
    assert host._share_security_snapshot["rollback_failed"] is True


def test_security_confirmation_persists_authenticated_decision_after_explicit_yes(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from AssetsManager.application.security_preflight import SecurityPreflight
    from AssetsManager.widgets.lan_sharing import confirm_security_preflight

    class _Settings:
        def __init__(self):
            self.calls = []

        def commit_share_safety_confirmation(self, ack_version, trusted):
            self.calls.append((ack_version, trusted))
            return True

    settings = _Settings()
    preflight = SecurityPreflight()
    snapshot = preflight.snapshot(
        sharing=True,
        bind="192.168.1.10",
        auth_status=(True, "password"),
    )
    monkeypatch.setattr(
        "AssetsManager.widgets.sharing_contracts.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    assert confirm_security_preflight(
        None,
        settings=settings,
        preflight=preflight,
        snapshot=snapshot,
        bind="192.168.1.10",
        auth_status=(True, "password"),
    ) is True
    assert settings.calls == [(1, False)]


def test_security_confirmation_cancel_does_not_persist_or_start(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from AssetsManager.application.security_preflight import SecurityPreflight
    from AssetsManager.widgets.lan_sharing import confirm_security_preflight

    class _Settings:
        def __init__(self):
            self.calls = []

        def commit_share_safety_confirmation(self, ack_version, trusted):
            self.calls.append((ack_version, trusted))
            return True

    settings = _Settings()
    preflight = SecurityPreflight()
    snapshot = preflight.snapshot(
        sharing=True,
        bind="0.0.0.0",
        auth_status=(False, "none"),
    )
    monkeypatch.setattr(
        "AssetsManager.widgets.sharing_contracts.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    assert confirm_security_preflight(
        None,
        settings=settings,
        preflight=preflight,
        snapshot=snapshot,
        bind="0.0.0.0",
        auth_status=(False, "none"),
    ) is False
    assert settings.calls == []
    assert preflight.snapshot(
        sharing=True,
        bind="0.0.0.0",
        auth_status=(False, "none"),
    ).share_state == "off"


def test_security_confirmation_commit_failure_is_fail_closed(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from AssetsManager.application.security_preflight import SecurityPreflight
    from AssetsManager.widgets.lan_sharing import confirm_security_preflight

    class _Settings:
        def commit_share_safety_confirmation(self, ack_version, trusted):
            return False

    warning = Mock()
    monkeypatch.setattr(
        "AssetsManager.widgets.sharing_contracts.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        "AssetsManager.widgets.sharing_contracts.QMessageBox.warning",
        warning,
    )

    preflight = SecurityPreflight()
    snapshot = preflight.snapshot(
        sharing=True,
        bind="0.0.0.0",
        auth_status=(False, "none"),
    )
    assert confirm_security_preflight(
        None,
        settings=_Settings(),
        preflight=preflight,
        snapshot=snapshot,
        bind="0.0.0.0",
        auth_status=(False, "none"),
    ) is False
    warning.assert_called_once()
    assert preflight.snapshot(
        sharing=True,
        bind="0.0.0.0",
        auth_status=(False, "none"),
    ).share_state == "off"

def test_format_bytes_tolerates_none_and_zero():
    """Server status can report bytes_transferred=None before any traffic."""
    dialog = SharingSettingsDialog.__new__(SharingSettingsDialog)
    assert dialog._format_bytes(None) == "0 B"
    assert dialog._format_bytes(0) == "0 B"
    assert dialog._format_bytes(0.0) == "0 B"
    assert dialog._format_bytes(1024) == "1.0 KB"
    assert dialog._format_bytes(1536) == "1.5 KB"
    assert dialog._format_bytes(5 * 1024 * 1024) == "5.0 MB"


def test_lan_utils_exclude_fake_ip_range():
    """TUN fake-ip space (RFC 2544 198.18.0.0/15) must never surface as a
    LAN address or default-route IP."""
    from AssetsManager.lan import utils as lan_utils

    assert lan_utils._is_private_ipv4("198.18.0.1") is False
    assert lan_utils._is_private_ipv4("198.19.255.254") is False
    assert lan_utils._is_fake_ip_or_benchmark("198.18.0.1") is True
    assert lan_utils._is_fake_ip_or_benchmark("198.19.10.5") is True
    assert lan_utils._is_fake_ip_or_benchmark("192.168.1.10") is False
    assert lan_utils._is_fake_ip_or_benchmark("10.0.0.5") is False


def test_default_route_ip_rejects_fake_ip(monkeypatch):
    """A TUN adapter as the default route must not be reported."""
    from AssetsManager.lan import utils as lan_utils

    class _Socket:
        def __init__(self, *_args, **_kwargs):
            self._closed = False

        def connect(self, _addr):
            pass

        def getsockname(self):
            return ("198.18.0.1", 0)

        def close(self):
            self._closed = True

    monkeypatch.setattr(lan_utils.socket, "socket", _Socket)
    assert lan_utils._default_route_ip() is None

    class _RealSocket:
        def __init__(self, *_args, **_kwargs):
            pass

        def connect(self, _addr):
            pass

        def getsockname(self):
            return ("192.168.1.20", 0)

        def close(self):
            pass

    monkeypatch.setattr(lan_utils.socket, "socket", _RealSocket)
    assert lan_utils._default_route_ip() == "192.168.1.20"


# ── Async stop on the toggle path ───────────────────────────────


def _pump(app, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class _FakeToggleServer:
    _port = 8080

    def __init__(self, stop_error=None):
        self._stop_error = stop_error
        self.stop_threads = []
        self.stop_started = threading.Event()
        self.release = threading.Event()

    def is_running(self):
        return True

    def stop(self):
        self.stop_threads.append(threading.current_thread())
        self.stop_started.set()
        self.release.wait(5.0)
        if self._stop_error is not None:
            raise self._stop_error


class _ToggleBtn:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, value):
        self.enabled = value


class _StatusLabel:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


def _stop_host(server):
    class _Host(LanSharingMixin):
        def __init__(self):
            self._lan_server = server
            self._share_toggle_btn = _ToggleBtn()
            self._share_status_label = _StatusLabel()
            self.status_updates = []

        def _update_share_status(self, running, port=8080):
            self.status_updates.append((running, port))

    return _Host()


def test_toggle_sharing_stop_runs_on_worker_thread_and_restores_state():
    from AssetsManager import i18n

    app = QApplication.instance() or QApplication([])
    gui_thread = threading.current_thread()
    server = _FakeToggleServer()
    host = _stop_host(server)

    host._toggle_sharing()

    # Immediate UI feedback: button disabled, status text switches to the
    # stopping hint, and the server handle is kept for correctness-order
    # callers (library switch) until the stop actually completes.
    assert host._share_stop_in_progress is True
    assert host._share_toggle_btn.enabled is False
    assert host._share_status_label.text == i18n.tr("sharing.stopping")
    assert host._lan_server is server

    assert server.stop_started.wait(2.0)
    assert server.stop_threads[0] is not gui_thread

    # While the stop is in flight, a re-entry must not double-stop.
    host._toggle_sharing()
    assert len(server.stop_threads) == 1
    assert host._lan_server is server

    server.release.set()
    assert _pump(app, lambda: host._lan_server is None)

    assert host._share_stop_in_progress is False
    assert host._share_toggle_btn.enabled is True
    assert host.status_updates[-1] == (False, 8080)


def test_toggle_sharing_stop_failure_keeps_handle_for_retry():
    app = QApplication.instance() or QApplication([])

    class _FailingServer(_FakeToggleServer):
        _port = 9090

    server = _FailingServer(stop_error=RuntimeError("stop failed"))
    host = _stop_host(server)

    host._toggle_sharing()
    server.release.set()
    assert _pump(app, lambda: host._share_stop_in_progress is False)

    # The handle is retained so a later toggle can retry the stop, and the
    # status reflects the still-running server instead of "off".
    assert host._lan_server is server
    assert host.status_updates[-1] == (True, 9090)
    assert host._share_toggle_btn.enabled is True
