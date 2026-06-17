"""File operation application service."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import FileCopied, FileCreated, FileDeleted, FileRenamed


@dataclass(frozen=True)
class FileOperationResult:
    changed_paths: tuple[Path, ...]
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


class FileOperationService:
    """Filesystem operations shared by desktop actions and future APIs."""

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
        if src == dst:
            return dst
        shutil.move(str(src), str(dst))
        if library_root:
            self._migrate_metadata(library_root, src, dst)
        get_event_bus().publish(FileRenamed(old_path=str(src), new_path=str(dst)))
        return dst

    def copy_to_directory(self, sources: list[str | Path], destination_dir: str | Path) -> FileOperationResult:
        changed: list[Path] = []
        errors: list[str] = []
        bus = get_event_bus()
        for source in sources:
            src = Path(source).resolve()
            try:
                target = unique_destination(Path(destination_dir).resolve() / src.name).resolve()
                if src.is_dir():
                    shutil.copytree(src, target)
                else:
                    shutil.copy2(src, target)
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
        for source in sources:
            src = Path(source).resolve()
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

    def delete_permanent(self, paths: list[str | Path]) -> FileOperationResult:
        changed: list[Path] = []
        errors: list[str] = []
        bus = get_event_bus()
        for path in paths:
            p = Path(path)
            try:
                is_dir = p.is_dir()
                if is_dir:
                    shutil.rmtree(p)
                else:
                    p.unlink()
                changed.append(p)
                bus.publish(FileDeleted(path=str(p), is_dir=is_dir))
            except OSError as exc:
                errors.append(str(exc))
        return FileOperationResult(tuple(changed), tuple(errors))

    def delete_to_trash(self, paths: list[str | Path]) -> FileOperationResult:
        from send2trash import send2trash

        changed: list[Path] = []
        errors: list[str] = []
        bus = get_event_bus()
        for path in paths:
            p = Path(path)
            try:
                is_dir = p.is_dir()
                send2trash(str(p))
                changed.append(p)
                bus.publish(FileDeleted(path=str(p), is_dir=is_dir))
            except OSError as exc:
                errors.append(str(exc))
        return FileOperationResult(tuple(changed), tuple(errors))

    @staticmethod
    def _migrate_metadata(library_root: str | Path, old_path: Path, new_path: Path) -> None:
        from AssetsManager.core.database import migrate_path_metadata
        migrate_path_metadata(str(library_root), str(old_path), str(new_path))


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
