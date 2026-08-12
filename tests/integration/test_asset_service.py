from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from AssetsManager.core.directory_cache import DirectoryCache

from AssetsManager.core import database
from AssetsManager.core.db_migrations import migrate


def _migrate_with_baseline(conn) -> int:
    conn.executescript(database._SCHEMA)
    return migrate(conn)


class _FakeDirEntry:
    """Minimal os.DirEntry stand-in for scan-failure tests."""

    def __init__(self, name, path, *, is_dir=True, is_file=True,
                 is_dir_error=None, is_file_error=None, stat_result=None):
        self.name = name
        self.path = path
        self._is_dir = is_dir
        self._is_file = is_file
        self._is_dir_error = is_dir_error
        self._is_file_error = is_file_error
        self._stat_result = stat_result or SimpleNamespace(st_mtime=1.0, st_size=0)

    def is_dir(self, *, follow_symlinks=True):
        if self._is_dir_error is not None:
            raise self._is_dir_error
        return self._is_dir

    def is_file(self, *, follow_symlinks=True):
        if self._is_file_error is not None:
            raise self._is_file_error
        return self._is_file

    def stat(self, *, follow_symlinks=True):
        return self._stat_result


def test_asset_service_lists_visible_items(tmp_path):
    from AssetsManager.application import AssetService

    (tmp_path / "visible.txt").write_text("hello", encoding="utf-8")
    (tmp_path / ".hidden.txt").write_text("secret", encoding="utf-8")
    (tmp_path / "folder").mkdir()

    listing = AssetService().list_directory(tmp_path, tmp_path)
    names = [item.name for item in listing.items]

    assert names == ["folder", "visible.txt"]
    assert listing.total_count == 2
    assert listing.current_path == ""


