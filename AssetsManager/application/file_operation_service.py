"""File operation application service."""
from __future__ import annotations

import os
import shutil
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from sqlite3 import Connection
from time import perf_counter
from typing import TYPE_CHECKING

from AssetsManager.application.context import session_operation
from AssetsManager.core.performance import PerformanceRecorder
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import (
    FileCopied, FileCreated, FileDeleted, FileRenamed, FileSystemChanged,
)

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


def _measure_command(command: str):
    """Record a public command only after its session lease has been acquired."""
    def decorate(method):
        @wraps(method)
        def measured(self, *args, **kwargs):
            depth = self._telemetry_depth()
            self._telemetry_local.depth = depth + 1
            started = perf_counter() if self._performance_recorder is not None else None
            try:
                result = method(self, *args, **kwargs)
            except Exception:
                if depth == 0 and not self._telemetry_suppressed():
                    self._record_command(command, started, "error", 0, "failed")
                raise
            finally:
                self._telemetry_local.depth = depth
            if depth == 0 and not self._telemetry_suppressed():
                errors = getattr(result, "errors", ())
                changed = getattr(result, "changed_paths", None)
                affected = len(changed) if changed is not None else 1
                self._record_command(
                    command,
                    started,
                    "partial" if errors else "success",
                    affected,
                    "events_published",
                )
            return result
        return measured
    return decorate


