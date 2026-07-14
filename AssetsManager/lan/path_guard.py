"""Path validation helpers for LAN sharing.

All user-provided LAN paths must be resolved through this module before file
system access. This keeps path traversal protection centralized while the LAN
routes are split into smaller modules.
"""
from __future__ import annotations

from pathlib import Path


class PathGuardError(ValueError):
    """Base error for path guard failures."""


class PathEscapeError(PathGuardError):
    """Raised when a path resolves outside the allowed root."""


class MissingPathError(PathGuardError):
    """Raised when an existing path is required but missing."""


class PathGuard:
    """Validate paths against a fixed root directory."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def resolve(self, rel_path: str | Path = "") -> Path:
        """Resolve a relative path and ensure it remains under the root."""
        text = str(rel_path or "")
        if not text or text == "/":
            return self.root
        cleaned = text.replace("\\", "/").strip("/")
        target = (self.root / cleaned).resolve()
        if not target.is_relative_to(self.root):
            raise PathEscapeError("Path escape detected")
        return target

    def existing(self, rel_path: str | Path = "") -> Path:
        """Resolve a path and require that it exists."""
        target = self.resolve(rel_path)
        if not target.exists():
            raise MissingPathError("File not found")
        return target

    def existing_key(self, rel_path: str | Path = "") -> str:
        """Return the normalized DB key for an existing path."""
        return str(self.existing(rel_path).resolve())
