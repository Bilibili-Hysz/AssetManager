"""PanelState — the single save/restore contract for desktop UI state.

Panels expose ``save_state()``/``restore_state()``; a ``PanelState`` binds
that surface to one ``AppSettings`` key so persisted UI keys all flow through
the same validation and persistence path.
"""
from __future__ import annotations

from typing import Any, Callable


class PanelState:
    """Keyed bridge between an owner object and persisted AppSettings state.

    ``ctx`` may be a panel, the workspace section, or any object exposing the
    panel save/restore methods.  Custom owners can pass explicit callables.
    """

    def __init__(
        self,
        key: str,
        *,
        save: Callable[[Any], dict] | None = None,
        restore: Callable[[Any, dict], None] | None = None,
    ) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("PanelState key must be a non-empty string")
        self.key = key
        self._save = save
        self._restore = restore

    def save(self, ctx: Any) -> dict:
        """Return the owner state dict, falling back to ``ctx.save_state``."""
        if self._save is not None:
            return self._save(ctx)
        saver = getattr(ctx, "save_state", None)
        if not callable(saver):
            return {}
        # ``callable()`` narrows the duck-typed saver to a return of ``object``;
        # the owner contract is a state dict.
        saved: Any = saver()
        return saved

    def restore(self, ctx: Any, state: dict) -> None:
        """Apply *state*, falling back to ``ctx.restore_state``."""
        if self._restore is not None:
            self._restore(ctx, state)
            return
        restorer = getattr(ctx, "restore_state", None)
        if callable(restorer):
            restorer(state)

    def read(self) -> dict | None:
        """Return the raw persisted state without applying it."""
        from AssetsManager.core.settings import AppSettings

        try:
            state = AppSettings.instance().get(self.key)
        except Exception:
            return None
        return state if isinstance(state, dict) else None

    def persist(self, ctx: Any) -> None:
        """Snapshot and persist the owner state."""
        from AssetsManager.core.settings import AppSettings

        settings = AppSettings.instance()
        settings.set(self.key, self.save(ctx))
        settings.save()

    def load(self, ctx: Any) -> bool:
        """Restore the owner from AppSettings; return False when absent/invalid."""
        from AssetsManager.core.settings import AppSettings

        try:
            state = AppSettings.instance().get(self.key)
        except Exception:
            return False
        if not isinstance(state, dict):
            return False
        self.restore(ctx, state)
        return True
