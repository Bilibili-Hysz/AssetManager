"""Desktop port interfaces (Protocol) and root-bound tag adapter.

Panel code depends on these ports instead of concrete services so the
presentation layer only sees the narrow slice of each service it actually
uses.  The adapters keep the same root-bound / root-first calling
conventions the panels already relied on through ``TagServiceAdapter``.

Usage (type annotation):
    from AssetsManager.application.desktop_ports import TagsViewPort
    def update_tags(port: TagsViewPort): ...

Usage (runtime check):
    from AssetsManager.application.desktop_ports import TagsViewPort
    assert isinstance(port, TagsViewPort)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TagsViewPort(Protocol):
    """Root-bound tag operations used by tag editors and the details view.

    Mirrors ``TagStoreProtocol``: every method is already bound to a single
    library root, so callers never pass a ``library_root`` argument.
    """

    def get_tags(self, filepath: str) -> list[str]:
        """Return tags for a file."""
        ...

    def get_tags_for_files(self, filepaths: list[str]) -> dict[str, list[str]]:
        """Return tags for many files keyed by resolved file path."""
        ...

    def add_tag(self, filepath: str, tag: str) -> None:
        """Add a tag to a file."""
        ...

    def remove_tag(self, filepath: str, tag: str) -> None:
        """Remove a tag from a file."""
        ...

    def remove_file(self, filepath: str) -> None:
        """Remove all tags for a file."""
        ...

    def get_all_tags(self) -> list[str]:
        """Return all unique tags."""
        ...

    def get_files_by_tag(self, tag: str) -> set[str]:
        """Return all file paths that have a given tag."""
        ...

    def get_tag_metadata(self, tag: str) -> dict[str, str] | None:
        """Return a tag's color/icon/category metadata, or None."""
        ...

    def save(self) -> None:
        """Persist pending changes."""
        ...


@runtime_checkable
class ShareSettingsPort(Protocol):
    """LAN utility surface used by the sharing-settings dialog.

    Implemented by ``AssetsManager.lan.ports.LanDesktopAdapter`` and
    injected by the desktop composition root, so dialog code never imports
    the ``lan`` package directly.
    """

    def tunnel_is_available(self) -> bool:
        """Return True when cloudflared can be used without downloading."""
        ...

    def ensure_tunnel_available(self) -> str | None:
        """Make cloudflared available, downloading it when possible."""
        ...

    def local_ip(self) -> str:
        """Return the best reachable LAN IP for share-link URLs."""
        ...

    def auth_headers(self, token_secret: str) -> dict[str, str]:
        """Return Authorization headers for local API polling."""
        ...


@runtime_checkable
class LanControlPort(Protocol):
    """Narrow lifecycle surface desktop widgets use on a running LAN server.

    ``AssetsManager.lan.LanServer`` satisfies this protocol.  The
    ``_port``/``_bind``/``_impl`` members are transitional facade details
    still used by the sharing mixin; new call sites should prefer the
    documented methods.
    """

    def start(self, port: int = 8080, bind: str = "0.0.0.0", *,
              preflight: Any = None) -> dict[str, Any] | None: ...

    def stop(self) -> None: ...

    def is_running(self) -> bool: ...

    def status(self) -> dict[str, Any]: ...

    def reload_settings(self, settings: dict[str, Any]) -> None: ...

    def auth_status(self) -> tuple[bool, str]: ...

    def start_tunnel(self, timeout: int = 30) -> str | None: ...

    def stop_tunnel(self) -> None: ...

    def is_tunnel_running(self) -> bool: ...

    @property
    def tunnel_start_block_reason(self) -> str | None: ...

    @property
    def token_secret(self) -> str: ...

    @property
    def tunnel(self) -> Any: ...

    @property
    def _port(self) -> int: ...

    @property
    def _bind(self) -> str: ...

    _impl: Any


class LanServerFactory(Protocol):
    """Constructor boundary for LAN server instances."""

    def __call__(self, runtime: Any, *, preflight: Any = None,
                 **options: Any) -> LanControlPort: ...


