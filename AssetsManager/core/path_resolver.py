"""PathResolver — resolves library-specific paths for data storage."""
import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RootIdentity:
    """Immutable identity captured once for a library lifecycle."""

    display_path: Path
    map_key: str

    def __fspath__(self) -> str:
        return str(self.display_path)

    def __str__(self) -> str:
        return str(self.display_path)


SQL_LIKE_ESCAPE = "\\"

# Deterministic slot for degenerate/empty roots.  A plain ``_temp`` name is
# shared by every empty-root caller and can collide with a real library slot;
# a hashed ``_empty_`` slot is independent of all hashed library slots while
# still resolving deterministically across calls and processes.
_EMPTY_ROOT_SLOT_NAME = "_empty_" + hashlib.sha256(b"__empty__").hexdigest()[:10]


def _identity_marker_owner(marker: Path) -> str | None:
    """Return the map_key recorded by a regular identity marker, else None.

    Missing markers, non-regular entries (e.g. a corrupt marker directory),
    and unreadable markers all yield ``None`` so the database layer's own
    formal-marker validation remains the authority for corrupt slots.
    """
    try:
        if not marker.is_file():
            return None
        return marker.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def path_key_separator(path: str | Path, *, default: str | None = None) -> str:
    """Return the separator represented by a stored file-path key.

    Database path keys historically follow the platform/caller representation
    (``\\`` on Windows and ``/`` in portable fixtures).  Preserve that
    representation for subtree predicates instead of hard-coding one style.
    Mixed keys use the last separator as the least-surprising boundary.
    """
    value = os.fspath(path)
    if not isinstance(value, str):
        value = os.fsdecode(value)
    slash = value.rfind("/")
    backslash = value.rfind("\\")
    if slash < 0 and backslash < 0:
        return default or os.sep
    return "\\" if backslash > slash else "/"


def escape_sql_like(value: str, *, escape: str = SQL_LIKE_ESCAPE) -> str:
    """Escape a SQLite LIKE value while keeping ``%`` as the wildcard caller."""
    return (
        value.replace(escape, escape + escape)
        .replace("%", escape + "%")
        .replace("_", escape + "_")
    )


def sql_like_descendant_pattern(path: str | Path) -> str:
    """Return an escaped LIKE pattern for ``path`` and its descendants only."""
    value = os.fspath(path)
    if not isinstance(value, str):
        value = os.fsdecode(value)
    separator = path_key_separator(value)
    return escape_sql_like(value) + escape_sql_like(separator) + "%"


def remap_path_subtree(old_path: str | Path, new_path: str | Path, path: str | Path) -> str:
    """Map one path key from an old subtree to a new subtree boundary."""
    old = os.fsdecode(os.fspath(old_path))
    new = os.fsdecode(os.fspath(new_path))
    current = os.fsdecode(os.fspath(path))
    if current == old:
        return new
    prefix = old + path_key_separator(old)
    return new + current[len(old):] if current.startswith(prefix) else current


def root_identity(
    root_path: str | Path | RootIdentity, *, strict: bool = True
) -> RootIdentity:
    """Resolve a root once, optionally allowing legacy lexical fallback.

    Lifecycle owners use the strict default. Low-level path/database compatibility
    helpers may request ``strict=False`` for synthetic or not-yet-created paths;
    those callers do not establish process-level ownership.
    """
    if isinstance(root_path, RootIdentity):
        return root_path
    candidate = Path(root_path)
    try:
        absolute = Path(os.path.abspath(os.path.normpath(str(candidate))))
        if not absolute.exists():
            absolute.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        if strict:
            raise RuntimeError(f"Cannot establish library root identity: {root_path}") from exc
    normalized = os.path.normpath(os.path.abspath(str(absolute)))
    return RootIdentity(Path(normalized), os.path.normcase(normalized))


def user_data_root() -> Path:
    """Return the application data root directory (portable, exe-adjacent).

    Frozen builds — both the single-file executable and the onedir bundle —
    keep all writable data NEXT TO the executable so the app is fully
    portable: ``Path(sys.executable).parent`` is the directory the exe sits in
    for onefile, and the ``dist/AssetManager`` directory (beside ``_internal``)
    for onedir.  Moving the executable moves its data with it.  Development
    runs keep the repository-local layout unchanged for zero-surprise parity.

    The portable contract assumes the install directory is writable (a green
    folder the user owns, or the per-user ``{localappdata}\\Programs`` install
    root).  A read-only location (e.g. Program Files) would make this fail; by
    design the app does not silently relocate data to a hidden per-user path.
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def runtime_root() -> Path:
    """Return the application's runtime data root directory."""
    return user_data_root() / "RuntimeData"


def shared_dir() -> Path:
    """Return the shared data directory (cross-library)."""
    d = runtime_root() / "Shared"
    d.mkdir(parents=True, exist_ok=True)
    return d


SHARED_DIR = shared_dir()


def library_data_dir(library_root: str | Path | RootIdentity) -> Path:
    """Return the data directory for a specific library."""
    name = library_data_name(library_root)
    return runtime_root() / name if name else runtime_root() / _EMPTY_ROOT_SLOT_NAME


