import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from AssetsManager.core.performance import PerformanceRecorder
from AssetsManager.panels.file_list._loader import (
    FileIdentity,
    ThumbnailLoader,
    _VIDEO_FRAME_DEFERRED,
)


def test_thumbnail_loader_emits_item_path_for_cached_preview(tmp_path):
    source = tmp_path / "cover.png"
    source.write_bytes(b"not decoded for cache hit")
    item = tmp_path / "folder"
    item.mkdir()

    img = QImage(1, 1, QImage.Format.Format_RGB32)
    loader = ThumbnailLoader()
    loader._cache[str(source)] = (img, os.path.getmtime(source))

    seen = []
    loader.thumbnail_ready.connect(lambda row, path, ready_img: seen.append((row, path, ready_img)))

    loader.request(7, str(source), item_path=str(item))

    assert seen == [(7, str(item), img)]


def test_thumbnail_regeneration_reports_terminal_completion(tmp_path):
    source = tmp_path / "cover.png"
    source.write_bytes(b"not a decoded image")
    loader = ThumbnailLoader()
    loader.set_lib_root(str(tmp_path))
    completed = []

    loader.regenerate_all(str(tmp_path), on_complete=completed.append)

    deadline = time.monotonic() + 5
    while not completed and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    loader._pool.waitForDone(5000)

    assert completed == [1]


def test_thumbnail_regeneration_reports_rejected_admission():
    loader = ThumbnailLoader(max_admitted_tasks=1)
    runtime = loader._runtime()
    started = threading.Event()
    release = threading.Event()

    class _BlockingTask:
        def run(self):
            started.set()
            assert release.wait(5)

    assert loader._start_task(_BlockingTask(), runtime.generation, runtime=runtime)
    assert started.wait(5)
    completed = []

    assert not loader.regenerate_all("unused", on_complete=completed.append)

    release.set()
    loader._pool.waitForDone(5000)
    assert completed == [0]


def test_thumbnail_loader_records_memory_hit_with_session_and_generation(tmp_path):
    source = tmp_path / "cover.png"
    source.write_bytes(b"cached")
    image = QImage(1, 1, QImage.Format.Format_RGB32)
    recorder = PerformanceRecorder(enabled=True)
    loader = ThumbnailLoader()
    loader.set_performance_context(recorder, "session-a")
    loader._cache[str(source)] = (image, os.path.getmtime(source))

    loader.request(1, str(source))

    event = recorder.recent()[0]
    assert event.name == "thumbnail.cache"
    assert event.session_token == "session-a"
    assert event.generation == loader.runtime_generation
    assert event.path == str(source)
    assert event.attributes == {"tier": "memory", "outcome": "hit"}


def test_thumbnail_loader_records_queue_and_stale_discard(tmp_path):
    source = tmp_path / "cover.png"
    source.write_bytes(b"pending")
    recorder = PerformanceRecorder(enabled=True)
    loader = ThumbnailLoader()
    loader.set_performance_context(recorder, "session-a")
    runtime = loader._runtime()
    loader.invalidate_runtime()

    loader._on_image_loaded(1, str(source), str(source), QImage(1, 1, QImage.Format.Format_RGB32), runtime)

    event = recorder.recent()[-1]
    assert event.name == "thumbnail.load"
    assert event.session_token == "session-a"
    assert event.generation == runtime.generation
    assert event.attributes == {"outcome": "stale_discard"}


def test_thumbnail_loader_drain_records_invalidated_generation():
    recorder = PerformanceRecorder(enabled=True)
    loader = ThumbnailLoader()
    loader.set_performance_context(recorder, "session-a")
    generation = loader.invalidate_runtime()

    loader.wait_for_runtime(generation)

    event = recorder.recent()[-1]
    assert event.name == "thumbnail.drain"
    assert event.session_token == "session-a"
    assert event.generation == generation
    assert event.attributes == {"outcome": "completed"}


def test_thumbnail_loader_drain_keeps_old_session_attribution_during_rebind():
    recorder = PerformanceRecorder(enabled=True)
    loader = ThumbnailLoader()
    loader.set_performance_context(recorder, "session-old")
    started = threading.Event()
    release = threading.Event()

    class Task:
        def run(self):
            started.set()
            assert release.wait(5)

    runtime = loader._runtime()
    loader._start_task(Task(), runtime.generation, runtime=runtime)
    assert started.wait(5)
    generation = loader.invalidate_runtime()
    drained = threading.Event()
    waiter = threading.Thread(target=lambda: (loader.wait_for_runtime(generation), drained.set()))
    waiter.start()
    loader.set_performance_context(recorder, "session-new")
    release.set()
    assert drained.wait(5)
    waiter.join(5)
    loader._pool.waitForDone(5000)

    event = recorder.recent()[-1]
    assert event.name == "thumbnail.drain"
    assert event.session_token == "session-old"
    assert event.generation == generation


def test_thumbnail_loader_disabled_telemetry_does_not_read_clock(tmp_path, monkeypatch):
    from AssetsManager.panels.file_list import _loader

    source = tmp_path / "cover.png"
    source.write_bytes(b"cached")
    loader = ThumbnailLoader()
    loader._cache[str(source)] = (QImage(1, 1, QImage.Format.Format_RGB32), os.path.getmtime(source))
    monkeypatch.setattr(_loader, "perf_counter", lambda: (_ for _ in ()).throw(AssertionError()))

    loader.request(1, str(source))


