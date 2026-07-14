from AssetsManager.widgets.lan_sharing import LanSharingMixin
from AssetsManager.dialogs.sharing_settings_dialog import SharingSettingsDialog


class _Server:
    _port = 9090
    token_secret = "secret"

    def is_running(self):
        return True

    def status(self):
        return {"url": "http://192.168.1.10:9090"}


def test_quick_share_uses_server_status_url():
    assert LanSharingMixin._quick_share_api_url(_Server()) == "http://192.168.1.10:9090/api/shares"


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
    assert dialog.settings_changed.emitted is True


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
