"""Path validation helpers for LAN sharing.

All user-provided LAN paths must be resolved through this module before file
system access. This keeps path traversal protection centralized while the LAN
routes are split into smaller modules.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from AssetsManager.domain.errors import MissingPathError as DomainMissingPathError
from AssetsManager.domain.errors import PathEscapeError as DomainPathEscapeError


class PathGuardError(ValueError):
    """Base error for path guard failures."""


class PathEscapeError(DomainPathEscapeError, PathGuardError):
    """Raised when a path resolves outside the allowed root.

    Inherits the domain :class:`AssetsManager.domain.errors.PathEscapeError`
    so domain-level handlers (e.g. the LAN error mapping) treat it uniformly,
    and ``PathGuardError`` so LAN route-local ``except PathGuardError``
    handlers keep working unchanged.
    """

    def __init__(self, path: str = "", root: str = ""):
        DomainPathEscapeError.__init__(self, path, root)


class MissingPathError(DomainMissingPathError, PathGuardError):
    """Raised when an existing path is required but missing.

    Mirrors :class:`AssetsManager.domain.errors.MissingPathError` for the
    same catch-compatibility reasons as :class:`PathEscapeError`.
    """

    def __init__(self, path: str = ""):
        DomainMissingPathError.__init__(self, path)


class InvalidPathError(PathGuardError):
    """Raised when a path contains characters that must never reach the
    filesystem (NUL / C0 control characters) or — on Windows — an NTFS
    alternate data stream separator (``:``)."""


# C0 control characters are never valid in a request path and must not be
# passed to pathlib (Python <=3.12 raises on NUL, newer versions silently
# pass it through, making the behavior version-dependent).
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def reject_path_text(text: str) -> None:
    """Reject path text that must never reach the filesystem.

    Raises :class:`InvalidPathError` for C0 control characters (including
    NUL) and — on Windows — the NTFS alternate data stream separator (``:``).
    Every route-level path resolution must go through this gate, either
    directly or via :meth:`PathGuard.resolve`, so no route re-implements
    the character check inline.
    """
    if _CONTROL_CHARS_RE.search(text):
        raise InvalidPathError("Path contains control characters")
    if os.name == "nt" and ":" in text:
        raise InvalidPathError("Path contains a stream separator")


def assert_under_root(root: str | Path, candidate: str | Path) -> Path:
    """Resolve *candidate* (an absolute path) and require it under *root*.

    Raises :class:`PathEscapeError` when the resolved candidate escapes the
    resolved root.  This is the single post-resolution containment re-check
    for TOCTOU defense: a symlink swap after ``PathGuard.resolve`` is caught
    here instead of by an inline ``is_relative_to`` in each route.
    """
    resolved_root = Path(root).resolve()
    resolved = Path(candidate).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise PathEscapeError(str(resolved), str(resolved_root))
    return resolved


class PathGuard:
    """Validate paths against a fixed root directory."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def resolve(self, rel_path: str | Path = "") -> Path:
        """Resolve a relative path and ensure it remains under the root."""
        text = str(rel_path or "")
        if not text or text == "/":
            return self.root
        if _CONTROL_CHARS_RE.search(text):
            raise InvalidPathError("Path contains control characters")
        cleaned = text.replace("\\", "/").strip("/")
        try:
            target = (self.root / cleaned).resolve()
        except (OSError, ValueError) as exc:
            # Windows rejects names with < > " | ? * or reserved device names
            # (and pathlib raises ValueError for lone surrogates); surface
            # these as a 400-class guard error instead of a 500.
            raise InvalidPathError("Invalid path syntax") from exc
        if not target.is_relative_to(self.root):
            raise PathEscapeError(str(target), str(self.root))
        if os.name == "nt":
            # NTFS alternate data streams (file.txt:Zone.Identifier) pass
            # is_relative_to but open a different stream on Windows; reject
            # the separator inside the resolved in-root segment (an absolute
            # path with a drive letter already failed the escape check, and
            # its drive colon must not be treated as a stream separator).
            if ":" in str(target.relative_to(self.root)):
                raise InvalidPathError("Path contains a stream separator")
        return target

    def existing(self, rel_path: str | Path = "") -> Path:
        """Resolve a path and require that it exists."""
        target = self.resolve(rel_path)
        if not target.exists():
            raise MissingPathError(str(target))
        return target

    def existing_key(self, rel_path: str | Path = "") -> str:
        """Return the normalized DB key for an existing path."""
        return str(self.existing(rel_path).resolve())
