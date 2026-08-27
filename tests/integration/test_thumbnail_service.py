"""Tests for ThumbnailService."""

import io
import sqlite3
import subprocess
from pathlib import Path
import sys

import pytest

from AssetsManager.application.thumbnail_cache_lifecycle import cache_owner_lock
from AssetsManager.application.thumbnail_service import (
    MAX_THUMBNAIL_SOURCE_BYTES,
    ThumbnailAdmissionError,
    ThumbnailService,
    ThumbnailSourceChangedError,
    thumbnail_cache_key,
    thumbnail_source_identity,
    validate_thumbnail_source,
)


def _write_webp(path: Path, size: tuple[int, int] = (256, 128)) -> None:
    from PIL import Image

    Image.new("RGB", size, color="green").save(path, format="WEBP")


def _write_jpeg(path: Path, color: str = "blue") -> None:
    from PIL import Image

    Image.new("RGB", (64, 48), color=color).save(path, format="JPEG")


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


def test_resolve_reads_legacy_webp_cache_after_key_versioning(tmp_path):
    pytest.importorskip("PIL")
    from AssetsManager.core.thumbnail_key import legacy_thumbnail_cache_key

    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"fake jpg")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    cached = thumbs / f"{legacy_thumbnail_cache_key(asset)}.webp"
    _write_webp(cached, (256, 128))

    result = ThumbnailService().resolve(asset, thumbs, max_size=256)

    assert result.found
    assert result.source_path == cached
    assert result.cache_hit is True


def test_resolve_returns_cache_hit(tmp_path):
    pytest.importorskip("PIL")

    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"fake jpg")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()

    svc = ThumbnailService()
    cache_key = svc._cache_key(asset)
    cached = thumbs / f"{cache_key}.webp"
    _write_webp(cached, (256, 128))

    result = svc.resolve(asset, thumbs, max_size=256)

    assert result.found
    assert result.source_path == cached
    assert result.cache_hit is True


def test_resolve_rejects_malformed_cache_and_falls_back(tmp_path):
    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"fake jpg")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    svc = ThumbnailService()
    cached = thumbs / f"{svc._cache_key(asset)}.webp"
    cached.write_bytes(b"not a webp")

    result = svc.resolve(asset, thumbs, max_size=256)

    assert result.source_path == asset
    assert result.cache_hit is False
    assert cached.exists()


def test_resolve_rejects_undersized_cache_and_falls_back(tmp_path):
    pytest.importorskip("PIL")

    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"fake jpg")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    svc = ThumbnailService()
    cached = thumbs / f"{svc._cache_key(asset)}.webp"
    _write_webp(cached, (128, 64))

    result = svc.resolve(asset, thumbs, max_size=256)

    assert result.source_path == asset
    assert result.cache_hit is False
    assert cached.exists()


def test_resolve_uses_legacy_after_invalid_versioned_cache(tmp_path):
    pytest.importorskip("PIL")
    from AssetsManager.core.thumbnail_key import legacy_thumbnail_cache_key

    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"fake jpg")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    svc = ThumbnailService()
    versioned = thumbs / f"{svc._cache_key(asset)}.webp"
    versioned.write_bytes(b"truncated")
    legacy = thumbs / f"{legacy_thumbnail_cache_key(asset)}.webp"
    _write_webp(legacy, (256, 128))

    result = svc.resolve(asset, thumbs, max_size=256)

    assert result.source_path == legacy
    assert result.cache_hit is True


def test_resolve_valid_cache_bypasses_oversized_source_admission(tmp_path):
    pytest.importorskip("PIL")

    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"x" * (MAX_THUMBNAIL_SOURCE_BYTES + 1))
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    svc = ThumbnailService()
    cached = thumbs / f"{svc._cache_key(asset)}.webp"
    _write_webp(cached, (256, 128))

    result = svc.resolve(asset, thumbs, max_size=256)

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
    # Fail closed: blur tags without any database access raise instead of
    # silently deciding the file does not need blurring.
    with pytest.raises(ValueError, match="blur policy"):
        svc._check_blur(asset, {"nsfw"}, None)
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