class FallbackShareSettingsPort:
    """Dependency-free ShareSettingsPort defaults for unattached dialogs.

    Production windows inject the real LAN adapter; these defaults keep
    standalone dialog construction safe (no tunnel card, loopback URLs,
    and no fabricated Authorization headers).
    """

    def tunnel_is_available(self) -> bool:
        return False

    def ensure_tunnel_available(self) -> str | None:
        return None

    def local_ip(self) -> str:
        return "127.0.0.1"

    def auth_headers(self, token_secret: str) -> dict[str, str]:
        return {}


@runtime_checkable
class MetadataViewPort(Protocol):
    """Root-first metadata operations used by the info panel.

    Unlike the tag ports, ``MetadataService`` keeps ``library_root`` as the
    leading argument, so these methods mirror that convention verbatim.
    """

    def get_dir_size(self, library_root: str | Path, dir_path: str | Path,
                     force: bool = False) -> tuple[int, bool]:
        """Return (size, was_cached) for a directory under ``library_root``."""
        ...


@runtime_checkable
class FileOpsViewPort(Protocol):
    """Session-bound file operations used by the file-list panel.

    ``FileOperationService`` is already bound to a ``LibrarySession``, so
    ``library_root`` is an optional consistency check rather than a scope
    selector.  The method surface is limited to exactly what the panel and
    its undo/redo wiring call.
    """

    def move(self, source: str | Path, destination: str | Path,
             library_root: str | Path | None = None):
        ...

    def move_to_directory(self, sources: list[str | Path], destination_dir: str | Path,
                          library_root: str | Path | None = None):
        ...

    def copy_to_directory(self, sources: list[str | Path], destination_dir: str | Path,
                          library_root: str | Path | None = None):
        ...

    def create_folder(self, parent: str | Path, name: str = "New Folder"):
        ...

    def duplicate(self, path: str | Path, copy_label: str = "_copy"):
        ...

    def delete_permanent(self, paths: list[str | Path],
                         library_root: str | Path | None = None):
        ...

    def delete_to_trash(self, paths: list[str | Path],
                        library_root: str | Path | None = None):
        ...

    def restore_backup(self, backup: str | Path, destination: str | Path,
                       library_root: str | Path | None = None):
        ...

    @property
    def last_operation_id(self) -> str | None:
        """Return the most recent command id observed on this thread."""
        ...

    def drain_refresh_diagnostics(self, operation_id: str | None = None):
        """Consume completed refresh diagnostics."""
        ...


class RootBoundTagService:
    """Bind a root-per-call ``TagService`` to one library root.

    ``TagEditorDialog`` and the details view expect a ``TagStore``-like
    object (a ``TagsViewPort``); this adapter wraps ``TagService`` so those
    consumers can use it without knowing about ``library_root``.
    """

    def __init__(self, library_root: str | Path, svc=None):
        self._root = str(Path(library_root).resolve())
        if svc is None:
            from AssetsManager.application.tag_service import TagService
            svc = TagService()
        self._svc = svc

    def get_tags(self, filepath: str) -> list[str]:
        return self._svc.get_tags(self._root, filepath)

    def get_tags_for_files(self, filepaths: list[str]) -> dict[str, list[str]]:
        return self._svc.get_tags_for_files(self._root, filepaths)

    def add_tag(self, filepath: str, tag: str) -> None:
        self._svc.add_tag(self._root, filepath, tag)

    def remove_tag(self, filepath: str, tag: str) -> None:
        self._svc.remove_tag(self._root, filepath, tag)

    def remove_file(self, filepath: str) -> None:
        self._svc.remove_file(self._root, filepath)

    def get_all_tags(self) -> list[str]:
        return self._svc.get_all_tags(self._root)

    def get_files_by_tag(self, tag: str) -> set[str]:
        return self._svc.get_files_by_tag(self._root, tag)

    def get_tag_metadata(self, tag: str) -> dict[str, str] | None:
        return self._svc.get_tag_metadata(self._root, tag)

    def save(self) -> None:
        pass  # auto-commit
