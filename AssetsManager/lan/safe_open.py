"""LAN compatibility adapter for root-confined final-open snapshots.

The implementation lives in ``core.file_snapshot`` so application services can
use the same final-byte contract without depending on the LAN package.  This
module retains the older LAN names and error mapping for route callers.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from AssetsManager.core.file_snapshot import (
    FileIdentity,
    FileSnapshotError,
    OpenedFile,
    SnapshotPathEscapeError,
    open_under_root,
    read_snapshot,
)
from AssetsManager.lan.path_guard import PathEscapeError

SafeOpenError = FileSnapshotError
SafeOpenedFile = OpenedFile


def _translate_path_error(exc: Exception) -> Exception:
    if isinstance(exc, SnapshotPathEscapeError):
        return PathEscapeError(exc.path, exc.root)
    return exc


def safe_open_under_root(
    root: str | Path,
    admitted_path: str | Path,
    *,
    expected_identity: FileIdentity | tuple[int, int, int, int] | None = None,
    retries: int = 2,
) -> SafeOpenedFile:
    """Open one root-confined regular file and return its owned handle."""
    try:
        return open_under_root(
            root,
            admitted_path,
            expected_identity=expected_identity,
            retries=retries,
        )
    except Exception as exc:
        translated = _translate_path_error(exc)
        if translated is not exc:
            raise translated from exc
        raise


def read_safe_file(
    root: str | Path,
    admitted_path: str | Path,
    *,
    expected_identity: FileIdentity | tuple[int, int, int, int] | None = None,
) -> tuple[bytes, FileIdentity]:
    """Read one final-open snapshot while preserving LAN error types."""
    try:
        return read_snapshot(root, admitted_path, expected_identity=expected_identity)
    except Exception as exc:
        translated = _translate_path_error(exc)
        if translated is not exc:
            raise translated from exc
        raise


def open_safe_file(root: str | Path, admitted_path: str | Path, **kwargs: Any) -> SafeOpenedFile:
    """Descriptive alias for callers migrating from the legacy LAN name."""
    return safe_open_under_root(root, admitted_path, **kwargs)


def read_file_snapshot(root: str | Path, admitted_path: str | Path, **kwargs: Any) -> tuple[bytes, FileIdentity]:
    """Descriptive alias for the shared core snapshot operation."""
    return read_safe_file(root, admitted_path, **kwargs)


__all__ = [
    "FileIdentity",
    "FileSnapshotError",
    "OpenedFile",
    "SafeOpenError",
    "SafeOpenedFile",
    "open_under_root",
    "open_safe_file",
    "read_snapshot",
    "read_file_snapshot",
    "read_safe_file",
    "safe_open_under_root",
]


# Keep this module-level marker as a stable audit anchor for the LAN adapter.
# The implementation remains in core.file_snapshot; callers should use the
# descriptive aliases above when introducing new code.
LEGACY_ADAPTER_VERSION = 2