def test_asset_service_filters_and_searches(tmp_path):
    from AssetsManager.application import AssetService, DirectoryListOptions

    (tmp_path / "hero.png").write_text("image", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("doc", encoding="utf-8")
    (tmp_path / "villain.png").write_text("image", encoding="utf-8")

    listing = AssetService().list_directory(
        tmp_path,
        tmp_path,
        DirectoryListOptions(filter_category="images", search="hero"),
    )

    assert [item.name for item in listing.items] == ["hero.png"]


def test_asset_service_category_filter_keeps_directories(tmp_path):
    """Directories survive category filtering so navigation never disappears.

    This is shared pipeline semantics with the desktop file list — a
    directory has no extension, so it can never match a category, but it
    must remain visible for the user to drill into it.
    """
    from AssetsManager.application import AssetService, DirectoryListOptions

    (tmp_path / "subfolder").mkdir()
    (tmp_path / "hero.png").write_text("image", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("doc", encoding="utf-8")

    listing = AssetService().list_directory(
        tmp_path,
        tmp_path,
        DirectoryListOptions(filter_category="images"),
    )

    assert [item.name for item in listing.items] == ["subfolder", "hero.png"]


def test_asset_service_search_is_case_insensitive(tmp_path):
    """The shared pipeline handles case itself; raw uppercase queries work."""
    from AssetsManager.application import AssetService, DirectoryListOptions

    (tmp_path / "hero.png").write_text("image", encoding="utf-8")

    listing = AssetService().list_directory(
        tmp_path,
        tmp_path,
        DirectoryListOptions(search="HERO"),
    )

    assert [item.name for item in listing.items] == ["hero.png"]


def test_asset_service_respects_include_and_exclude(tmp_path):
    from AssetsManager.application import AssetService, DirectoryListOptions

    (tmp_path / "asset.png").write_text("image", encoding="utf-8")
    (tmp_path / "asset.tmp").write_text("tmp", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("doc", encoding="utf-8")

    listing = AssetService().list_directory(
        tmp_path,
        tmp_path,
        DirectoryListOptions(include_types=("images", "documents"), exclude_patterns=("*.tmp",)),
    )

    assert [item.name for item in listing.items] == ["asset.png", "notes.txt"]


def test_asset_service_applies_max_depth_to_child_dirs(tmp_path):
    from AssetsManager.application import AssetService, DirectoryListOptions

    (tmp_path / "child").mkdir()
    (tmp_path / "asset.txt").write_text("doc", encoding="utf-8")

    listing = AssetService().list_directory(
        tmp_path,
        tmp_path,
        DirectoryListOptions(max_depth=1, current_depth=1),
    )

    assert [item.name for item in listing.items] == ["asset.txt"]


def test_asset_service_marks_directories_using_project_depth_config(tmp_path):
    from AssetsManager.application import AssetService, DirectoryListOptions

    category = tmp_path / "category"
    project = category / "project"
    project.mkdir(parents=True)
    (tmp_path / "asset.txt").write_text("doc", encoding="utf-8")

    service = AssetService()
    root_listing = service.list_directory(
        tmp_path,
        tmp_path,
        DirectoryListOptions(project_depth=1, branch_depths={"category": 3}),
    )
    child_listing = service.list_directory(
        tmp_path, category, DirectoryListOptions(project_depth=2, branch_name="category"),
    )

    assert {item.name: item.is_project for item in root_listing.items} == {
        "category": False, "asset.txt": False,
    }
    assert {item.name: item.is_project for item in child_listing.items} == {"project": True}


def test_asset_service_uses_branch_project_depth(tmp_path):
    from AssetsManager.application import AssetService, DirectoryListOptions

    branch = tmp_path / "branch"
    project = branch / "project"
    project.mkdir(parents=True)

    listing = AssetService().list_directory(
        tmp_path,
        branch,
        DirectoryListOptions(project_depth=2, branch_name="branch", branch_depths={"branch": 3}),
    )

    assert [(item.name, item.is_project) for item in listing.items] == [("project", False)]


def test_asset_service_records_directory_summary_cache_hit_and_miss(tmp_path, memory_db):
    from AssetsManager.application import AssetService
    from AssetsManager.core.directory_cache import DirectoryCache
    from AssetsManager.core.performance import PerformanceRecorder

    child = tmp_path / "child"
    child.mkdir()
    (child / "asset.png").write_bytes(b"data")
    _migrate_with_baseline(memory_db)
    recorder = PerformanceRecorder(enabled=True)
    service = AssetService(DirectoryCache(memory_db), recorder, session_token="session-a")

    service.list_directory(tmp_path, tmp_path)
    service.list_directory(tmp_path, tmp_path)

    events = [event for event in recorder.recent() if event.name == "directory.summary"]
    assert [event.attributes["cache_hit"] for event in events] == [False, True]
    assert all(event.path == str(child) and event.session_token == "session-a" for event in events)


def test_asset_service_records_stale_summary_cache_as_miss(tmp_path, memory_db):
    from AssetsManager.application import AssetService
    from AssetsManager.core.directory_cache import DirectoryCache
    from AssetsManager.core.performance import PerformanceRecorder

    child = tmp_path / "child"
    child.mkdir()
    _migrate_with_baseline(memory_db)
    cache = DirectoryCache(memory_db)
    cache.set(str(child), 99, None, mtime=0)
    recorder = PerformanceRecorder(enabled=True)

    listing = AssetService(cache, recorder).list_directory(tmp_path, tmp_path)

    event = recorder.recent()[0]
    assert event.attributes["cache_hit"] is False
    assert listing.items[0].item_count == 0
    refreshed = cache.get(str(child), mtime=child.stat().st_mtime)
    assert refreshed is not None
    assert refreshed.item_count == 0


def test_asset_service_ignores_recorder_failure(tmp_path, memory_db, monkeypatch):
    from AssetsManager.application import AssetService
    from AssetsManager.core.directory_cache import DirectoryCache
    from AssetsManager.core.performance import PerformanceRecorder

    child = tmp_path / "child"
    child.mkdir()
    _migrate_with_baseline(memory_db)
    recorder = PerformanceRecorder(enabled=True)
    monkeypatch.setattr(recorder, "record", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()))

    listing = AssetService(DirectoryCache(memory_db), recorder).list_directory(tmp_path, tmp_path)

    assert [item.name for item in listing.items] == ["child"]


def test_asset_service_ignores_disabled_recorder(tmp_path, memory_db):
    from AssetsManager.application import AssetService
    from AssetsManager.core.directory_cache import DirectoryCache
    from AssetsManager.core.performance import PerformanceRecorder

    (tmp_path / "child").mkdir()
    _migrate_with_baseline(memory_db)
    recorder = PerformanceRecorder()

    AssetService(DirectoryCache(memory_db), recorder).list_directory(tmp_path, tmp_path)

    assert recorder.recent() == ()


def test_asset_service_records_directory_listing_first_screen(tmp_path):
    from AssetsManager.application import AssetService, DirectoryListOptions
    from AssetsManager.core.performance import PerformanceRecorder

    (tmp_path / "child").mkdir()
    (tmp_path / "asset.txt").write_text("data", encoding="utf-8")
    recorder = PerformanceRecorder(enabled=True)

    AssetService(performance_recorder=recorder, session_token="session-a").list_directory(
        tmp_path,
        tmp_path,
        DirectoryListOptions(scan_summaries=False),
    )

    event = next(event for event in recorder.recent() if event.name == "directory.list")
    assert event.elapsed_ms >= 0
    assert event.session_token == "session-a"
    assert event.path == str(tmp_path.resolve())
    assert event.attributes == {"outcome": "success", "item_count": 2, "scan_summaries": False}


def test_asset_service_ignores_listing_recorder_failure(tmp_path, monkeypatch):
    from AssetsManager.application import AssetService, DirectoryListOptions
    from AssetsManager.core.performance import PerformanceRecorder

    (tmp_path / "asset.txt").write_text("data", encoding="utf-8")
    recorder = PerformanceRecorder(enabled=True)
    monkeypatch.setattr(recorder, "record", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()))

    listing = AssetService(performance_recorder=recorder).list_directory(
        tmp_path, tmp_path, DirectoryListOptions(scan_summaries=False)
    )

    assert [item.name for item in listing.items] == ["asset.txt"]


def test_asset_service_records_failed_directory_listing_without_masking_error(tmp_path):
    from AssetsManager.application import AssetService
    from AssetsManager.core.performance import PerformanceRecorder

    recorder = PerformanceRecorder(enabled=True)
    outside = tmp_path.parent

    with pytest.raises(ValueError, match="under library_root"):
        AssetService(performance_recorder=recorder).list_directory(tmp_path, outside)

    event = recorder.recent()[0]
    assert event.name == "directory.list"
    assert event.attributes["outcome"] == "error"
    assert event.attributes["item_count"] == -1


def test_asset_service_records_summary_events_before_enclosing_listing(tmp_path, memory_db):
    from AssetsManager.application import AssetService
    from AssetsManager.core.directory_cache import DirectoryCache
    from AssetsManager.core.performance import PerformanceRecorder

    child = tmp_path / "child"
    child.mkdir()
    _migrate_with_baseline(memory_db)
    recorder = PerformanceRecorder(enabled=True)

    AssetService(DirectoryCache(memory_db), recorder, session_token="session-a").list_directory(
        tmp_path, tmp_path
    )

    events = recorder.recent()
    assert [event.name for event in events] == ["directory.summary", "directory.list"]
    assert all(event.session_token == "session-a" for event in events)
    assert events[0].path == str(child)
    assert events[1].path == str(tmp_path.resolve())


def test_asset_service_batches_summary_cache_misses_per_listing(tmp_path):
    from AssetsManager.application import AssetService

    class Cache:
        def __init__(self):
            self.set_calls = []
            self.batch_calls = []

        def get(self, _path, mtime=None):
            assert mtime is not None
            self.get_calls = getattr(self, "get_calls", 0) + 1
            return None

        def get_batch(self, _paths):
            self.batch_get_calls = getattr(self, "batch_get_calls", 0) + 1
            return {}

        def set(self, *entry):
            self.set_calls.append(entry)

        def set_batch(self, entries):
            self.batch_calls.append(entries)

    for name in ("one", "two"):
        child = tmp_path / name
        child.mkdir()
        (child / "asset.png").write_bytes(b"data")
    cache = Cache()

    listing = AssetService(directory_cache=cast(DirectoryCache, cache)).list_directory(tmp_path, tmp_path)

    assert [item.name for item in listing.items] == ["one", "two"]
    assert cache.set_calls == []
    assert len(cache.batch_calls) == 1
    assert cache.batch_get_calls == 1
    assert getattr(cache, "get_calls", 0) == 0
    assert {Path(entry[0]).name for entry in cache.batch_calls[0]} == {"one", "two"}


def test_asset_service_batch_lookup_mixes_hits_and_misses_without_per_entry_reads(tmp_path):
    from AssetsManager.application import AssetService
    from AssetsManager.core.directory_cache import DirCacheEntry

    hit = tmp_path / "hit"
    miss = tmp_path / "miss"
    hit.mkdir()
    miss.mkdir()
    (miss / "asset.png").write_bytes(b"data")

    class Cache:
        def __init__(self):
            self.get_calls = 0
            self.batch_writes = []

        def get_batch(self, paths):
            assert set(paths) == {str(hit), str(miss)}
            return {str(hit): DirCacheEntry(7, None, hit.stat().st_mtime, 0.0)}

        def get(self, *_args, **_kwargs):
            self.get_calls += 1
            return None

        def set_batch(self, entries):
            self.batch_writes.append(entries)

    cache = Cache()
    listing = AssetService(directory_cache=cast(DirectoryCache, cache)).list_directory(tmp_path, tmp_path)

    assert {item.name: item.item_count for item in listing.items} == {"hit": 7, "miss": 1}
    assert cache.get_calls == 0
    assert cache.batch_writes == [[(str(miss), 1, str(miss / "asset.png"), miss.stat().st_mtime)]]


def test_asset_service_batch_lookup_chunks_over_500_paths_without_per_entry_reads(tmp_path):
    from AssetsManager.application import AssetService

    for index in range(501):
        (tmp_path / f"directory-{index:03d}").mkdir()

    class Cache:
        def __init__(self):
            self.batch_calls = []
            self.get_calls = 0

        def get_batch(self, paths):
            self.batch_calls.append(paths)
            return {}

        def get(self, *_args, **_kwargs):
            self.get_calls += 1
            return None

        def set_batch(self, _entries):
            pass

    cache = Cache()
    AssetService(directory_cache=cast(DirectoryCache, cache)).list_directory(tmp_path, tmp_path)

    assert len(cache.batch_calls) == 1
    assert len(cache.batch_calls[0]) == 501
    assert cache.get_calls == 0


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("empty", "parent_path and 1-48 paths are required"),
        ("over_limit", "parent_path and 1-48 paths are required"),
        ("duplicate", "paths must be unique strings"),
        ("mixed_unhashable", "paths must be unique strings"),
    ],
)
def test_asset_service_validates_directory_summary_request_before_cache_access(
    tmp_path, case, message, monkeypatch,
):
    from AssetsManager.application import AssetService
    from AssetsManager.domain.errors import ValidationError

    class FailFastCache:
        def get_batch(self, _paths):
            raise AssertionError("invalid requests must not read the directory cache")

    def fail_scan(*_args, **_kwargs):
        raise AssertionError("invalid requests must not scan directories")

    import AssetsManager.application.asset_service as asset_service_module

    monkeypatch.setattr(asset_service_module, "_scan_dir_summary", fail_scan)
    service = AssetService(cast(DirectoryCache, FailFastCache()))

    if case == "empty":
        directories = []
    elif case == "over_limit":
        directories = [tmp_path / f"child-{i}" for i in range(49)]
    elif case == "duplicate":
        directories = [tmp_path / "child", tmp_path / "child"]
    else:
        directories = ["child", []]
    resolved_directories = [Path(directory) if isinstance(directory, str) else directory for directory in directories]
    with pytest.raises(ValidationError) as exc_info:
        service.summarize_directories(resolved_directories, parent=tmp_path)

    assert exc_info.value.message == message


