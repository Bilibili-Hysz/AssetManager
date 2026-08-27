"""Tests for the shared versioned thumbnail key contract."""

import os

from AssetsManager.core.thumbnail_key import (
    THUMBNAIL_KEY_VERSION,
    ThumbnailSourceFingerprint,
    legacy_thumbnail_cache_key,
    profiled_thumbnail_cache_key_v3,
    thumbnail_cache_key,
    thumbnail_source_fingerprint,
)


def test_identity_fields_change_the_versioned_key(tmp_path):
    source = tmp_path / "image.png"
    source.write_bytes(b"one")
    first = thumbnail_source_fingerprint(source)
    first_key = thumbnail_cache_key(source, fingerprint=first)

    source.write_bytes(b"two-bytes")
    second = thumbnail_source_fingerprint(source)
    second_key = thumbnail_cache_key(source, fingerprint=second)

    assert first_key != second_key
    assert len(first_key) == 16
    assert len(second_key) == 16
    assert first != second


def test_key_uses_nanosecond_mtime_when_second_precision_is_unchanged(tmp_path):
    source = tmp_path / "image.png"
    source.write_bytes(b"one")
    initial = os.stat(source)
    updated = (initial.st_dev, initial.st_ino, initial.st_size, initial.st_mtime_ns + 1)

    assert int(initial.st_mtime) == int(updated[3] / 1_000_000_000)
    assert thumbnail_cache_key(source, initial) != thumbnail_cache_key(source, updated)


def test_provided_identity_does_not_stat_source(monkeypatch, tmp_path):
    source = tmp_path / "missing-after-snapshot.png"
    fingerprint = ThumbnailSourceFingerprint(
        str(source.resolve()), 1, 2, 3, 4,
    )

    def fail_stat(*_args, **_kwargs):
        raise AssertionError("provided fingerprint must avoid stat")

    monkeypatch.setattr("AssetsManager.core.thumbnail_key.os.stat", fail_stat)
    key = thumbnail_cache_key(source, fingerprint=fingerprint)

    assert key == thumbnail_cache_key(source, fingerprint=fingerprint)
    assert THUMBNAIL_KEY_VERSION == "v2"


def test_profiled_v3_key_changes_with_profile_and_keeps_v2_legacy(tmp_path):
    source = tmp_path / "image.png"
    source.write_bytes(b"image")
    fingerprint = thumbnail_source_fingerprint(source)

    low = profiled_thumbnail_cache_key_v3(
        source, "desktop-webp-256-v1", fingerprint=fingerprint
    )
    high = profiled_thumbnail_cache_key_v3(
        source, "desktop-webp-512-v1", fingerprint=fingerprint
    )

    assert low != high
    assert len(low) == len(high) == 16
    assert low != thumbnail_cache_key(source, fingerprint=fingerprint)
    assert low != legacy_thumbnail_cache_key(source)


def test_profiled_v3_key_rejects_unknown_profile(tmp_path):
    source = tmp_path / "image.png"
    source.write_bytes(b"image")

    import pytest
    with pytest.raises(ValueError, match="unsupported WebP render profile"):
        profiled_thumbnail_cache_key_v3(source, "desktop-webp-999-v1")


def test_legacy_key_remains_distinct_from_versioned_key(tmp_path):
    source = tmp_path / "image.png"
    source.write_bytes(b"image")

    assert legacy_thumbnail_cache_key(source) != thumbnail_cache_key(source)
