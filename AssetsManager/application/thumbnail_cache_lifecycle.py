"""Process-local lifecycle coordination for persistent thumbnail artifacts."""
from __future__ import annotations

import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from AssetsManager.core.library_lock import LibraryAlreadyOpenError, LibraryLock
from AssetsManager.repositories.thumbnail_repository import ThumbnailMetadata

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.RLock] = {}
_ARTIFACT_KINDS = frozenset({"webp", "jpg"})


def _lock_for(thumb_dir: str | Path) -> threading.RLock:
    key = str(Path(thumb_dir).resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


@contextmanager
def artifact_lock(thumb_dir: str | Path) -> Iterator[None]:
    """Serialize cache artifact writes and cleanup within this process."""
    with _lock_for(thumb_dir):
        yield


@contextmanager
def cache_owner_lock(
    thumb_dir: str | Path,
    *,
    timeout: float = 30.0,
    poll_interval: float = 0.02,
) -> Iterator[None]:
    """Acquire the cross-process owner lease for one thumbnail directory.

    The marker is retained by ``QLockFile`` while ownership is represented by
    the OS lock.  A bounded wait lets concurrent workers single-flight without
    turning a cache operation into an unbounded stall.
    """
    root = Path(thumb_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".thumbnail-owner.lock"
    deadline = time.monotonic() + max(0.0, timeout)
    owner: LibraryLock | None = None
    while owner is None:
        try:
            owner = LibraryLock(lock_path)
        except LibraryAlreadyOpenError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Thumbnail cache owner busy: {root}") from None
            time.sleep(max(0.001, poll_interval))
    try:
        with artifact_lock(root):
            yield
    finally:
        if not owner.release():
            raise RuntimeError(f"Failed to release thumbnail cache owner: {lock_path}")


def artifact_path(
    thumb_dir: str | Path,
    cache_key: str,
    artifact_kind: str = "webp",
) -> Path | None:
    """Derive one safe artifact path from a cache key and known extension."""
    if not _KEY_RE.fullmatch(str(cache_key)) or artifact_kind not in _ARTIFACT_KINDS:
        return None
    root = Path(thumb_dir).resolve()
    candidate = (root / f"{cache_key}.{artifact_kind}").resolve()
    if candidate.parent != root:
        return None
    return candidate


def remove_artifacts(
    thumb_dir: str | Path,
    cache_key: str,
    *,
    artifact_kind: str | None = None,
    include_temp: bool = True,
) -> int:
    """Remove only derived cache artifacts, returning successful removals."""
    if not _KEY_RE.fullmatch(str(cache_key)):
        return 0
    kinds = (artifact_kind,) if artifact_kind else tuple(sorted(_ARTIFACT_KINDS))
    removed = 0
    with artifact_lock(thumb_dir):
        for kind in kinds:
            path = artifact_path(thumb_dir, cache_key, kind)
            if path is not None:
                try:
                    path.unlink()
                    removed += 1
                except FileNotFoundError:
                    pass
                except OSError:
                    continue
        if include_temp:
            root = Path(thumb_dir).resolve()
            for suffix in ("webp", "jpg"):
                for path in root.glob(f"{cache_key}.*.{suffix}.tmp"):
                    try:
                        path.unlink()
                        removed += 1
                    except OSError:
                        pass
    return removed


def eviction_artifact(metadata: ThumbnailMetadata, thumb_dir: str | Path) -> Path | None:
    """Resolve the artifact represented by one metadata row."""
    return artifact_path(thumb_dir, metadata.cache_key, metadata.artifact_kind)
