"""Tests for FileListController."""
from AssetsManager.controllers.file_list_controller import FileListController
from AssetsManager.core.format_utils import format_size


class TestFileListController:

    def test_format_total_size_suffix(self):
        assert FileListController.format_total_size_suffix(1024) == "  |  1.0 KB"
        assert FileListController.format_total_size_suffix(0) == ""

    def test_set_file_operations_binds_and_clears_services(self):
        ctrl = FileListController()
        assert ctrl._file_ops is None
        assert ctrl._undo_svc is None

        ctrl.set_file_operations(object(), object())
        assert ctrl._file_ops is not None
        assert ctrl._undo_svc is not None

        ctrl.set_file_operations(None, None)
        assert ctrl._file_ops is None
        assert ctrl._undo_svc is None


def test_fmt_size():
    """The controller formats sizes through the shared core.format_size."""
    assert format_size(0) == "0.0 B"
    assert format_size(1023) == "1023.0 B"
    assert format_size(1024) == "1.0 KB"
    assert format_size(1048576) == "1.0 MB"
