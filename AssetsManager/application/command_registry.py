"""Machine-readable command registry over existing desktop services.

This is the declaration layer for the future automation/MCP gateway
(evolution strategy §T2): every entry describes one operation with
impact/approval metadata and binds a handler onto already-injected
per-library services.  The desktop UI keeps its own call paths — nothing
here changes their behaviour; the registry exists so an external caller
(MCP, scripts) can eventually execute the same operations through the same
permission and audit surface.

First batch (H2-d): 8 commands over the file-operation and tag services.
Destructive deletion is undo-wrapped (prepare → service → commit_batch)
so a registry-driven delete honours the same safety net as the desktop
path; move/copy keep service-level semantics with undo noted as
follow-up.  Writes go through ``activity_recorder``-backed services where
the service already records, so the execution journal stays the same.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

_log = logging.getLogger(__name__)

Impact = Literal["read", "metadata_write", "file_write", "destructive"]
Approval = Literal["none", "execution"]


@dataclass(frozen=True)
class CommandResult:
    """Normalised outcome of one registry command execution."""

    status: Literal["ok", "partial", "failed"]
    succeeded: int = 0
    failed: int = 0
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandDescriptor:
    """One registered operation: metadata + bound handler."""

    command_id: str
    title_key: str
    impact: Impact
    approval: Approval
    handler: Callable[..., CommandResult]
    required_capabilities: tuple[str, ...] = ()
    supports_undo: bool = False
    atomicity: str = "best_effort"


def _result_from_operation(result) -> CommandResult:
    """Translate a ``FileOperationResult`` into a normalised result."""
    errors = tuple(str(error) for error in result.errors)
    succeeded = len(result.changed_paths)
    if not errors:
        status: Literal["ok", "partial", "failed"] = "ok"
    elif succeeded:
        status = "partial"
    else:
        status = "failed"
    return CommandResult(
        status=status, succeeded=succeeded, failed=len(errors), errors=errors)


def build_command_registry(
    *,
    file_operations,
    tag_service,
    undo_service,
    library_root: str,
) -> "CommandRegistry":
    """Bind the first command batch onto the session's services."""

    def delete_permanent(targets: list[str], **params) -> CommandResult:
        # Undo-wrapped batch delete — the same safety net as the desktop
        # path (prepare → service → commit_batch), minus the Qt feedback.
        entries = []
        backup_failures: list[str] = []
        for path in targets:
            entry = undo_service.prepare_delete(path)
            if entry is None:
                reason = getattr(undo_service, "last_backup_error", None)
                backup_failures.append(
                    f"{path}: {reason if isinstance(reason, str) else 'backup failed'}")
            entries.append(entry)
        try:
            result = file_operations.delete_permanent(targets, library_root=library_root)
        except Exception:
            for entry in entries:
                undo_service.discard_delete(entry)
            raise
        changed = {str(Path(path).resolve()) for path in result.changed_paths}
        committed = []
        for path, entry in zip(targets, entries, strict=True):
            if str(Path(path).resolve()) in changed and entry is not None:
                committed.append(entry)
            else:
                undo_service.discard_delete(entry)
        undo_service.commit_batch(committed)
        outcome = _result_from_operation(result)
        if backup_failures:
            return CommandResult(
                status="partial" if outcome.succeeded else "failed",
                succeeded=outcome.succeeded,
                failed=outcome.failed + len(backup_failures),
                errors=outcome.errors + tuple(backup_failures),
            )
        return outcome

    def move_to_directory(targets: list[str], destination_dir: str, **params) -> CommandResult:
        result = file_operations.move_to_directory(
            targets, destination_dir, library_root=library_root)
        pairs = [(str(old), str(new)) for old, new in result.moved_pairs]
        if pairs and undo_service is not None:
            try:
                undo_service.record_rename_batch(pairs)
            except Exception:
                _log.exception("undo recording for registry move failed")
        return _result_from_operation(result)

    def tag_add(targets: list[str], tag: str, **params) -> CommandResult:
        added = tag_service.add_tag_to_files(library_root, targets, tag)
        skipped = len(targets) - added
        if added == 0 and targets:
            return CommandResult(status="ok", succeeded=0, failed=0)
        return CommandResult(status="ok", succeeded=added, failed=0) if skipped == 0 else \
            CommandResult(status="partial", succeeded=added, failed=skipped)

    def tag_remove(targets: list[str], tag: str, **params) -> CommandResult:
        removed = tag_service.remove_tag_from_files(library_root, targets, tag)
        skipped = len(targets) - removed
        return CommandResult(status="ok", succeeded=removed, failed=0) if skipped == 0 else \
            CommandResult(status="partial", succeeded=removed, failed=skipped)

    descriptors = {
        "file.delete_trash": CommandDescriptor(
            command_id="file.delete_trash", title_key="command.file.delete_trash",
            impact="file_write", approval="execution",
            handler=lambda targets, **params: _result_from_operation(
                file_operations.delete_to_trash(targets, library_root=library_root)),
            supports_undo=False, atomicity="recoverable_file_operation"),
        "file.delete_permanent": CommandDescriptor(
            command_id="file.delete_permanent", title_key="command.file.delete_permanent",
            impact="destructive", approval="execution",
            handler=delete_permanent,
            supports_undo=True, atomicity="recoverable_file_operation"),
        "file.move_to_directory": CommandDescriptor(
            command_id="file.move_to_directory", title_key="command.file.move",
            impact="file_write", approval="execution",
            handler=move_to_directory,
            supports_undo=True, atomicity="recoverable_file_operation"),
        "file.copy_to_directory": CommandDescriptor(
            command_id="file.copy_to_directory", title_key="command.file.copy",
            impact="file_write", approval="none",
            handler=lambda targets, destination_dir, **params: _result_from_operation(
                file_operations.copy_to_directory(
                    targets, destination_dir, library_root=library_root)),
            atomicity="best_effort"),
        "file.create_folder": CommandDescriptor(
            command_id="file.create_folder", title_key="command.file.create_folder",
            impact="file_write", approval="none",
            handler=lambda targets, name="New Folder", **params: CommandResult(
                status="ok", succeeded=1,
            ) if file_operations.create_folder(
                targets[0], name) is not None else CommandResult(status="failed"),
            atomicity="single_transaction"),
        "file.rename": CommandDescriptor(
            command_id="file.rename", title_key="command.file.rename",
            impact="file_write", approval="execution",
            handler=lambda targets, new_name, **params: _result_from_operation(
                file_operations.rename(targets[0], new_name, library_root=library_root))
            if len(targets) == 1 else CommandResult(
                status="failed", failed=1,
                errors=("file.rename expects exactly one target",)),
            supports_undo=True, atomicity="single_transaction"),
        "tag.add": CommandDescriptor(
            command_id="tag.add", title_key="command.tag.add",
            impact="metadata_write", approval="none",
            handler=tag_add, supports_undo=True,
            atomicity="single_transaction"),
        "tag.remove": CommandDescriptor(
            command_id="tag.remove", title_key="command.tag.remove",
            impact="metadata_write", approval="none",
            handler=tag_remove, supports_undo=True,
            atomicity="single_transaction"),
    }
    return CommandRegistry(descriptors)


class CommandRegistry:
    """Lookup + uniform execution entry for registered commands."""

    def __init__(self, descriptors: dict[str, CommandDescriptor]):
        self._descriptors = dict(descriptors)

    def descriptors(self) -> dict[str, CommandDescriptor]:
        """Return a copy of the registered descriptors (declaration view)."""
        return dict(self._descriptors)

    def get(self, command_id: str) -> CommandDescriptor:
        return self._descriptors[command_id]

    def execute(self, command_id: str, targets: list[str], **params) -> CommandResult:
        """Run one command through its bound handler.

        ``targets`` must be a non-empty list of paths; handler exceptions
        are translated into a ``failed`` result so a gateway caller never
        sees a raw exception.
        """
        if not targets:
            raise ValueError(f"{command_id}: targets must not be empty")
        descriptor = self.get(command_id)
        try:
            return descriptor.handler(targets, **params)
        except Exception as exc:
            _log.exception("registry command %s failed", command_id)
            return CommandResult(status="failed", errors=(str(exc),))
