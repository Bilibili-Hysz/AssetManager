import os

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


def test_thumbnail_loader_invalidation_clears_queued_tasks(monkeypatch):
    loader = ThumbnailLoader()
    cleared = []
    monkeypatch.setattr(loader._pool, "clear", lambda: cleared.append(True))

    loader.invalidate_tasks()

    assert cleared == [True]


def test_thumbnail_loader_waits_for_running_tasks(monkeypatch):
    loader = ThumbnailLoader()
    waited = []
    monkeypatch.setattr(loader._pool, "waitForDone", lambda timeout: waited.append(timeout))

    loader.wait_for_tasks(250)

    assert waited == [250]


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
