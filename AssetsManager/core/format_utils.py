"""Shared formatting and classification utilities."""

from threading import RLock
from typing import TypeVar, overload

from AssetsManager.core.constants import MEDIA_IMAGE_EXTS

_T = TypeVar("_T")


def format_size(size: int) -> str:
    """Format bytes to human readable string.

    Examples:
        format_size(1024) -> "1.0 KB"
        format_size(1048576) -> "1.0 MB"
    """
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


_BUILTIN_CATEGORY_MAP: dict[str, str] = {
    ".png": "images", ".jpg": "images", ".jpeg": "images", ".gif": "images",
    ".bmp": "images", ".webp": "images", ".tiff": "images", ".svg": "images",
    ".blend": "3d", ".fbx": "3d", ".obj": "3d", ".gltf": "3d", ".glb": "3d",
    ".max": "3d", ".ma": "3d", ".mb": "3d", ".3ds": "3d", ".stl": "3d",
    ".mp4": "videos", ".mov": "videos", ".avi": "videos", ".mkv": "videos",
    ".webm": "videos", ".wmv": "videos",
    ".zip": "archives", ".rar": "archives", ".7z": "archives",
    ".tar": "archives", ".gz": "archives", ".bz2": "archives",
    ".txt": "documents", ".pdf": "documents", ".docx": "documents",
    ".xlsx": "documents", ".pptx": "documents", ".md": "documents",
    ".json": "documents", ".py": "documents", ".xml": "documents",
}

# Professional-format images (RAW/PSD/EXR) share the "images" category even
# though QImageReader/Pillow cannot decode them; see core/constants.py.
_BUILTIN_CATEGORY_MAP.update({ext: "images" for ext in MEDIA_IMAGE_EXTS})

class LiveCategoryMap(dict[str, str]):
    """Stable dict-compatible category mapping with atomic snapshot publication.

    Imported callers retain the same mapping object. Reads use the current
    immutable backing snapshot, and :meth:`publish` swaps that snapshot in one
    assignment so no consumer can traverse an in-place rebuild generation.
    """

    def __init__(self, initial: dict[str, str]):
        super().__init__()
        self._lock = RLock()
        self._snapshot = dict(initial)

    def _read_snapshot(self) -> dict[str, str]:
        return self._snapshot

    def publish(self, mapping: dict[str, str]) -> None:
        with self._lock:
            self._snapshot = dict(mapping)

    def snapshot(self) -> dict[str, str]:
        return dict(self._read_snapshot())

    def __getitem__(self, key):
        return self._read_snapshot()[key]

    def __contains__(self, key):
        return key in self._read_snapshot()

    def __iter__(self):
        return iter(self._read_snapshot())

    def __len__(self):
        return len(self._read_snapshot())

    # Mirror dict.get()'s overloads exactly: a plain `default=None` signature
    # would make every `.get(key, "other")` call resolve to `str | None`
    # instead of `str` for callers (e.g. domain/asset.category_for_extension).
    @overload
    def get(self, key: str) -> str | None: ...
    @overload
    def get(self, key: str, default: str | _T) -> str | _T: ...
    def get(self, key, default: str | _T | None = None) -> str | _T | None:
        return self._read_snapshot().get(key, default)

    def items(self):
        return self._read_snapshot().items()

    def keys(self):
        return self._read_snapshot().keys()

    def values(self):
        return self._read_snapshot().values()

    def copy(self):
        return self.snapshot()

    def __eq__(self, other):
        return self._read_snapshot() == other

    def __ne__(self, other):
        return self._read_snapshot() != other

    def __repr__(self):
        return repr(self._read_snapshot())

    def __or__(self, other):
        return self.snapshot() | other

    def __ror__(self, other):
        return other | self.snapshot()

    def __ior__(self, other):
        self.update(other)
        return self

    @classmethod
    def fromkeys(cls, iterable, value=None):
        """Match dict.fromkeys() by returning a normal independent dict."""
        return dict.fromkeys(iterable, value)

    # Preserve ordinary mutable-dict call sites by applying their changes to a
    # copied snapshot and publishing that complete result.
    def __setitem__(self, key, value):
        with self._lock:
            next_snapshot = self.snapshot()
            next_snapshot[key] = value
            self._snapshot = next_snapshot

    def __delitem__(self, key):
        with self._lock:
            next_snapshot = self.snapshot()
            del next_snapshot[key]
            self._snapshot = next_snapshot

    def clear(self):
        self.publish({})

    def update(self, *args, **kwargs):
        with self._lock:
            next_snapshot = self.snapshot()
            next_snapshot.update(*args, **kwargs)
            self._snapshot = next_snapshot

    def pop(self, key, *default):
        with self._lock:
            next_snapshot = self.snapshot()
            result = next_snapshot.pop(key, *default)
            self._snapshot = next_snapshot
            return result

    def popitem(self):
        with self._lock:
            next_snapshot = self.snapshot()
            result = next_snapshot.popitem()
            self._snapshot = next_snapshot
            return result

    # dict.setdefault() has no implicit-default form; the backing snapshot is
    # dict[str, str], so the default is a plain str (no existing caller relies
    # on the old `=None` sentinel — nothing calls setdefault without one).
    def setdefault(self, key: str, default: str) -> str:
        with self._lock:
            next_snapshot = self.snapshot()
            result = next_snapshot.setdefault(key, default)
            self._snapshot = next_snapshot
            return result


# Kept as a stable dict-compatible mapping for callers that import it directly.
CATEGORY_MAP: LiveCategoryMap = LiveCategoryMap(_BUILTIN_CATEGORY_MAP)