@pytest.mark.parametrize(
    ("parent_setup", "directories", "message"),
    [
        ("file", ["child"], "Parent is not a directory"),
        ("directory", ["child/nested"], "paths must be direct child directories"),
        ("directory", ["missing"], "paths must be direct child directories"),
    ],
)
def test_asset_service_rejects_invalid_directory_summary_paths(
    tmp_path, parent_setup, directories, message,
):
    from AssetsManager.application import AssetService
    from AssetsManager.domain.errors import ValidationError

    parent = tmp_path / "projects"
    if parent_setup == "file":
        parent.write_text("not a directory", encoding="utf-8")
    else:
        parent.mkdir()
        (parent / "child" / "nested").mkdir(parents=True)

    resolved_directories = [parent / directory for directory in directories]
    with pytest.raises(ValidationError) as exc_info:
        AssetService().summarize_directories(resolved_directories, parent=parent)

    assert exc_info.value.message == message


def test_asset_service_summarizes_48_unique_direct_child_directories(tmp_path):
    from AssetsManager.application import AssetService

    parent = tmp_path / "projects"
    parent.mkdir()
    directories = []
    for index in range(48):
        directory = parent / f"project-{index}"
        directory.mkdir()
        (directory / "asset.txt").write_text("asset", encoding="utf-8")
        directories.append(directory)

    summaries = AssetService().summarize_directories(directories, parent=parent)

    assert len(summaries) == 48
    assert {Path(path).name for path in summaries} == {f"project-{i}" for i in range(48)}


