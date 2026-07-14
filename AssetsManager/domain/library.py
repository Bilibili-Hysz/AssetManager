"""Library domain model — value objects for library concepts."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LibraryPath:
    """Resolved library path with deterministic data directory naming.

    This is a pure value object that encapsulates the path resolution
    logic used throughout the application for per-library data directories.
    """
    root: Path
    data_dir: Path
    thumb_dir: Path

    @classmethod
    def from_root(cls, root: str | Path, runtime_root: Path) -> LibraryPath:
        """Create a LibraryPath from a root path and runtime root.

        The data directory name is deterministic: basename + 10-char SHA256 digest
        of the resolved root path. This avoids collisions for libraries with the
        same basename on different drives.
        """
        resolved = Path(root).resolve()
        name = _library_data_name(resolved)
        data_dir = runtime_root / name
        thumb_dir = data_dir / ".thumbnails"
        return cls(root=resolved, data_dir=data_dir, thumb_dir=thumb_dir)

    @property
    def db_path(self) -> Path:
        """Path to the SQLite database file."""
        return self.data_dir / "assetmanager.db"

    @property
    def favorites_path(self) -> Path:
        """Path to the favorites JSON file."""
        return self.data_dir / "favorites.json"

    @property
    def recent_path(self) -> Path:
        """Path to the recent folders JSON file."""
        return self.data_dir / "recent.json"

    def exists(self) -> bool:
        """Check if the library root directory exists."""
        return self.root.exists() and self.root.is_dir()


def _library_data_name(resolved_root: Path) -> str:
    """Generate a deterministic directory name for a library.

    Format: {basename}_{10-char-sha256}
    """
    root_str = str(resolved_root)
    digest = hashlib.sha256(root_str.encode()).hexdigest()[:10]
    return f"{resolved_root.name}_{digest}"
