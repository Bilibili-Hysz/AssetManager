"""Explicit import service for bringing external assets into a library.

Importing is deliberately distinct from the in-library ``copy_to_directory``
operation: import walks directory trees from outside (or inside) the library
and reports a single ``FileSystemChanged(kind='import')`` event for the whole
batch, so a large directory import does not flood the event bus with one
``copied`` event per file.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping
from uuid import uuid4

from AssetsManager.application.file_operation_service import unique_destination
from AssetsManager.application.context import LibrarySession, session_operation
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import FileSystemChanged

ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]


def _reject_link_or_reparse_ancestors(
    root: Path,
    candidate: Path,
) -> None:
    """Reject existing link/reparse components below a session root.

    Missing trailing directories are allowed so the caller can create a new
    destination tree. The session root itself is the trust anchor and is not
    inspected, preserving its existing lexical alias contract.
    """
    root_lexical = Path(os.path.abspath(str(root)))
    candidate_lexical = Path(os.path.abspath(str(candidate)))
    try:
        relative = candidate_lexical.relative_to(root_lexical)
    except ValueError as exc:
        raise OSError(
            f"Import path escapes the session root: {candidate}"
        ) from exc

    current = root_lexical
    for part in relative.parts:
        current /= part
        try:
            if not os.path.lexists(current):
                break
            info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode):
                raise OSError(f"Import path passes through a symlink: {current}")
            if os.name == "nt":
                is_junction = getattr(current, "is_junction", None)
                if callable(is_junction) and is_junction():
                    raise OSError(f"Import path passes through a junction: {current}")
                is_mount = getattr(current, "is_mount", None)
                if callable(is_mount) and is_mount():
                    raise OSError(f"Import path passes through a mount: {current}")
                if int(getattr(info, "st_file_attributes", 0)) & 0x400:
                    raise OSError(
                        f"Import path passes through a reparse point: {current}"
                    )
            if not stat.S_ISDIR(info.st_mode):
                raise OSError(f"Import path component is not a directory: {current}")
        except (OSError, RuntimeError, ValueError):
            raise
        except Exception as exc:
            raise OSError(f"Unable to inspect import path component: {current}") from exc


class ImportCancelled(Exception):
    """Raised when an import observes its cancellation check returning True."""

    def __init__(self, partial_result: "ImportResult | None" = None) -> None:
        super().__init__("Import cancelled")
        self.partial_result = partial_result


@dataclass
class ImportResult:
    """Outcome of one import_sources() call."""

    copied: int
    skipped: int
    failed: list[str] = field(default_factory=list)
    processed: int = 0
    total: int = 0
    degraded: bool = False
    cancelled: bool = False
    operation_id: str | None = None
    refresh_warnings: tuple[object, ...] = ()


class ImportService:
    """Import files/folders into a destination inside an open library session.

    The service owns the batch boundary: it validates sources/destination,
    expands directory sources into (source, relative-path) pairs preserving
    the directory structure (skipping dot-prefixed entries), copies each file
    with name-conflict renaming, and emits exactly one
    ``FileSystemChanged(kind='import')`` event on completion.
    """

    def __init__(self, session: LibrarySession, file_operations) -> None:
        self.session = session
        self.file_operations = file_operations

    # ── helpers ────────────────────────────────────────────────

    @classmethod
    def _collect_files(
        cls,
        sources: list[str | Path],
        should_cancel: CancelCheck | None = None,
    ) -> list[tuple[Path, Path]]:
        """Expand sources into (source, relative-path) pairs, skipping dot entries.

        Directory sources are walked recursively with ``os.scandir``; each
        file keeps its path relative to the directory source so the imported
        tree structure is preserved.  File sources get an empty relative path.
        """
        collected: list[tuple[Path, Path]] = []

        def walk_dir(directory: Path, base: Path) -> None:
            with os.scandir(directory) as it:
                for entry in it:
                    if should_cancel is not None and should_cancel():
                        raise ImportCancelled()
                    if entry.name.startswith("."):
                        continue
                    path = Path(entry.path)
                    if entry.is_dir(follow_symlinks=False):
                        walk_dir(path, base)
                    elif entry.is_file(follow_symlinks=False):
                        collected.append((path, path.relative_to(base)))

        for source in sources:
            if should_cancel is not None and should_cancel():
                raise ImportCancelled()
            src = Path(source)
            if src.is_dir():
                walk_dir(src, src)
            else:
                collected.append((src, Path()))
        return collected

    @staticmethod
    def _under_root(path: str | Path, root: str | Path) -> bool:
        # application-layer containment check (the LAN PathGuard lives in the
        # lan layer, which application must not import).
        try:
            Path(path).resolve().relative_to(Path(root).resolve())
            return True
        except ValueError:
            return False

    def _read_source(self, src: Path):
        """Open a source for reading; injectable seam for fault tests."""
        return open(src, "rb")

    def _source_fingerprint(self, src: Path) -> dict[str, object]:
        """Read a stable content fingerprint for one regular source file."""
        before = src.stat()
        if not stat.S_ISREG(before.st_mode):
            raise OSError(f"{src}: source is not a regular file")
        digest = hashlib.sha256()
        size = 0
        with self._read_source(src) as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
            after_handle = os.fstat(handle.fileno())
        after_path = src.stat()
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after_handle.st_dev,
            after_handle.st_ino,
            after_handle.st_size,
            after_handle.st_mtime_ns,
        ) or (
            after_path.st_dev,
            after_path.st_ino,
            after_path.st_size,
            after_path.st_mtime_ns,
        ) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ):
            raise OSError(f"{src}: source changed while fingerprinting")
        return {
            "size": size,
            "mtime_ns": int(before.st_mtime_ns),
            "sha256": digest.hexdigest(),
        }

    def _replay_target_fingerprint(
        self,
        target: Path,
    ) -> dict[str, object]:
        """Fingerprint an existing replay target without following links."""
        root = Path(self.session.root).resolve()
        _reject_link_or_reparse_ancestors(root, target.parent)
        if not os.path.lexists(target):
            raise FileNotFoundError(str(target))
        info = os.lstat(target)
        if stat.S_ISLNK(info.st_mode):
            raise OSError(f"{target}: replay target is a symlink")
        if os.name == "nt" and int(getattr(info, "st_file_attributes", 0)) & 0x400:
            raise OSError(f"{target}: replay target is a reparse point")
        if not stat.S_ISREG(info.st_mode):
            raise OSError(f"{target}: replay target is not a regular file")
        return self._source_fingerprint(target)

    def _copy_one(
        self,
        src: Path,
        rel: Path,
        destination_dir: Path,
        target: Path | None = None,
        *,
        expected_fingerprint: Mapping[str, object] | None = None,
    ) -> Path:
        """Copy one file through an exclusive-create write boundary.

        The target is materialized with ``O_CREAT|O_EXCL`` so a rival file
        that appears after planning is never overwritten, and a dangling
        symlink at the planned path is rejected instead of followed. Cleanup
        removes only a target this call created inside the verified planned
        directory; an escaped resolution is left untouched rather than
        deleting through an unknown external path.
        """
        session_root = Path(self.session.root).resolve()
        _reject_link_or_reparse_ancestors(session_root, destination_dir)
        target_dir = destination_dir / rel.parent
        _reject_link_or_reparse_ancestors(session_root, target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        _reject_link_or_reparse_ancestors(session_root, target_dir)
        target = target or unique_destination(target_dir / src.name)
        _reject_link_or_reparse_ancestors(session_root, Path(target).parent)
        if os.path.lexists(target):
            raise FileExistsError(str(target))
        expected_parent = Path(os.path.realpath(target_dir))
        created_fd: int | None = None
        created_identity: tuple[int, int] | None = None
        owned = False
        escaped = False

        def path_is_ours() -> bool:
            if created_identity is None:
                return False
            try:
                current = os.stat(str(target), follow_symlinks=False)
            except OSError:
                return False
            return (current.st_dev, current.st_ino) == created_identity

        try:
            with self._read_source(src) as source_handle:
                opened_source_stat: os.stat_result | None = None
                if expected_fingerprint is not None:
                    opened_source_stat = os.fstat(source_handle.fileno())
                    if (
                        opened_source_stat.st_size
                        != expected_fingerprint.get("size")
                        or int(opened_source_stat.st_mtime_ns)
                        != expected_fingerprint.get("mtime_ns")
                    ):
                        raise OSError(
                            f"{src}: source changed since manifest fingerprint"
                        )
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_BINARY"):
                    flags |= os.O_BINARY
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                created_fd = os.open(str(target), flags, 0o600)
                owned = True
                created_stat = os.fstat(created_fd)
                if not stat.S_ISREG(created_stat.st_mode):
                    raise OSError(
                        f"{target}: exclusive create did not yield a regular file"
                    )
                created_identity = (created_stat.st_dev, created_stat.st_ino)
                if Path(os.path.realpath(target)).parent != expected_parent:
                    escaped = True
                    raise OSError(f"{target}: resolved outside its planned directory")
                with os.fdopen(created_fd, "wb") as target_handle:
                    created_fd = None
                    shutil.copyfileobj(source_handle, target_handle)
                if not path_is_ours():
                    escaped = True
                    raise OSError(f"{target}: target identity changed during copy")
                if expected_fingerprint is not None:
                    # Same-handle stability recheck after streaming: a source
                    # replaced mid-copy must not land under the manifest's
                    # recorded fingerprint.
                    copied_bytes = source_handle.tell()
                    final_source_stat = os.fstat(source_handle.fileno())
                    if (
                        final_source_stat.st_size != opened_source_stat.st_size
                        or int(final_source_stat.st_mtime_ns)
                        != int(opened_source_stat.st_mtime_ns)
                    ):
                        raise OSError(f"{src}: source changed while copying")
                    if copied_bytes != expected_fingerprint.get("size"):
                        raise OSError(
                            f"{src}: copied byte count diverges from manifest fingerprint"
                        )
                shutil.copystat(src, str(target), follow_symlinks=False)
        except OSError:
            if created_fd is not None:
                os.close(created_fd)
            if owned and not escaped and path_is_ours():
                # Remove only our own partial result inside the verified
                # directory; never unlink a rival or an escaped path.
                try:
                    os.unlink(str(target))
                except OSError:
                    pass
            raise
        return target

    @staticmethod
    def _plan_targets(
        files: list[tuple[Path, Path]], destination: Path
    ) -> list[Path]:
        """Choose deterministic targets without mutating the filesystem."""
        planned: set[Path] = set()
        targets: list[Path] = []
        for source, relative in files:
            target_dir = destination / relative.parent
            candidate = target_dir / source.name
            if candidate.exists() or candidate in planned:
                base = candidate.stem
                suffix = candidate.suffix
                for index in range(1, 1001):
                    candidate = target_dir / f"{base}_{index}{suffix}"
                    if not candidate.exists() and candidate not in planned:
                        break
                else:
                    raise OSError(f"Could not reserve a unique destination for {source}")
            planned.add(candidate)
            targets.append(candidate)
        return targets

    def _manifest_finish(
        self,
        store,
        operation_id: str,
        *,
        state: str,
        error: str | None = None,
    ) -> bool:
        if store is None:
            return True
        try:
            return bool(store.finish(operation_id, state=state, error=error))
        except Exception:
            return False

    def _publish_cancelled_import(self, destination: Path) -> None:
        """Publish the single compensating invalidation for a cancelled import.

        Mirrors the completed-import batch boundary: one event, destination
        scoped.  ``kind`` is pass-through data (no consumer branches on it);
        the runtime router maps it like any other FileSystemChanged.
        """
        get_event_bus().publish(FileSystemChanged(
            library_root=self.session.root_str,
            session_token=self.session.event_token,
            kind="cancelled_import",
            paths=(str(destination),),
        ))

    # ── public API ─────────────────────────────────────────────

    @session_operation
    def import_sources(
        self,
        sources: list[str | Path],
        destination_dir: str | Path,
        *,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCheck | None = None,
    ) -> ImportResult:
        """Import sources while holding the session operation lease."""
        operation_id = f"import-{uuid4().hex}"
        if self.session.is_closed:
            raise RuntimeError("Cannot use a closed LibrarySession")
        if not sources:
            return ImportResult(
                copied=0, skipped=0, failed=[], operation_id=operation_id
            )

        root = self.session.root
        manifest_store = getattr(self.file_operations, "_import_manifest_store", None)
        if not self._under_root(destination_dir, root):
            raise ValueError(
                f"Import destination escapes the library root: {destination_dir}"
            )
        destination = Path(destination_dir).resolve()
        if destination.exists() and not destination.is_dir():
            return ImportResult(
                copied=0,
                skipped=0,
                failed=[f"{destination}: is not a directory"],
                degraded=True,
                operation_id=operation_id,
            )
        try:
            # Check the lexical destination before using its canonical form so
            # an alias through an existing link is rejected rather than erased
            # by Path.resolve(). The session root itself remains the trust
            # anchor and is intentionally not inspected.
            _reject_link_or_reparse_ancestors(Path(root), Path(destination_dir))
        except OSError as exc:
            raise ValueError(f"Import destination is not a real directory: {destination_dir}") from exc

        in_library: list[str | Path] = []
        external: list[str | Path] = []
        for source in sources:
            if self._under_root(source, root):
                in_library.append(source)
            else:
                external.append(source)

        skipped = len(in_library)
        try:
            files = self._collect_files(external, should_cancel)
        except ImportCancelled as exc:
            partial = ImportResult(
                copied=0,
                skipped=skipped,
                failed=[],
                processed=0,
                total=0,
                cancelled=True,
                operation_id=operation_id,
            )
            raise ImportCancelled(partial) from exc
        except OSError as exc:
            files = []
            failed = [f"source scan: {exc}"]
            result = ImportResult(
                copied=0,
                skipped=skipped,
                failed=failed,
                degraded=True,
                operation_id=operation_id,
            )
            self._enqueue_index_rescan(operation_id, "import_partial")
            return result

        total = len(files)
        try:
            targets = self._plan_targets(files, destination)
        except OSError as exc:
            result = ImportResult(
                copied=0,
                skipped=skipped,
                failed=[f"destination planning: {exc}"],
                processed=0,
                total=total,
                degraded=True,
                operation_id=operation_id,
            )
            if manifest_store is not None:
                try:
                    manifest_store.create(
                        operation_id=operation_id,
                        destination=destination,
                        payload={
                            "payload_version": 1,
                            "destination": str(destination),
                            "items": [
                                {
                                    "source": str(source),
                                    "target": str(destination / relative.parent / source.name),
                                    "state": "failed",
                                    "error": str(exc),
                                }
                                for source, relative in files
                            ],
                        },
                        state="recovery_pending",
                    )
                except Exception:
                    pass
            self._enqueue_index_rescan(operation_id, "import_partial")
            return result

        fingerprints: list[dict[str, object] | None] = []
        use_v2 = False
        if manifest_store is not None and files:
            try:
                for source, _relative in files:
                    try:
                        fingerprints.append(self._source_fingerprint(source))
                    except OSError:
                        fingerprints.append(None)
                use_v2 = all(fingerprint is not None for fingerprint in fingerprints)
                items = []
                for index, ((source, relative), target) in enumerate(
                    zip(files, targets, strict=True)
                ):
                    item = {
                        "source": str(source),
                        "relative": str(relative),
                        "target": str(target),
                        "state": "pending",
                    }
                    if use_v2:
                        item["copy_id"] = f"{operation_id}:{index}"
                        item["source_fingerprint"] = fingerprints[index]
                    items.append(item)
                manifest_store.create(
                    operation_id=operation_id,
                    destination=destination,
                    payload={
                        "payload_version": 2 if use_v2 else 1,
                        "destination": str(destination),
                        "items": items,
                    },
                    state="running",
                )
            except Exception as exc:
                return ImportResult(
                    copied=0,
                    skipped=skipped,
                    failed=[f"manifest prepare: {exc}"],
                    processed=0,
                    total=total,
                    degraded=True,
                    operation_id=operation_id,
                )

        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._manifest_finish(
                manifest_store,
                operation_id,
                state="recovery_pending",
                error=str(exc),
            )
            return ImportResult(
                copied=0,
                skipped=skipped,
                failed=[f"{destination}: {exc}"],
                processed=0,
                total=total,
                degraded=True,
                operation_id=operation_id,
            )

        copied = 0
        failed: list[str] = []
        done = 0
        if progress is not None:
            progress(done, total)

        for src, rel in files:
            if should_cancel is not None and should_cancel():
                partial = ImportResult(
                    copied=copied,
                    skipped=skipped,
                    failed=failed,
                    processed=done,
                    total=total,
                    cancelled=True,
                    operation_id=operation_id,
                )
                # Compensation must be durable before the terminal cancelled
                # state can hide already-copied files from every future
                # recovery pass.
                compensated = copied == 0 or self._enqueue_index_rescan(
                    operation_id, "import_partial"
                )
                if compensated:
                    self._manifest_finish(
                        manifest_store,
                        operation_id,
                        state="cancelled",
                    )
                else:
                    self._manifest_finish(
                        manifest_store,
                        operation_id,
                        state="recovery_pending",
                        error="import cancelled while index rescan was unavailable",
                    )
                if copied:
                    # Compensating invalidation: already-copied files exist
                    # under the destination, so live projections must refresh
                    # even though the batch never completed.
                    self._publish_cancelled_import(destination)
                raise ImportCancelled(partial)
            copied_this_item = False
            try:
                self._copy_one(
                    src,
                    rel,
                    destination,
                    targets[done],
                    expected_fingerprint=(
                        fingerprints[done] if use_v2 else None
                    ),
                )
                copied += 1
                copied_this_item = True
            except OSError as exc:
                failed.append(f"{src}: {exc}")
            if manifest_store is not None:
                try:
                    update_ok = manifest_store.update_item(
                        operation_id,
                        item_index=done,
                        state="copied" if copied_this_item else "failed",
                        error=None if copied_this_item else failed[-1],
                    )
                except Exception as exc:
                    update_ok = False
                    failed.append(f"manifest update {src}: {exc}")
                if not update_ok:
                    failed.append(f"manifest update unavailable: {src}")
            done += 1
            if progress is not None:
                progress(done, total)

        if should_cancel is not None and should_cancel():
            partial = ImportResult(
                copied=copied,
                skipped=skipped,
                failed=failed,
                processed=done,
                total=total,
                cancelled=True,
                operation_id=operation_id,
            )
            compensated = copied == 0 or self._enqueue_index_rescan(
                operation_id, "import_partial"
            )
            if compensated:
                self._manifest_finish(
                    manifest_store,
                    operation_id,
                    state="cancelled",
                )
            else:
                self._manifest_finish(
                    manifest_store,
                    operation_id,
                    state="recovery_pending",
                    error="import cancelled while index rescan was unavailable",
                )
            if copied:
                # Same compensating invalidation as the mid-loop cancellation.
                self._publish_cancelled_import(destination)
            raise ImportCancelled(partial)

        refresh_warnings: tuple[object, ...] = ()
        refresh_failed: list[str] = []
        begin = getattr(self.file_operations, "_begin_refresh_diagnostics", None)
        if callable(begin):
            begin()
        try:
            self.file_operations._refresh_directory_tree(destination)
            self.file_operations._refresh_parents(destination.parent)
        except Exception as exc:
            refresh_failed.append(f"refresh: {exc}")
        refresh_warnings = tuple(
            getattr(self.file_operations, "last_refresh_warnings", ())
        )
        degraded = bool(failed or refresh_failed or refresh_warnings)
        all_failed = [*failed, *refresh_failed]
        manifest_state = "degraded" if degraded else "completed"
        queue_ok = True
        if degraded:
            queue_ok = self._enqueue_index_rescan(
                operation_id,
                "import_refresh_degraded" if refresh_warnings or refresh_failed else "import_partial",
            )
            if not queue_ok:
                manifest_state = "recovery_pending"
        if not self._manifest_finish(
            manifest_store,
            operation_id,
            state=manifest_state,
            error=("; ".join(all_failed) if all_failed else None),
        ) and manifest_store is not None:
            self._enqueue_index_rescan(operation_id, "import_manifest_recovery")
        result = ImportResult(
            copied=copied,
            skipped=skipped,
            failed=all_failed,
            processed=done,
            total=total,
            degraded=degraded,
            operation_id=operation_id,
            refresh_warnings=refresh_warnings,
        )
        get_event_bus().publish(FileSystemChanged(
            library_root=self.session.root_str,
            session_token=self.session.event_token,
            kind="import",
            paths=(str(destination),),
        ))
        return result

    @session_operation
    def replay_import(self, operation_id: str) -> ImportResult:
        """Replay only uncertain v2 items from one persisted import intent.

        Existing targets are adopted only when their stable content fingerprint
        matches the manifest snapshot; otherwise the target is preserved and
        the item is recorded as a deterministic conflict.
        """
        if self.session.is_closed:
            raise RuntimeError("Cannot use a closed LibrarySession")
        manifest_store = getattr(self.file_operations, "_import_manifest_store", None)
        if manifest_store is None:
            return ImportResult(0, 0, ["import manifest store unavailable"], degraded=True, operation_id=operation_id)
        existing = manifest_store.get(operation_id)
        eligible = False
        if existing is not None and not existing.get("malformed"):
            payload = existing.get("payload")
            if (
                isinstance(payload, Mapping)
                and payload.get("payload_version") == 2
                and any(
                    isinstance(item, Mapping) and item.get("state") == "pending"
                    for item in payload.get("items", ())
                )
                and str(existing["state"])
                in {"completed", "degraded", "recovery_pending"}
            ):
                eligible = True
        record = manifest_store.begin_replay(operation_id)
        if record is None:
            if eligible:
                # A concurrent replay won the CAS; report the race instead of
                # an empty success the caller cannot distinguish.
                return ImportResult(
                    0, 0, [f"{operation_id}: replay claim lost to a concurrent writer"],
                    degraded=True, operation_id=operation_id,
                )
            return ImportResult(0, 0, [], operation_id=operation_id)
        payload = record["payload"]
        destination = Path(str(record["destination"]))
        items = list(payload["items"])
        copied = 0
        failed: list[str] = []
        processed = 0
        for index, raw_item in enumerate(items):
            item = dict(raw_item)
            if item.get("state") != "pending":
                continue
            processed += 1
            source = Path(str(item["source"]))
            target = Path(str(item["target"]))
            fingerprint = item.get("source_fingerprint")
            error: str | None = None
            copied_this_item = False
            if not isinstance(fingerprint, dict):
                error = "legacy import manifest item has no replay fingerprint"
            else:
                try:
                    current_source = self._source_fingerprint(source)
                    if current_source != fingerprint:
                        error = f"{source}: source_changed"
                    elif os.path.lexists(target):
                        current_target = self._replay_target_fingerprint(target)
                        if (
                            current_target.get("size") == fingerprint.get("size")
                            and current_target.get("sha256") == fingerprint.get("sha256")
                        ):
                            copied_this_item = True
                        else:
                            error = f"{target}: replay_conflict"
                    else:
                        self._copy_one(
                            source,
                            Path(str(item.get("relative", ""))),
                            destination,
                            target,
                            expected_fingerprint=fingerprint,
                        )
                        copied_this_item = True
                except OSError as exc:
                    error = f"{source}: {exc}"
            next_state = "copied" if copied_this_item else "failed"
            if copied_this_item:
                copied += 1
            else:
                failed.append(error or f"{source}: replay failed")
            try:
                update_ok = manifest_store.update_item(
                    operation_id,
                    item_index=index,
                    state=next_state,
                    error=None if copied_this_item else error,
                )
            except Exception as exc:
                update_ok = False
                failed.append(f"manifest replay update {source}: {exc}")
            if not update_ok:
                failed.append(f"manifest replay update unavailable: {source}")
        begin = getattr(self.file_operations, "_begin_refresh_diagnostics", None)
        if callable(begin):
            begin()
        refresh_failed: list[str] = []
        try:
            self.file_operations._refresh_directory_tree(destination)
            self.file_operations._refresh_parents(destination.parent)
        except Exception as exc:
            refresh_failed.append(f"refresh: {exc}")
        all_failed = [*failed, *refresh_failed]
        final_state = "degraded" if all_failed else "completed"
        queue_ok = True
        if all_failed:
            queue_ok = self._enqueue_index_rescan(
                operation_id,
                "import_refresh_degraded" if refresh_failed else "import_partial",
            )
        try:
            finished = manifest_store.finish(
                operation_id,
                state="recovery_pending" if (all_failed and not queue_ok) else final_state,
                error="; ".join(all_failed) if all_failed else None,
            )
        except Exception:
            finished = False
        if not finished:
            self._enqueue_index_rescan(operation_id, "import_manifest_recovery")
            all_failed.append(f"{operation_id}: manifest replay finish unavailable")
        get_event_bus().publish(FileSystemChanged(
            library_root=self.session.root_str,
            session_token=self.session.event_token,
            kind="import",
            paths=(str(destination),),
        ))
        return ImportResult(
            copied=copied,
            skipped=0,
            failed=all_failed,
            processed=processed,
            total=processed,
            degraded=bool(all_failed),
            operation_id=operation_id,
        )

    def _enqueue_index_rescan(self, operation_id: str, reason: str) -> bool:
        queue = getattr(self.file_operations, "_reconciliation_queue", None)
        if queue is None:
            return False
        try:
            queue.enqueue_or_merge(
                path=self.session.root,
                reason=reason,
                operation_id=operation_id,
            )
            return True
        except Exception:
            # Import results remain truthful while the manifest stays
            # unresolved for restart-time recovery.
            return False
