"""Unit tests for FileSystemModel."""
import os
import tempfile
import pytest

# Set QT_QPA_PLATFORM before any Qt imports
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from AssetsManager.panels.file_list._model import FileSystemModel

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def tmp_dir():
    """Create a temporary directory with test files."""
    d = tempfile.mkdtemp()
    # Create test files
    for name in ["image.png", "model.fbx", "readme.txt", ".hidden"]:
        open(os.path.join(d, name), "w").close()
    os.makedirs(os.path.join(d, "subfolder"))
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def model():
    return FileSystemModel()


class TestFileSystemModel:
    def test_inline_rename_delegates_without_direct_filesystem_mutation(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        row = next(i for i in range(model.rowCount()) if model.data(model.index(i, 0)) == "readme.txt")
        requested = []
        model.rename_requested.connect(lambda requested_row, name: requested.append((requested_row, name)))

        assert model.setData(model.index(row, 0), "renamed.txt", Qt.ItemDataRole.EditRole)

        assert requested == [(row, "renamed.txt")]
        assert os.path.exists(os.path.join(tmp_dir, "readme.txt"))
        assert not os.path.exists(os.path.join(tmp_dir, "renamed.txt"))

    def test_set_directory(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        # 3 files (excl .hidden) + 1 folder = 4 items
        assert model.rowCount() == 4

    def test_set_directory_includes_hidden(self, model, tmp_dir):
        model._show_hidden = True
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        assert model.rowCount() == 5  # 4 files + 1 folder

    def test_filter_by_category(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        model.set_filter(category="images")
        assert model.rowCount() >= 1  # at least image.png

    def test_filter_accepts_legacy_category_label(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        model.set_filter(category="images")
        internal_key_paths = [model.path_at(i) for i in range(model.rowCount())]

        model.set_filter(category="Images")
        legacy_label_paths = [model.path_at(i) for i in range(model.rowCount())]

        assert legacy_label_paths == internal_key_paths

    def test_filter_by_text(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        model.set_filter(text="image")
        assert model.rowCount() == 1

    def test_sort_by_name(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        model.set_sort("name", asc=True)
        first = model.data(model.index(0, 0))
        # Folders come first, then files alphabetically
        assert first == "subfolder"

    def test_sort_accepts_legacy_label(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        model.set_sort("Name", asc=True)
        assert model.data(model.index(0, 0)) == "subfolder"

    def test_entry_at(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        entry = model.entry_at(0)
        assert entry is not None
        assert entry.name in ["image.png", "model.fbx", "readme.txt", ".hidden", "subfolder"]

    def test_path_at(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        path = model.path_at(0)
        assert path is not None
        assert os.path.exists(path)

    def test_subtitle_file(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        # Find a file entry
        for i in range(model.rowCount()):
            entry = model.entry_at(i)
            if entry and entry.is_file():
                subtitle = model._subtitle(entry)
                assert subtitle  # Should have a size string
                break

    def test_subtitle_dir(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        for i in range(model.rowCount()):
            entry = model.entry_at(i)
            if entry and entry.is_dir():
                subtitle = model._subtitle(entry)
                assert subtitle  # Should have a count or "Empty"
                break

    def test_stat_cache(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        entry = model.entry_at(0)
        st1 = model._cached_stat(entry)
        st2 = model._cached_stat(entry)
        assert st1 is st2  # Same object from cache

    def test_is_dir_role(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        for i in range(model.rowCount()):
            entry = model.entry_at(i)
            is_dir = model.data(model.index(i, 0), FileSystemModel.IS_DIR_ROLE)
            assert is_dir == entry.is_dir()

    def test_subtitle_cache_invalidation(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        entry = model.entry_at(0)
        model._subtitle(entry)
        assert entry.path in model._subtitle_cache
        model.set_directory(tmp_dir)  # Re-set clears cache
        model._wait_for_scan()
        assert entry.path not in model._subtitle_cache

    def test_stat_cache_invalidation(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        entry = model.entry_at(0)
        model._cached_stat(entry)
        assert entry.path in model._stat_cache
        model.set_directory(tmp_dir)
        # Cache is cleared immediately by set_directory(), then repopulated by async scan
        assert entry.path not in model._stat_cache

    def test_cached_dir_size_returns_and_caches_size(self, tmp_path):
        lib = tmp_path / "library"
        folder = lib / "folder"
        folder.mkdir(parents=True)
        (folder / "asset.bin").write_bytes(b"abc")

        from AssetsManager.application.metadata_service import MetadataService
        from AssetsManager.core import database
        from AssetsManager.core.db_migrations import migrate
        import sqlite3
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.executescript(database._SCHEMA)
        migrate(conn)
        svc = MetadataService(connection_provider=lambda _root: conn)

        size, cached = svc.get_dir_size(str(lib), str(folder), force=True)
        assert size == 3
        assert cached is False

        size2, cached2 = svc.get_dir_size(str(lib), str(folder), force=False)
        assert size2 == 3
        assert cached2 is True
        conn.close()


class TestFilterAccepts:
    def test_hidden_files(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        # _show_hidden is False by default, so hidden files are filtered out
        # filter_accepts doesn't check _show_hidden — that's done in _apply_sort
        visible = [e for e in model._raw_entries if model.filter_accepts(e) and not e.name.startswith(".")]
        hidden = [e for e in model._raw_entries if e.name.startswith(".")]
        assert len(hidden) == 1
        assert len(visible) == 4

    def test_category_filter(self, model, tmp_dir):
        model.set_directory(tmp_dir)
        model._wait_for_scan()
        model._filter_cat = "Images"
        for entry in model._raw_entries:
            if entry.name.endswith(".png"):
                assert model.filter_accepts(entry)
            elif not entry.is_dir():
                assert not model.filter_accepts(entry)
