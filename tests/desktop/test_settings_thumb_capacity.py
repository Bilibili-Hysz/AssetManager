"""H2-a2: thumbnail capacity-cap controls on the settings maintenance tab.

The combo persists ``thumbnail_cache_max_bytes`` (0 = unlimited disables the
evict button), and "Clean Up to Capacity Cap Now" runs the eviction through
the shared MaintenanceTaskRunner async mode.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QApplication

from AssetsManager import i18n
from AssetsManager.application.library_settings_adapter import (
    LibrarySettingsAdapter,
)
from AssetsManager.core.constants import (
    THUMBNAIL_CACHE_DEFAULT_MAX_BYTES,
)
from AssetsManager.core.settings import AppSettings
from AssetsManager.dialogs.settings_dialog import SettingsDialog


def _adapter(tmp_path: Path):
    session = SimpleNamespace(
        root=tmp_path / "library",
        thumb_dir=tmp_path / "data" / ".thumbnails",
        event_token="thumb-cap-session-token",
        is_closed=False,
    )
    session.root.mkdir(parents=True, exist_ok=True)
    session.thumb_dir.mkdir(parents=True, exist_ok=True)
    services = SimpleNamespace(
        session=session,
        integrity_service=SimpleNamespace(
            running=False, last_report=None, last_schedule_error=None),
        maintenance_service=SimpleNamespace(
            running=False, last_result=None, last_schedule_error=None),
        thumbnail_service=SimpleNamespace(
            enforce_cache_capacity=Mock(return_value=(2, 1024))),
    )
    return LibrarySettingsAdapter(services), services


def _dialog(adapter):
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog()
    dialog.set_library_settings_adapter(adapter)
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


def test_capacity_combo_reflects_and_persists_setting(tmp_path):
    original_language = i18n.current_language()
    i18n.set_language("en")
    settings = AppSettings.instance()
    original_cap = settings.get_thumbnail_cache_max_bytes()
    adapter, _services = _adapter(tmp_path)
    app, dialog = _dialog(adapter)
    try:
        dialog.show()
        app.processEvents()

        assert dialog._thumb_cap_group.title() == "Thumbnail Cache Capacity"
        assert dialog._current_thumb_cap_bytes() == THUMBNAIL_CACHE_DEFAULT_MAX_BYTES
        assert dialog._thumb_evict_btn.isEnabled()

        # Unlimited (userData=0) persists 0 and disables the evict button.
        unlimited_index = dialog._thumb_cap_combo.findData(0)
        dialog._thumb_cap_combo.setCurrentIndex(unlimited_index)
        assert settings.get_thumbnail_cache_max_bytes() == 0
        assert not dialog._thumb_evict_btn.isEnabled()

        # A 5 GB cap persists and re-enables the evict button.
        gb5_index = dialog._thumb_cap_combo.findData(5 * 1024 ** 3)
        dialog._thumb_cap_combo.setCurrentIndex(gb5_index)
        assert settings.get_thumbnail_cache_max_bytes() == 5 * 1024 ** 3
        assert dialog._thumb_evict_btn.isEnabled()
    finally:
        settings.set_thumbnail_cache_max_bytes(original_cap)
        settings.save()
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_evict_button_runs_enforcement_through_runner(tmp_path):
    original_language = i18n.current_language()
    i18n.set_language("en")
    adapter, services = _adapter(tmp_path)
    app, dialog = _dialog(adapter)
    try:
        dialog.show()
        app.processEvents()

        dialog._thumb_evict_btn.click()
        assert _wait_until(
            lambda: "Evicted 2 artifacts (1.0 KB reclaimed)"
            in dialog._thumb_cap_status.text(),
        )
        services.thumbnail_service.enforce_cache_capacity.assert_called_once_with(
            services.session.root, services.session.thumb_dir,
            max_bytes=THUMBNAIL_CACHE_DEFAULT_MAX_BYTES,
        )
        # The runner re-enabled its disabled widgets on completion.
        assert dialog._thumb_evict_btn.isEnabled()
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_evict_button_disabled_without_adapter(tmp_path):
    original_language = i18n.current_language()
    try:
        i18n.set_language("en")
        app = QApplication.instance() or QApplication([])
        dialog = SettingsDialog()
        try:
            assert not dialog._thumb_evict_btn.isEnabled()
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()
    finally:
        i18n.set_language(original_language)
