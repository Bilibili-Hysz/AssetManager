"""Tests for FileListController."""
import os

from AssetsManager.controllers.file_list_controller import FileListController, _fmt_size


class TestFileListController:

    def test_compute_status_text_no_selection(self):
        text = FileListController.compute_status_text(
            total=10, selected=0, total_size=1024, view_mode="Grid",
        )
        assert text == "10 items  |  1.0 KB  |  Grid"

    def test_compute_status_text_with_selection(self):
        text = FileListController.compute_status_text(
            total=10, selected=3, total_size=2048, view_mode="Details",
        )
        assert text == "3 selected / 10 items  |  2.0 KB  |  Details"

    def test_compute_status_text_zero_size(self):
        text = FileListController.compute_status_text(
            total=5, selected=0, total_size=0, view_mode="Grid",
        )
        assert text == "5 items  |  Grid"

    def test_find_first_image_caches_result(self, tmp_path):
        (tmp_path / "image.png").write_bytes(b"png")
        (tmp_path / "text.txt").write_text("x")

        ctrl = FileListController()
        result1 = ctrl.find_first_image(str(tmp_path))
        result2 = ctrl.find_first_image(str(tmp_path))

        assert result1 is not None
        assert result1.endswith(".png")
        assert result1 == result2

    def test_find_first_image_returns_none_for_empty_dir(self, tmp_path):
        ctrl = FileListController()
        assert ctrl.find_first_image(str(tmp_path)) is None

    def test_clear_first_image_cache(self, tmp_path):
        (tmp_path / "image.png").write_bytes(b"png")

        ctrl = FileListController()
        ctrl.find_first_image(str(tmp_path))
        assert len(ctrl._first_image_cache) == 1

        ctrl.clear_first_image_cache()
        assert len(ctrl._first_image_cache) == 0

    def test_first_image_cache_is_bounded(self, tmp_path):
        ctrl = FileListController()
        ctrl._first_image_cache_max = 2
        ctrl._first_image_cache["a"] = None
        ctrl._first_image_cache["b"] = None

        ctrl.find_first_image(str(tmp_path))

        assert len(ctrl._first_image_cache) == 1
        assert str(tmp_path) in ctrl._first_image_cache

    def test_compute_total_size(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")  # 5 bytes
        (tmp_path / "b.txt").write_text("world!")  # 6 bytes
        (tmp_path / "sub").mkdir()

        entries = list(os.scandir(str(tmp_path)))
        stat_cache = {}
        total = FileListController.compute_total_size(entries, stat_cache)
        assert total == 11  # 5 + 6 (directory excluded)

    def test_compute_total_size_with_stat_cache(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")

        entries = list(os.scandir(str(tmp_path)))
        # Pre-populate stat cache
        stat_cache = {}
        for entry in entries:
            if entry.is_file():
                stat_cache[entry.path] = entry.stat()

        total = FileListController.compute_total_size(entries, stat_cache)
        assert total == 5


def test_fmt_size():
    assert _fmt_size(0) == "0.0 B"
    assert _fmt_size(1023) == "1023.0 B"
    assert _fmt_size(1024) == "1.0 KB"
    assert _fmt_size(1048576) == "1.0 MB"
