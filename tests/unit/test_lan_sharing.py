from unittest.mock import Mock
import asyncio

import pytest
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
            return default

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
            return default

    session = type("Session", (), {"is_closed": False})()
    runtime = object()
    bootstrap = Mock()
    bootstrap.runtime_for.return_value = runtime

    class _Host(LanSharingMixin):
        _library_session = session
        _bootstrap = bootstrap
        _lan_server = None

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

    with pytest.raises(RuntimeError, match="server stop failed"):
        manager.stop()

    assert server.stop_calls == 1
    assert manager._server is server
    assert manager._state["running"] is True

    manager.stop()

    assert server.stop_calls == 2
    assert manager._server is None
    assert manager._state["running"] is False


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
    assert dialog._get_api_base() == "http://localhost:8080"


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
