"""Tests for ThumbnailService."""

import io
import sqlite3

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


def test_check_blur_uses_case_insensitive_repository_tags(tmp_path):
    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"fake")
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE file_tags (file_path TEXT, tag TEXT)")
    conn.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
        (str(asset.resolve()), "NSFW"),
    )

    assert ThumbnailService()._check_blur(asset, {"nsfw"}, conn) is True


def test_resolve_uses_connection_provider_for_blur_tags(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    asset = library / "photo.jpg"
    asset.write_bytes(b"fake")
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE file_tags (file_path TEXT, tag TEXT)")
    conn.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
        (str(asset.resolve()), "NSFW"),
    )
    roots = []
    service = ThumbnailService(connection_provider=lambda root: roots.append(root) or conn)

    result = service.resolve(
        asset, tmp_path / "thumbs", blur_tags={"nsfw"}, library_root=library
    )

    assert result.should_blur is True
    assert roots == [library.resolve()]


def test_check_blur_degrades_for_closed_connection(tmp_path):
    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"fake")
    conn = sqlite3.connect(":memory:")
    conn.close()

    assert ThumbnailService()._check_blur(asset, {"nsfw"}, conn) is False


def test_resolve_degrades_when_connection_provider_fails(tmp_path):
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "photo.jpg"
    asset.write_bytes(b"fake")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    calls = []

    def failing_provider(root):
        calls.append(root)
        raise RuntimeError("provider unavailable")

    result = ThumbnailService(
        connection_provider=failing_provider, session=session
    ).resolve(
        asset, tmp_path / "thumbs", blur_tags={"nsfw"}, library_root=library
    )

    assert result.source_path == asset
    assert result.should_blur is False
    assert calls == [library.resolve()]
    session.close()


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


def test_cache_metadata_round_trip(tmp_path):
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    library = tmp_path / "library"
    library.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    service = bootstrap.runtime_for(session).services.thumbnail_service

    assert service.get_cached_source_mtime(library, "key-1") is None

    service.upsert_cache_metadata(
        library,
        "key-1",
        str(library / "image.png"),
        1234.5,
        100,
        512,
        80,
    )

    assert service.get_cached_source_mtime(library, "key-1") == 1234.5
    assert service.list_cache_metadata(library) == [
        ("key-1", str(library / "image.png"), 1234.5)
    ]

    conn = session.connection_for(library)
    conn.execute(
        "UPDATE thumbnail_cache SET last_access=0 WHERE cache_key=?", ("key-1",)
    )
    conn.commit()
    service.touch_cache_metadata(library, "key-1")
    assert conn.execute(
        "SELECT last_access FROM thumbnail_cache WHERE cache_key=?", ("key-1",)
    ).fetchone()[0] > 0

    service.delete_cache_metadata(library, "key-1")
    assert service.get_cached_source_mtime(library, "key-1") is None


def test_clear_cache_metadata(tmp_path):
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    library = tmp_path / "library"
    library.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    service = bootstrap.runtime_for(session).services.thumbnail_service
    for key in ("key-1", "key-2"):
        service.upsert_cache_metadata(
            library, key, str(library / f"{key}.png"), 1.0, 10, 512, 5
        )

    service.clear_cache_metadata(library)

    assert service.list_cache_metadata(library) == []


def test_cache_metadata_rejects_closed_session(tmp_path):
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    library = tmp_path / "library"
    library.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    service = bootstrap.runtime_for(session).services.thumbnail_service
    bootstrap.library_service.close_session(session)

    with pytest.raises(RuntimeError, match="closed LibrarySession"):
        service.get_cached_source_mtime(library, "key-1")


def test_cache_metadata_provider_failure_releases_session_lease(tmp_path):
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    library = tmp_path / "library"
    library.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    calls = []

    def failing_provider(root):
        calls.append(root)
        raise RuntimeError("provider unavailable")

    service = ThumbnailService(connection_provider=failing_provider, session=session)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.get_cached_source_mtime(library, "key-1")

    assert calls == [library.resolve()]
    session.close()
