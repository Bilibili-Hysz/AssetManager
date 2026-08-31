"""H2-c: the "AI Tagging" settings group — round-trip and mock probe.

Covers: the enable switch persisting and dimming the dependent rows,
endpoint/model/max-tags/force-existing round-trips (including invalid
endpoint rejection), and the "Test Connection" button reporting the
mocked probe result.
"""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from AssetsManager.core.settings import AppSettings
from AssetsManager.dialogs.settings_dialog import SettingsDialog


@pytest.fixture()
def clean_ai_settings():
    """Restore the factory-off AI settings after each test."""
    settings = AppSettings.instance()
    yield settings
    settings.set_ai_tagging_enabled(False)
    settings.set_ai_tagging_endpoint("http://localhost:11434/v1")
    settings.set_ai_tagging_model("qwen2.5vl:3b")
    settings.set_ai_tagging_max_tags(8)
    settings.set_ai_tagging_force_existing(True)
    settings.save()


def _dialog():
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog()
    return app, dialog


def _wait_until(predicate, timeout=5.0):
    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestGroupLayout:
    def test_group_present_on_general_tab(self, clean_ai_settings):
        app, dialog = _dialog()
        try:
            dialog.show()
            app.processEvents()
            assert dialog._ai_group.title() == "AI Tagging"
            assert dialog._ai_enable_check.text() == "Enable AI tagging (local Ollama)"
            assert dialog._ai_test_btn.text() == "Test Connection"
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()

    def test_dependent_rows_disabled_while_feature_off(self, clean_ai_settings):
        app, dialog = _dialog()
        try:
            dialog.show()
            app.processEvents()
            assert not dialog._ai_endpoint_edit.isEnabled()
            assert not dialog._ai_model_edit.isEnabled()
            assert not dialog._ai_max_tags_spin.isEnabled()
            assert not dialog._ai_test_btn.isEnabled()
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()


class TestRoundTrip:
    def test_enable_switch_persists_and_enables_rows(self, clean_ai_settings):
        app, dialog = _dialog()
        try:
            dialog.show()
            app.processEvents()
            dialog._ai_enable_check.setChecked(True)
            assert clean_ai_settings.get_ai_tagging_enabled() is True
            assert dialog._ai_endpoint_edit.isEnabled()
            assert dialog._ai_test_btn.isEnabled()

            dialog._ai_enable_check.setChecked(False)
            assert clean_ai_settings.get_ai_tagging_enabled() is False
            assert not dialog._ai_test_btn.isEnabled()
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()

    def test_endpoint_round_trip(self, clean_ai_settings):
        app, dialog = _dialog()
        try:
            dialog.show()
            app.processEvents()
            dialog._ai_enable_check.setChecked(True)
            dialog._ai_endpoint_edit.setText("http://127.0.0.1:11434/v1")
            dialog._ai_endpoint_edit.editingFinished.emit()
            assert clean_ai_settings.get_ai_tagging_endpoint() == \
                "http://127.0.0.1:11434/v1"
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()

    def test_invalid_endpoint_reverts_and_reports(self, clean_ai_settings):
        app, dialog = _dialog()
        try:
            dialog.show()
            app.processEvents()
            dialog._ai_enable_check.setChecked(True)
            persisted = clean_ai_settings.get_ai_tagging_endpoint()
            dialog._ai_endpoint_edit.setText("not a url")
            dialog._ai_endpoint_edit.editingFinished.emit()
            assert clean_ai_settings.get_ai_tagging_endpoint() == persisted
            assert dialog._ai_endpoint_edit.text() == persisted
            assert dialog._ai_status.text() == "Invalid endpoint — must be an http(s) URL."
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()

    def test_model_max_tags_and_force_existing_round_trip(self, clean_ai_settings):
        app, dialog = _dialog()
        try:
            dialog.show()
            app.processEvents()
            dialog._ai_enable_check.setChecked(True)
            dialog._ai_model_edit.setText("llava:7b")
            dialog._ai_model_edit.editingFinished.emit()
            dialog._ai_max_tags_spin.setValue(12)
            dialog._ai_force_check.setChecked(False)
            app.processEvents()
            assert clean_ai_settings.get_ai_tagging_model() == "llava:7b"
            assert clean_ai_settings.get_ai_tagging_max_tags() == 12
            assert clean_ai_settings.get_ai_tagging_force_existing() is False
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()

    def test_widgets_reflect_persisted_settings_on_open(self, clean_ai_settings):
        clean_ai_settings.set_ai_tagging_enabled(True)
        clean_ai_settings.set_ai_tagging_model("llava:7b")
        clean_ai_settings.set_ai_tagging_max_tags(5)
        clean_ai_settings.set_ai_tagging_force_existing(False)
        app, dialog = _dialog()
        try:
            dialog.show()
            app.processEvents()
            assert dialog._ai_enable_check.isChecked()
            assert dialog._ai_model_edit.text() == "llava:7b"
            assert dialog._ai_max_tags_spin.value() == 5
            assert not dialog._ai_force_check.isChecked()
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()


class TestConnectionProbe:
    def test_probe_success_reports_ok(
        self, clean_ai_settings, monkeypatch
    ):
        monkeypatch.setattr(
            "AssetsManager.application.ai_tagging.ollama_client.probe",
            lambda endpoint, timeout=5: endpoint == "http://127.0.0.1:11434/v1",
        )
        app, dialog = _dialog()
        try:
            dialog.show()
            app.processEvents()
            dialog._ai_enable_check.setChecked(True)
            dialog._ai_endpoint_edit.setText("http://127.0.0.1:11434/v1")
            dialog._ai_endpoint_edit.editingFinished.emit()
            dialog._ai_test_btn.click()
            assert _wait_until(
                lambda: dialog._ai_status.text() == "Ollama reachable.")
            assert dialog._ai_test_btn.isEnabled()
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()

    def test_probe_failure_reports_fail(
        self, clean_ai_settings, monkeypatch
    ):
        def refused(endpoint, timeout=5):
            return False

        monkeypatch.setattr(
            "AssetsManager.application.ai_tagging.ollama_client.probe", refused)
        app, dialog = _dialog()
        try:
            dialog.show()
            app.processEvents()
            dialog._ai_enable_check.setChecked(True)
            dialog._ai_test_btn.click()
            assert _wait_until(
                lambda: dialog._ai_status.text() ==
                "Ollama not reachable — check the endpoint and service.")
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()