def test_check_blur_fails_closed_for_closed_connection(tmp_path):
    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"fake")
    conn = sqlite3.connect(":memory:")
    conn.close()

    with pytest.raises(sqlite3.ProgrammingError):
        ThumbnailService()._check_blur(asset, {"nsfw"}, conn)


def test_check_blur_returns_false_for_no_matching_tags(tmp_path):
    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"fake")
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE file_tags (file_path TEXT, tag TEXT)")

    assert ThumbnailService()._check_blur(asset, {"nsfw"}, conn) is False


def test_check_blur_fails_closed_for_schema_error(tmp_path):
    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"fake")
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE file_tags (file_path TEXT, wrong_column TEXT)")

    with pytest.raises(sqlite3.OperationalError):
        ThumbnailService()._check_blur(asset, {"nsfw"}, conn)


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

    service = ThumbnailService(session=session)
    service._connection_provider = failing_provider
    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.resolve(
            asset, tmp_path / "thumbs", blur_tags={"nsfw"}, library_root=library
        )
    assert calls == [library.resolve()]
    session.close()


def test_process_image_bytes_processes_captured_snapshot(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    source = tmp_path / "snapshot.png"
    Image.new("RGB", (32, 24), color="green").save(source)
    body = source.read_bytes()
    result = ThumbnailService().process_image_bytes(body, max_size=16)
    assert result is not None
    encoded, mime = result
    assert mime == "image/webp"
    with Image.open(io.BytesIO(encoded)) as output:
        assert max(output.size) <= 16


def test_process_image_uses_snapshot_before_path_replacement(tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    from PIL import Image

    source = tmp_path / "snapshot.png"
    Image.new("RGB", (32, 24), color="green").save(source)
    identity = thumbnail_source_identity(source)
    original = source.read_bytes()
    source.write_bytes(b"not an image")
    with pytest.raises(ThumbnailSourceChangedError):
        ThumbnailService().process_image(source, expected_identity=identity)
    assert original != source.read_bytes()


def test_process_image_returns_none_for_missing_file(tmp_path):
    svc = ThumbnailService()
    result = svc.process_image(tmp_path / "missing.jpg", max_size=256)
    assert result is None


def test_validate_thumbnail_source_rejects_replaced_source(tmp_path):
    src = tmp_path / "image.jpg"
    src.write_bytes(b"before")
    identity = thumbnail_source_identity(src)
    src.write_bytes(b"after with a different size")

    with pytest.raises(ThumbnailSourceChangedError):
        validate_thumbnail_source(src, identity)


def test_process_image_rejects_oversized_source_before_decode(tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    from PIL import Image

    src = tmp_path / "oversized.jpg"
    src.write_bytes(b"x" * (MAX_THUMBNAIL_SOURCE_BYTES + 1))
    monkeypatch.setattr(Image, "open", lambda *_args: pytest.fail("decoder called"))

    with pytest.raises(ThumbnailAdmissionError) as exc_info:
        ThumbnailService().process_image(src, max_size=256)

    assert exc_info.value.size == MAX_THUMBNAIL_SOURCE_BYTES + 1
    assert exc_info.value.limit == MAX_THUMBNAIL_SOURCE_BYTES


def test_resolve_rejects_oversized_video_before_extraction(tmp_path, monkeypatch):
    src = tmp_path / "oversized.mp4"
    src.write_bytes(b"x" * (MAX_THUMBNAIL_SOURCE_BYTES + 1))
    monkeypatch.setattr(
        ThumbnailService,
        "_extract_video_frame",
        staticmethod(lambda *_args: pytest.fail("extractor called")),
    )

    with pytest.raises(ThumbnailAdmissionError):
        ThumbnailService().resolve(src, tmp_path / "thumbs")


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


def test_process_image_converts_cmyk_to_webp(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    img = Image.new("CMYK", (64, 64), color=(0, 255, 255, 0))
    src = tmp_path / "cmyk.jpg"
    img.save(src)

    svc = ThumbnailService()
    result = svc.process_image(src, max_size=256)

    assert result is not None
    data, mime = result
    assert mime == "image/webp"
    out = Image.open(io.BytesIO(data))
    assert out.mode in ("RGB", "RGBA")


def test_process_image_converts_palette_to_webp(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    img = Image.new("P", (64, 64))
    img.putpalette([0, 0, 0] * 256)
    src = tmp_path / "palette.png"
    img.save(src)

    svc = ThumbnailService()
    result = svc.process_image(src, max_size=256)

    assert result is not None
    data, mime = result
    assert mime == "image/webp"


def test_process_image_applies_exif_orientation(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    img = Image.new("RGB", (100, 50), color="red")
    exif = img.getexif()
    exif[274] = 6  # Orientation: rotate 90 degrees clockwise
    src = tmp_path / "rotated.jpg"
    img.save(src, exif=exif)

    svc = ThumbnailService()
    result = svc.process_image(src, max_size=256)

    assert result is not None
    data, mime = result
    out = Image.open(io.BytesIO(data))
    assert out.size == (50, 100)


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


def test_thumbnail_cache_key_distinguishes_same_path_identity_replacement(tmp_path):
    asset = tmp_path / "image.png"
    asset.write_bytes(b"fake png")
    first = thumbnail_source_identity(asset)
    second = (first[0], first[1] + 1, first[2] + 1, first[3])

    assert thumbnail_cache_key(asset, first) != thumbnail_cache_key(asset, second)


def test_thumbnail_cache_key_changes_on_mtime(tmp_path):
    asset = tmp_path / "image.png"
    asset.write_bytes(b"v1")
    k1 = thumbnail_cache_key(asset)

    import time
    time.sleep(0.05)
    asset.write_bytes(b"v2")
    k2 = thumbnail_cache_key(asset)

    assert k1 != k2


def test_cache_eviction_removes_oldest_artifact_and_metadata(tmp_path):
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    library = tmp_path / "library"
    library.mkdir()
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    service = bootstrap.runtime_for(session).services.thumbnail_service
    try:
        service.upsert_cache_metadata(library, "old", library / "old.png", 1.0, 1, 1, 10)
        service.upsert_cache_metadata(library, "new", library / "new.png", 2.0, 1, 1, 10)
        session.connection_for(library).execute(
            "UPDATE thumbnail_cache SET last_access=CASE cache_key "
            "WHEN 'old' THEN 1 ELSE 2 END WHERE cache_key IN ('old','new')"
        )
        session.connection_for(library).commit()
        (thumbs / "old.webp").write_bytes(b"old")
        (thumbs / "new.webp").write_bytes(b"new")
        assert service.evict_cache(library, thumbs, max_bytes=10) == 1
        assert not (thumbs / "old.webp").exists()
        assert (thumbs / "new.webp").exists()
        assert service.get_cache_metadata(library, "old") is None
    finally:
        bootstrap.library_service.close()


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


def test_strict_cache_metadata_rejects_unmanaged_provider_result(tmp_path):
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    library = tmp_path / "library"
    library.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    raw = sqlite3.connect(":memory:")
    service = ThumbnailService(session=session)
    service._connection_provider = lambda _root: raw

    try:
        with pytest.raises(ValueError, match="does not belong to the bound LibrarySession"):
            service.get_cached_source_mtime(library, "key-1")
    finally:
        raw.close()
        bootstrap.library_service.close_session(session)


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

    service = ThumbnailService(session=session)
    service._connection_provider = failing_provider

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.get_cached_source_mtime(library, "key-1")

    assert calls == [library.resolve()]
    session.close()


def test_thumbnail_service_accepts_managed_same_root_connection(tmp_path):
    from AssetsManager.core.database import DatabaseManager

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "photo.jpg"
    asset.write_bytes(b"asset")
    manager = DatabaseManager()
    try:
        conn = manager.connection_for(library)
        conn.execute(
            "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
            (str(asset.resolve()), "NSFW"),
        )
        conn.commit()

        result = ThumbnailService(connection_provider=lambda _root: conn).resolve(
            asset,
            tmp_path / "thumbs",
            blur_tags={"nsfw"},
            library_root=library,
        )

        assert result.should_blur is True
    finally:
        manager.close()


def test_thumbnail_service_rejects_provider_managed_foreign_root(tmp_path):
    from AssetsManager.core.database import DatabaseManager

    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    asset = root_a / "photo.jpg"
    asset.write_bytes(b"asset")
    manager = DatabaseManager()
    try:
        foreign_conn = manager.connection_for(root_b)
        service = ThumbnailService(connection_provider=lambda _root: foreign_conn)

        with pytest.raises(ValueError, match="different library root"):
            service.resolve(
                asset,
                tmp_path / "thumbs",
                blur_tags={"nsfw"},
                library_root=root_a,
            )
    finally:
        manager.close()


def test_thumbnail_service_rejects_explicit_managed_foreign_root(tmp_path):
    from AssetsManager.core.database import DatabaseManager

    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    asset = root_a / "photo.jpg"
    asset.write_bytes(b"asset")
    manager = DatabaseManager()
    try:
        foreign_conn = manager.connection_for(root_b)

        with pytest.raises(ValueError, match="different library root"):
            ThumbnailService().resolve(
                asset,
                tmp_path / "thumbs",
                blur_tags={"nsfw"},
                db_conn=foreign_conn,
                library_root=root_a,
            )
    finally:
        manager.close()


def test_thumbnail_cache_metadata_rejects_managed_foreign_root(tmp_path):
    from AssetsManager.core.database import DatabaseManager

    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    manager = DatabaseManager()
    try:
        foreign_conn = manager.connection_for(root_b)
        service = ThumbnailService(connection_provider=lambda _root: foreign_conn)

        with pytest.raises(ValueError, match="different library root"):
            service.get_cached_source_mtime(root_a, "cache-key")
    finally:
        manager.close()


def _make_video(path, size=(64, 48), duration=0.5):
    """Create a tiny test video via ffmpeg; skip if ffmpeg is unavailable."""
    import subprocess

    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=c=red:s={size[0]}x{size[1]}:d={duration}",
                "-pix_fmt", "yuv420p", str(path),
            ],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip("ffmpeg unavailable")
    if result.returncode != 0 or not path.exists():
        pytest.skip("ffmpeg could not create a test video")
    return path


def test_video_snapshot_extractor_does_not_use_source_path(tmp_path, monkeypatch):
    calls = []
    destination = tmp_path / "thumbs" / "frame.jpg"

    def fake_run(argv, **kwargs):
        calls.append(argv)
        output = Path(argv[-1])
        output.write_bytes(b"frame")
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert ThumbnailService._extract_video_frame_from_bytes(
        b"video", ".mp4", destination,
    )
    assert calls and str(tmp_path) not in calls[0][3]
    assert destination.read_bytes() == b"frame"


def test_cache_owner_lock_rejects_another_process(tmp_path):
    lock_dir = tmp_path / "thumbs"
    lock_dir.mkdir()
    owner_script = (
        "from AssetsManager.application.thumbnail_cache_lifecycle import cache_owner_lock\n"
        "import sys, time\n"
        "with cache_owner_lock(sys.argv[1]):\n"
        "    open(sys.argv[2], 'w', encoding='utf-8').close()\n"
        "    time.sleep(3)\n"
    )
    marker = tmp_path / "held"
    child = subprocess.Popen(
        [sys.executable, "-c", owner_script, str(lock_dir), str(marker)],
        cwd=str(Path(__file__).resolve().parents[2]),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(100):
            if marker.exists():
                break
            import time
            time.sleep(0.02)
        assert marker.exists()
        with pytest.raises(TimeoutError):
            with cache_owner_lock(lock_dir, timeout=0.05, poll_interval=0.01):
                pass
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_cache_owner_lock_recovers_after_owner_exit(tmp_path):
    lock_dir = tmp_path / "thumbs"
    lock_dir.mkdir()
    owner_script = (
        "from AssetsManager.application.thumbnail_cache_lifecycle import cache_owner_lock\n"
        "import sys, time\n"
        "with cache_owner_lock(sys.argv[1]):\n"
        "    open(sys.argv[2], 'w', encoding='utf-8').close()\n"
        "    time.sleep(30)\n"
    )
    marker = tmp_path / "held"
    child = subprocess.Popen(
        [sys.executable, "-c", owner_script, str(lock_dir), str(marker)],
        cwd=str(Path(__file__).resolve().parents[2]),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(100):
            if marker.exists():
                break
            import time
            time.sleep(0.02)
        assert marker.exists()
        child.terminate()
        child.wait(timeout=5)
        with cache_owner_lock(lock_dir, timeout=2.0, poll_interval=0.02):
            (lock_dir / "recovered").write_text("ok", encoding="utf-8")
        assert (lock_dir / "recovered").read_text(encoding="utf-8") == "ok"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_resolve_extracts_video_first_frame(tmp_path):
    video = _make_video(tmp_path / "clip.mp4")
    thumbs = tmp_path / "thumbs"

    svc = ThumbnailService()
    result = svc.resolve(video, thumbs, max_size=256)

    assert result.found
    assert result.source_path is not None
    assert result.source_path.suffix == ".jpg"
    assert result.source_path.exists()
    # The extracted frame is a real image Pillow can open.
    from PIL import Image
    with Image.open(result.source_path) as frame:
        assert frame.size[0] > 0 and frame.size[1] > 0


def test_resolve_returns_empty_for_missing_video(tmp_path):
    svc = ThumbnailService()
    result = svc.resolve(tmp_path / "missing.mp4", tmp_path / "thumbs", max_size=256)
    assert not result.found


def test_resolve_reuses_cached_video_frame(tmp_path):
    video = _make_video(tmp_path / "clip.mov")
    thumbs = tmp_path / "thumbs"
    svc = ThumbnailService()

    first = svc.resolve(video, thumbs, max_size=256)
    assert first.found and first.source_path is not None

    second = svc.resolve(video, thumbs, max_size=256)
    assert second.found
    assert second.source_path == first.source_path


def test_resolve_reads_legacy_cached_video_frame_before_extracting(tmp_path, monkeypatch):
    video = _make_video(tmp_path / "clip.mp4")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    from AssetsManager.core.thumbnail_key import legacy_thumbnail_cache_key

    legacy_frame = thumbs / f"{legacy_thumbnail_cache_key(video)}.jpg"
    _write_jpeg(legacy_frame)
    svc = ThumbnailService()
    monkeypatch.setattr(
        svc,
        "_extract_video_frame_from_bytes",
        lambda *args, **kwargs: pytest.fail("legacy frame should be reused"),
    )

    result = svc.resolve(video, thumbs, max_size=256)

    assert result.found
    assert result.source_path == legacy_frame
    assert result.cache_hit is False
    assert not (thumbs / f"{svc._cache_key(video)}.jpg").exists()


def test_resolve_prefers_v2_cached_video_frame_over_legacy(tmp_path, monkeypatch):
    video = _make_video(tmp_path / "clip.mp4")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    from AssetsManager.core.thumbnail_key import legacy_thumbnail_cache_key

    legacy_frame = thumbs / f"{legacy_thumbnail_cache_key(video)}.jpg"
    _write_jpeg(legacy_frame, color="blue")
    v2_frame = thumbs / f"{ThumbnailService()._cache_key(video)}.jpg"
    _write_jpeg(v2_frame, color="red")
    svc = ThumbnailService()
    monkeypatch.setattr(
        svc,
        "_extract_video_frame_from_bytes",
        lambda *args, **kwargs: pytest.fail("cached frame should be reused"),
    )

    result = svc.resolve(video, thumbs, max_size=256)

    assert result.found
    assert result.source_path == v2_frame
    assert result.cache_hit is False


def test_resolve_registers_video_frame_metadata_for_managed_service(tmp_path):
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    library = tmp_path / "library"
    library.mkdir()
    video = _make_video(library / "clip.mp4")
    thumbs = tmp_path / "thumbs"
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    service = bootstrap.runtime_for(session).services.thumbnail_service
    try:
        first = service.resolve(
            video, thumbs, max_size=256, library_root=library,
        )
        assert first.found and first.source_path is not None

        source_identity = thumbnail_source_identity(video)
        assert source_identity is not None
        key = service._cache_key(video, source_identity)
        metadata = service.get_cache_metadata(library, key)
        assert metadata is not None
        assert metadata.artifact_kind == "jpg"
        assert metadata.source_mtime_ns == source_identity[3]
        assert metadata.source_size == source_identity[2]
        assert metadata.cache_size == first.source_path.stat().st_size

        second = service.resolve(
            video, thumbs, max_size=256, library_root=library,
        )
        assert second.found and second.source_path == first.source_path
        assert service.get_cache_metadata(library, key) is not None
    finally:
        bootstrap.library_service.close()
