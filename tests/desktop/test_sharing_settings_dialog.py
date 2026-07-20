from PySide6.QtWidgets import QApplication

from AssetsManager.dialogs.sharing_settings_dialog import SharingSettingsDialog


def test_sharing_shell_uses_named_pages_and_desktop_navigation(monkeypatch):
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: type("_Settings", (), {"get": lambda _self, _key, default=None: default})()),
    )
    dialog = SharingSettingsDialog()

    assert dialog.width() == 980
    assert dialog.height() == 720
    assert dialog._page_stack.count() == 4
    assert [button.text() for button in dialog._nav_buttons] == [
        "Endpoint", "Links", "Access", "Configuration",
    ]
    assert dialog._nav_rail.isVisible() is False

    dialog.show()
    QApplication.processEvents()
    assert dialog._nav_rail.isVisible() is True

    dialog.resize(799, 720)
    QApplication.processEvents()
    assert dialog._nav_rail.isVisible() is False
    assert dialog._top_nav.isVisible() is True


def test_endpoint_public_primary_action_stops_tunnel_only():
    dialog = SharingSettingsDialog.__new__(SharingSettingsDialog)
    dialog._server_status = {"running": True}
    dialog._server = type("_Server", (), {"is_tunnel_running": lambda _self: True})()
    calls = []
    dialog._toggle_tunnel = lambda: calls.append("tunnel")
    dialog._on_toggle_server = lambda: calls.append("server")

    dialog._on_primary_endpoint_action()

    assert calls == ["tunnel"]


def test_endpoint_public_state_prefers_tunnel_url(monkeypatch):
    monkeypatch.setattr("AssetsManager.lan.tunnel.is_available", lambda: True)
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: type("_Settings", (), {"get": lambda _self, _key, default=None: default})()),
    )
    dialog = SharingSettingsDialog(server_status={"running": True, "url": "http://192.168.1.10:8080"})
    dialog._server = type("_Server", (), {"is_tunnel_running": lambda _self: True})()
    dialog._tunnel_url_label.setText("https://share.example.test")

    dialog._update_status()

    assert dialog._url_label.text() == "https://share.example.test"


def test_access_page_persists_guest_policy_immediately(monkeypatch):
    class Settings:
        def __init__(self):
            self.values = {}
            self.saved = 0

        def get(self, _key, default=None):
            return default

        def set(self, key, value):
            self.values[key] = value

        def save(self):
            self.saved += 1

    settings = Settings()
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: settings),
    )
    dialog = SharingSettingsDialog()

    dialog._guest_download.setChecked(True)

    assert settings.values["lan_guest_download"] is True
    assert settings.values["lan_guest_preview"] is True
    assert settings.values["lan_guest_list"] is True
    assert settings.saved == 1
    assert dialog._guest_policy_status.text() == "Guest access policy updated."


def test_access_page_invite_failures_are_region_local(monkeypatch):
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: type("_Settings", (), {"get": lambda _self, _key, default=None: default})()),
    )
    dialog = SharingSettingsDialog()

    dialog._on_generate_code_result(False, None)
    assert dialog._codes_status.text() == "Could not generate invitation."

    dialog._invite_codes = [{"code": "INVITE"}]
    dialog._codes_table.selectRow(0)
    dialog._on_revoke_result(False, 0)
    assert dialog._codes_status.text() == "Could not revoke invitation."
