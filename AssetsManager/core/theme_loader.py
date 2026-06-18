"""ThemeLoader — dynamic theme scanning, validation, and hot-reload.

Scans a themes directory for JSON files, validates schema, groups by
filename prefix (D_, L_, U_), and watches for filesystem changes via
QFileSystemWatcher.

Prefix convention:
  D_  — Dark theme
  L_  — Light theme
  U_  — User/custom theme
  (no prefix) — Uncategorized
"""
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal

_REQUIRED_COLOR_TOKENS = [
    "base", "panel", "header", "border",
    "heading", "body", "muted", "accent",
    "success", "warning", "danger",
    "favorite", "recent",
]

_PREFIX_GROUPS = {
    "D_": "Dark",
    "L_": "Light",
    "U_": "User",
}


def _default_themes_dir() -> str:
    """Resolve the bundled themes directory (PyInstaller or dev)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
        return os.path.join(base, "AssetsManager", "themes")
    return os.path.join(os.path.dirname(__file__), "..", "themes")


class ThemeLoader(QObject):
    """Loads and monitors theme JSON files from a directory."""

    themes_changed = Signal()

    def __init__(self, themes_dir: str | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._themes_dir = themes_dir or _default_themes_dir()
        self._themes: dict[str, dict] = {}
        self._paths: dict[str, str] = {}
        self._watcher = None

    @property
    def themes_dir(self) -> str:
        return self._themes_dir

    def scan_directory(self) -> None:
        """Scan the themes directory and load all valid JSON files."""
        self._themes.clear()
        self._paths.clear()

        themes_dir = self._themes_dir
        if not os.path.isdir(themes_dir):
            return

        for filename in sorted(os.listdir(themes_dir)):
            if not filename.endswith(".json") or filename.startswith("."):
                continue
            filepath = os.path.join(themes_dir, filename)
            if not os.path.isfile(filepath):
                continue
            data = self.parse_theme(filepath)
            if data is not None:
                name = data["name"]
                self._themes[name] = data
                self._paths[name] = filepath

    def parse_theme(self, path: str) -> dict | None:
        """Parse and validate a single theme JSON file.

        Returns the parsed dict on success, None on failure.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError, OSError):
            return None

        valid, _errors = self.validate_theme(data)
        return data if valid else None

    @staticmethod
    def validate_theme(data: dict) -> tuple[bool, list[str]]:
        """Validate a theme dict against the required schema.

        Returns (is_valid, list_of_error_messages).
        """
        errors: list[str] = []

        if not isinstance(data, dict):
            return False, ["theme data must be a dict"]
        if "name" not in data:
            errors.append("missing required field: name")
        colors = data.get("colors")
        if not isinstance(colors, dict):
            errors.append("missing or invalid 'colors' object")
            return False, errors
        for token in _REQUIRED_COLOR_TOKENS:
            if token not in colors:
                errors.append(f"missing required color token: {token}")

        return len(errors) == 0, errors

    def get_theme(self, name: str) -> dict | None:
        """Return theme data by name, or None if not found."""
        return self._themes.get(name)

    def list_themes(self) -> dict[str, list[dict]]:
        """Return all themes grouped by filename prefix.

        Groups: "Dark" (D_), "Light" (L_), "User" (U_), "Other" (no prefix).
        """
        groups: dict[str, list[dict]] = {}
        for name, data in self._themes.items():
            filepath = self._paths.get(name, "")
            prefix = self._extract_prefix(filepath)
            group = _PREFIX_GROUPS.get(prefix, "Other")
            groups.setdefault(group, []).append(data)
        return groups

    def watch_changes(self) -> None:
        """Start watching the themes directory for file changes."""
        if not os.path.isdir(self._themes_dir):
            return
        from PySide6.QtCore import QFileSystemWatcher

        self._watcher = QFileSystemWatcher(self)
        self._watcher.addPath(self._themes_dir)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watcher.directoryChanged.connect(self._on_dir_changed)

    def reload_on_change(self, path: str) -> None:
        """Re-parse a single theme file and emit themes_changed."""
        name_to_remove = None
        for n, p in self._paths.items():
            if os.path.normpath(p) == os.path.normpath(path):
                name_to_remove = n
                break

        if not os.path.isfile(path):
            if name_to_remove is not None:
                del self._themes[name_to_remove]
                del self._paths[name_to_remove]
                self.themes_changed.emit()
            return

        data = self.parse_theme(path)
        if data is not None:
            if name_to_remove is not None and name_to_remove != data["name"]:
                del self._themes[name_to_remove]
                del self._paths[name_to_remove]
            name = data["name"]
            self._themes[name] = data
            self._paths[name] = path
            self.themes_changed.emit()
        elif name_to_remove is not None:
            del self._themes[name_to_remove]
            del self._paths[name_to_remove]
            self.themes_changed.emit()

    def _on_file_changed(self, path: str) -> None:
        self.reload_on_change(path)

    def _on_dir_changed(self, _path: str) -> None:
        self.scan_directory()
        self.themes_changed.emit()

    @staticmethod
    def _extract_prefix(filepath: str) -> str:
        """Extract D_, L_, or U_ prefix from a filename, or '' if none."""
        stem = Path(filepath).stem
        for prefix in _PREFIX_GROUPS:
            if stem.startswith(prefix):
                return prefix
        return ""
