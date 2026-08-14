"""Thumbnail application service."""
from __future__ import annotations

import hashlib
import io
import logging
import sqlite3
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from AssetsManager.application.context import (
    ConnectionProvider,
    LibrarySession,
    session_operation,
)
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.path_resolver import root_identity
from AssetsManager.domain.asset import IMAGE_EXTS, VIDEO_EXTS
from AssetsManager.repositories.tag_repository import TagRepository
from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository

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

    def __init__(
        self,
        connection_provider: ConnectionProvider | None = None,
        session: LibrarySession | None = None,
    ):
        self._session = session
        self._tag_repository: TagRepository | None = None
        self._root_identity = None
        if isinstance(session, LibrarySession):
            expected_provider = session.connection_for
            provider = connection_provider or expected_provider
            provider_self = getattr(provider, "__self__", None)
            provider_func = getattr(provider, "__func__", None)
            expected_func = getattr(expected_provider, "__func__", None)
            if not (
                provider == expected_provider
                or (provider_self is session and provider_func is expected_func)
            ):
                raise ValueError(
                    "ThumbnailService connection provider does not belong to "
                    "the LibrarySession"
                )
            # Retain the exact provider object supplied by the runtime.
            # Besides preserving the session binding, this keeps the provider
            # identity shared by sibling runtime services.
            self._connection_provider = provider
            self._root_identity = session.context.root_identity
            self._tag_repository = TagRepository.for_session(session)
        else:
            self._connection_provider = connection_provider or (
                session.connection_for if session is not None else None
            )

    def _connection(self, library_root: str | Path) -> sqlite3.Connection:
        if self._connection_provider is None:
            raise RuntimeError(
                "ThumbnailService cache metadata requires an explicit "
                "ConnectionProvider."
            )
        requested = root_identity(library_root, strict=False)
        if isinstance(self._session, LibrarySession):
            captured = self._root_identity
            if captured is None or requested.map_key != captured.map_key:
                raise ValueError(
                    "ThumbnailService library_root does not match the bound "
                    "LibrarySession"
                )
            conn = self._connection_provider(requested.display_path)
            expected = self._session.connection_for(captured)
            if conn is not expected:
                raise ValueError(
                    "ThumbnailService connection provider returned a connection "
                    "that does not belong to the bound LibrarySession"
                )
            return DatabaseManager.require_managed_connection_owner(captured, conn)

        conn = self._connection_provider(requested.display_path)
        return DatabaseManager.validate_connection_owner(
            requested, conn, allow_unmanaged=True
        )

    def _repo(self, library_root: str | Path) -> ThumbnailRepository:
        return ThumbnailRepository(self._connection(library_root))

    @session_operation
    def get_cached_source_mtime(
        self, library_root: str | Path, cache_key: str
    ) -> float | None:
        """Return the source mtime recorded for ``cache_key``, if present."""
        return self._repo(library_root).get_source_mtime(cache_key)

    @session_operation
    def touch_cache_metadata(
        self, library_root: str | Path, cache_key: str
    ) -> None:
        """Mark a cache metadata entry as recently accessed."""
        self._repo(library_root).touch_access(cache_key)

    @session_operation
    def delete_cache_metadata(
        self, library_root: str | Path, cache_key: str
    ) -> None:
        """Delete the cache metadata entry identified by ``cache_key``."""
        self._repo(library_root).delete_entry(cache_key)

    @session_operation
    def upsert_cache_metadata(
        self,
        library_root: str | Path,
        cache_key: str,
        source_path: str | Path,
        source_mtime: float,
        source_size: int,
        baked_size: int,
        cache_size: int,
    ) -> None:
        """Insert or replace one thumbnail cache metadata entry."""
        self._repo(library_root).upsert_entry(
            cache_key,
            str(source_path),
            source_mtime,
            source_size,
            baked_size,
            cache_size,
        )

    @session_operation
    def list_cache_metadata(
        self, library_root: str | Path
    ) -> list[tuple[str, str, float]]:
        """Return ``(cache_key, source_path, source_mtime)`` metadata rows."""
        return self._repo(library_root).list_all_with_metadata()

    @session_operation
    def clear_cache_metadata(self, library_root: str | Path) -> None:
        """Delete all thumbnail cache metadata for a library."""
        self._repo(library_root).clear_all()

    @session_operation
    def resolve(
        self,
        target: Path,
        thumbnail_dir: Path,
        max_size: int = 512,
        blur_tags: set[str] | None = None,
        db_conn: sqlite3.Connection | None = None,
        library_root: str | Path | None = None,
    ) -> ThumbnailResult:
        """Resolve the source image for a thumbnail request.

        Checks the disk cache first, then falls back to the original file.
        Also determines if the image should be blurred based on tags.
        """
        should_blur = self._check_blur(target, blur_tags, db_conn, library_root)
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

        # Video: extract the first frame into the cache and serve that.
        if target.suffix.lower() in VIDEO_EXTS and target.exists():
            cache_key = self._cache_key(target)
            frame = thumbnail_dir / f"{cache_key}.jpg"
            if not frame.exists() and not self._extract_video_frame(target, frame):
                return ThumbnailResult()
            return ThumbnailResult(
                source_path=frame, should_blur=should_blur, cache_hit=False,
            )

        return ThumbnailResult()

    @staticmethod
    def _extract_video_frame(source_path: Path, destination: Path) -> bool:
        """Extract the first frame of a video into *destination* via ffmpeg."""
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(source_path),
                    "-frames:v", "1",
                    "-vf", "scale=512:512:force_original_aspect_ratio=decrease",
                    str(destination),
                ],
                capture_output=True,
                timeout=30,
            )
            return result.returncode == 0 and destination.exists()
        except (OSError, subprocess.SubprocessError):
            _log.debug("video frame extraction failed for %s", source_path)
            return False

    def process_image(
        self,
        source_path: Path,
        max_size: int = 512,
        should_blur: bool = False,
    ) -> tuple[bytes, str] | None:
        """Process an image: resize and/or blur. Returns (bytes, mime_type) or None."""
        try:
            from PIL import Image, ImageFilter, ImageOps
        except ImportError:
            _log.warning("Pillow not installed — cannot process thumbnails")
            return None
        try:
            img = Image.open(source_path)
            # Apply EXIF orientation so the thumbnail matches the displayed image.
            img = ImageOps.exif_transpose(img)
            w, h = img.size
            if max(w, h) > max_size:
                ratio = max_size / max(w, h)
                resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
                img = img.resize((int(w * ratio), int(h * ratio)), resample)
            if should_blur:
                img = img.filter(ImageFilter.GaussianBlur(radius=15))
            # WEBP only accepts RGB/RGBA: convert other modes (CMYK, P, L,
            # LA, ...) before saving so paletted or CMYK sources do not fail.
            has_alpha = "A" in img.getbands() or img.mode in ("LA", "PA", "RGBA")
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if has_alpha else "RGB")
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=80)
            buf.seek(0)
            return buf.getvalue(), "image/webp"
        except (OSError, ValueError) as exc:
            _log.debug("process_image failed for %s: %s", source_path, exc)
            return None

    def _check_blur(
        self,
        target: Path,
        blur_tags: set[str] | None,
        db_conn: sqlite3.Connection | None,
        library_root: str | Path | None = None,
    ) -> bool:
        if not blur_tags:
            return False
        root = Path(library_root).resolve() if library_root is not None else None
        if db_conn is None and root is not None and self._connection_provider is not None:
            # Blur policy is security-sensitive: an unavailable provider must
            # not be interpreted as "the file does not need blurring".
            db_conn = self._connection_provider(root)
        if db_conn is None:
            # Fail closed: with blur tags configured, an undecidable policy
            # must not silently un-blur the asset.
            raise ValueError(
                "ThumbnailService blur policy requires a database connection "
                "when blur_tags are configured"
            )
        if isinstance(self._session, LibrarySession):
            requested = root_identity(
                root if root is not None else self._session.context.root_identity,
                strict=False,
            )
            captured = self._root_identity
            if captured is None or requested.map_key != captured.map_key:
                raise ValueError(
                    "ThumbnailService library_root does not match the bound "
                    "LibrarySession"
                )
            expected = self._session.connection_for(captured)
            if db_conn is not None and db_conn is not expected:
                raise ValueError(
                    "ThumbnailService connection does not belong to the bound "
                    "LibrarySession"
                )
            tag_repository = self._tag_repository
            if tag_repository is None:
                raise RuntimeError("ThumbnailService tag repository binding is unavailable")
        else:
            if root is not None:
                db_conn = DatabaseManager.validate_connection_owner(root, db_conn, allow_unmanaged=True)
            tag_repository = TagRepository(db_conn)
        file_tags = {
            tag.lower()
            for tag in tag_repository.get_tags(str(target.resolve()))
        }
        return bool(file_tags & {t.lower() for t in blur_tags})

    @staticmethod
    def _cache_key(target: Path) -> str:
        return thumbnail_cache_key(target)
