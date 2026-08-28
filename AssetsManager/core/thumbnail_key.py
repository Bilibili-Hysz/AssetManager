"""Versioned identity-aware keys for persistent thumbnail artifacts."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

THUMBNAIL_KEY_VERSION = "v2"
THUMBNAIL_V3_KEY_VERSION = "v3"
THUMBNAIL_KEY_LENGTH = 16
WEBP_RENDER_PROFILES = {
    "desktop-webp-256-v1": 256,
    "desktop-webp-512-v1": 512,
    "desktop-webp-1024-v1": 1024,
}


@dataclass(frozen=True)
class ThumbnailSourceFingerprint:
    """Canonical source path and filesystem identity used by the v2 key."""

    resolved_path: str
    device: int | None
    inode: int | None
    size: int | None
    mtime_ns: int | None

    @property
    def identity(self) -> tuple[int, int, int, int] | None:
        if (
            self.device is None
            or self.inode is None
            or self.size is None
            or self.mtime_ns is None
        ):
            return None
        return (self.device, self.inode, self.size, self.mtime_ns)


def _identity_tuple(identity: Any) -> tuple[int, int, int, int] | None:
    if identity is None:
        return None
    if hasattr(identity, "as_tuple"):
        value = identity.as_tuple()
    elif all(hasattr(identity, field) for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns")):
        value = (identity.st_dev, identity.st_ino, identity.st_size, identity.st_mtime_ns)
    else:
        value = tuple(identity)
    if len(value) != 4:
        raise ValueError("thumbnail source identity must have four fields")
    # The len check above pins the tuple to exactly four items.
    return cast("tuple[int, int, int, int]", tuple(int(item) for item in value))


def thumbnail_source_fingerprint(
    path: str | Path,
    identity: Any = None,
) -> ThumbnailSourceFingerprint:
    """Build one canonical fingerprint, reusing an already observed identity."""
    target = Path(path)
    resolved = str(target.resolve())
    observed = _identity_tuple(identity)
    if observed is None:
        try:
            observed = _identity_tuple(os.stat(target))
        except OSError:
            observed = None
    if observed is None:
        return ThumbnailSourceFingerprint(resolved, None, None, None, None)
    return ThumbnailSourceFingerprint(resolved, *observed)


def thumbnail_cache_key(
    path: str | Path,
    identity: Any = None,
    *,
    fingerprint: ThumbnailSourceFingerprint | None = None,
) -> str:
    """Generate the versioned 16-character identity-aware cache key."""
    value = fingerprint or thumbnail_source_fingerprint(path, identity)
    payload = "|".join(
        (
            THUMBNAIL_KEY_VERSION,
            value.resolved_path,
            "" if value.device is None else str(value.device),
            "" if value.inode is None else str(value.inode),
            "" if value.size is None else str(value.size),
            "" if value.mtime_ns is None else str(value.mtime_ns),
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:THUMBNAIL_KEY_LENGTH]


def normalize_webp_render_profile(profile: str) -> str:
    """Return one supported persistent WebP profile token."""
    if profile not in WEBP_RENDER_PROFILES:
        raise ValueError(f"unsupported WebP render profile: {profile}")
    return profile


def profiled_thumbnail_cache_key_v3(
    path: str | Path,
    profile: str,
    identity: Any = None,
    *,
    fingerprint: ThumbnailSourceFingerprint | None = None,
) -> str:
    """Generate an identity- and profile-aware persistent WebP key."""
    profile = normalize_webp_render_profile(profile)
    value = fingerprint or thumbnail_source_fingerprint(path, identity)
    payload = "|".join(
        (
            THUMBNAIL_V3_KEY_VERSION,
            "webp",
            profile,
            value.resolved_path,
            "" if value.device is None else str(value.device),
            "" if value.inode is None else str(value.inode),
            "" if value.size is None else str(value.size),
            "" if value.mtime_ns is None else str(value.mtime_ns),
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:THUMBNAIL_KEY_LENGTH]


def legacy_thumbnail_cache_key(path: str | Path) -> str:
    """Generate the pre-v2 path/second-mtime key for compatibility reads."""
    target = Path(path)
    raw_path = str(target)
    try:
        resolved = str(target.resolve())
        mtime = str(target.stat().st_mtime) if target.exists() else ""
    except OSError:
        resolved = raw_path
        mtime = ""
    return hashlib.sha256(f"{resolved}|{mtime}".encode()).hexdigest()[:THUMBNAIL_KEY_LENGTH]
