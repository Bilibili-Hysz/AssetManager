

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QApplication

from AssetsManager import i18n
from AssetsManager.application.database_maintenance_service import (
    DatabaseSizeResult,
    WalCheckpointResult,
)
from AssetsManager.application.library_settings_adapter import LibrarySettingsAdapter
from AssetsManager.dialogs.settings_dialog import SettingsDialog
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import MaintenanceChanged


class _Session:
    def __init__(self, root: Path):
        self.root = root
        self.event_token = "maintenance-session-token"
        self.is_closed = False


def _adapter(tmp_path: Path):
    """Real LibrarySettingsAdapter over mocked scoped services."""
    session = _Session(tmp_path / "library")
    session.root.mkdir()
    maintenance = SimpleNamespace(
        running=False,
        last_result=None,
        last_schedule_error=None,
        database_size=Mock(return_value=DatabaseSizeResult(
            database_path=session.root / "library.db", size_bytes=1048576)),
        schedule=Mock(return_value=True),
    )
    integrity = SimpleNamespace(
        running=False,
        last_report=None,
        last_schedule_error=None,
        schedule=Mock(return_value=True),
    )
    services = SimpleNamespace(
        session=session,
        integrity_service=integrity,
        maintenance_service=maintenance,
        export_service=SimpleNamespace(),
    )
    return LibrarySettingsAdapter(services), maintenance


def _dialog(tmp_path):
    """Build a SettingsDialog under a fixed English locale.

    The maintenance status label holds dynamic state and is intentionally not
    retranslated, so the locale must be pinned before the dialog is built.
    Returns (app, dialog, maintenance, original_language).
    """
    original_language = i18n.current_language()
    i18n.set_language("en")
    app = QApplication.instance() or QApplication([])
    adapter, maintenance = _adapter(tmp_path)
    dialog = SettingsDialog()
    dialog.set_library_settings_adapter(adapter)
    return app, dialog, maintenance, original_language


def _publish_for(adapter):
    get_event_bus().publish(MaintenanceChanged(
        library_root=str(adapter.library_root),
        session_token=adapter.session_token,
    ))


