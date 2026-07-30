from pathlib import Path

import pytest


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
    from AssetsManager.core.db_migrations import migrate

    child = tmp_path / "child"
    child.mkdir()
    (child / "asset.png").write_bytes(b"data")
    migrate(memory_db)
    recorder = PerformanceRecorder(enabled=True)
    service = AssetService(DirectoryCache(memory_db), recorder, session_token="session-a")

    service.list_directory(tmp_path, tmp_path)
    service.list_directory(tmp_path, tmp_path)

    events = [event for event in recorder.recent() if event.name == "directory.summary"]
    assert [event.attributes["cache_hit"] for event in events] == [False, True]
    assert all(event.path == str(child) and event.session_token == "session-a" for event in events)


def test_asset_service_records_stale_summary_cache_as_miss(tmp_path, memory_db):
    from AssetsManager.application import AssetService
    from AssetsManager.core.db_migrations import migrate
    from AssetsManager.core.directory_cache import DirectoryCache
    from AssetsManager.core.performance import PerformanceRecorder

    child = tmp_path / "child"
    child.mkdir()
    migrate(memory_db)
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
    from AssetsManager.core.db_migrations import migrate
    from AssetsManager.core.directory_cache import DirectoryCache
    from AssetsManager.core.performance import PerformanceRecorder

    child = tmp_path / "child"
    child.mkdir()
    migrate(memory_db)
    recorder = PerformanceRecorder(enabled=True)
    monkeypatch.setattr(recorder, "record", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()))

    listing = AssetService(DirectoryCache(memory_db), recorder).list_directory(tmp_path, tmp_path)

    assert [item.name for item in listing.items] == ["child"]


def test_asset_service_ignores_disabled_recorder(tmp_path, memory_db):
    from AssetsManager.application import AssetService
    from AssetsManager.core.db_migrations import migrate
    from AssetsManager.core.directory_cache import DirectoryCache
    from AssetsManager.core.performance import PerformanceRecorder

    (tmp_path / "child").mkdir()
    migrate(memory_db)
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
    from AssetsManager.core.db_migrations import migrate
    from AssetsManager.core.directory_cache import DirectoryCache
    from AssetsManager.core.performance import PerformanceRecorder

    child = tmp_path / "child"
    child.mkdir()
    migrate(memory_db)
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

    listing = AssetService(directory_cache=cache).list_directory(tmp_path, tmp_path)

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
    listing = AssetService(directory_cache=cache).list_directory(tmp_path, tmp_path)

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
    AssetService(directory_cache=cache).list_directory(tmp_path, tmp_path)

    assert len(cache.batch_calls) == 1
    assert len(cache.batch_calls[0]) == 501
    assert cache.get_calls == 0
