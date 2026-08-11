from unittest.mock import Mock

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
    assert [button.accessibleName() for button in dialog._nav_buttons] == [
        "Endpoint", "Links", "Access", "Configuration",
    ]
    assert [button.toolTip() for button in dialog._nav_buttons] == [
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


def test_configuration_navigation_is_named_and_theme_refreshes(monkeypatch):
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: type("_Settings", (), {"get": lambda _self, _key, default=None: default})()),
    )
    dialog = SharingSettingsDialog()
    refresh = Mock(wraps=dialog._apply_configuration_theme)
    dialog._apply_configuration_theme = refresh
    dialog.show()
    QApplication.processEvents()

    labels = [button.text() for button in dialog._configuration_nav_buttons]
    assert labels[:5] == ["Network", "Protection", "Presentation", "Library scope", "Diagnostics"]
    assert [button.accessibleName() for button in dialog._configuration_nav_buttons] == labels
    dialog._select_configuration_section(2)
    from AssetsManager.core.signal_bus import get as bus
    bus().theme_changed.emit("default")
    QApplication.processEvents()

    assert dialog._configuration_nav_buttons[2].isChecked()
    refresh.assert_called_once()
    dialog.close()


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
    assert not dialog._qr_btn.isHidden()


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


def test_commerce_and_seller_switches_enforce_dependency_on_load_and_save(monkeypatch):
    class Settings:
        def __init__(self):
            self.values = {
                "lan_commerce_enabled": False,
                "lan_seller_enabled": True,
            }
            self.saved = 0

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value):
            self.values[key] = value

        def save(self):
            self.saved += 1
            return True

    settings = Settings()
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: settings),
    )
    dialog = SharingSettingsDialog()

    assert dialog._commerce_enabled.isChecked() is False
    assert dialog._seller_enabled.isChecked() is False
    assert dialog._seller_enabled.isEnabled() is False
    assert dialog._seller_helper.text() == "Enable Commerce first to make Seller features available."

    # An inconsistent persisted pair is normalized before it can be saved.
    assert dialog._apply_configuration_changes(force=True) is True
    assert settings.values["lan_commerce_enabled"] is False
    assert settings.values["lan_seller_enabled"] is False

    dialog._commerce_enabled.setChecked(True)
    assert dialog._seller_enabled.isEnabled() is True
    assert dialog._seller_helper.text() == "Seller features are available because Commerce is enabled."
    dialog._seller_enabled.setChecked(True)
    assert dialog._configuration_values()["lan_seller_enabled"] is True

    dialog._commerce_enabled.setChecked(False)
    assert dialog._seller_enabled.isChecked() is False
    assert dialog._seller_enabled.isEnabled() is False
    assert dialog._configuration_values()["lan_seller_enabled"] is False
    dialog.close()


def test_free_download_quota_settings_load_and_save(monkeypatch):
    class Settings:
        def __init__(self):
            self.values = {
                "lan_quota_enabled": True,
                "lan_quota_period": "weekly",
                "lan_quota_limit": 42,
                "lan_quota_min_interval_seconds": 12,
            }
            self.saved = 0

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value):
            self.values[key] = value

        def save(self):
            self.saved += 1
            return True

    settings = Settings()
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: settings),
    )
    dialog = SharingSettingsDialog()

    assert dialog._quota_enabled.isChecked() is True
    assert dialog._quota_period.currentData() == "weekly"
    assert dialog._quota_limit.value() == 42
    assert dialog._quota_min_interval.value() == 12
    assert dialog._quota_period.isEnabled() is True

    dialog._quota_period.setCurrentIndex(0)
    dialog._quota_limit.setValue(100)
    dialog._quota_min_interval.setValue(0)
    assert dialog._apply_configuration_changes(force=True) is True
    assert settings.values["lan_quota_enabled"] is True
    assert settings.values["lan_quota_period"] == "daily"
    assert settings.values["lan_quota_limit"] == 100
    assert settings.values["lan_quota_min_interval_seconds"] == 0
    assert settings.saved == 1
    dialog.close()


def test_password_mode_requires_password_before_save(monkeypatch):
    class Settings:
        def __init__(self):
            self.values = {"lan_auth_mode": "password"}
            self.saved = 0

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value):
            self.values[key] = value

        def save(self):
            self.saved += 1
            return True

    settings = Settings()
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: settings),
    )
    dialog = SharingSettingsDialog()

    assert dialog._auth_mode() == "password"
    assert dialog._pw_edit.text() == ""
    assert dialog._has_existing_password is False

    # An empty password with no existing one must not be persisted: the server
    # would otherwise fall back to an ambiguous auth state.
    assert dialog._apply_configuration_changes(force=True) is False
    assert settings.saved == 0
    assert dialog._auth_error_label.isHidden() is False
    assert dialog._auth_error_label.text() == (
        "Password protection requires a password. Enter one to enable it."
    )

    # Entering a password clears the inline error and saves a hash.
    dialog._pw_edit.setText("s3cret")
    assert dialog._auth_error_label.isHidden() is True
    assert dialog._apply_configuration_changes(force=True) is True
    assert settings.values["lan_auth_mode"] == "password"
    assert settings.values["lan_password"] != "s3cret"
    assert settings.saved == 1
    dialog.close()


