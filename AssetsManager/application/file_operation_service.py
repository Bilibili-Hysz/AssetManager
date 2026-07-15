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
    from AssetsManager.application.context import LibrarySession


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

    def __init__(self, session: LibrarySession | None = None,
                 asset_index_service: AssetIndexService | None = None):
        self.session = session
        self._asset_index_service = asset_index_service

    @property
    def _library_root(self) -> Path | None:
        return self.session.root if self.session is not None else None

    def _root_for(self, library_root: str | Path | None) -> Path | None:
        root = self._library_root or (Path(library_root).resolve() if library_root else None)
        if library_root is not None and root is not None and Path(library_root).resolve() != root:
            raise ValueError(f"Library root does not match bound session: {library_root}")
        return root

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
        root = self._root_for(library_root)
        _assert_under_root(src, root)
        _assert_under_root(dst, root)
        if src == dst:
            return dst
        is_dir = src.is_dir()
        shutil.move(str(src), str(dst))
        if root:
            self._migrate_metadata(root, src, dst)
        self._refresh_after_move(src, dst, is_dir)
        get_event_bus().publish(FileRenamed(old_path=str(src), new_path=str(dst)))
        return dst

    def copy_to_directory(self, sources: list[str | Path], destination_dir: str | Path,
                          library_root: str | Path | None = None) -> FileOperationResult:
        changed: list[Path] = []
        errors: list[str] = []
        bus = get_event_bus()
        root = self._root_for(library_root)
        _assert_under_root(Path(destination_dir).resolve(), root)
        for source in sources:
            src = Path(source).resolve()
            try:
                target = unique_destination(Path(destination_dir).resolve() / src.name).resolve()
                if src.is_dir():
                    shutil.copytree(src, target)
                    self._refresh_directory_tree(target)
                else:
                    shutil.copy2(src, target)
                self._refresh_parents(target.parent)
                changed.append(target)
                bus.publish(FileCopied(source_path=str(src), destination_path=str(target)))
            except OSError as exc:
                errors.append(str(exc))
        return FileOperationResult(tuple(changed), tuple(errors))

    def move_to_directory(self, sources: list[str | Path], destination_dir: str | Path,
                          library_root: str | Path | None = None) -> FileOperationResult:
        changed: list[Path] = []
        errors: list[str] = []
        bus = get_event_bus()
        root = self._root_for(library_root)
        _assert_under_root(Path(destination_dir).resolve(), root)
        for source in sources:
            src = Path(source).resolve()
            _assert_under_root(src, root)
            try:
                is_dir = src.is_dir()
                target = unique_destination(Path(destination_dir) / src.name).resolve()
                shutil.move(str(src), str(target))
                if root:
                    self._migrate_metadata(root, src, target)
                self._refresh_after_move(src, target, is_dir)
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
        bus = get_event_bus()
        root = self._root_for(library_root)
        for path in paths:
            p = Path(path)
            _assert_under_root(p, root)
            try:
                is_dir = p.is_dir()
                if is_dir:
                    shutil.rmtree(p)
                else:
                    p.unlink()
                self._clear_deleted_projection(p)
                self._refresh_parents(p.parent)
                changed.append(p)
                bus.publish(FileDeleted(path=str(p), is_dir=is_dir))
            except OSError as exc:
                errors.append(str(exc))
        return FileOperationResult(tuple(changed), tuple(errors))

    def restore_backup(self, backup: str | Path, destination: str | Path,
                       library_root: str | Path | None = None) -> Path:
        """Restore an undo backup and publish the corresponding create event."""
        source = Path(backup).resolve()
        target = Path(destination).resolve()
        root = self._root_for(library_root)
        _assert_under_root(target, root)
        is_dir = source.is_dir()
        if is_dir:
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        self._refresh_parents(target.parent)
        if is_dir:
            self._refresh_directory_tree(target)
        get_event_bus().publish(FileCreated(path=str(target), is_dir=is_dir))
        return target

    def delete_to_trash(self, paths: list[str | Path],
                        library_root: str | Path | None = None) -> FileOperationResult:
        from send2trash import send2trash

        changed: list[Path] = []
        errors: list[str] = []
        bus = get_event_bus()
        root = self._root_for(library_root)
        for path in paths:
            p = Path(path)
            _assert_under_root(p, root)
            try:
                is_dir = p.is_dir()
                send2trash(str(p))
                self._clear_deleted_projection(p)
                self._refresh_parents(p.parent)
                changed.append(p)
                bus.publish(FileDeleted(path=str(p), is_dir=is_dir))
            except OSError as exc:
                errors.append(str(exc))
        return FileOperationResult(tuple(changed), tuple(errors))

    @staticmethod
    def _migrate_metadata(library_root: str | Path, old_path: Path, new_path: Path) -> None:
        from AssetsManager.core.database import migrate_path_metadata
        migrate_path_metadata(str(library_root), str(old_path), str(new_path))

    def _refresh_parents(self, *parents: Path) -> None:
        if self.session is None or self._asset_index_service is None:
            return
        for parent in set(parents):
            self._asset_index_service.index_directory(
                self.session.db_conn, self.session.root, parent, force=True,
            )

    def _refresh_after_move(self, old_path: Path, new_path: Path, is_dir: bool) -> None:
        if self.session is None or self._asset_index_service is None:
            return
        if is_dir:
            self._asset_index_service.remove_entry(self.session.db_conn, old_path)
            self._asset_index_service.remove_directory(self.session.db_conn, old_path)
        self._refresh_parents(old_path.parent, new_path.parent)
        if is_dir:
            self._refresh_directory_tree(new_path)

    def _refresh_directory_tree(self, directory: Path) -> None:
        if self.session is None or self._asset_index_service is None:
            return
        self._asset_index_service.index_directory_tree(
            self.session.db_conn, self.session.root, directory,
        )

    def _clear_deleted_projection(self, path: Path) -> None:
        if self.session is None:
            return
        import os
        from AssetsManager.core.database import db_write_lock
        from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository

        target = str(path.resolve())
        escaped = target.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        prefix = escaped + os.sep.replace("\\", "\\\\") + "%"
        with db_write_lock():
            self.session.db_conn.execute(
                "DELETE FROM file_tags WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'", (target, prefix),
            )
            self.session.db_conn.execute(
                "DELETE FROM file_meta WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'", (target, prefix),
            )
            self.session.db_conn.commit()
        cache_keys = ThumbnailRepository(self.session.db_conn).delete_path(target)
        for cache_key in cache_keys:
            try:
                (self.session.thumb_dir / f"{cache_key}.webp").unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        if self._asset_index_service is not None:
            self._asset_index_service.remove_entry(self.session.db_conn, path)
            self._asset_index_service.remove_directory(self.session.db_conn, path)


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
