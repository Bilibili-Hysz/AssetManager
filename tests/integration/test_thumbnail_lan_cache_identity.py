"""Strict thumbnail cache identity checks used by LAN preview routes."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from AssetsManager.application.thumbnail_service import (
    ThumbnailService,
    ThumbnailSourceChangedError,
    thumbnail_source_identity,
)
from AssetsManager.core.thumbnail_key import (
    legacy_thumbnail_cache_key,
    profiled_thumbnail_cache_key_v3,
)


def _write_webp(path: Path) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (256, 128), "red").save(path, "WEBP")


def test_strict_mode_ignores_same_mtime_legacy_webp_after_source_replacement(tmp_path) -> None:
    pytest.importorskip("PIL")
    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"old-image")
    original_stat = asset.stat()
    thumbs = tmp_path / "thumbs"
    legacy = thumbs / f"{legacy_thumbnail_cache_key(asset)}.webp"
    _write_webp(legacy)

    replacement = tmp_path / "replacement.jpg"
    replacement.write_bytes(b"new-image")
    os.utime(replacement, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    os.replace(replacement, asset)

    service = ThumbnailService()
    assert service.resolve(asset, thumbs, max_size=256).source_path == legacy
    strict = service.resolve(asset, thumbs, max_size=256, allow_legacy_cache=False)
    assert strict.source_path == asset
    assert strict.cache_hit is False


@pytest.mark.parametrize("kind", ["v3", "v2"])
def test_strict_mode_accepts_identity_bound_webp_cache(tmp_path, kind) -> None:
    pytest.importorskip("PIL")
    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"source")
    identity = thumbnail_source_identity(asset)
    assert identity is not None
    thumbs = tmp_path / "thumbs"
    service = ThumbnailService()
    if kind == "v3":
        key = profiled_thumbnail_cache_key_v3(asset, "desktop-webp-256-v1", identity)
    else:
        key = service._cache_key(asset, identity)
    cached = thumbs / f"{key}.webp"
    _write_webp(cached)

    result = service.resolve(asset, thumbs, max_size=256, allow_legacy_cache=False)
    assert result.source_path == cached
    assert result.cache_hit is True


def test_strict_mode_raises_when_source_changes_during_cache_admission(monkeypatch, tmp_path) -> None:
    pytest.importorskip("PIL")
    from AssetsManager.application import thumbnail_service

    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"source")
    identity = thumbnail_source_identity(asset)
    assert identity is not None
    thumbs = tmp_path / "thumbs"
    cached = thumbs / f"{ThumbnailService()._cache_key(asset, identity)}.webp"
    _write_webp(cached)
    original_admission = thumbnail_service.admit_thumbnail_cache_artifact

    def replace_after_admission(path: Path, required_size: int):
        admitted = original_admission(path, required_size)
        replacement = tmp_path / "replacement.jpg"
        replacement.write_bytes(b"changed")
        os.replace(replacement, asset)
        return admitted

    monkeypatch.setattr(thumbnail_service, "admit_thumbnail_cache_artifact", replace_after_admission)
    with pytest.raises(ThumbnailSourceChangedError):
        ThumbnailService().resolve(asset, thumbs, max_size=256, allow_legacy_cache=False)


def test_strict_mode_raises_when_source_changes_during_blur_lookup(monkeypatch, tmp_path) -> None:
    pytest.importorskip("PIL")
    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"source")
    identity = thumbnail_source_identity(asset)
    assert identity is not None
    thumbs = tmp_path / "thumbs"
    cached = thumbs / f"{ThumbnailService()._cache_key(asset, identity)}.webp"
    _write_webp(cached)
    service = ThumbnailService()

    def replace_during_blur(*_args, **_kwargs) -> bool:
        replacement = tmp_path / "replacement.jpg"
        replacement.write_bytes(b"changed")
        os.replace(replacement, asset)
        return False

    monkeypatch.setattr(service, "_check_blur", replace_during_blur)
    with pytest.raises(ThumbnailSourceChangedError):
        service.resolve(asset, thumbs, max_size=256, allow_legacy_cache=False)


def test_strict_mode_missing_original_returns_empty_result(tmp_path) -> None:
    result = ThumbnailService().resolve(
        tmp_path / "missing.jpg", tmp_path / "thumbs", allow_legacy_cache=False
    )
    assert not result.found


def test_strict_cache_hit_bypasses_original_admission_size_limit(monkeypatch, tmp_path) -> None:
    pytest.importorskip("PIL")
    from AssetsManager.application import thumbnail_service

    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"x" * 2_048)
    identity = thumbnail_source_identity(asset)
    assert identity is not None
    thumbs = tmp_path / "thumbs"
    cached = thumbs / f"{ThumbnailService()._cache_key(asset, identity)}.webp"
    _write_webp(cached)
    monkeypatch.setattr(thumbnail_service, "MAX_THUMBNAIL_SOURCE_BYTES", 1_024)

    result = ThumbnailService().resolve(asset, thumbs, max_size=256, allow_legacy_cache=False)
    assert result.source_path == cached
    assert result.cache_hit is True


@pytest.mark.parametrize("suffix", [".jpg", ".txt"])
def test_strict_cache_hit_rejects_original_escaping_library_root(tmp_path, suffix) -> None:
    pytest.importorskip("PIL")
    library = tmp_path / "library"
    library.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_asset = outside / f"photo{suffix}"
    outside_asset.write_bytes(b"outside source")
    swapped_parent = library / "swapped"
    swapped_parent.mkdir()
    target = swapped_parent / f"photo{suffix}"
    target.write_bytes(b"in root source")
    thumbs = library / "thumbs"
    identity = thumbnail_source_identity(outside_asset)
    assert identity is not None
    cached = thumbs / f"{ThumbnailService()._cache_key(outside_asset, identity)}.webp"
    _write_webp(cached)
    target.unlink()
    swapped_parent.rmdir()

    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(swapped_parent), str(outside)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip("junction creation unavailable")
    else:
        try:
            swapped_parent.symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("symlink creation unavailable")

    try:
        with pytest.raises(ThumbnailSourceChangedError):
            ThumbnailService().resolve(
                target,
                thumbs,
                max_size=256,
                library_root=library,
                allow_legacy_cache=False,
            )
    finally:
        if os.name == "nt":
            swapped_parent.rmdir()
        else:
            swapped_parent.unlink()


def test_strict_video_skips_legacy_frame_and_extracts_identity_bound_frame(monkeypatch, tmp_path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video bytes")
    thumbs = tmp_path / "thumbs"
    legacy = thumbs / f"{legacy_thumbnail_cache_key(video)}.jpg"
    legacy.parent.mkdir()
    legacy.write_bytes(b"legacy frame")
    service = ThumbnailService()
    extracted: list[Path] = []
    identity = thumbnail_source_identity(video)
    assert identity is not None
    strict_frame = thumbs / f"{service._cache_key(video, identity)}.jpg"
    real_is_file = Path.is_file
    strict_frame_checks = 0

    def frame_appears_after_first_check(path: Path) -> bool:
        nonlocal strict_frame_checks
        if path == strict_frame:
            strict_frame_checks += 1
            return strict_frame_checks > 1
        return real_is_file(path)

    def extract(_body: bytes, _suffix: str, destination: Path) -> bool:
        extracted.append(destination)
        destination.write_bytes(b"new frame")
        return True

    monkeypatch.setattr(service, "_extract_video_frame_from_bytes", extract)
    monkeypatch.setattr(Path, "is_file", frame_appears_after_first_check)
    result = service.resolve(video, thumbs, max_size=256, allow_legacy_cache=False)
    assert extracted == [result.source_path]
    assert result.source_path is not None
    assert result.source_path != legacy
    assert result.source_path.read_bytes() == b"new frame"
    assert strict_frame_checks == 1


def test_default_mode_still_reads_legacy_webp_cache(tmp_path) -> None:
    pytest.importorskip("PIL")
    asset = tmp_path / "photo.jpg"
    asset.write_bytes(b"source")
    thumbs = tmp_path / "thumbs"
    legacy = thumbs / f"{legacy_thumbnail_cache_key(asset)}.webp"
    _write_webp(legacy)

    result = ThumbnailService().resolve(asset, thumbs, max_size=256)
    assert result.source_path == legacy
    assert result.cache_hit is True
