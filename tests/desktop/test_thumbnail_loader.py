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
