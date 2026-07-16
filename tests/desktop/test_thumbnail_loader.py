import os
import threading

from PySide6.QtGui import QImage

from AssetsManager.panels.file_list._loader import ThumbnailLoader


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


def test_thumbnail_loader_stop_discards_late_results():
    img = QImage(1, 1, QImage.Format.Format_RGB32)
    loader = ThumbnailLoader()
    seen = []
    loader.thumbnail_ready.connect(lambda row, path, ready_img: seen.append((row, path, ready_img)))

    loader.stop()
    loader._on_image_loaded(1, "source.png", "item.png", img)

    assert seen == []
    assert "source.png" not in loader._cache


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
    loader._failed_paths.add("failed-old-runtime.png")
    loader._queued_keys.add("queued-old-runtime.png")
    loader._pending_items["queued-old-runtime.png"].append((1, "item.png"))
    monkeypatch.setattr(loader._pool, "clear", lambda: None)

    loader.invalidate_runtime()

    assert loader._cache == {}
    assert loader._failed_paths == set()
    assert loader._queued_keys == set()
    assert loader._pending_items == {}


def test_thumbnail_loader_invalidation_rejects_old_bake_cache_and_repository_writes(tmp_path):
    class Repository:
        def __init__(self):
            self.entries = []

        def upsert_entry(self, *args):
            self.entries.append(args)

    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    cache_dir = tmp_path / "cache"
    loader = ThumbnailLoader()
    loader.set_cache_dir(str(cache_dir))
    repository = Repository()
    loader._repo = repository
    runtime = loader._runtime()
    loader.invalidate_tasks()

    img = QImage(1, 1, QImage.Format.Format_RGB32)
    loader._store_baked_image("old", str(source), 96, img, runtime)

    assert not (cache_dir / "old.webp").exists()
    assert repository.entries == []


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


def test_old_thumbnail_runtime_quiesces_before_repository_close(tmp_path):
    loader = ThumbnailLoader()
    entered_repository = threading.Event()
    release_repository = threading.Event()
    repository_finished = threading.Event()

    class Repository:
        def get_source_mtime(self, key):
            entered_repository.set()
            assert release_repository.wait(5)
            repository_finished.set()
            return None

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    key = loader._disk_key(str(source))
    (cache_dir / f"{key}.webp").write_bytes(b"cached")
    loader.set_cache_dir(str(cache_dir))
    loader._repo = Repository()
    runtime = loader._runtime()

    class CacheTask:
        def run(self):
            loader._try_load_cached(key, str(source), runtime)

    loader._start_task(CacheTask(), runtime.generation)
    assert entered_repository.wait(5)
    invalidated = loader.invalidate_runtime()
    closed = threading.Event()
    closer = threading.Thread(
        target=lambda: (loader.wait_for_runtime(invalidated), closed.set())
    )
    closer.start()
    assert not closed.wait(0.2)
    release_repository.set()
    assert closed.wait(5)
    assert repository_finished.is_set()
    closer.join(5)
