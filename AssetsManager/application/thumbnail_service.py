"""Thumbnail application service."""
from __future__ import annotations

import io
import logging
import os
import sqlite3
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from AssetsManager.application.context import (
    ConnectionProvider,
    LibrarySession,
    session_operation,
)
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.file_snapshot import FileSnapshotError, read_snapshot
from AssetsManager.core.path_resolver import root_identity
from AssetsManager.core.thumbnail_key import (
    ThumbnailSourceFingerprint,
    WEBP_RENDER_PROFILES,
    legacy_thumbnail_cache_key,
    profiled_thumbnail_cache_key_v3,
    thumbnail_cache_key as _versioned_thumbnail_cache_key,
    thumbnail_source_fingerprint,
)
from AssetsManager.domain.asset import IMAGE_EXTS, VIDEO_EXTS
from AssetsManager.repositories.tag_repository import TagRepository
from AssetsManager.application.thumbnail_cache_lifecycle import (
    artifact_path,
    cache_owner_lock,
)
from AssetsManager.repositories.thumbnail_repository import ThumbnailMetadata, ThumbnailRepository

_log = logging.getLogger(__name__)

# ── Cache key cache ──────────────────────────────────────────────

_cache_lock = threading.Lock()
_cache: dict[str, tuple[ThumbnailSourceFingerprint, str]] = {}
_CACHE_MAX_SIZE = 8192

# Admission limits apply to source bytes before Pillow or ffmpeg gets involved.
MAX_THUMBNAIL_SOURCE_BYTES = 64 * 1024 * 1024
MAX_THUMBNAIL_BATCH_BYTES = 256 * 1024 * 1024


class ThumbnailAdmissionError(ValueError):
    """A thumbnail source exceeds the bounded media admission budget."""

    def __init__(self, path: Path, size: int, limit: int):
        self.path = path
        self.size = size
        self.limit = limit
        super().__init__(f"Thumbnail source exceeds limit ({size} > {limit} bytes)")


