"""PathResolver — resolves library-specific paths for data storage."""
import hashlib
import sys
from pathlib import Path


def runtime_root() -> Path:
    """Return the application's runtime data root directory."""
    if getattr(sys, 'frozen', False):
        # PyInstaller extracts bundled files to _MEIPASS
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            bundled = Path(meipass) / "RuntimeData"
            if bundled.exists():
                return bundled
        return Path(sys.executable).parent / "RuntimeData"
    return Path(__file__).resolve().parent.parent.parent / "RuntimeData"


def shared_dir() -> Path:
    """Return the shared data directory (cross-library)."""
    d = runtime_root() / "Shared"
    d.mkdir(parents=True, exist_ok=True)
    return d


def library_data_dir(library_root: str) -> Path:
    """Return the data directory for a specific library."""
    name = library_data_name(library_root)
    return runtime_root() / name if name else runtime_root() / "_temp"


def library_data_name(library_root: str) -> str:
    """Return a stable, collision-resistant data directory name."""
    if not library_root:
        return ""
    resolved = str(Path(library_root).resolve())
    base = Path(resolved).name or "library"
    digest = hashlib.sha256(resolved.casefold().encode("utf-8")).hexdigest()[:10]
    return f"{base}_{digest}"


def legacy_library_data_dir(library_root: str) -> Path:
    """Return the pre-hash data directory used by older versions."""
    name = Path(library_root).resolve().name if library_root else ""
    return runtime_root() / name if name else runtime_root() / "_temp"


def thumb_dir(library_root: str) -> Path:
    """Return the thumbnail cache directory for a library."""
    return library_data_dir(library_root) / ".thumbnails"


def favorites_path(library_root: str) -> Path:
    """Return the favorites JSON path for a library."""
    return library_data_dir(library_root) / "favorites.json"


def recent_path(library_root: str) -> Path:
    """Return the recent folders JSON path for a library."""
    return library_data_dir(library_root) / "recent.json"


def db_path(library_root: str) -> Path:
    """Return the SQLite database path for a library."""
    return library_data_dir(library_root) / "assetmanager.db"


def plugins_root() -> Path:
    """Return the Plugins/ directory (sibling of RuntimeData/)."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / "Plugins"
    return Path(__file__).resolve().parent.parent.parent / "Plugins"


def addons_dir() -> Path:
    """Return the addons subdirectory (Plugins/Addons/)."""
    d = plugins_root() / "Addons"
    d.mkdir(parents=True, exist_ok=True)
    return d


def plugins_docs_dir() -> Path:
    """Return the plugins docs directory (Plugins/Docs/)."""
    d = plugins_root() / "Docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def themes_dir() -> Path:
    """Return the Assets/Themes/ directory (sibling of RuntimeData/)."""
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            bundled = Path(meipass) / "Assets" / "Themes"
            if bundled.exists():
                return bundled
        return Path(sys.executable).parent / "Assets" / "Themes"
    return Path(__file__).resolve().parent.parent.parent / "Assets" / "Themes"
