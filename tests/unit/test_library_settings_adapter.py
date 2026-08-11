from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from AssetsManager.application.library_settings_adapter import (
    LibrarySettingsAdapter,
    LibrarySettingsBlockedError,
)


class _Session:
    def __init__(self, root: Path):
        self.root = root
        self.event_token = "session-token"
        self.is_closed = False


def _services(tmp_path: Path):
    session = _Session(tmp_path / "library")
    session.root.mkdir()
    integrity = SimpleNamespace(
        running=False,
        last_report=None,
        last_schedule_error=None,
        schedule=Mock(return_value=True),
    )
    maintenance = SimpleNamespace(
        running=False,
        last_result=None,
        last_schedule_error=None,
        database_size=Mock(return_value="size-result"),
        schedule=Mock(return_value=True),
    )
    export = SimpleNamespace(
        export_metadata_json=Mock(return_value="export-result"),
        create_backup=Mock(return_value="backup-result"),
        validate_backup=Mock(return_value="validation-result"),
        list_restore_quarantine=Mock(return_value=()),
        restore_backup=Mock(return_value="restore-result"),
    )
    return session, SimpleNamespace(
        session=session,
        integrity_service=integrity,
        maintenance_service=maintenance,
        export_service=export,
    )


def test_view_model_exposes_maintenance_failure(tmp_path):
    session, services = _services(tmp_path)
    services.maintenance_service.last_result = SimpleNamespace(
        success=False,
        error="checkpoint unavailable",
    )
    state = LibrarySettingsAdapter(services).view_model()
    assert state.maintenance_result.error == "checkpoint unavailable"
    assert state.maintenance_error == "checkpoint unavailable"


def test_view_model_exposes_integrity_and_schedule_failures(tmp_path):
    _session, services = _services(tmp_path)
    services.integrity_service.last_report = SimpleNamespace(
        healthy=False,
        quick_check="error",
        issues=("RuntimeError: integrity worker failed",),
    )
    services.integrity_service.last_schedule_error = (
        "worker_start_failed: RuntimeError: thread start failed"
    )
    services.maintenance_service.last_schedule_error = "already_running"

    state = LibrarySettingsAdapter(services).view_model()

    assert state.integrity_error == "RuntimeError: integrity worker failed"
    assert state.integrity_schedule_error == (
        "worker_start_failed: RuntimeError: thread start failed"
    )
    assert state.maintenance_schedule_error == "already_running"


def test_view_model_blocks_restore_until_session_closes(tmp_path):
    session, services = _services(tmp_path)
    adapter = LibrarySettingsAdapter(services)

    state = adapter.view_model()

    assert state.library_root == session.root
    assert state.session_token == "session-token"
    assert state.restore_allowed is False
    assert state.restore_block_reason == "restore_requires_closed_session"

    session.is_closed = True
    state = adapter.view_model()
    assert state.restore_allowed is True
    assert state.restore_block_reason is None


def test_live_operations_delegate_to_scoped_services(tmp_path):
    session, services = _services(tmp_path)
    adapter = LibrarySettingsAdapter(services)
    destination = tmp_path / "out.json"
    archive = tmp_path / "backup.assetbackup.zip"

    assert adapter.start_integrity_check() is True
    assert adapter.read_database_size() == "size-result"
    assert adapter.start_wal_checkpoint("PASSIVE") is True
    assert adapter.export_metadata(destination) == "export-result"
    assert adapter.create_backup(archive, include_thumbnails=True) == "backup-result"
    assert adapter.validate_backup(archive) == "validation-result"
    assert adapter.list_restore_quarantine() == ()

    services.integrity_service.schedule.assert_called_once_with()
    services.maintenance_service.schedule.assert_called_once_with(
        "checkpoint", mode="PASSIVE"
    )
    services.export_service.export_metadata_json.assert_called_once_with(
        session.root, destination
    )
    services.export_service.create_backup.assert_called_once_with(
        session.root, archive, include_thumbnails=True
    )
    services.export_service.validate_backup.assert_called_once_with(
        archive, expected_library_root=session.root
    )


def test_restore_is_blocked_live_and_allowed_after_close(tmp_path):
    session, services = _services(tmp_path)
    adapter = LibrarySettingsAdapter(services)
    archive = tmp_path / "backup.assetbackup.zip"

    with pytest.raises(LibrarySettingsBlockedError, match="restore_requires_closed_session"):
        adapter.restore_backup(archive, overwrite_existing=True)
    services.export_service.restore_backup.assert_not_called()

    session.is_closed = True
    assert adapter.restore_backup(archive, overwrite_existing=True) == "restore-result"
    services.export_service.restore_backup.assert_called_once_with(
        archive, session.root, overwrite_existing=True
    )


def test_live_operation_is_rejected_after_session_close(tmp_path):
    session, services = _services(tmp_path)
    adapter = LibrarySettingsAdapter(services)
    session.is_closed = True

    with pytest.raises(LibrarySettingsBlockedError, match="database_size_requires_live_session"):
        adapter.read_database_size()
    with pytest.raises(LibrarySettingsBlockedError, match="integrity_check_requires_live_session"):
        adapter.start_integrity_check()
    services.maintenance_service.database_size.assert_not_called()
    services.integrity_service.schedule.assert_not_called()