class FileOperationService:
    """Filesystem operations shared by desktop actions and future APIs."""

    def __init__(self, session: LibrarySession | None = None,
                  asset_index_service: AssetIndexService | None = None,
                  performance_recorder: PerformanceRecorder | None = None):
        self.session = session
        self._asset_index_service = asset_index_service
        self._performance_recorder = (
            performance_recorder if performance_recorder is not None and performance_recorder.enabled else None
        )
        self._telemetry_local = threading.local()

    def _telemetry_depth(self) -> int:
        return getattr(self._telemetry_local, "depth", 0)

    def _telemetry_suppressed(self) -> int:
        return getattr(self._telemetry_local, "suppressed", 0)

    @contextmanager
    def suppress_command_telemetry(self):
        """Let a higher-level command own telemetry for delegated file work."""
        suppressed = self._telemetry_suppressed()
        self._telemetry_local.suppressed = suppressed + 1
        try:
            yield
        finally:
            self._telemetry_local.suppressed = suppressed

    def _record_command(
        self, command: str, started: float | None, outcome: str, affected: int, phase: str
    ) -> None:
        if self._performance_recorder is None or started is None:
            return
        try:
            self._performance_recorder.record(
                "file.command",
                (perf_counter() - started) * 1000,
                session_token=self.session.event_token if self.session is not None else None,
                path=self.session.root_str if self.session is not None else None,
                attributes={
                    "command": command,
                    "outcome": outcome,
                    "affected_count": affected,
                    "phase": phase,
                },
            )
        except Exception:
            pass

    @property
    def _library_root(self) -> Path | None:
        return self.session.root if self.session is not None else None

    def _root_for(self, library_root: str | Path | None) -> Path | None:
        root = self._library_root or (Path(library_root).resolve() if library_root else None)
        if library_root is not None and root is not None and Path(library_root).resolve() != root:
            raise ValueError(f"Library root does not match bound session: {library_root}")
        return root

    def _connection(self) -> Connection:
        if self.session is None:
            raise RuntimeError("A bound session is required for projection updates")
        return self.session.connection_for(self.session.root)

    def _publish_file_change(
        self, kind: str, paths: tuple[Path, ...], old_paths: tuple[Path, ...] = ()
    ) -> None:
        if self.session is None:
            return
        get_event_bus().publish(FileSystemChanged(
            library_root=self.session.root_str,
            session_token=self.session.event_token,
            kind=kind,
            paths=tuple(str(path) for path in paths),
            old_paths=tuple(str(path) for path in old_paths),
        ))

    @session_operation
    @_measure_command("create_folder")
    def create_folder(self, parent: str | Path, name: str = "New Folder") -> Path:
        base = Path(parent) / name
        for _ in range(100):
            target = unique_destination(base)
            try:
                target.mkdir()
                self._refresh_parents(target.parent)
                self._refresh_directory_tree(target)
                get_event_bus().publish(FileCreated(path=str(target), is_dir=True))
                self._publish_file_change("created", (target,))
                return target
            except FileExistsError:
                base = target
        raise OSError(f"Could not create unique folder under {parent}")

    @session_operation
    @_measure_command("rename")
    def rename(self, old_path: str | Path, new_name: str,
               library_root: str | Path | None = None) -> Path:
        old = Path(old_path).resolve()
        dst = (old.parent / new_name).resolve()
        if dst.parent != old.parent:
            raise ValueError("New name must stay in the original directory")
        result = self.move(old, dst, library_root=library_root)
        return result

    @session_operation
    @_measure_command("move")
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
        self._publish_file_change("moved", (dst,), (src,))
        return dst

    @session_operation
    @_measure_command("copy")
    def copy_to_directory(self, sources: list[str | Path], destination_dir: str | Path,
                          library_root: str | Path | None = None) -> FileOperationResult:
        changed: list[Path] = []
        errors: list[str] = []
        bus = get_event_bus()
        root = self._root_for(library_root)
        is_bound = root is not None
        destination = Path(destination_dir).resolve()
        if root is None:
            # Legacy unbound copies may rearrange files within the destination's
            # containing tree, but cannot import from outside that tree.
            root = destination.parent
        _assert_under_root(destination, root)
        for source in sources:
            src = Path(source).resolve()
            if not is_bound:
                _assert_under_root(src, root)
            try:
                target = unique_destination(destination / src.name).resolve()
                if src.is_dir():
                    shutil.copytree(src, target)
                    self._refresh_directory_tree(target)
                else:
                    shutil.copy2(src, target)
                self._refresh_parents(target.parent)
                changed.append(target)
                bus.publish(FileCopied(source_path=str(src), destination_path=str(target)))
                self._publish_file_change("copied", (target,), (src,))
            except OSError as exc:
                errors.append(str(exc))
        return FileOperationResult(tuple(changed), tuple(errors))

    @session_operation
    @_measure_command("move_batch")
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
                self._publish_file_change("moved", (target,), (src,))
            except OSError as exc:
                errors.append(str(exc))
        return FileOperationResult(tuple(changed), tuple(errors))

    @session_operation
    @_measure_command("duplicate")
    def duplicate(self, path: str | Path, copy_label: str = "_copy") -> Path:
        src = Path(path).resolve()
        root = self._root_for(None)
        _assert_under_root(src, root)
        target = unique_destination(src.with_name(f"{src.stem}{copy_label}{src.suffix}")).resolve()
        _assert_under_root(target, root)
        if src.is_dir():
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)
        self._refresh_parents(target.parent)
        if target.is_dir():
            self._refresh_directory_tree(target)
        get_event_bus().publish(FileCreated(path=str(target), is_dir=target.is_dir()))
        self._publish_file_change("created", (target,), (src,))
        return target

    @session_operation
    @_measure_command("delete_permanent")
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
                self._publish_file_change("deleted", (p,))
            except OSError as exc:
                errors.append(str(exc))
        return FileOperationResult(tuple(changed), tuple(errors))

    @session_operation
    @_measure_command("restore_backup")
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
        self._publish_file_change("restored", (target,))
        return target

    @session_operation
    @_measure_command("delete_to_trash")
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
                self._publish_file_change("deleted", (p,))
            except OSError as exc:
                errors.append(str(exc))
        return FileOperationResult(tuple(changed), tuple(errors))

    def _migrate_metadata(self, library_root: Path, old_path: Path, new_path: Path) -> None:
        if self.session is None:
            # Compatibility path for callers that still supply library_root
            # without a scoped session. New UI/application code is session-bound.
            from AssetsManager.core.database import migrate_path_metadata_for_library
            migrate_path_metadata_for_library(library_root, old_path, new_path)
            return
        from AssetsManager.core.database import migrate_path_metadata
        migrate_path_metadata(
            self._connection(), self.session.thumb_dir, old_path, new_path,
        )

    def _refresh_parents(self, *parents: Path) -> None:
        if self.session is None or self._asset_index_service is None:
            return
        conn = self._connection()
        for parent in set(parents):
            self._asset_index_service.index_directory(
                conn, self.session.root, parent, force=True,
            )

    def _refresh_after_move(self, old_path: Path, new_path: Path, is_dir: bool) -> None:
        if self.session is None or self._asset_index_service is None:
            return
        conn = self._connection()
        if is_dir:
            self._asset_index_service.remove_entry(conn, old_path)
            self._asset_index_service.remove_directory(conn, old_path)
        self._refresh_parents(old_path.parent, new_path.parent)
        if is_dir:
            self._refresh_directory_tree(new_path)

    def _refresh_directory_tree(self, directory: Path) -> None:
        if self.session is None or self._asset_index_service is None:
            return
        self._asset_index_service.index_directory_tree(
            self._connection(), self.session.root, directory,
        )

    def _clear_deleted_projection(self, path: Path) -> None:
        if self.session is None:
            return
        from AssetsManager.core.database import db_write_lock
        from AssetsManager.repositories.metadata_repository import MetadataRepository
        from AssetsManager.repositories.tag_repository import TagRepository
        from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository

        target = str(path.resolve())
        conn = self._connection()
        with db_write_lock(conn):
            TagRepository(conn).delete_path(target, commit=False)
            MetadataRepository(conn).delete_path(target, commit=False)
            conn.commit()
        cache_keys = ThumbnailRepository(conn).delete_path(target)
        for cache_key in cache_keys:
            try:
                (self.session.thumb_dir / f"{cache_key}.webp").unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        if self._asset_index_service is not None:
            self._asset_index_service.remove_entry(conn, path)
            self._asset_index_service.remove_directory(conn, path)


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