def test_password_mode_keeps_existing_password_when_field_empty(monkeypatch):
    class Settings:
        def __init__(self):
            self.values = {"lan_auth_mode": "password", "lan_password": "hash:old"}
            self.saved = 0

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value):
            self.values[key] = value

        def save(self):
            self.saved += 1
            return True

    settings = Settings()
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: settings),
    )
    dialog = SharingSettingsDialog()

    assert dialog._has_existing_password is True
    assert dialog._apply_configuration_changes(force=True) is True
    assert settings.values["lan_password"] == "hash:old"
    assert settings.saved == 1
    dialog.close()


def test_tunnel_failure_maps_auth_required_reason(monkeypatch):
    monkeypatch.setattr("AssetsManager.lan.tunnel.is_available", lambda: True)
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: type("_Settings", (), {"get": lambda _self, _key, default=None: default})()),
    )
    dialog = SharingSettingsDialog()
    dialog._server = type(
        "_Server", (), {"tunnel_start_block_reason": "authentication_required"}
    )()

    dialog._on_tunnel_result("")

    assert "Password" in dialog._tunnel_status.text()
    assert dialog._tunnel_btn.isEnabled() is True
    dialog.close()


def test_dialog_close_cancels_pending_tunnel_worker(monkeypatch):
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: type("_Settings", (), {"get": lambda _self, _key, default=None: default})()),
    )

    class FakeWorker:
        def __init__(self):
            self.cancelled = False
            self.waited = False
            self.running = True

        def cancel(self):
            self.cancelled = True

        def isRunning(self):
            return self.running

        def wait(self, _ms):
            self.waited = True
            return True

    stops = []
    dialog = SharingSettingsDialog()
    dialog._server = type("_Server", (), {"stop_tunnel": lambda self: stops.append(1)})()
    worker = FakeWorker()
    dialog._tunnel_worker = worker

    dialog._on_dialog_closed()

    assert worker.cancelled is True
    assert worker.waited is True
    assert stops == [1]
    assert dialog._tunnel_worker is None
    assert dialog._closed is True


def test_done_stops_status_timer(monkeypatch):
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: type("_Settings", (), {"get": lambda _self, _key, default=None: default})()),
    )
    dialog = SharingSettingsDialog()
    dialog._status_timer.start()
    assert dialog._status_timer.isActive() is True

    dialog.done(0)  # Cancel path hides the dialog without closeEvent.

    assert dialog._status_timer.isActive() is False
    assert dialog._closed is True


def test_summary_reports_planned_and_live_quota_settings(monkeypatch):
    class Settings:
        def __init__(self):
            self.values = {}
            self.saved = 0

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value):
            self.values[key] = value

        def save(self):
            self.saved += 1
            return True

    settings = Settings()
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: settings),
    )
    dialog = SharingSettingsDialog()

    # Quota switches are read per-request by LAN routes: counted as live.
    dialog._quota_enabled.setChecked(True)
    summary = dialog._configuration_summary_label.text()
    assert "1 change(s) apply now" in summary
    assert "0 change(s) saved for the next start" in summary

    # Dead settings are reported as planned instead of "saved for next start".
    dialog._quota_enabled.setChecked(False)
    dialog._max_conn.setValue(77)
    summary = dialog._configuration_summary_label.text()
    assert "planned — not yet active" in summary
    assert "0 change(s) saved for the next start" in summary
    dialog.close()


def test_shares_loaded_ignores_non_dict_payload(monkeypatch):
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: type("_Settings", (), {"get": lambda _self, _key, default=None: default})()),
    )
    dialog = SharingSettingsDialog()

    dialog._on_shares_loaded(True, ["not", "a", "dict"])
    assert dialog._shares == []

    dialog._on_shares_loaded(True, {"shares": [{"id": 1}]})
    assert dialog._shares == [{"id": 1}]
    dialog.close()


def test_poll_result_ignored_after_dialog_closed(monkeypatch):
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: type("_Settings", (), {"get": lambda _self, _key, default=None: default})()),
    )
    dialog = SharingSettingsDialog()
    dialog._closed = True

    dialog._on_poll_result(True, {"connections": 9, "bytes_transferred": 100})

    assert dialog._online_info_value.text() == "0"
    assert dialog._traffic_info_value.text() == "0 B"
    dialog.close()


def test_toggle_server_confirms_before_starting_with_unapplied_changes(monkeypatch):
    class Settings:
        def __init__(self):
            self.values = {}
            self.saved = 0

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value):
            self.values[key] = value

        def save(self):
            self.saved += 1
            return True

    settings = Settings()
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: settings),
    )

    from PySide6.QtWidgets import QMessageBox

    class QuestionBox:
        StandardButton = QMessageBox.StandardButton

        @staticmethod
        def question(*_args, **_kwargs):
            return QuestionBox.StandardButton.No

    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.QMessageBox", QuestionBox
    )
    dialog = SharingSettingsDialog()
    dialog._name_edit.setText("Renamed")  # make the configuration dirty
    saved = []
    dialog._save_settings = lambda: saved.append(1)

    dialog._on_toggle_server()

    assert saved == []
    assert dialog._toggle_btn.isEnabled() is True
    dialog.close()