def test_asset_service_keeps_legacy_directory_summary_signature(tmp_path):
    from AssetsManager.application import AssetService

    parent = tmp_path / "projects"
    child = parent / "child"
    child.mkdir(parents=True)
    (child / "asset.txt").write_text("asset", encoding="utf-8")

    service = AssetService()
    positional = service.summarize_directories([child])
    keyword = service.summarize_directories(directories=[child])

    expected = {str(child): (None, 1)}
    assert positional == expected
    assert keyword == expected


def test_asset_service_rejects_directory_cache_from_foreign_managed_library(tmp_path):
    from AssetsManager.application import AssetService
    from AssetsManager.core.database import DatabaseManager

    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    manager = DatabaseManager()
    try:
        cache = DirectoryCache(manager.connection_for(root_b))

        with pytest.raises(ValueError, match="different library root"):
            AssetService(directory_cache=cache).list_directory(root_a, root_a)
    finally:
        manager.close()


def test_canonical_asset_service_and_directory_cache_reject_after_session_close(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    root = tmp_path / "library"
    (root / "child").mkdir(parents=True)
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(root)
    asset_service = bootstrap.runtime_for(session).services.asset_service
    cache = asset_service._directory_cache
    assert cache is not None

    session.close()

    with pytest.raises(RuntimeError, match="closed LibrarySession"):
        asset_service.list_directory(root, root)
    with pytest.raises(RuntimeError, match="closed LibrarySession"):
        asset_service.summarize_directories([root / "child"], parent=root)
    with pytest.raises(RuntimeError, match="closed LibrarySession"):
        cache.get(str(root / "child"))
    with pytest.raises(RuntimeError, match="closed LibrarySession"):
        cache.set(str(root / "child"), 1, None, 0.0)
    with pytest.raises(RuntimeError, match="closed LibrarySession"):
        cache.validate_for(root)


def test_scan_dir_summary_skips_failing_entry_without_caching(tmp_path, monkeypatch):
    import AssetsManager.application.asset_service as asset_service_module
    from AssetsManager.application.asset_service import _scan_dir_summary

    child = tmp_path / "child"
    child.mkdir()
    # The failing entry must precede the first image: once a preview is found
    # the loop stops probing entry.is_file(), so the error is only exercised
    # while preview is still None.
    entries = [
        _FakeDirEntry("vanished.bin", str(child / "vanished.bin"), is_file_error=OSError(2, "vanished")),
        _FakeDirEntry("a.png", str(child / "a.png"), is_file=True),
        _FakeDirEntry("b.txt", str(child / "b.txt"), is_file=False),
    ]
    monkeypatch.setattr(asset_service_module.os, "scandir", lambda path: entries)

    class Cache:
        def get(self, *_args, **_kwargs):
            return None

        def set(self, *_args, **_kwargs):
            raise AssertionError("incomplete scans must not write the cache")

    cache_writes: list = []
    preview, count = _scan_dir_summary(child, cache=Cache(), cache_writes=cache_writes)

    assert count == 3
    assert preview == child / "a.png"
    assert cache_writes == []


def test_scan_dir_summary_skips_cache_write_when_scandir_fails(tmp_path, monkeypatch):
    import AssetsManager.application.asset_service as asset_service_module
    from AssetsManager.application.asset_service import _scan_dir_summary

    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.setattr(
        asset_service_module.os, "scandir", lambda path: (_ for _ in ()).throw(OSError(13, "denied"))
    )

    class Cache:
        def get(self, *_args, **_kwargs):
            return None

        def set(self, *_args, **_kwargs):
            raise AssertionError("incomplete scans must not write the cache")

    preview, count = _scan_dir_summary(child, cache=Cache(), cache_writes=[])

    assert preview is None
    assert count == 0


def test_list_directory_survives_entry_disappearing_mid_scan(tmp_path, monkeypatch):
    import AssetsManager.application.asset_service as asset_service_module
    from AssetsManager.application import AssetService

    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (tmp_path / "inner.txt").write_text("data", encoding="utf-8")

    entries = [
        _FakeDirEntry("vanished", str(tmp_path / "vanished"), is_dir_error=OSError(2, "vanished")),
        _FakeDirEntry("inner.txt", str(tmp_path / "inner.txt"), is_dir=False, is_file=True),
        _FakeDirEntry("subdir", str(subdir), is_dir=True),
    ]
    monkeypatch.setattr(asset_service_module.os, "scandir", lambda path: entries)

    class Cache:
        def __init__(self):
            self.get_batch_calls = []

        def get_batch(self, paths):
            self.get_batch_calls.append(paths)
            return {}

        def set_batch(self, _entries):
            pass

        def validate_for(self, _root):
            pass

    service = AssetService(directory_cache=cast(DirectoryCache, Cache()))
    listing = service.list_directory(tmp_path, tmp_path)

    assert sorted(item.name for item in listing.items) == ["inner.txt", "subdir"]
