"""Centralized keyboard shortcut registration and discovery."""

from collections.abc import Callable
from typing import Any

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget


class ShortcutManager:
    """Centralized keyboard shortcut registry."""

    _instance: "ShortcutManager | None" = None

    _DEFAULTS = (
        ("Ctrl+K", "Command Palette", "navigation"),
        ("Ctrl+P", "File Picker", "navigation"),
        ("Ctrl+B", "Toggle Sidebar", "view"),
        ("Ctrl+,", "Settings", "navigation"),
        ("Ctrl+Q", "Quit", "application"),
        ("F1", "Help", "application"),
        ("Escape", "Close dialog/palette", "navigation"),
    )

    def __init__(self) -> None:
        self._shortcuts: dict[str, dict[str, Any]] = {
            key: {
                "key": key,
                "description": description,
                "category": category,
                "shortcut": None,
            }
            for key, description, category in self._DEFAULTS
        }

    @classmethod
    def instance(cls) -> "ShortcutManager":
        """Singleton accessor."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _normalize_key(key: str) -> str:
        sequence = QKeySequence(key)
        normalized = sequence.toString(QKeySequence.SequenceFormat.PortableText)
        if not normalized:
            raise ValueError("Shortcut key must be a valid, non-empty key sequence")
        return "Escape" if normalized == "Esc" else normalized

    def register(
        self,
        context: QWidget,
        key: str,
        callback: Callable[[], Any],
        description: str = "",
        category: str = "general",
    ) -> QShortcut:
        """Register a keyboard shortcut."""
        normalized_key = self._normalize_key(key)
        existing = self._shortcuts.get(normalized_key)
        if existing is not None and existing["shortcut"] is not None:
            existing["shortcut"].setEnabled(False)
            existing["shortcut"].deleteLater()

        shortcut = QShortcut(QKeySequence(normalized_key), context)
        shortcut.activated.connect(callback)
        self._shortcuts[normalized_key] = {
            "key": normalized_key,
            "description": description,
            "category": category,
            "shortcut": shortcut,
        }
        return shortcut

    def unregister(self, key: str) -> None:
        """Remove a registered shortcut."""
        entry = self._shortcuts.pop(self._normalize_key(key), None)
        if entry is not None and entry["shortcut"] is not None:
            entry["shortcut"].setEnabled(False)
            entry["shortcut"].deleteLater()

    def get_shortcuts(self) -> list[dict]:
        """Return all registered shortcuts as list of {key, description, category}."""
        return [
            {
                "key": entry["key"],
                "description": entry["description"],
                "category": entry["category"],
            }
            for entry in self._shortcuts.values()
        ]

    def get_shortcuts_by_category(self, category: str) -> list[dict]:
        """Return shortcuts filtered by category."""
        return [
            shortcut
            for shortcut in self.get_shortcuts()
            if shortcut["category"] == category
        ]