def test_maintenance_tab_renders_and_buttons_call_adapter(tmp_path):
    app, dialog, maintenance, original_language = _dialog(tmp_path)
    try:
        dialog.show()
        app.processEvents()

        assert dialog._tabs.count() == 6
        assert dialog._tabs.tabText(3) == "Maintenance"
        assert dialog._run_checkpoint_btn.text() == "Run WAL Checkpoint"
        assert dialog._read_size_btn.text() == "Read Database Size"
        assert dialog._maintenance_group.title() == "Maintenance"
        assert dialog._maintenance_status.text() == "Ready"
        assert dialog._run_checkpoint_btn.isEnabled()

        dialog._run_checkpoint_btn.click()
        maintenance.schedule.assert_called_once_with("checkpoint", mode="PASSIVE")

        dialog._read_size_btn.click()
        maintenance.database_size.assert_called_once_with()
        assert dialog._maintenance_status.text() == "Database size: 1.0 MB"
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_maintenance_changed_refreshes_status_and_filters_other_sessions(tmp_path):
    app, dialog, maintenance, original_language = _dialog(tmp_path)
    adapter = dialog.library_settings_adapter
    try:
        dialog.show()
        app.processEvents()

        # Events from another session must be ignored.
        get_event_bus().publish(MaintenanceChanged(
            library_root="other", session_token="other-token"))
        app.processEvents()
        assert dialog._maintenance_status.text() == "Ready"

        # Running state disables the buttons and shows a busy label.
        maintenance.running = True
        _publish_for(adapter)
        app.processEvents()
        assert dialog._maintenance_status.text() == "Maintenance running..."
        assert not dialog._run_checkpoint_btn.isEnabled()
        assert not dialog._read_size_btn.isEnabled()

        # Completed checkpoint result is rendered from the view model.
        maintenance.running = False
        maintenance.last_result = WalCheckpointResult(
            mode="PASSIVE", busy=0, log_frames=12, checkpointed_frames=12)
        _publish_for(adapter)
        app.processEvents()
        assert dialog._maintenance_status.text() == (
            "WAL checkpoint: 12/12 frames, busy 0")
        assert dialog._run_checkpoint_btn.isEnabled()

        # Failure result surfaces the error text.
        maintenance.last_result = SimpleNamespace(
            success=False, error="checkpoint unavailable")
        _publish_for(adapter)
        app.processEvents()
        assert dialog._maintenance_status.text() == (
            "Maintenance failed: checkpoint unavailable")
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_maintenance_event_unsubscribes_on_close_and_resubscribes_on_show(tmp_path):
    app, dialog, maintenance, original_language = _dialog(tmp_path)
    adapter = dialog.library_settings_adapter
    try:
        dialog.show()
        app.processEvents()

        maintenance.last_result = SimpleNamespace(success=False, error="boom")
        _publish_for(adapter)
        app.processEvents()
        assert "boom" in dialog._maintenance_status.text()

        dialog.close()
        app.processEvents()
        maintenance.last_result = SimpleNamespace(success=False, error="after-close")
        _publish_for(adapter)
        app.processEvents()
        assert "after-close" not in dialog._maintenance_status.text()

        # Re-showing the dialog re-establishes the subscription.
        dialog.show()
        app.processEvents()
        _publish_for(adapter)
        app.processEvents()
        assert "after-close" in dialog._maintenance_status.text()
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_maintenance_event_from_worker_thread_runs_on_gui_thread(tmp_path):
    """Regression: the raw weak bus subscription ran _on_maintenance_event on
    the publishing (worker) thread, performing UI writes off the GUI thread.
    The queued DomainEventSubscription bridge must deliver it on the main
    thread instead."""
    import threading
    import time

    app, dialog, maintenance, original_language = _dialog(tmp_path)
    adapter = dialog.library_settings_adapter
    received_threads: list[int] = []
    main_thread = threading.get_ident()

    # Observe the queued bridge signal directly: it must fire on the
    # subscription's (GUI) thread, never on the publisher's.
    dialog._maintenance_subscription.event_received.connect(
        lambda _event: received_threads.append(threading.get_ident()))
    try:
        dialog.show()
        app.processEvents()

        maintenance.running = True
        worker = threading.Thread(target=lambda: _publish_for(adapter))
        worker.start()
        worker.join(timeout=2.0)

        deadline = time.monotonic() + 2.0
        while not received_threads and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

        assert received_threads == [main_thread]
        assert dialog._maintenance_status.text() == "Maintenance running..."
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_maintenance_tab_renders_without_adapter(tmp_path):
    original_language = i18n.current_language()
    try:
        i18n.set_language("en")
        app = QApplication.instance() or QApplication([])
        dialog = SettingsDialog()
        assert dialog._tabs.count() == 6
        assert not dialog._run_checkpoint_btn.isEnabled()
        assert not dialog._read_size_btn.isEnabled()
        assert dialog._maintenance_status.text() == "No library is open."
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
    finally:
        i18n.set_language(original_language)


def test_backup_tab_restore_disabled_while_session_open(tmp_path):
    original_language = i18n.current_language()
    try:
        i18n.set_language("en")
        app = QApplication.instance() or QApplication([])
        adapter, _maintenance = _adapter(tmp_path)
        dialog = SettingsDialog()
        dialog.set_library_settings_adapter(adapter)
        try:
            dialog.show()
            app.processEvents()

            assert dialog._tabs.tabText(4) == "Backup & Restore"
            assert dialog._export_btn.isEnabled()
            assert dialog._backup_btn.isEnabled()
            assert not dialog._restore_btn.isEnabled()
            assert dialog._backup_status.text() == (
                "Restore is unavailable while the library is open. "
                "Close the library first."
            )
            assert dialog._quarantine_status.text() == "No quarantined restore data."
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()
    finally:
        i18n.set_language(original_language)