def library_data_name(library_root: str | Path | RootIdentity) -> str:
    """Return a stable data directory name guarded by a full identity marker.

    The primary name keeps the historical 40-bit digest so existing libraries
    keep resolving to their already-created RuntimeData slots.  When a foreign
    identity marker *and* its data directory already occupy that primary slot
    (two roots sharing basename and digest), a deterministic secondary name
    (``-2``, ``-3``, ...) is probed instead of failing the open, giving each
    colliding root its own independent slot.  A marker without its data
    directory is left to the database layer's formal-marker validation, which
    keeps the fail-closed contract for stale or corrupt marker states.
    """
    if not library_root:
        return ""
    identity = root_identity(library_root, strict=False)
    base = identity.display_path.name or "library"
    digest = hashlib.sha256(identity.map_key.encode("utf-8")).hexdigest()[:10]
    primary = f"{base}_{digest}"
    marker_dir = runtime_root() / "Shared"
    candidate = primary
    suffix = 2
    owner = _identity_marker_owner(marker_dir / f"{candidate}.identity")
    while (
        owner is not None
        and owner != identity.map_key
        and (runtime_root() / candidate).is_dir()
    ):
        candidate = f"{primary}-{suffix}"
        suffix += 1
        owner = _identity_marker_owner(marker_dir / f"{candidate}.identity")
    return candidate


def library_data_identity_path(library_root: str | Path | RootIdentity) -> Path:
    """Return the collision guard marker for one hashed RuntimeData slot."""
    identity = root_identity(library_root, strict=False)
    return runtime_root() / "Shared" / f"{library_data_name(identity)}.identity"


def library_lock_path(library_root: str | Path | RootIdentity) -> Path:
    """Return the cross-process lock path for one canonical library root.

    The lock lives under ``RuntimeData/Shared`` so acquiring it never creates
    or changes a library's data directory before ``DatabaseManager`` has had
    a chance to perform its legacy-directory migration.
    """
    identity = root_identity(library_root, strict=False)
    digest = hashlib.sha256(identity.map_key.encode("utf-8")).hexdigest()[:16]
    return runtime_root() / "Shared" / f"library-{digest}.lock"


def legacy_library_data_dir(library_root: str | Path | RootIdentity) -> Path:
    """Return the pre-hash data directory used by older versions."""
    name = root_identity(library_root, strict=False).display_path.name if library_root else ""
    return runtime_root() / name if name else runtime_root() / _EMPTY_ROOT_SLOT_NAME


def thumb_dir(library_root: str | Path | RootIdentity) -> Path:
    """Return the thumbnail cache directory for a library."""
    return library_data_dir(library_root) / ".thumbnails"


def favorites_path(library_root: str) -> Path:
    """Return the favorites JSON path for a library."""
    return library_data_dir(library_root) / "favorites.json"


def recent_path(library_root: str) -> Path:
    """Return the recent folders JSON path for a library."""
    return library_data_dir(library_root) / "recent.json"


def db_path(library_root: str | Path | RootIdentity) -> Path:
    """Return the SQLite database path for a library."""
    return library_data_dir(library_root) / "assetmanager.db"


def plugins_root() -> Path:
    """Return the writable Plugins/ directory (user extension location).

    Frozen builds keep user plugins next to the executable (portable) so they
    follow the data root; development keeps the repository ``Plugins/``
    directory unchanged.
    """
    if getattr(sys, 'frozen', False):
        return user_data_root() / "Plugins"
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


def builtin_plugins_addons_dir() -> Path | None:
    """Return the bundled read-only seed-plugin Addons directory, if separate.

    Seed plugins are bundled under ``_MEIPASS/Plugins`` (spec datas mirror the
    repository layout); the plugin manager scans them as an extra read-only
    source in addition to the writable user extension locations.  Returns None
    when no separate bundled source exists (development, where the repository
    ``Plugins/Addons`` is already ``addons_dir()``, or a layout without a
    bundled Plugins/ tree).
    """
    if not getattr(sys, 'frozen', False):
        return None
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        bundled = Path(meipass) / "Plugins" / "Addons"
        if bundled.is_dir():
            return bundled
    legacy = Path(sys.executable).parent / "Plugins" / "Addons"
    return legacy if legacy.is_dir() else None


def themes_dir() -> Path:
    """Return the writable user themes directory.

    Frozen builds store user themes next to the executable (portable) under
    the data root — in onefile the bundled ``_MEIPASS`` location is a
    session-scoped temp directory and must never be written to.  Development
    keeps the repository ``Assets/Themes`` directory (built-in + user themes
    coexist) unchanged.  Built-in read-only themes are resolved separately
    (builtin_themes_dir()).
    """
    if getattr(sys, 'frozen', False):
        d = user_data_root() / "Themes"
        d.mkdir(parents=True, exist_ok=True)
        return d
    return Path(__file__).resolve().parent.parent.parent / "Assets" / "Themes"


def builtin_themes_dir() -> Path | None:
    """Return the bundled read-only built-in themes directory, if separate.

    In frozen builds the built-in themes are bundled under ``_MEIPASS``
    (PyInstaller datas mirror the repository layout): onefile extracts to a
    session-scoped temp directory, onedir (>=6.x) to the ``_internal``
    directory.  In development built-in and user themes share ``Assets/Themes``,
    so there is no separate built-in source (returns None).
    """
    if not getattr(sys, 'frozen', False):
        return None
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        bundled = Path(meipass) / "Assets" / "Themes"
        if bundled.is_dir():
            return bundled
    legacy = Path(sys.executable).parent / "Assets" / "Themes"
    return legacy if legacy.is_dir() else None