class ThumbnailSourceChangedError(ValueError):
    """A source changed after resolution and before consumption."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"Thumbnail source changed before consumption: {path}")


ThumbnailSourceIdentity = tuple[int, int, int, int]


def thumbnail_source_identity(path: str | Path) -> ThumbnailSourceIdentity | None:
    """Return metadata identifying one observed filesystem source."""
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def validate_thumbnail_source(
    path: str | Path,
    expected_identity: ThumbnailSourceIdentity | None = None,
    limit: int | None = None,
) -> ThumbnailSourceIdentity | None:
    """Validate size and, when supplied, identity immediately before opening."""
    source = Path(path)
    identity = thumbnail_source_identity(source)
    if identity is None:
        return None
    if expected_identity is not None and identity != expected_identity:
        raise ThumbnailSourceChangedError(source)
    effective_limit = MAX_THUMBNAIL_SOURCE_BYTES if limit is None else limit
    if identity[2] > effective_limit:
        raise ThumbnailAdmissionError(source, identity[2], effective_limit)
    return identity


def admit_thumbnail_source(
    path: str | Path, limit: int | None = None
) -> int | None:
    """Check source bytes before a decoder or frame extractor opens a file."""
    source = Path(path)
    try:
        size = source.stat().st_size
    except OSError:
        return None
    effective_limit = MAX_THUMBNAIL_SOURCE_BYTES if limit is None else limit
    if size > effective_limit:
        raise ThumbnailAdmissionError(source, size, effective_limit)
    return size


def admit_thumbnail_cache_artifact(
    path: str | Path,
    required_size: int,
) -> ThumbnailSourceIdentity | None:
    """Validate one persistent WebP cache artifact from a stable byte snapshot."""
    cached = Path(path)
    try:
        body, identity = read_snapshot(
            cached.parent,
            cached,
            max_bytes=MAX_THUMBNAIL_SOURCE_BYTES,
        )
    except (FileSnapshotError, OSError, ValueError):
        return None

    try:
        from PIL import Image

        with io.BytesIO(body) as stream:
            with Image.open(stream) as image:
                if image.format != "WEBP":
                    return None
                width, height = image.size
                image.verify()
            stream.seek(0)
            with Image.open(stream) as image:
                image.load()
                width, height = image.size
        if (
            not isinstance(width, int)
            or not isinstance(height, int)
            or width <= 0
            or height <= 0
            or max(width, height) < max(required_size, 0)
        ):
            return None
    except Exception:
        return None
    return identity.as_tuple()


def thumbnail_cache_key(
    path: str | Path,
    identity: ThumbnailSourceIdentity | None = None,
) -> str:
    """Generate a bounded, versioned key for one source identity."""
    target = Path(path)
    raw_path = str(target)
    fingerprint = thumbnail_source_fingerprint(target, identity)
    with _cache_lock:
        cached = _cache.get(raw_path)
        if cached and cached[0] == fingerprint:
            return cached[1]
    key = _versioned_thumbnail_cache_key(target, fingerprint=fingerprint)
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX_SIZE:
            _cache.pop(next(iter(_cache)), None)
        _cache[raw_path] = (fingerprint, key)
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
    source_identity: ThumbnailSourceIdentity | None = None

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
        *,
        source_mtime_ns: int | None = None,
        artifact_kind: str = "webp",
        render_profile: str | None = None,
        commit: bool = True,
    ) -> None:
        """Insert or update one thumbnail cache metadata entry."""
        self._repo(library_root).upsert_entry(
            cache_key,
            str(source_path),
            source_mtime,
            source_size,
            baked_size,
            cache_size,
            source_mtime_ns=source_mtime_ns,
            artifact_kind=artifact_kind,
            render_profile=render_profile,
            commit=commit,
        )

    @session_operation
    def get_cache_metadata(
        self, library_root: str | Path, cache_key: str
    ) -> ThumbnailMetadata | None:
        return self._repo(library_root).get_entry(cache_key)

    @session_operation
    def list_cache_eviction_candidates(
        self, library_root: str | Path, limit: int | None = None
    ) -> list[ThumbnailMetadata]:
        return self._repo(library_root).list_eviction_candidates(limit)

    @session_operation
    def delete_cache_entries(
        self, library_root: str | Path, cache_keys: list[str], *, commit: bool = True
    ) -> int:
        return self._repo(library_root).delete_entries(cache_keys, commit=commit)

    @session_operation
    def register_video_frame_metadata(
        self,
        library_root: str | Path | None,
        source_path: str | Path,
        frame_path: str | Path,
        source_identity: ThumbnailSourceIdentity | None = None,
        *,
        cache_key: str | None = None,
    ) -> bool:
        """Best-effort registration for a successfully published JPG frame."""
        if library_root is None or self._connection_provider is None:
            return False
        source = Path(source_path)
        frame = Path(frame_path)
        identity = source_identity or thumbnail_source_identity(source)
        if identity is None:
            return False
        try:
            if hasattr(identity, "mtime_ns"):
                source_size = int(identity.size)
                source_mtime_ns = int(identity.mtime_ns)
            else:
                source_size = int(identity[2])
                source_mtime_ns = int(identity[3])
            key = cache_key or self._cache_key(source, identity)
            with cache_owner_lock(frame.parent):
                if not frame.is_file():
                    return False
                frame_size = frame.stat().st_size
                self.upsert_cache_metadata(
                    library_root,
                    key,
                    source,
                    source_mtime_ns / 1_000_000_000,
                    source_size,
                    512,
                    frame_size,
                    source_mtime_ns=source_mtime_ns,
                    artifact_kind="jpg",
                )
            return True
        except (OSError, RuntimeError, ValueError, sqlite3.Error):
            _log.exception("Video frame metadata insert failed: %s", frame)
            return False

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
    def evict_cache(
        self,
        library_root: str | Path,
        thumbnail_dir: str | Path,
        *,
        max_bytes: int | None = None,
        max_entries: int | None = None,
    ) -> int:
        """Evict oldest persistent artifacts within one process."""
        if max_bytes is None and max_entries is None:
            return 0
        if max_bytes is not None and max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")
        if max_entries is not None and max_entries < 0:
            raise ValueError("max_entries must be non-negative")
        repo = self._repo(library_root)
        selected_count = 0
        with cache_owner_lock(thumbnail_dir):
            candidates = repo.list_eviction_candidates()
            total_bytes = sum(max(0, item.cache_size) for item in candidates)
            total_entries = len(candidates)
            for item in candidates:
                over_bytes = max_bytes is not None and total_bytes > max_bytes
                over_entries = max_entries is not None and total_entries > max_entries
                if not (over_bytes or over_entries):
                    break
                current = repo.get_entry(item.cache_key)
                if current != item:
                    continue
                path = artifact_path(thumbnail_dir, item.cache_key, item.artifact_kind)
                if path is None:
                    continue
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    continue
                if repo.delete_if_matches(item):
                    selected_count += 1
                    total_bytes = max(0, total_bytes - max(0, item.cache_size))
                    total_entries = max(0, total_entries - 1)
        return selected_count

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
        is_original_request = max_size >= 1024
        is_image = target.suffix.lower() in IMAGE_EXTS
        is_video = target.suffix.lower() in VIDEO_EXTS

        # Try cache before admitting the original. A cache hit does not consume
        # the source bytes, so it can still be served when the source changed.
        if thumbnail_dir.exists() and not is_original_request:
            cache_keys = []
            for profile in self._webp_profiles_for_size(max_size):
                cache_key = profiled_thumbnail_cache_key_v3(target, profile)
                if cache_key not in cache_keys:
                    cache_keys.append(cache_key)
            v2_key = self._cache_key(target)
            if v2_key not in cache_keys:
                cache_keys.append(v2_key)
            legacy_key = self._legacy_cache_key(target)
            if legacy_key not in cache_keys:
                cache_keys.append(legacy_key)
            for cache_key in cache_keys:
                cached = thumbnail_dir / f"{cache_key}.webp"
                artifact_identity = admit_thumbnail_cache_artifact(cached, max_size)
                if artifact_identity is None:
                    continue
                should_blur = self._check_blur(target, blur_tags, db_conn, library_root)
                return ThumbnailResult(
                    source_path=cached,
                    should_blur=should_blur,
                    cache_hit=True,
                    source_identity=artifact_identity,
                )

        # This is a pre-open size check. It bounds the source before blur policy
        # lookup or decoding, but does not make a later path-based open atomic.
        source_identity = None
        if (is_image or is_video) and target.is_file():
            source_identity = validate_thumbnail_source(target)

        should_blur = self._check_blur(target, blur_tags, db_conn, library_root)

        if is_image and target.is_file():
            return ThumbnailResult(
                source_path=target,
                should_blur=should_blur,
                cache_hit=False,
                source_identity=source_identity,
            )

        # Video: extract the first frame into the cache and serve that.
        if is_video and target.is_file():
            cache_key = self._cache_key(target, source_identity)
            frame = thumbnail_dir / f"{cache_key}.jpg"
            legacy_key = self._legacy_cache_key(target)
            if legacy_key != cache_key:
                legacy_frame = thumbnail_dir / f"{legacy_key}.jpg"
            else:
                legacy_frame = frame
            with cache_owner_lock(thumbnail_dir):
                if frame.is_file():
                    selected_frame = frame
                    selected_key = cache_key
                elif legacy_frame.is_file():
                    selected_frame = legacy_frame
                    selected_key = legacy_key
                else:
                    try:
                        body, _identity = read_snapshot(
                            target.parent,
                            target,
                            expected_identity=source_identity,
                            max_bytes=MAX_THUMBNAIL_SOURCE_BYTES,
                        )

                    except FileSnapshotError as exc:
                        raise ThumbnailSourceChangedError(target) from exc
                    if not self._extract_video_frame_from_bytes(body, target.suffix, frame):
                        return ThumbnailResult()
                    selected_frame = frame
                    selected_key = cache_key
                self.register_video_frame_metadata(
                    library_root,
                    target,
                    selected_frame,
                    source_identity,
                    cache_key=selected_key,
                )
                frame = selected_frame
            return ThumbnailResult(
                source_path=frame,
                should_blur=should_blur,
                cache_hit=False,
                source_identity=thumbnail_source_identity(frame),
            )

        return ThumbnailResult()

    @session_operation
    def check_blur(
        self,
        target: Path,
        blur_tags: set[str] | None = None,
        db_conn: sqlite3.Connection | None = None,
        library_root: str | Path | None = None,
    ) -> bool:
        """Blur-policy decision independent of the thumbnail pipeline.

        ``resolve`` computes the decision but discards it for formats its
        pipeline cannot handle (``.ktx2`` has no Pillow decoder, ``.tga`` is
        outside IMAGE_EXTS); LAN routes still deliver those bytes and must
        apply the same policy before doing so.
        """
        return self._check_blur(target, blur_tags, db_conn, library_root)

    @staticmethod
    def _extract_video_frame_from_bytes(
        body: bytes, suffix: str, destination: Path,
    ) -> bool:
        """Extract a frame from a captured media snapshot."""
        input_path = None
        output_path = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, input_path = tempfile.mkstemp(suffix=suffix or ".bin")
            with os.fdopen(fd, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            output_fd, output_path = tempfile.mkstemp(
                suffix=".jpg", dir=str(destination.parent),
            )
            os.close(output_fd)
            os.unlink(output_path)
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", input_path,
                    "-frames:v", "1",
                    "-vf", "scale=512:512:force_original_aspect_ratio=decrease",
                    output_path,
                ],
                capture_output=True,
                timeout=30,
            )
            if result.returncode != 0 or not Path(output_path).exists():
                return False
            os.replace(output_path, destination)
            output_path = None
            return True
        except (OSError, subprocess.SubprocessError):
            _log.debug("video frame extraction from snapshot failed")
            return False
        finally:
            for path in (input_path, output_path):
                if path:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

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
        expected_identity: ThumbnailSourceIdentity | None = None,
    ) -> tuple[bytes, str] | None:
        """Snapshot and process an image without reopening its path after validation."""
        source = Path(source_path)
        identity = validate_thumbnail_source(source, expected_identity)
        if identity is None:
            return None
        try:
            body, _opened_identity = read_snapshot(
                source.parent,
                source,
                expected_identity=identity,
                max_bytes=MAX_THUMBNAIL_SOURCE_BYTES,
            )
        except FileSnapshotError as exc:
            if identity is not None and "limit" in str(exc):
                raise ThumbnailAdmissionError(
                    source, identity[2], MAX_THUMBNAIL_SOURCE_BYTES
                ) from exc
            raise ThumbnailSourceChangedError(source) from exc
        return self.process_image_bytes(body, max_size, should_blur)

    def process_image_bytes(
        self,
        body: bytes,
        max_size: int = 512,
        should_blur: bool = False,
    ) -> tuple[bytes, str] | None:
        """Process an already captured image snapshot using a file object."""
        try:
            from PIL import Image, ImageFilter, ImageOps
        except ImportError:
            _log.warning("Pillow not installed — cannot process thumbnails")
            return None
        try:
            with io.BytesIO(body) as source:
                with Image.open(source) as original:
                    original.load()
                    img = ImageOps.exif_transpose(original)
                    w, h = img.size
                    if max(w, h) > max_size:
                        ratio = max_size / max(w, h)
                        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
                        img = img.resize((int(w * ratio), int(h * ratio)), resample)
                    if should_blur:
                        img = img.filter(ImageFilter.GaussianBlur(radius=15))
                    has_alpha = "A" in img.getbands() or img.mode in ("LA", "PA", "RGBA")
                    if img.mode not in ("RGB", "RGBA"):
                        img = img.convert("RGBA" if has_alpha else "RGB")
                    buf = io.BytesIO()
                    with img:
                        img.save(buf, format="WEBP", quality=80)
                    return buf.getvalue(), "image/webp"
        except (OSError, ValueError) as exc:
            _log.debug("process_image bytes failed: %s", exc)
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
    def _webp_profiles_for_size(max_size: int) -> list[str]:
        required = max(int(max_size), 0)
        return [
            profile
            for profile, size in sorted(WEBP_RENDER_PROFILES.items(), key=lambda item: item[1])
            if size >= required
        ]

    @staticmethod
    def _cache_key(
        target: Path,
        identity: ThumbnailSourceIdentity | None = None,
    ) -> str:
        return thumbnail_cache_key(target, identity)

    @staticmethod
    def _legacy_cache_key(target: Path) -> str:
        return legacy_thumbnail_cache_key(target)


def process_image_snapshot(
    service: ThumbnailService,
    source_path: Path,
    body: bytes,
    max_size: int,
    should_blur: bool,
    expected_identity: ThumbnailSourceIdentity | None = None,
) -> tuple[bytes, str] | None:
    """Process captured bytes while preserving legacy service test seams."""
    process_bytes = getattr(service, "process_image_bytes", None)
    process_path = getattr(service, "process_image", None)
    bound_function = getattr(process_path, "__func__", process_path)
    if not callable(process_bytes) or bound_function is not ThumbnailService.process_image:
        if not callable(process_path):
            return None
        return process_path(source_path, max_size, should_blur, expected_identity)
    return process_bytes(body, max_size, should_blur)