def test_thumbnail_loader_stop_discards_late_results():
    img = QImage(1, 1, QImage.Format.Format_RGB32)
    loader = ThumbnailLoader()
    seen = []
    loader.thumbnail_ready.connect(lambda row, path, ready_img: seen.append((row, path, ready_img)))

    loader.stop()
    loader._on_image_loaded(1, "source.png", "item.png", img)

    assert seen == []
    assert "source.png" not in loader._cache


def test_thumbnail_loader_reads_completion_mtime_before_acquiring_state_lock(monkeypatch):
    loader = ThumbnailLoader()
    lock_held_during_stat = []

    def capture_mtime(_path):
        lock_held_during_stat.append(loader._mutex.tryLock())
        if lock_held_during_stat[-1]:
            loader._mutex.unlock()
        return 0.0

    monkeypatch.setattr(os.path, "getmtime", capture_mtime)

    loader._on_image_loaded(1, "source.png", "item.png", QImage(1, 1, QImage.Format.Format_RGB32))

    assert lock_held_during_stat == [True]


def test_thumbnail_loader_invalidation_discards_old_generation_completion():
    img = QImage(1, 1, QImage.Format.Format_RGB32)
    loader = ThumbnailLoader()
    seen = []
    loader.thumbnail_ready.connect(lambda row, path, ready_img: seen.append((row, path, ready_img)))

    generation = loader.runtime_generation
    loader.invalidate_tasks()
    loader._on_image_loaded(1, "source.png", "item.png", img, generation)

    assert seen == []
    assert "source.png" not in loader._cache


def test_thumbnail_loader_invalidation_returns_old_generation(monkeypatch):
    loader = ThumbnailLoader()
    monkeypatch.setattr(loader._pool, "clear", lambda: None)

    old_generation = loader.invalidate_tasks()

    assert old_generation == 0
    assert loader.runtime_generation == 1


def test_thumbnail_loader_runtime_invalidation_clears_memory_and_failed_paths(monkeypatch):
    loader = ThumbnailLoader()
    img = QImage(1, 1, QImage.Format.Format_RGB32)
    loader._cache["old-runtime.png"] = (img, 0.0)
    loader._failed_paths["failed-old-runtime.png"] = time.perf_counter()
    loader._queued_keys.add("queued-old-runtime.png")
    loader._pending_items["queued-old-runtime.png"].append((1, "item.png"))
    monkeypatch.setattr(loader._pool, "clear", lambda: None)

    loader.invalidate_runtime()

    assert loader._cache == {}
    assert loader._failed_paths == {}
    assert loader._queued_keys == set()
    assert loader._pending_items == {}


