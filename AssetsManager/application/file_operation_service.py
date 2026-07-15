"""File operation application service."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import FileCopied, FileCreated, FileDeleted, FileRenamed

if TYPE_CHECKING:
    from AssetsManager.application.asset_index_service import AssetIndexService
    from AssetsManager.application.context import ConnectionProvider


@dataclass(frozen=True)
class FileOperationResult:
    changed_paths: tuple[Path, ...]
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def _assert_under_root(path: Path, root: str | Path | None) -> None:
    if root is not None and not Path(path).resolve().is_relative_to(Path(root)):
        raise ValueError(f'Path {path} is outside library root')


class FileOperationService:
    """Filesystem operations shared by desktop actions and future APIs."""

    def __init__(
        self,
        asset_index_service: AssetIndexService | None = None,
        connection_provider: ConnectionProvider | None = None,
        library_root: str | Path | None = None,
    ):
        self._asset_index_service = asset_index_service
        self._connection_provider = connection_provider
        self._library_root = Path(library_root).resolve() if library_root else None

    def create_folder(self, parent: str | Path, name: str = "New Folder") -> Path:
        base = Path(parent) / name
        for _ in range(100):
            target = unique_destination(base)
            try:
                target.mkdir()
                get_event_bus().publish(FileCreated(path=str(target), is_dir=True))
                return target
            except FileExistsError:
                base = target
        raise OSError(f"Could not create unique folder under {parent}")

    def rename(self, old_path: str | Path, new_name: str,
               library_root: str | Path | None = None) -> Path:
        old = Path(old_path).resolve()
        dst = (old.parent / new_name).resolve()
        if dst.parent != old.parent:
            raise ValueError("New name must stay in the original directory")
        result = self.move(old, dst, library_root=library_root)
        return result

    def move(self, source: str | Path, destination: str | Path,
             library_root: str | Path | None = None) -> Path:
        src = Path(source).resolve()
        dst = Path(destination).resolve()
        _assert_under_root(src, library_root)
        _assert_under_root(dst, library_root)
        if src == dst:
            return dst
        source_is_dir = src.is_dir()
        shutil.move(str(src), str(dst))
        if library_root:
            self._migrate_metadata(library_root, src, dst)
            self._reconcile_renamed(src, dst, source_is_dir, library_root)
        get_event_bus().publish(FileRenamed(old_path=str(src), new_path=str(dst)))
        return dst

    def copy_to_directory(self, sources: list[str | Path], destination_dir: str | Path,
                          library_root: str | Path | None = None) -> FileOperationResult:
        changed: list[Path] = []
        errors: list[str] = []
        bus = get_event_bus()
        root = self._resolve_library_root(library_root)
        _assert_under_root(Path(destination_dir).resolve(), root)
        for source in sources:
            src = Path(source).resolve()
            _assert_under_root(src, root)
            try:
                target = unique_destination(Path(destination_dir).resolve() / src.name).resolve()
                if src.is_dir():
                    shutil.copytree(src, target)
                else:
                    shutil.copy2(src, target)
                changed.append(target)
                if src.is_dir() and root and self._asset_index_service and self._connection_provider:
                    conn = self._connection_provider(root)
                    self._asset_index_service.index_directory(conn, root, target.parent, force=True)
                    self._asset_index_service.index_directory_tree(
                        conn, root, target
                    )
                bus.publish(FileCopied(source_path=str(src), destination_path=str(target)))
            except OSError as exc:
                errors.append(str(exc))
        return FileOperationResult(tuple(changed), tuple(errors))

    def move_to_directory(self, sources: list[str | Path], destination_dir: str | Path,
                          library_root: str | Path | None = None) -> FileOperationResult:
        changed: list[Path] = []
        errors: list[str] = []
        bus = get_event_bus()
        root = self._resolve_library_root(library_root)
        _assert_under_root(Path(destination_dir).resolve(), root)
        for source in sources:
            src = Path(source).resolve()
            _assert_under_root(src, root)
            try:
                target = unique_destination(Path(destination_dir) / src.name).resolve()
                shutil.move(str(src), str(target))
                if library_root:
                    self._migrate_metadata(library_root, src, target)
                changed.append(target)
                bus.publish(FileRenamed(old_path=str(src), new_path=str(target)))
            except OSError as exc:
                errors.append(str(exc))
        return FileOperationResult(tuple(changed), tuple(errors))

    def duplicate(self, path: str | Path, copy_label: str = "_copy") -> Path:
        src = Path(path)
        target = unique_destination(src.with_name(f"{src.stem}{copy_label}{src.suffix}"))
        if src.is_dir():
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)
        get_event_bus().publish(FileCreated(path=str(target), is_dir=target.is_dir()))
        return target

    def delete_permanent(self, paths: list[str | Path],
                         library_root: str | Path | None = None) -> FileOperationResult:
        changed: list[Path] = []
        errors: list[str] = []
        root = self._resolve_library_root(library_root)
        for path in paths:
            p = Path(path)
            _assert_under_root(p, root)
            try:
                is_dir = p.is_dir()
                if is_dir:
                    shutil.rmtree(p)
                else:
                    p.unlink()
                changed.append(p)
                self.reconcile_deleted(p, is_dir, library_root=root)
            except OSError as exc:
                errors.append(str(exc))
        return FileOperationResult(tuple(changed), tuple(errors))

    def delete_to_trash(self, paths: list[str | Path]) -> FileOperationResult:
        from send2trash import send2trash

        changed: list[Path] = []
        errors: list[str] = []
        for path in paths:
            p = Path(path)
            try:
                is_dir = p.is_dir()
                send2trash(str(p))
                changed.append(p)
                self.reconcile_deleted(p, is_dir)
            except OSError as exc:
                errors.append(str(exc))
        return FileOperationResult(tuple(changed), tuple(errors))

    @staticmethod
    def _migrate_metadata(library_root: str | Path, old_path: Path, new_path: Path) -> None:
        from AssetsManager.core.database import migrate_path_metadata
        migrate_path_metadata(str(library_root), str(old_path), str(new_path))

    def reconcile_created(self, path: str | Path, is_dir: bool | None = None,
                          library_root: str | Path | None = None) -> None:
        """Refresh projections and notify subscribers after a file is restored."""
        target = Path(path).resolve()
        directory = target.is_dir() if is_dir is None else is_dir
        self._index_directory(target.parent, library_root)
        if directory:
            self._index_directory_tree(target, library_root)
        get_event_bus().publish(FileCreated(path=str(target), is_dir=directory))

    def reconcile_deleted(self, path: str | Path, is_dir: bool,
                          library_root: str | Path | None = None) -> None:
        """Remove stale projections and notify subscribers after deletion."""
        target = Path(path).resolve()
        root = self._resolve_library_root(library_root)
        if root is not None and self._connection_provider is not None:
            conn = self._connection_provider(root)
            self._delete_metadata_and_thumbnails(conn, target, root)
            if self._asset_index_service is not None:
                self._asset_index_service.remove_entry(conn, target)
                if is_dir:
                    self._asset_index_service.remove_directory(conn, target)
                self._asset_index_service.index_directory(conn, root, target.parent, force=True)
        get_event_bus().publish(FileDeleted(path=str(target), is_dir=is_dir))

    def _reconcile_renamed(self, source: Path, destination: Path, source_is_dir: bool,
                           library_root: str | Path) -> None:
        """Refresh the index after moving an entry within a library."""
        root = self._resolve_library_root(library_root)
        if root is None or self._asset_index_service is None or self._connection_provider is None:
            return
        conn = self._connection_provider(root)
        self._asset_index_service.remove_entry(conn, source)
        if source_is_dir:
            self._asset_index_service.remove_directory(conn, source)
        self._asset_index_service.index_directory(conn, root, source.parent, force=True)
        self._asset_index_service.index_directory(conn, root, destination.parent, force=True)
        if source_is_dir:
            self._asset_index_service.index_directory_tree(conn, root, destination)

    def _index_directory(self, directory: Path, library_root: str | Path | None) -> None:
        root = self._resolve_library_root(library_root)
        if root is None or self._asset_index_service is None or self._connection_provider is None:
            return
        self._asset_index_service.index_directory(
            self._connection_provider(root), root, directory, force=True,
        )

    def _index_directory_tree(self, directory: Path, library_root: str | Path | None) -> None:
        root = self._resolve_library_root(library_root)
        if root is None or self._asset_index_service is None or self._connection_provider is None:
            return
        self._asset_index_service.index_directory_tree(self._connection_provider(root), root, directory)

    @staticmethod
    def _delete_metadata_and_thumbnails(conn, path: Path, library_root: Path) -> None:
        """Delete database and disk cache projections for a removed path subtree."""
        from AssetsManager.core.path_resolver import thumb_dir

        target = str(path)
        escaped = target.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        descendant = escaped + os.sep.replace("\\", "\\\\") + "%"
        rows = conn.execute(
            "SELECT cache_key FROM thumbnail_cache WHERE source_path=? OR source_path LIKE ? ESCAPE '\\'",
            (target, descendant),
        ).fetchall()
        conn.execute(
            "DELETE FROM file_tags WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
            (target, descendant),
        )
        conn.execute(
            "DELETE FROM file_meta WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
            (target, descendant),
        )
        conn.execute(
            "DELETE FROM thumbnail_cache WHERE source_path=? OR source_path LIKE ? ESCAPE '\\'",
            (target, descendant),
        )
        conn.commit()
        for (cache_key,) in rows:
            try:
                (thumb_dir(library_root) / f"{cache_key}.webp").unlink()
            except OSError:
                pass

    def _resolve_library_root(self, library_root: str | Path | None) -> Path | None:
        if library_root is None:
            return self._library_root
        root = Path(library_root).resolve()
        if self._library_root is not None and root != self._library_root:
            raise ValueError(f"Library root does not match bound service: {library_root}")
        return root


def unique_destination(path: str | Path) -> Path:
    """Return a non-existing path by appending `_1`, `_2`, ... if needed.

    For numbered suffixes, the name is atomically reserved via
    ``os.open(O_CREAT | O_EXCL)`` to avoid TOCTOU races.
    """
    candidate = Path(path)
    if not candidate.exists():
        return candidate
    base = candidate.stem
    suffix = candidate.suffix
    parent = candidate.parent
    index = 1
    while True:
        candidate = parent / f"{base}_{index}{suffix}"
        if _try_reserve(candidate):
            return candidate
        index += 1


def _try_reserve(path: Path) -> bool:
    """Atomically create *path* as an empty file; return True on success.

    Uses ``O_CREAT | O_EXCL`` so the kernel rejects the call if the file
    already exists — no check-then-act race.  The file is deleted
    immediately after creation; callers must create the real content
    promptly (the window is milliseconds, acceptable for desktop use).
    """
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        path.unlink()
        return True
    except FileExistsError:
        return False
    except OSError:
        return False
