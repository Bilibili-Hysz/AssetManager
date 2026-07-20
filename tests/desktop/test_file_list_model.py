"""Unit tests for FileSystemModel."""
import os
import tempfile
import threading
from unittest.mock import Mock
import pytest

# Set QT_QPA_PLATFORM before any Qt imports
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from AssetsManager.panels.file_list._model import FileSystemModel
from AssetsManager.application.bootstrap import ApplicationBootstrap

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
    value = FileSystemModel()
    yield value
    value.shutdown()


class TestFileSystemModel:
    def test_list_state_distinguishes_empty_and_filtered_results(self, model, tmp_path):
        model.set_directory(str(tmp_path))
        model._wait_for_scan()

        assert model.list_state == model.STATE_EMPTY_FOLDER

        (tmp_path / "asset.txt").write_text("asset")
        model.refresh()
        model._wait_for_scan()
        model.set_filter(text="missing")

        assert model.list_state == model.STATE_EMPTY_FILTERED

    def test_scan_error_is_retained_as_current_state(self, model, tmp_path, monkeypatch):
        def fail_scan(_path):
            raise PermissionError("denied")

        monkeypatch.setattr("AssetsManager.panels.file_list._model.os.scandir", fail_scan)
        model.set_directory(str(tmp_path))
        model._wait_for_scan()

        assert model.list_state == model.STATE_SCAN_ERROR
        assert isinstance(model._scan_error, PermissionError)

    def test_stale_scan_error_cannot_replace_newer_success(self, model, tmp_path):
        model.set_directory(str(tmp_path))
        stale_generation = model.scan_generation
        model.set_directory(str(tmp_path))
        current_generation = model.scan_generation
        entry = next(os.scandir(tmp_path), None)

        model._on_scan_done([entry] if entry is not None else [], {}, None, current_generation)
        model._on_scan_done([], {}, PermissionError("stale"), stale_generation)

        expected_state = model.STATE_READY if entry is not None else model.STATE_EMPTY_FOLDER
        assert model.list_state == expected_state
        assert model._scan_error is None

    def test_safe_stat_uses_zeroed_stat_result_for_missing_entry(self):
        class MissingEntry:
            def stat(self):
                raise OSError("removed during scan")

        stat = FileSystemModel._safe_stat(MissingEntry())

        assert isinstance(stat, os.stat_result)
        assert stat.st_size == 0
        assert stat.st_mtime == 0

    def test_unscoped_directory_size_skips_db_cache_write(self, tmp_path, monkeypatch):
        class CapturingPool:
            def __init__(self):
                self.tasks = []

            def setMaxThreadCount(self, _count):
                pass

            def start(self, task):
                self.tasks.append(task)

            def waitForDone(self):
                pass

        library = tmp_path / "library"
        folder = library / "folder"
        folder.mkdir(parents=True)
        (folder / "asset.bin").write_bytes(b"abc")
        pool = CapturingPool()
        monkeypatch.setattr("AssetsManager.panels.file_list._model.QThreadPool", lambda: pool)
        metadata_service = Mock()
        metadata_service.get_dir_size.return_value = (0, False)
        model = FileSystemModel()
        model.set_library_root(str(library))
        model.set_metadata_service(metadata_service)

        model._start_async_dir_size(str(folder))
        pool.tasks.pop().run()

        assert model._session is None
        metadata_service.get_dir_size.assert_not_called()
        metadata_service.set_dir_size.assert_not_called()

    def test_directory_size_worker_leases_originating_session_through_cache_write(self, tmp_path, monkeypatch):
        """A running worker drains before A closes; queued A work refuses after close."""
        class CapturingPool:
            def __init__(self):
                self.tasks = []

            def setMaxThreadCount(self, _count):
                pass

            def start(self, task):
                self.tasks.append(task)

            def waitForDone(self):
                pass

        library_a = tmp_path / "library-a"
        library_b = tmp_path / "library-b"
        folder_a = library_a / "folder"
        folder_b = library_b / "folder"
        folder_a.mkdir(parents=True)
        folder_b.mkdir(parents=True)
        (folder_a / "asset.bin").write_bytes(b"abc")
        pool = CapturingPool()
        monkeypatch.setattr("AssetsManager.panels.file_list._model.QThreadPool", lambda: pool)
        bootstrap = ApplicationBootstrap()
        session_a = bootstrap.library_service.open_session(library_a)
        session_b = bootstrap.library_service.open_session(library_b)
        model = FileSystemModel()
        entered_write = threading.Event()
        release_write = threading.Event()
        closed = threading.Event()
        svc_a = Mock()
        svc_a.get_dir_size.return_value = (0, False)

        def block_write(*_args):
            entered_write.set()
            assert release_write.wait(5)

        svc_a.set_dir_size.side_effect = block_write
        model.set_library_root(str(library_a), session_a)
        model.set_metadata_service(svc_a)
        model._start_async_dir_size(str(folder_a))
        worker = threading.Thread(target=pool.tasks.pop().run)
        worker.start()
        assert entered_write.wait(5)
        closer = threading.Thread(
            target=lambda: (bootstrap.library_service.close_session(session_a), closed.set()),
        )
        closer.start()
        assert not closed.wait(0.1)
        release_write.set()
        worker.join(5)
        closer.join(5)
        assert closed.is_set()
        svc_a.get_dir_size.assert_called_once_with(str(library_a.resolve()), str(folder_a), force=False)
        svc_a.set_dir_size.assert_called_once_with(str(library_a.resolve()), str(folder_a), 3)

        # A task queued before close cannot begin after close or write through B.
        model._pending_dir_sizes.clear()
        # Restore A's captured context only long enough to queue the task.
        model._session = session_a
        model._lib_root = str(library_a.resolve())
        model._metadata_service = svc_a
        model._start_async_dir_size(str(folder_a))
        pool.tasks.pop().run()
        svc_a.set_dir_size.assert_called_once()
        svc_b = Mock()
        svc_b.get_dir_size.return_value = (7, True)
        model.set_library_root(str(library_b), session_b)
        model.set_metadata_service(svc_b)
        model._start_async_dir_size(str(folder_b))
        pool.tasks.pop().run()
        svc_b.get_dir_size.assert_called_once_with(str(library_b.resolve()), str(folder_b), force=False)
        svc_b.set_dir_size.assert_not_called()

    def test_prepare_library_switch_drains_directory_size_workers(self, model):
        class CapturingPool:
            def __init__(self):
                self.waited = False

            def waitForDone(self):
                self.waited = True

        pool = CapturingPool()
        model._size_pool = pool
        model._pending_dir_sizes.update({"/library/a", "/library/b"})
        model._dir_size_gen = 7

        model.prepare_library_switch()

        assert pool.waited
        assert model._dir_size_gen == 8
        assert not model._pending_dir_sizes

    def test_clear_scoped_services_releases_closed_library_references(self, model, tmp_path):
        session = Mock()
        metadata_service = Mock()
        model.set_library_root(str(tmp_path), session)
        model.set_metadata_service(metadata_service)

        model.clear_scoped_services()

        assert model._session is None
        assert model._metadata_service is None
        assert model._lib_root == ""

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
        lifecycle = []
        model.scan_started.connect(lambda generation: lifecycle.append(("started", generation)))
        model.scan_committed.connect(lambda generation: lifecycle.append(("committed", generation)))

        model.set_directory(tmp_dir)
        model._wait_for_scan()
        # 3 files (excl .hidden) + 1 folder = 4 items
        assert model.rowCount() == 4
        assert lifecycle == [("started", 1), ("committed", 1)]

    def test_empty_directory_resolves_empty_folder_state(self, model, tmp_path):
        model.set_directory(str(tmp_path))
        model._wait_for_scan()

        assert model.list_state == model.STATE_EMPTY_FOLDER
        assert model._scan_error is None

    def test_filter_with_no_results_resolves_filtered_empty_state(self, model, tmp_path):
        (tmp_path / "asset.txt").write_text("asset")
        model.set_directory(str(tmp_path))
        model._wait_for_scan()
        model.set_filter(text="does-not-match")

        assert model.rowCount() == 0
        assert model.list_state == model.STATE_EMPTY_FILTERED

    def test_scan_error_resolves_error_state_and_is_cleared_by_next_scan(self, model, tmp_path, monkeypatch):
        def denied(_path):
            raise PermissionError("denied")

        monkeypatch.setattr("AssetsManager.panels.file_list._model.os.scandir", denied)
        model.set_directory(str(tmp_path))
        model._wait_for_scan()

        assert model.list_state == model.STATE_SCAN_ERROR
        assert isinstance(model._scan_error, PermissionError)

        monkeypatch.undo()
        (tmp_path / "asset.txt").write_text("asset")
        model.refresh()
        model._wait_for_scan()

        assert model.list_state == model.STATE_READY
        assert model._scan_error is None

    def test_stale_scan_error_cannot_replace_newer_result(self, model, tmp_path):
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        (second / "asset.txt").write_text("asset")
        model.set_directory(str(first))
        old_generation = model.scan_generation
        model.set_directory(str(second))
        current_generation = model.scan_generation

        with os.scandir(second) as entries:
            model._on_scan_done(list(entries), {}, None, current_generation)
        model._on_scan_done([], {}, PermissionError("stale"), old_generation)

        assert model.list_state == model.STATE_READY
        assert model._scan_error is None
        assert model.data(model.index(0, 0)) == "asset.txt"

    def test_rapid_directory_switch_commits_only_latest_generation(self, model, tmp_path):
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        (first / "only-first.txt").write_text("")
        (second / "only-second.txt").write_text("")

        model.set_directory(str(first))
        model.set_directory(str(second))
        model._wait_for_scan()

        names = {
            model.data(model.index(row, 0))
            for row in range(model.rowCount())
        }
        assert model.scan_generation == 2
        assert names == {"only-second.txt"}

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
