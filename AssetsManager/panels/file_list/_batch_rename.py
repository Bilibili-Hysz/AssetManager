"""Pure planning and validation for FileList batch rename previews."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


@dataclass(frozen=True)
class BatchRenameEntry:
    source: Path
    target: Path
    errors: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return self.source != self.target


@dataclass(frozen=True)
class BatchRenamePlan:
    entries: tuple[BatchRenameEntry, ...]

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(error for entry in self.entries for error in entry.errors)

    @property
    def is_valid(self) -> bool:
        return bool(self.changed_entries) and not self.errors

    @property
    def changed_entries(self) -> tuple[BatchRenameEntry, ...]:
        return tuple(entry for entry in self.entries if entry.changed)


def plan_batch_rename(
    sources: Iterable[str | Path],
    pattern: str,
    *,
    occupied_paths: Iterable[str | Path],
    windows_rules: bool,
) -> BatchRenamePlan:
    """Create a deterministic, collision-checked batch rename plan."""
    ordered = tuple(sorted((Path(path) for path in sources), key=lambda path: str(path).casefold()))
    occupied = {str(Path(path).resolve()).casefold() for path in occupied_paths}
    source_keys = {str(path.resolve()).casefold() for path in ordered}
    entries: list[BatchRenameEntry] = []
    targets: dict[str, list[int]] = {}

    for number, source in enumerate(ordered, start=1):
        name = pattern.replace("{name}", source.stem).replace("{n}", str(number))
        target = source.with_name(f"{name}{source.suffix}")
        errors = list(_name_errors(name, windows_rules))
        target_key = str(target.resolve()).casefold()
        if target_key in occupied and target_key not in source_keys:
            errors.append("existing_target")
        elif target_key in source_keys and target_key != str(source.resolve()).casefold():
            errors.append("selected_source_target")
        targets.setdefault(target_key, []).append(len(entries))
        entries.append(BatchRenameEntry(source, target, tuple(errors)))

    for indexes in targets.values():
        if len(indexes) > 1:
            for index in indexes:
                entries[index] = BatchRenameEntry(
                    entries[index].source,
                    entries[index].target,
                    (*entries[index].errors, "duplicate_target"),
                )
    return BatchRenamePlan(tuple(entries))


def _name_errors(name: str, windows_rules: bool) -> tuple[str, ...]:
    if not name or name in {".", ".."}:
        return ("invalid_name",)
    if any(ord(character) < 32 for character in name):
        return ("invalid_name",)
    if not windows_rules:
        return ()
    if any(character in '<>:"/\\|?*' for character in name):
        return ("invalid_name",)
    if name.endswith((".", " ")):
        return ("invalid_name",)
    if name.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        return ("reserved_name",)
    if len(name.encode("utf-16-le")) // 2 > 255:
        return ("invalid_name",)
    return ()
