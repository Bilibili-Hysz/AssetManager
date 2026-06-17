"""Tests for ThumbnailService."""

import io

import pytest

from AssetsManager.application.thumbnail_service import ThumbnailService, thumbnail_cache_key


def test_cache_key_deterministic(tmp_path):
    asset = tmp_path / "image.png"
    asset.write_bytes(b"fake png")

    svc = ThumbnailService()
    k1 = svc._cache_key(asset)
    k2 = svc._cache_key(asset)

    assert k1 == k2
    assert len(k1) == 16


def test_cache_key_changes_on_mtime(tmp_path):
    asset = tmp_path / "image.png"
    asset.write_bytes(b"v1")

    svc = ThumbnailService()
    k1 = svc._cache_key(asset)

    import time
    time.sleep(0.05)
    asset.write_bytes(b"v2")

    k2 = svc._cache_key(asset)
    assert k1 != k2


def test_resolve_finds_original_image(tmp_path):
    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"fake jpg")

    svc = ThumbnailService()
    result = svc.resolve(asset, tmp_path / "thumbs", max_size=256)

    assert result.found
    assert result.source_path == asset
    assert result.cache_hit is False


def test_resolve_returns_cache_hit(tmp_path):

    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"fake jpg")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()

    svc = ThumbnailService()
    cache_key = svc._cache_key(asset)
    cached = thumbs / f"{cache_key}.webp"
    cached.write_bytes(b"fake webp")

    result = svc.resolve(asset, thumbs, max_size=256)

    assert result.found
    assert result.source_path == cached
    assert result.cache_hit is True


def test_resolve_returns_not_found_for_non_image(tmp_path):
    asset = tmp_path / "readme.txt"
    asset.write_text("hello")

    svc = ThumbnailService()
    result = svc.resolve(asset, tmp_path / "thumbs", max_size=256)

    assert not result.found


def test_check_blur_returns_false_without_db(tmp_path):
    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"fake")

    svc = ThumbnailService()
    assert svc._check_blur(asset, {"nsfw"}, None) is False
    assert svc._check_blur(asset, None, None) is False


def test_process_image_returns_none_for_missing_file(tmp_path):
    svc = ThumbnailService()
    result = svc.process_image(tmp_path / "missing.jpg", max_size=256)
    assert result is None


def test_process_image_resizes_large_image(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    img = Image.new("RGB", (1024, 768), color="red")
    src = tmp_path / "large.png"
    img.save(src)

    svc = ThumbnailService()
    result = svc.process_image(src, max_size=256)

    assert result is not None
    data, mime = result
    assert mime == "image/webp"
    assert len(data) > 0

    out = Image.open(io.BytesIO(data))
    assert max(out.size) <= 256


def test_process_image_blur(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    img = Image.new("RGB", (64, 64), color="blue")
    src = tmp_path / "small.png"
    img.save(src)

    svc = ThumbnailService()
    result = svc.process_image(src, max_size=512, should_blur=True)

    assert result is not None
    data, mime = result
    assert mime == "image/webp"


def test_process_image_returns_none_for_non_image(tmp_path):
    src = tmp_path / "readme.txt"
    src.write_text("not an image")

    svc = ThumbnailService()
    result = svc.process_image(src, max_size=256)
    assert result is None


def test_thumbnail_cache_key_consistent_with_service(tmp_path):
    asset = tmp_path / "image.png"
    asset.write_bytes(b"fake png")

    svc = ThumbnailService()
    assert thumbnail_cache_key(asset) == svc._cache_key(asset)


def test_thumbnail_cache_key_deterministic(tmp_path):
    asset = tmp_path / "image.png"
    asset.write_bytes(b"fake png")

    k1 = thumbnail_cache_key(asset)
    k2 = thumbnail_cache_key(asset)
    assert k1 == k2
    assert len(k1) == 16


def test_thumbnail_cache_key_changes_on_mtime(tmp_path):
    asset = tmp_path / "image.png"
    asset.write_bytes(b"v1")
    k1 = thumbnail_cache_key(asset)

    import time
    time.sleep(0.05)
    asset.write_bytes(b"v2")
    k2 = thumbnail_cache_key(asset)

    assert k1 != k2
