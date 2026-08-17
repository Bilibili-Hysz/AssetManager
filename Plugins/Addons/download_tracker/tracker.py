"""Download Tracker — v2 example plugin.

Records import/copy events, exposes last-download metadata, and mounts a
small history dock.  Preferences persist under plugin_prefs.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from AssetsManager.domain.events import FileSystemChanged
from AssetsManager.plugin_api import (
    CommandOperator,
    EventHook,
    FileParser,
    PanelContributor,
    PluginContext,
    Preferences,
)

_TRACKED_KINDS = frozenset({"import", "copied"})
_history: dict[str, dict[str, Any]] = {}


def _load_history(ctx: PluginContext) -> None:
    bag = ctx.preferences("download_tracker")
    if bag is None:
        return
    raw = bag.get("history") or {}
    if isinstance(raw, dict):
        _history.clear()
        _history.update(raw)


def _save_history(ctx: PluginContext) -> None:
    bag = ctx.preferences("download_tracker")
    if bag is None:
        return
    bag.set("history", dict(_history))


def _prune(keep_days: int) -> None:
    if keep_days <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    stale: list[str] = []
    for path, rec in _history.items():
        stamp = str((rec or {}).get("last") or "")
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when < cutoff:
            stale.append(path)
    for path in stale:
        _history.pop(path, None)


class TrackerPrefs(Preferences):
    settings = {
        "keep_days": {"type": "int", "default": 30, "label": "Keep history (days)"},
    }


class DownloadParser(FileParser):
    id = "download_tracker"

    @classmethod
    def match(cls, ctx: PluginContext, file_path: str) -> bool:
        return str(file_path) in _history

    def parse(self, ctx: PluginContext, file_path: str) -> dict[str, Any]:
        rec = _history.get(str(file_path)) or {}
        count = rec.get("count", 0)
        return {
            "last_downloaded": str(rec.get("last") or ""),
            "download_count": str(count),
        }


class ImportHook(EventHook):
    event = FileSystemChanged

    def handle(self, ctx: PluginContext, event: Any) -> None:
        if getattr(event, "kind", "") not in _TRACKED_KINDS:
            return
        bag = ctx.preferences("download_tracker")
        keep_days = 30
        if bag is not None:
            try:
                keep_days = int(bag.get("keep_days", 30) or 30)
            except (TypeError, ValueError):
                keep_days = 30
        now = datetime.now(timezone.utc).isoformat()
        changed = False
        for raw in getattr(event, "paths", ()) or ():
            path = str(raw or "").strip()
            if not path:
                continue
            rec = dict(_history.get(path) or {})
            rec["count"] = int(rec.get("count") or 0) + 1
            rec["last"] = now
            _history[path] = rec
            changed = True
        if not changed:
            return
        _prune(keep_days)
        _save_history(ctx)


class ClearHistory(CommandOperator):
    id = "download_tracker.clear"
    title = "Clear download history"
    menu_paths = ("tools",)
    undoable = True
    params = {
        "confirm": {"type": "bool", "default": False, "label": "Confirm clear"},
    }

    def execute(self, ctx: PluginContext, params: dict[str, Any] | None = None) -> Any:
        if not (params or {}).get("confirm"):
            return False
        previous = dict(_history)
        _history.clear()
        _save_history(ctx)
        return {"previous": previous}

    def undo(self, ctx: PluginContext, record: dict[str, Any]) -> None:
        previous = record.get("previous") if isinstance(record, dict) else None
        _history.clear()
        if isinstance(previous, dict):
            _history.update(previous)
        _save_history(ctx)


class HistoryPanel(PanelContributor):
    id = "download_tracker.history"
    title = "Downloads"
    area = "right"

    def build(self, ctx: PluginContext) -> Any:
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

        widget = QWidget()
        layout = QVBoxLayout(widget)
        items = sorted(
            _history.items(),
            key=lambda item: str((item[1] or {}).get("last") or ""),
            reverse=True,
        )[:20]
        if not items:
            layout.addWidget(QLabel("No recorded downloads yet."))
        for path, rec in items:
            count = (rec or {}).get("count", 0)
            layout.addWidget(QLabel(f"{count}×  {path}"))
        layout.addStretch()
        return widget


class Plugin:
    def register(self, host):
        host.register_class(TrackerPrefs)
        _load_history(host.plugin_context())
        host.register_class(DownloadParser)
        host.register_class(ImportHook)
        host.register_class(ClearHistory)
        host.register_class(HistoryPanel)

    def unregister(self, host):
        _history.clear()
