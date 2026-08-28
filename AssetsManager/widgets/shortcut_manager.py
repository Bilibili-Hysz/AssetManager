"""Centralized keyboard shortcut registration and discovery."""

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

_log = logging.getLogger(__name__)


class ShortcutManager:
    """Centralized keyboard shortcut registry.

    ``description`` values are i18n keys (translated by the help dialog via
    :func:`AssetsManager.i18n.tr`) so registry-generated help retranslates
    with the UI language instead of freezing English text at registration
    time.
    """

    _instance: "ShortcutManager | None" = None

    # Documentation seeds for shortcuts whose target features actually exist.
    # (Ctrl+K Command Palette, Ctrl+P File Picker and Ctrl+B Toggle Sidebar
    # were removed: the product has no such features, and the help dialog is
    # generated from this registry.)
    _DEFAULTS = (
        ("Ctrl+,", "menu.settings", "navigation"),
        ("Ctrl+Q", "menu.exit", "application"),
        ("F1", "menu.keyboard_shortcuts", "application"),
        # Escape closes dialogs natively (QDialog); documented, never wired
        # as a QShortcut so it cannot interfere with widget-level handling.
        ("Escape", "shortcuts.close_dialog", "navigation"),
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

    def _replacing_conflict(self, normalized_key: str) -> None:
        existing = self._shortcuts.get(normalized_key)
        if existing is not None and existing["shortcut"] is not None:
            _log.warning(
                "Shortcut conflict: %s is already registered (%s); "
                "replacing it — last registration wins",
                normalized_key,
                existing["description"] or "unlabelled",
            )

    def register(
        self,
        context: QWidget,
        key: str,
        callback: Callable[[], Any],
        description: str = "",
        category: str = "general",
    ) -> QShortcut:
        """Register a keyboard shortcut as a new QShortcut on ``context``."""
        normalized_key = self._normalize_key(key)
        self._replacing_conflict(normalized_key)
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

    def register_action(
        self,
        action: QAction,
        key: str,
        description: str = "",
        category: str = "general",
    ) -> QAction:
        """Record a menu ``QAction`` shortcut in the registry.

        The action keeps dispatching through its own ``setShortcut``;
        recording it here only feeds the help dialog.  Creating an extra
        QShortcut for the same sequence instead would make Qt treat both
        entries as ambiguous and fire neither.
        """
        normalized_key = self._normalize_key(key)
        existing = self._shortcuts.get(normalized_key)
        if (
            existing is not None
            and existing["shortcut"] is not None
            and existing["shortcut"] is not action
        ):
            self._replacing_conflict(normalized_key)
            existing["shortcut"].setEnabled(False)
            existing["shortcut"].deleteLater()
        action.setShortcut(QKeySequence(normalized_key))
        self._shortcuts[normalized_key] = {
            "key": normalized_key,
            "description": description,
            "category": category,
            "shortcut": action,
        }
        return action

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
