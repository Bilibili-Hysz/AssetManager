"""Thumbnail application service."""
from __future__ import annotations

import hashlib
import io
import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from AssetsManager.domain.asset import IMAGE_EXTS

_log = logging.getLogger(__name__)

# ── Cache key cache ──────────────────────────────────────────────

_cache_lock = threading.Lock()
_cache: dict[str, tuple[str, str]] = {}  # path -> (mtime, key)
_CACHE_MAX_SIZE = 8192


def thumbnail_cache_key(path: str | Path) -> str:
    """Generate a deterministic cache key for a thumbnail source path.

    Uses the resolved path and mtime to ensure the key is stable across
    symlinks and changes when the file is modified.

    Results are cached in-memory to avoid repeated syscalls.
    """
    target = Path(path)
    raw_path = str(target)
    try:
        resolved = str(target.resolve())
        mtime = str(target.stat().st_mtime) if target.exists() else ""
    except OSError:
        resolved = raw_path
        mtime = ""

    cache_key = f"{resolved}|{mtime}"
    with _cache_lock:
        cached = _cache.get(raw_path)
        if cached and cached[0] == mtime:
            return cached[1]

    key = hashlib.sha256(cache_key.encode()).hexdigest()[:16]

    with _cache_lock:
        if len(_cache) >= _CACHE_MAX_SIZE:
            _cache.pop(next(iter(_cache)), None)
        _cache[raw_path] = (mtime, key)

    return key


def clear_thumbnail_cache_keys() -> None:
    """Clear the thumbnail cache key cache."""
    with _cache_lock:
        _cache.clear()


@dataclass(frozen=True)
class ThumbnailResult:
    """Result of a thumbnail resolution."""
    source_path: Path | None = None
    should_blur: bool = False
    cache_hit: bool = False

    @property
    def found(self) -> bool:
        return self.source_path is not None


class ThumbnailService:
    """Resolve and process thumbnails for assets."""

    def resolve(
        self,
        target: Path,
        thumbnail_dir: Path,
        max_size: int = 512,
        blur_tags: set[str] | None = None,
        db_conn: sqlite3.Connection | None = None,
    ) -> ThumbnailResult:
        """Resolve the source image for a thumbnail request.

        Checks the disk cache first, then falls back to the original file.
        Also determines if the image should be blurred based on tags.
        """
        should_blur = self._check_blur(target, blur_tags, db_conn)
        is_original_request = max_size >= 1024

        # Try cache
        if thumbnail_dir.exists() and not is_original_request:
            cache_key = self._cache_key(target)
            cached = thumbnail_dir / f"{cache_key}.webp"
            if cached.exists():
                return ThumbnailResult(
                    source_path=cached, should_blur=should_blur, cache_hit=True,
                )

        # Fall back to original
        if target.suffix.lower() in IMAGE_EXTS and target.exists():
            return ThumbnailResult(
                source_path=target, should_blur=should_blur, cache_hit=False,
            )

        return ThumbnailResult()

    def process_image(
        self,
        source_path: Path,
        max_size: int = 512,
        should_blur: bool = False,
    ) -> tuple[bytes, str] | None:
        """Process an image: resize and/or blur. Returns (bytes, mime_type) or None."""
        try:
            from PIL import Image, ImageFilter
        except ImportError:
            _log.warning("Pillow not installed — cannot process thumbnails")
            return None
        try:
            img = Image.open(source_path)
            if should_blur:
                img = img.filter(ImageFilter.GaussianBlur(radius=15))
            w, h = img.size
            if max(w, h) > max_size:
                ratio = max_size / max(w, h)
                resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
                img = img.resize((int(w * ratio), int(h * ratio)), resample)
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=80)
            buf.seek(0)
            return buf.getvalue(), "image/webp"
        except (OSError, ValueError) as exc:
            _log.debug("process_image failed for %s: %s", source_path, exc)
            return None

    @staticmethod
    def _check_blur(
        target: Path,
        blur_tags: set[str] | None,
        db_conn: sqlite3.Connection | None,
    ) -> bool:
        if not blur_tags or not db_conn:
            return False
        try:
            rows = db_conn.execute(
                "SELECT tag FROM file_tags WHERE file_path=?", (str(target.resolve()),)
            ).fetchall()
            file_tags = {r[0].lower() for r in rows}
            return bool(file_tags & {t.lower() for t in blur_tags})
        except sqlite3.Error:
            _log.debug("_check_blur query failed for %s", target)
            return False

    @staticmethod
    def _cache_key(target: Path) -> str:
        return thumbnail_cache_key(target)
