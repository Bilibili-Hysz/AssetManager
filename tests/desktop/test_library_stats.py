from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

from AssetsManager.panels.file_list._navigation import NavigationMixin


class _Panel:
    def __init__(self, services):
        self._scoped_services = services
        self.started_tasks = []

    def _run_in_background(self, task):
        self.started_tasks.append(task)


def _services(root, metadata_service):
    session = SimpleNamespace(root=root, operation=lambda: nullcontext())
    return SimpleNamespace(session=session, metadata_service=metadata_service)


def test_library_stats_update_uses_metadata_service_and_runs_in_background(tmp_path):
    metadata_service = Mock()
    metadata_service.get_dir_size.return_value = (1234, False)
    panel = _Panel(_services(tmp_path, metadata_service))

    NavigationMixin._schedule_library_stats_update(panel, str(tmp_path))

    assert len(panel.started_tasks) == 1
    metadata_service.get_dir_size.assert_not_called()

    panel.started_tasks[0]()

    metadata_service.get_dir_size.assert_called_once_with(
        str(tmp_path.resolve()), str(tmp_path.resolve()), force=True,
    )
    metadata_service.set_library_total_size.assert_called_once_with(
        str(tmp_path.resolve()), 1234,
    )


def test_library_stats_update_skips_stale_runtime_snapshot(tmp_path, caplog):
    metadata_service = Mock()
    panel = _Panel(_services(tmp_path / "current", metadata_service))
    stale_root = tmp_path / "stale"

    NavigationMixin._schedule_library_stats_update(panel, str(stale_root))

    assert panel.started_tasks == []
    assert "stale runtime snapshot" in caplog.text


def test_library_stats_update_logs_failures(tmp_path, caplog):
    metadata_service = Mock()
    metadata_service.get_dir_size.side_effect = OSError("scan failed")
    panel = _Panel(_services(tmp_path, metadata_service))

    NavigationMixin._schedule_library_stats_update(panel, str(tmp_path))
    panel.started_tasks[0]()

    assert "Failed to update library stats" in caplog.text
