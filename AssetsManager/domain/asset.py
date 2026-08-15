"""Asset domain model — value objects for file system entities."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from AssetsManager.core.constants import (
    IMAGE_EXTS,
    VIDEO_EXTS as VIDEO_EXTS,  # noqa: F401  (re-exported compatibility surface)
)
from AssetsManager.domain.errors import PathEscapeError


def category_for_extension(ext: str) -> str:
    """Return the category name for a file extension.

    Uses the CATEGORY_MAP from core.format_utils. This function lives in
    the domain layer so that ``AssetType.from_path()`` can classify paths
    without importing the application layer.
    """
    from AssetsManager.core.format_utils import CATEGORY_MAP
    return CATEGORY_MAP.get(ext, "other")


def assert_under_root(target: Path, root: Path) -> Path:
    """Resolve *target* and verify it stays under *root*.

    Returns the resolved path.  Raises ``PathEscapeError`` if the resolved
    path escapes the root (e.g. via ``../`` or absolute path).
    """
    resolved = Path(target).resolve()
    root_resolved = Path(root).resolve()
    if not resolved.is_relative_to(root_resolved):
        raise PathEscapeError(str(target), str(root))
    return resolved


@dataclass(frozen=True)
class AssetPath:
    """Resolved path to a file or directory within a library.

    Encapsulates the relationship between an absolute path and its
    library-relative representation.
    """
    absolute: Path
    relative: str
    library_root: Path

    @classmethod
    def from_absolute(cls, absolute: str | Path, library_root: str | Path) -> AssetPath:
        """Create an AssetPath from an absolute path and library root."""
        abs_path = Path(absolute).resolve()
        root = Path(library_root).resolve()
        rel = str(abs_path.relative_to(root)).replace("\\", "/")
        return cls(absolute=abs_path, relative=rel, library_root=root)

    @classmethod
    def from_relative(cls, relative: str, library_root: str | Path) -> AssetPath:
        """Create an AssetPath from a relative path and library root.

        Raises PathEscapeError if the resolved path escapes the library root.
        """
        root = Path(library_root).resolve()
        abs_path = assert_under_root(root / relative, root)
        return cls(absolute=abs_path, relative=relative.replace("\\", "/"), library_root=root)

    @property
    def name(self) -> str:
        """File or directory name."""
        return self.absolute.name

    @property
    def extension(self) -> str:
        """File extension (lowercase, with dot)."""
        return self.absolute.suffix.lower()

    @property
    def is_image(self) -> bool:
        """Check if this path points to an image file."""
        return self.extension in IMAGE_EXTS


@dataclass(frozen=True)
class AssetType:
    """Classification of an asset."""
    category: str
    extension: str
    is_dir: bool

    @classmethod
    def from_path(cls, path: Path) -> AssetType:
        """Classify a path by its extension."""
        is_dir = path.is_dir()
        ext = path.suffix.lower() if not is_dir else ""
        category = "folder" if is_dir else category_for_extension(ext)
        return cls(category=category, extension=ext, is_dir=is_dir)


@dataclass(frozen=True)
class AssetInfo:
    """Basic information about a file system entity."""
    path: AssetPath
    asset_type: AssetType
    size: int
    modified: float

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def is_dir(self) -> bool:
        return self.asset_type.is_dir

    @property
    def category(self) -> str:
        return self.asset_type.category