def test_thumbnail_loader_invalidation_rejects_old_bake_cache_and_service_writes(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    cache_dir = tmp_path / "cache"
    service = Mock()
    loader = ThumbnailLoader()
    loader.bind_runtime(service, str(cache_dir), str(tmp_path))
    runtime = loader._runtime()
    loader.invalidate_tasks()

    img = QImage(1, 1, QImage.Format.Format_RGB32)
    loader._store_baked_image("old", str(source), 96, img, runtime)

    assert not (cache_dir / "old.webp").exists()
    service.upsert_cache_metadata.assert_not_called()


def test_thumbnail_loader_emits_all_waiting_items_for_same_source(tmp_path):
    source = tmp_path / "cover.png"
    source.write_bytes(b"pending")
    first = tmp_path / "folder-a"
    second = tmp_path / "folder-b"
    first.mkdir()
    second.mkdir()

    img = QImage(1, 1, QImage.Format.Format_RGB32)
    loader = ThumbnailLoader()
    seen = []
    loader.thumbnail_ready.connect(lambda row, path, ready_img: seen.append((row, path, ready_img)))

    loader.request(1, str(source), item_path=str(first))
    loader.request(2, str(source), item_path=str(second))
    loader._on_image_loaded(1, str(source), str(first), img)

    assert seen == [(1, str(first), img), (2, str(second), img)]


def test_wait_for_runtime_waits_only_for_invalidated_generation(monkeypatch):
    loader = ThumbnailLoader()
    old_started = threading.Event()
    release_old = threading.Event()
    new_started = threading.Event()
    release_new = threading.Event()

    class Task:
        def __init__(self, started, release):
            self.started = started
            self.release = release

        def run(self):
            self.started.set()
            assert self.release.wait(5)

    old_runtime = loader._runtime()
    loader._start_task(Task(old_started, release_old), old_runtime.generation)
    assert old_started.wait(5)
    invalidated = loader.invalidate_runtime()
    new_runtime = loader._runtime()
    loader._start_task(Task(new_started, release_new), new_runtime.generation)
    assert new_started.wait(5)

    waited = threading.Event()
    waiter = threading.Thread(
        target=lambda: (loader.wait_for_runtime(invalidated), waited.set())
    )
    waiter.start()
    assert not waited.wait(0.2)
    release_old.set()
    assert waited.wait(5)
    assert not release_new.is_set()
    release_new.set()
    waiter.join(5)
    loader._pool.waitForDone(5000)


def test_old_thumbnail_runtime_quiesces_before_thumbnail_service_close(tmp_path):
    loader = ThumbnailLoader()
    entered_service = threading.Event()
    release_service = threading.Event()
    service_finished = threading.Event()

    service = Mock()
    def get_mtime(_root, _key):
        entered_service.set()
        assert release_service.wait(5)
        service_finished.set()
        return None
    service.get_cached_source_mtime.side_effect = get_mtime

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    key = loader._disk_key(str(source))
    (cache_dir / f"{key}.webp").write_bytes(b"cached")
    loader.bind_runtime(service, str(cache_dir), str(tmp_path))
    runtime = loader._runtime()

    class CacheTask:
        def run(self):
            loader._try_load_cached(key, str(source), runtime)

    loader._start_task(CacheTask(), runtime.generation)
    assert entered_service.wait(5)
    invalidated = loader.invalidate_runtime()
    closed = threading.Event()
    closer = threading.Thread(
        target=lambda: (loader.wait_for_runtime(invalidated), closed.set())
    )
    closer.start()
    assert not closed.wait(0.2)
    release_service.set()
    assert closed.wait(5)
    assert service_finished.is_set()
    closer.join(5)


def test_thumbnail_loader_orphan_cleanup_uses_thumbnail_service(tmp_path):
    loader = ThumbnailLoader()
    service = Mock()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    orphan_source = tmp_path / "missing" / "source.png"
    key = loader._disk_key(str(orphan_source))
    cached_file = cache_dir / f"{key}.webp"
    cached_file.write_bytes(b"cached")
    service.list_cache_metadata.return_value = [(key, str(orphan_source), 1.0)]

    loader.bind_runtime(service, str(cache_dir), str(tmp_path))
    loader.orphan_cleanup()

    assert not cached_file.exists()
    service.delete_cache_metadata.assert_called_once_with(str(tmp_path.resolve()), key)


def test_thumbnail_loader_clear_thumb_cache_uses_service_and_disk_runtime(tmp_path):
    loader = ThumbnailLoader()
    service = Mock()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    webp = cache_dir / "one.webp"
    temp = cache_dir / "two.webp.tmp"
    jpg = cache_dir / "three.jpg"
    keep = cache_dir / "keep.txt"
    webp.write_bytes(b"one")
    temp.write_bytes(b"two")
    jpg.write_bytes(b"three")
    keep.write_text("keep", encoding="utf-8")

    loader.bind_runtime(service, str(cache_dir), str(tmp_path))
    assert loader.clear_thumb_cache() == 3

    assert not webp.exists()
    assert not temp.exists()
    assert not jpg.exists()
    assert keep.exists()
    service.clear_cache_metadata.assert_called_once_with(str(tmp_path.resolve()))


def test_thumbnail_loader_bind_publishes_complete_runtime_before_drain(monkeypatch, tmp_path):
    loader = ThumbnailLoader()
    service = Mock()
    observed = {}

    def capture_wait(generation):
        observed["generation"] = generation
        observed["runtime"] = loader._runtime()

    monkeypatch.setattr(loader, "wait_for_runtime", capture_wait)
    loader.bind_runtime(service, str(tmp_path / "cache"), str(tmp_path))

    runtime = observed["runtime"]
    assert runtime.generation == observed["generation"] + 1
    assert runtime.thumbnail_service is service
    assert runtime.cache_dir == str(tmp_path / "cache")
    assert runtime.lib_root == str(tmp_path.resolve())


def test_thumbnail_loader_cache_clear_rejects_old_bake_runtime(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    cache_dir = tmp_path / "cache"
    service = Mock()
    loader = ThumbnailLoader()
    loader.bind_runtime(service, str(cache_dir), str(tmp_path))
    runtime = loader._runtime()

    loader.clear_thumb_cache()
    loader._store_baked_image(
        "old", str(source), 96,
        QImage(1, 1, QImage.Format.Format_RGB32), runtime,
    )

    assert not (cache_dir / "old.webp").exists()
    service.upsert_cache_metadata.assert_not_called()


def test_thumbnail_loader_clear_cache_drops_pending_items():
    loader = ThumbnailLoader()
    loader._pending_items["source.png"].append((1, "old-item.png"))

    loader.clear_cache()

    assert loader._pending_items == {}


def test_thumbnail_loader_wait_releases_invalidated_runtime_snapshot():
    loader = ThumbnailLoader()
    generation = loader.invalidate_runtime()

    loader.wait_for_runtime(generation)

    assert generation not in loader._invalidated_runtimes


def test_thumbnail_loader_orphan_cleanup_removes_missing_source_with_existing_parent(tmp_path):
    loader = ThumbnailLoader()
    service = Mock()
    assets = tmp_path / "assets"
    assets.mkdir()
    source = assets / "deleted.png"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    key = loader._disk_key(str(source))
    cached_file = cache_dir / f"{key}.webp"
    cached_file.write_bytes(b"cached")
    service.list_cache_metadata.return_value = [(key, str(source), 1.0)]

    loader.bind_runtime(service, str(cache_dir), str(tmp_path))
    loader.orphan_cleanup()

    assert not cached_file.exists()
    service.delete_cache_metadata.assert_called_once_with(str(tmp_path.resolve()), key)

def test_thumbnail_loader_defers_unique_request_at_capacity_and_retries(tmp_path, monkeypatch):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    loader = ThumbnailLoader(max_admitted_tasks=1)
    started = threading.Event()
    release = threading.Event()

    def blocking_load(path, _runtime):
        if path == str(first):
            started.set()
            assert release.wait(5)
        return None

    monkeypatch.setattr(loader, "_load_image", blocking_load)
    loader.request(1, str(first))
    assert started.wait(5)

    loader.request(2, str(second))

    assert str(second) in loader._queued_keys
    assert str(second) in loader._pending_items
    assert str(second) in loader._deferred_loads
    release.set()
    loader._pool.waitForDone(5000)
    loader._pool.waitForDone(5000)
    assert str(second) in loader._failed_paths


def test_thumbnail_loader_duplicate_fanout_remains_admitted_at_capacity(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    loader = ThumbnailLoader(max_admitted_tasks=1)
    started = threading.Event()
    release = threading.Event()
    image = QImage(2, 2, QImage.Format.Format_RGBA8888)
    seen = []
    loader.thumbnail_ready.connect(lambda row, path, ready: seen.append((row, path, ready)))

    def blocking_load(_path, _runtime):
        started.set()
        assert release.wait(5)
        return image

    monkeypatch.setattr(loader, "_load_image", blocking_load)
    loader.request(1, str(source), item_path="first")
    assert started.wait(5)
    loader.request(2, str(source), item_path="second")
    assert loader._pending_items[str(source)] == [(1, "first"), (2, "second")]

    release.set()
    loader._pool.waitForDone(5000)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    assert [(row, path) for row, path, _ in seen] == [(1, "first"), (2, "second")]


def test_thumbnail_loader_capacity_is_loader_wide_across_generations():
    loader = ThumbnailLoader(max_admitted_tasks=1)
    started = threading.Event()
    release = threading.Event()

    class Task:
        def run(self):
            started.set()
            assert release.wait(5)

    old_runtime = loader._runtime()
    assert loader._start_task(Task(), old_runtime.generation, runtime=old_runtime)
    assert started.wait(5)
    loader.invalidate_runtime()
    new_runtime = loader._runtime()
    assert not loader._start_task(Task(), new_runtime.generation, runtime=new_runtime)
    release.set()
    loader._pool.waitForDone(5000)


def test_thumbnail_loader_bounds_deferred_unique_requests(tmp_path, monkeypatch):
    paths = [tmp_path / f"{index}.png" for index in range(3)]
    for path in paths:
        path.write_bytes(b"source")
    loader = ThumbnailLoader(max_admitted_tasks=1, max_deferred_loads=1)
    started = threading.Event()
    release = threading.Event()

    def blocking_load(path, _runtime):
        if path == str(paths[0]):
            started.set()
            assert release.wait(5)
        return None

    monkeypatch.setattr(loader, "_load_image", blocking_load)
    loader.request(1, str(paths[0]))
    assert started.wait(5)
    loader.request(2, str(paths[1]))
    loader.request(3, str(paths[2]))

    assert list(loader._deferred_loads) == [str(paths[1])]
    assert str(paths[2]) not in loader._queued_keys
    assert str(paths[2]) not in loader._pending_items
    release.set()
    loader._pool.waitForDone(5000)


def test_thumbnail_loader_resize_clears_deferred_requests(tmp_path, monkeypatch):
    paths = [tmp_path / f"{index}.png" for index in range(2)]
    for path in paths:
        path.write_bytes(b"source")
    loader = ThumbnailLoader(max_admitted_tasks=1)
    started = threading.Event()
    release = threading.Event()

    def blocking_load(path, _runtime):
        if path == str(paths[0]):
            started.set()
            assert release.wait(5)
        return None

    monkeypatch.setattr(loader, "_load_image", blocking_load)
    loader.request(1, str(paths[0]))
    assert started.wait(5)
    loader.request(2, str(paths[1]))
    assert str(paths[1]) in loader._deferred_loads

    loader.set_size(128)
    assert loader._deferred_loads == {}
    assert loader._pending_items == {}
    release.set()
    loader._pool.waitForDone(5000)


def test_thumbnail_loader_discards_deferred_paths_outside_viewport(tmp_path):
    loader = ThumbnailLoader()
    runtime = loader._runtime()
    first = str(tmp_path / "old-visible.png")
    second = str(tmp_path / "current-visible.png")
    task = object()
    loader._deferred_loads = {
        first: (task, runtime, 1),
        second: (task, runtime, 1),
    }
    loader._queued_keys = {first, second}
    loader._queued_generations = {first: runtime.generation, second: runtime.generation}
    loader._pending_items[first].append((1, first))
    loader._pending_items[second].append((2, second))

    loader.retain_deferred({second})

    assert list(loader._deferred_loads) == [second]
    assert loader._queued_keys == {second}
    assert dict(loader._pending_items) == {second: [(2, second)]}


def test_thumbnail_loader_invalidation_wakes_capacity_waiter():
    loader = ThumbnailLoader(max_admitted_tasks=2)
    started = threading.Barrier(3)
    waiting = threading.Event()
    released = threading.Event()
    runtime = loader._runtime()

    class Task:
        def run(self):
            started.wait(5)
            assert released.wait(5)

    assert loader._start_task(Task(), runtime.generation, runtime=runtime)
    assert loader._start_task(Task(), runtime.generation, runtime=runtime)
    started.wait(5)

    def wait_for_capacity():
        waiting.set()
        return loader._wait_for_task_capacity(runtime)

    result = []
    waiter = threading.Thread(target=lambda: result.append(wait_for_capacity()))
    waiter.start()
    assert waiting.wait(5)
    loader.invalidate_runtime()
    waiter.join(5)
    assert result == [False]
    released.set()
    loader._pool.waitForDone(5000)


def test_thumbnail_loader_evicts_memory_cache_by_lru_bytes(tmp_path):
    paths = [tmp_path / f"{name}.png" for name in ("a", "b", "c")]
    for path in paths:
        path.write_bytes(b"source")
    image = QImage(10, 10, QImage.Format.Format_RGBA8888)
    budget = image.sizeInBytes() * 2
    loader = ThumbnailLoader(max_cache_bytes=budget)

    for path in paths[:2]:
        loader._on_image_loaded(1, str(path), str(path), image)
    loader.request(1, str(paths[0]))  # Mark A as most recently used.
    loader._on_image_loaded(1, str(paths[2]), str(paths[2]), image)

    assert list(loader._cache) == [str(paths[0]), str(paths[2])]
    assert loader._cache_bytes == budget


def test_thumbnail_loader_oversize_image_is_delivered_but_not_cached(tmp_path):
    source = tmp_path / "large.png"
    source.write_bytes(b"source")
    image = QImage(10, 10, QImage.Format.Format_RGBA8888)
    loader = ThumbnailLoader(max_cache_bytes=image.sizeInBytes() - 1)
    seen = []
    loader.thumbnail_ready.connect(lambda row, path, ready: seen.append((row, path, ready)))

    loader._on_image_loaded(1, str(source), "item", image)

    assert seen == [(1, "item", image)]
    assert str(source) not in loader._cache
    assert loader._cache_bytes == 0


def test_thumbnail_loader_capacity_rejection_records_bounded_telemetry(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    recorder = PerformanceRecorder(enabled=True)
    loader = ThumbnailLoader(max_admitted_tasks=1)
    loader.set_performance_context(recorder, "session-a")
    started = threading.Event()
    release = threading.Event()

    class Task:
        def run(self):
            started.set()
            assert release.wait(5)

    runtime = loader._runtime()
    assert loader._start_task(Task(), runtime.generation, runtime=runtime)
    assert started.wait(5)
    assert not loader._start_task(Task(), runtime.generation, runtime=runtime)
    event = recorder.recent()[-1]
    assert event.name == "thumbnail.queue"
    assert event.session_token == "session-a"
    assert event.generation == runtime.generation
    assert event.attributes == {"outcome": "capacity_rejected", "queue_depth": 1, "queue_capacity": 1}
    release.set()
    loader._pool.waitForDone(5000)


def test_thumbnail_loader_cache_accounting_resets_on_clear_resize_and_invalidation(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    image = QImage(10, 10, QImage.Format.Format_RGBA8888)
    loader = ThumbnailLoader(max_cache_bytes=image.sizeInBytes() * 2)

    loader._on_image_loaded(1, str(source), str(source), image)
    assert loader._cache_bytes == image.sizeInBytes()
    loader.clear_cache()
    assert loader._cache_bytes == 0
    loader._on_image_loaded(1, str(source), str(source), image)
    loader.set_size(128)
    assert loader._cache_bytes == 0
    loader._on_image_loaded(1, str(source), str(source), image)
    loader.invalidate_runtime()
    assert loader._cache_bytes == 0


def test_thumbnail_loader_invalid_recorder_context_is_ignored():
    loader = ThumbnailLoader()

    class _BrokenRecorder:
        @property
        def enabled(self):
            raise RuntimeError()

    loader.set_performance_context(_BrokenRecorder(), "session-a")

    assert loader._performance_recorder is None


def test_thumbnail_loader_visible_duplicate_promotes_deferred_prefetch(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    loader = ThumbnailLoader(max_admitted_tasks=1)
    runtime = loader._runtime()
    task = object()
    loader._queued_keys.add(str(source))
    loader._queued_generations[str(source)] = runtime.generation
    loader._pending_items[str(source)].append((1, "prefetch"))
    loader._deferred_loads[str(source)] = (task, runtime, 0)

    loader.request(2, str(source), priority=0, item_path="visible")

    promoted_task, promoted_runtime, priority = loader._deferred_loads[str(source)]
    assert (promoted_task, promoted_runtime, priority) == (task, runtime, 1)
    assert loader._pending_items[str(source)] == [(1, "prefetch"), (2, "visible")]


def test_thumbnail_loader_visible_request_displaces_deferred_prefetch_at_capacity(tmp_path, monkeypatch):
    paths = [tmp_path / f"{name}.png" for name in ("active", "prefetch", "visible")]
    for path in paths:
        path.write_bytes(b"source")
    loader = ThumbnailLoader(max_admitted_tasks=1, max_deferred_loads=1)
    started = threading.Event()
    release = threading.Event()

    def blocking_load(path, _runtime):
        if path == str(paths[0]):
            started.set()
            assert release.wait(5)
        return None

    monkeypatch.setattr(loader, "_load_image", blocking_load)
    loader.request(1, str(paths[0]), priority=0)
    assert started.wait(5)
    loader.request(2, str(paths[1]), priority=1)
    loader.request(3, str(paths[2]), priority=0)

    assert list(loader._deferred_loads) == [str(paths[2])]
    assert str(paths[1]) not in loader._queued_keys
    assert str(paths[1]) not in loader._pending_items
    release.set()
    loader._pool.waitForDone(5000)


def test_thumbnail_loader_image_decodes_captured_body_without_reopening_source(tmp_path, monkeypatch):
    source = tmp_path / "photo.png"
    image = QImage(24, 12, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    assert image.save(str(source), "PNG")
    loader = ThumbnailLoader()
    runtime = loader._runtime()
    original = source.read_bytes()

    def capture_snapshot(_path, _runtime):
        identity = FileIdentity.from_stat(source.stat())
        source.unlink()
        return original, identity

    monkeypatch.setattr(loader, "_snapshot_source", capture_snapshot)
    decoded = loader._load_image(str(source), runtime)
    assert decoded is not None and not decoded.isNull()
    assert (decoded.width(), decoded.height()) == (24, 12)


def test_thumbnail_loader_cache_completion_uses_snapshot_identity(tmp_path):
    source = tmp_path / "photo.png"
    source.write_bytes(b"captured")
    loader = ThumbnailLoader()
    runtime = loader._runtime()
    identity = FileIdentity.from_stat(source.stat())
    image = QImage(2, 2, QImage.Format.Format_RGB32)
    loader._source_identities[str(source)] = identity
    loader._on_image_loaded(1, str(source), str(source), image, runtime)
    assert loader._source_identities[str(source)] == identity


def test_thumbnail_loader_reads_legacy_webp_cache_after_key_versioning(tmp_path):
    from AssetsManager.core.thumbnail_key import legacy_thumbnail_cache_key

    source = tmp_path / "photo.png"
    image = QImage(16, 8, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    assert image.save(str(source), "PNG")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cached = cache_dir / f"{legacy_thumbnail_cache_key(source)}.webp"
    assert image.save(str(cached), "WEBP")

    loader = ThumbnailLoader()
    loader.bind_runtime(Mock(), str(cache_dir), str(tmp_path))

    loaded = loader._load_image(str(source), loader._runtime())

    assert loaded is not None and not loaded.isNull()


def test_thumbnail_loader_rejects_profile_insufficient_cache(tmp_path, monkeypatch):
    source = tmp_path / "photo.png"
    image = QImage(256, 128, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    assert image.save(str(source), "PNG")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    loader = ThumbnailLoader(size=96)
    key = loader._disk_key(str(source))
    cached = cache_dir / f"{key}.webp"
    assert image.save(str(cached), "WEBP")
    service = Mock()
    service.get_cache_metadata.return_value = SimpleNamespace(
        source_mtime=os.path.getmtime(source),
        source_mtime_ns=None,
        source_size=source.stat().st_size,
        baked_size=256,
        artifact_kind="webp",
    )
    loader.bind_runtime(service, str(cache_dir), str(tmp_path))
    monkeypatch.setattr("AssetsManager.panels.file_list._loader.get_bake_size", lambda: 512)

    assert loader._try_load_cached(key, str(source), loader._runtime(), bake_size=512) is None
    assert cached.exists()
    service.delete_cache_metadata.assert_not_called()


def test_thumbnail_loader_admission_uses_loader_size(tmp_path, monkeypatch):
    source = tmp_path / "photo.png"
    image = QImage(512, 256, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    assert image.save(str(source), "PNG")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    loader = ThumbnailLoader(size=512)
    key = loader._disk_key(str(source))
    cached = cache_dir / f"{key}.webp"
    assert image.save(str(cached), "WEBP")
    service = Mock()
    service.get_cache_metadata.return_value = SimpleNamespace(
        source_mtime=os.path.getmtime(source), source_mtime_ns=None,
        source_size=source.stat().st_size, baked_size=256, artifact_kind="webp",
    )
    loader.bind_runtime(service, str(cache_dir), str(tmp_path))
    monkeypatch.setattr("AssetsManager.panels.file_list._loader.get_bake_size", lambda: 256)

    assert loader._try_load_cached(key, str(source), loader._runtime(), bake_size=256) is None
    assert cached.exists()


def test_thumbnail_loader_compatible_profile_cache_hits(tmp_path, monkeypatch):
    source = tmp_path / "photo.png"
    image = QImage(512, 256, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    assert image.save(str(source), "PNG")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    loader = ThumbnailLoader(size=96)
    key = loader._disk_key(str(source))
    cached = cache_dir / f"{key}.webp"
    assert image.save(str(cached), "WEBP")
    service = Mock()
    service.get_cache_metadata.return_value = SimpleNamespace(
        source_mtime=os.path.getmtime(source), source_mtime_ns=None,
        source_size=source.stat().st_size, baked_size=512, artifact_kind="webp",
    )
    loader.bind_runtime(service, str(cache_dir), str(tmp_path))
    monkeypatch.setattr("AssetsManager.panels.file_list._loader.get_bake_size", lambda: 256)

    loaded = loader._try_load_cached(key, str(source), loader._runtime(), bake_size=256)
    assert loaded is not None and not loaded.isNull()


def test_thumbnail_loader_missing_metadata_uses_artifact_dimensions(tmp_path, monkeypatch):
    source = tmp_path / "photo.png"
    image = QImage(512, 256, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    assert image.save(str(source), "PNG")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    loader = ThumbnailLoader(size=96)
    key = loader._disk_key(str(source))
    cached = cache_dir / f"{key}.webp"
    assert image.save(str(cached), "WEBP")
    service = Mock()
    service.get_cache_metadata.return_value = None
    loader.bind_runtime(service, str(cache_dir), str(tmp_path))
    monkeypatch.setattr("AssetsManager.panels.file_list._loader.get_bake_size", lambda: 512)

    assert loader._try_load_cached(key, str(source), loader._runtime(), bake_size=512) is not None
    service.upsert_cache_metadata.assert_not_called()


def test_thumbnail_loader_wrong_artifact_kind_is_cache_miss(tmp_path, monkeypatch):
    source = tmp_path / "photo.png"
    image = QImage(512, 256, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    assert image.save(str(source), "PNG")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    loader = ThumbnailLoader(size=96)
    key = loader._disk_key(str(source))
    cached = cache_dir / f"{key}.webp"
    assert image.save(str(cached), "WEBP")
    service = Mock()
    service.get_cache_metadata.return_value = SimpleNamespace(
        source_mtime=os.path.getmtime(source), source_mtime_ns=None,
        source_size=source.stat().st_size, baked_size=512, artifact_kind="jpg",
    )
    loader.bind_runtime(service, str(cache_dir), str(tmp_path))
    monkeypatch.setattr("AssetsManager.panels.file_list._loader.get_bake_size", lambda: 512)

    assert loader._try_load_cached(key, str(source), loader._runtime(), bake_size=512) is None
    assert cached.exists()


def test_thumbnail_loader_video_reads_existing_cached_frame(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not a real video")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    frame = tmp_path / "frame.jpg"
    frame_img = QImage(16, 12, QImage.Format.Format_RGB32)
    frame_img.fill(0xFF336699)
    assert frame_img.save(str(frame), "JPG")

    loader = ThumbnailLoader()
    cache_key = loader._disk_key(str(video))
    (cache_dir / f"{cache_key}.jpg").write_bytes(frame.read_bytes())

    service = Mock()
    loader.bind_runtime(service, str(cache_dir), str(tmp_path))
    runtime = loader._runtime()

    img = loader._load_image(str(video), runtime)

    assert img is not None and not img.isNull()
    assert (img.size().width(), img.size().height()) == (16, 12)
    # The cached frame is served directly; ffmpeg extraction is never needed.
    service.resolve.assert_not_called()


def test_thumbnail_loader_video_returns_none_when_service_missing(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not a real video")

    loader = ThumbnailLoader()
    runtime = loader._runtime()

    assert loader._load_image(str(video), runtime) is None


def test_video_extraction_runs_on_dedicated_ffmpeg_pool_and_does_not_block_images(
    tmp_path, monkeypatch
):
    from AssetsManager.application.thumbnail_service import ThumbnailService
    from AssetsManager.panels.file_list._loader import ffmpeg_pool

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not a real video")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    started = threading.Event()
    release = threading.Event()

    def fake_extract(body, suffix, destination):
        assert body == b"not a real video"
        assert suffix == ".mp4"
        started.set()
        assert release.wait(5)
        frame_img = QImage(16, 12, QImage.Format.Format_RGB32)
        frame_img.fill(0xFF336699)
        frame_img.save(str(destination), "JPG")
        return True

    monkeypatch.setattr(
        ThumbnailService, "_extract_video_frame_from_bytes", staticmethod(fake_extract)
    )

    loader = ThumbnailLoader()
    loader.bind_runtime(Mock(), str(cache_dir), str(tmp_path))
    app = QApplication.instance()

    def wait_for(event, timeout=5.0):
        deadline = time.monotonic() + timeout
        while not event.is_set() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        return event.is_set()

    # A missing video frame defers immediately and runs on the dedicated pool.
    runtime = loader._runtime()
    video_ready = threading.Event()
    loader.thumbnail_ready.connect(
        lambda _row, path, _img: video_ready.set() if path == str(video) else None
    )
    assert loader._load_image(str(video), runtime) is _VIDEO_FRAME_DEFERRED
    assert started.wait(5)
    assert ffmpeg_pool.activeThreadCount() >= 1

    # While ffmpeg is blocked, a concurrent image thumbnail is still serviced
    # by the loader pool — the slow video cannot starve image loading.
    image = tmp_path / "photo.png"
    image_pix = QImage(8, 8, QImage.Format.Format_RGB32)
    image_pix.fill(0xFF00FF00)
    assert image_pix.save(str(image), "PNG")
    image_ready = threading.Event()
    loader.thumbnail_ready.connect(
        lambda _row, path, _img: image_ready.set() if path == str(image) else None
    )
    loader.request(2, str(image))
    assert wait_for(image_ready)

    # Release extraction: the frame is picked up and delivered async.
    release.set()
    assert wait_for(video_ready)
    loader._pool.waitForDone(5000)
    ffmpeg_pool.waitForDone(5000)


# ── Background thumbnail cache clear ────────────────────────────


def test_clear_thumb_cache_detailed_counts_failures(monkeypatch, tmp_path):
    loader = ThumbnailLoader()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "a.webp").write_bytes(b"a")
    (cache_dir / "b.webp.tmp").write_bytes(b"b")
    (cache_dir / "keep.txt").write_bytes(b"k")
    loader.set_cache_dir(str(cache_dir))

    real_remove = os.remove

    def _flaky_remove(path, *args, **kwargs):
        if str(path).endswith("b.webp.tmp"):
            raise OSError("locked")
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr("AssetsManager.panels.file_list._loader.os.remove", _flaky_remove)

    progress = []
    removed, failed = loader.clear_thumb_cache_detailed(
        on_progress=lambda done, total: progress.append((done, total))
    )

    assert (removed, failed) == (1, 1)
    assert not (cache_dir / "a.webp").exists()
    assert (cache_dir / "keep.txt").exists()
    assert progress[-1] == (2, 2)


def test_clear_thumb_cache_async_reports_counts_from_worker_thread(
    monkeypatch, tmp_path
):
    loader = ThumbnailLoader()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "one.webp").write_bytes(b"one")
    (cache_dir / "two.jpg").write_bytes(b"two")
    (cache_dir / "bad.webp").write_bytes(b"bad")
    loader.set_cache_dir(str(cache_dir))

    real_remove = os.remove

    def _flaky_remove(path, *args, **kwargs):
        if str(path).endswith("bad.webp"):
            raise OSError("locked")
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr("AssetsManager.panels.file_list._loader.os.remove", _flaky_remove)

    main_thread = threading.current_thread()
    seen = {}
    done = threading.Event()

    def on_progress(done_count, total):
        seen.setdefault("progress", []).append(
            (done_count, total, threading.current_thread())
        )

    def on_complete(removed, failed):
        seen["removed"] = removed
        seen["failed"] = failed
        seen["thread"] = threading.current_thread()
        done.set()

    assert loader.clear_thumb_cache_async(
        on_progress=on_progress, on_complete=on_complete
    ) is True

    assert done.wait(5.0)
    assert seen["removed"] == 2
    assert seen["failed"] == 1
    # The removal loop and the completion callback run off the GUI thread.
    assert seen["thread"] is not main_thread
    assert seen["progress"] and seen["progress"][-1][:2] == (3, 3)


def test_clear_thumb_cache_async_reports_completion_when_not_admitted():
    loader = ThumbnailLoader(max_admitted_tasks=1)
    loader._active_tasks[0] = 1  # occupy the single admission slot

    completions = []
    admitted = loader.clear_thumb_cache_async(
        on_complete=lambda removed, failed: completions.append((removed, failed))
    )

    assert admitted is False
    # A non-admitted clear still reports completion so the caller's
    # progress UI resets instead of waiting forever.
    assert completions == [(0, 0)]


def test_thumbnail_loader_failed_cooldown_suppresses_then_allows_retry(tmp_path, monkeypatch):
    source = tmp_path / "broken.png"
    source.write_bytes(b"not a decodable image")
    loader = ThumbnailLoader()
    attempts: list[str] = []

    def failing_load(path, _runtime):
        attempts.append(path)
        return None

    monkeypatch.setattr(loader, "_load_image", failing_load)
    failures: list[str] = []
    loader.thumbnail_failed.connect(failures.append)

    loader.request(0, str(source))
    assert loader._pool.waitForDone(5000)
    assert attempts == [str(source)]
    # Failure is delivered to the UI thread (danger marker) instead of being
    # silently swallowed.  The emit crosses threads, so pump the loop for the
    # queued delivery before asserting.
    app = QApplication.instance() or QApplication([])
    app.processEvents()
    assert failures == [str(source)]
    assert loader.is_failed(str(source))

    # Inside the cooldown the re-request is suppressed without a new load.
    loader.request(0, str(source))
    assert loader._pool.waitForDone(5000)
    assert attempts == [str(source)]

    # Once the cooldown elapses the request is admitted again.
    loader._failed_paths[str(source)] = time.perf_counter() - 61.0
    loader.request(0, str(source))
    assert loader._pool.waitForDone(5000)
    assert attempts == [str(source), str(source)]


def test_thumbnail_loader_failed_capacity_evicts_oldest_entry():
    loader = ThumbnailLoader()
    loader._failed_paths_max = 3
    for i in range(3):
        loader._mark_failed(f"old{i}.png", 0)
    loader._mark_failed("new.png", 0)

    # Oldest entry evicted only; the remaining cooldown semantics survive
    # (the old wholesale clear() re-admitted every known-bad path at once).
    assert len(loader._failed_paths) == 3
    assert "old0.png" not in loader._failed_paths
    assert "old1.png" in loader._failed_paths
    assert "old2.png" in loader._failed_paths
    assert "new.png" in loader._failed_paths


def test_thumbnail_loader_clear_cache_resets_cooldown():
    loader = ThumbnailLoader()
    loader._mark_failed("broken.png", 0)
    assert loader.is_failed("broken.png")

    # Manual refresh (clear_cache) bypasses the cooldown: immediate retry.
    loader.clear_cache()
    assert not loader.is_failed("broken.png")


def test_thumbnail_loader_failure_stale_generation_is_dropped_and_not_emitted():
    loader = ThumbnailLoader()
    loader.invalidate_runtime()  # current generation becomes 1
    failures: list[str] = []
    loader.thumbnail_failed.connect(failures.append)

    loader._mark_failed("stale.png", 0)  # runtime from the old generation

    assert failures == []
    assert "stale.png" not in loader._failed_paths
