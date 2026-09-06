"""Download Tracker — v2 example plugin.

Records import/copy events, exposes last-download metadata, and mounts a
small history dock.  Preferences persist under plugin_prefs.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
from typing import Any

try:  # Qt bindings are optional: the plugin core must load headless.
    from PySide6.QtCore import QObject as _QObject
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtCore import Signal as _Signal

    _QT_READY = True
except ImportError:  # pragma: no cover - environments without PySide6
    _QObject = None  # type: ignore[assignment]
    _Qt = None  # type: ignore[assignment]
    _Signal = None  # type: ignore[assignment]
    _QT_READY = False

from AssetsManager import i18n
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
_history_lock = threading.RLock()


if _QT_READY:

    class _RefreshSignal(_QObject):  # type: ignore[misc,valid-type]
        """Cross-thread refresh notifications for mounted HistoryPanel widgets."""

        # Must be a class attribute: instance-assigned signals break in PySide6.
        sig = _Signal()

else:  # pragma: no cover - headless fallback keeps attribute lookups safe

    class _RefreshSignal:
        """Inert stand-in used only when PySide6 is unavailable."""

        sig = None


_refresh_notifier: Any = None
_refresh_lock = threading.Lock()


def _realign_to_main_thread(obj: Any) -> None:
    """Best-effort move of the notifier onto the GUI thread.

    Queued signal deliveries land on the emitter object's owning thread, so
    the notifier must live on the main thread even when history updates first
    fire from a worker thread.
    """
    try:
        from PySide6.QtCore import QCoreApplication

        app = QCoreApplication.instance()
        if app is None or obj.thread() is app.thread():
            return
        obj.moveToThread(app.thread())
    except Exception:  # pragma: no cover - alignment is best effort only
        pass


def _ensure_refresh_notifier() -> Any:
    """Lazily create the module-wide notifier exactly once (thread-safe)."""
    global _refresh_notifier
    if not _QT_READY or _refresh_notifier is not None:
        return _refresh_notifier
    with _refresh_lock:
        if _refresh_notifier is None:
            notifier = _RefreshSignal()
            _realign_to_main_thread(notifier)
            _refresh_notifier = notifier
    return _refresh_notifier


def _emit_refresh() -> None:
    """Emit a refresh ping; safe to call from any thread, no-op without Qt."""
    notifier = _ensure_refresh_notifier()
    if notifier is None:
        return
    try:
        notifier.sig.emit()
    except RuntimeError:  # pragma: no cover - C++ object already deleted
        pass


def _load_history(ctx: PluginContext) -> None:
    with _history_lock:
        bag = ctx.preferences("download_tracker")
        if bag is None:
            return
        raw = bag.get("history") or {}
        if isinstance(raw, dict):
            _history.clear()
            _history.update(raw)


def _save_history(ctx: PluginContext) -> None:
    with _history_lock:
        bag = ctx.preferences("download_tracker")
        if bag is None:
            return
        bag.set("history", dict(_history))


def _prune(keep_days: int) -> None:
    if keep_days <= 0:
        return
    with _history_lock:
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
        # V10: user-visible labels go through the trilingual catalog.
        "keep_days": {
            "type": "int",
            "default": 30,
            "label": i18n.tr("plugin_tracker.pref_keep_days", default="Keep history (days)"),
        },
    }


class DownloadParser(FileParser):
    id = "download_tracker"

    @classmethod
    def match(cls, ctx: PluginContext, file_path: str) -> bool:
        with _history_lock:
            return str(file_path) in _history

    def parse(self, ctx: PluginContext, file_path: str) -> dict[str, Any]:
        with _history_lock:
            rec = dict(_history.get(str(file_path)) or {})
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
        with _history_lock:
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
        # History changed: ping mounted panels (queued across threads).
        _emit_refresh()


class ClearHistory(CommandOperator):
    id = "download_tracker.clear"
    title = i18n.tr("plugin_tracker.cmd_clear", default="Clear download history")
    menu_paths = ("tools",)
    undoable = True
    params = {
        "confirm": {
            "type": "bool",
            "default": False,
            "label": i18n.tr("plugin_tracker.pref_confirm", default="Confirm clear"),
        },
    }

    def execute(self, ctx: PluginContext, params: dict[str, Any] | None = None) -> Any:
        if not (params or {}).get("confirm"):
            return False
        with _history_lock:
            previous = {path: dict(record) for path, record in _history.items()}
            _history.clear()
            _save_history(ctx)
        return {"previous": previous}

    def undo(self, ctx: PluginContext, record: dict[str, Any]) -> None:
        previous = record.get("previous") if isinstance(record, dict) else None
        with _history_lock:
            _history.clear()
            if isinstance(previous, dict):
                _history.update(previous)
            _save_history(ctx)


class HistoryPanel(PanelContributor):
    id = "download_tracker.history"
    title = i18n.tr("plugin_tracker.title", default="Downloads")
    area = "right"

    def build(self, ctx: PluginContext) -> Any:
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        widget = QWidget()
        layout = QVBoxLayout(widget)
        self._populate(layout)
        self._connect_refresh(layout, widget)
        return widget

    def _populate(self, layout: Any) -> None:
        """(Re)fill the layout from a consistent snapshot of _history."""
        from PySide6.QtWidgets import QLabel

        with _history_lock:
            items = sorted(
                ((path, dict(record or {})) for path, record in _history.items()),
                key=lambda item: str((item[1] or {}).get("last") or ""),
                reverse=True,
            )[:20]
        if not items:
            # V10: empty state goes through the trilingual catalog (rendered
            # at populate time, so it follows the current language).
            layout.addWidget(QLabel(
                i18n.tr("plugin_tracker.empty", default="No recorded downloads yet.")
            ))
        for path, rec in items:
            count = (rec or {}).get("count", 0)
            layout.addWidget(QLabel(f"{count}×  {path}"))
        layout.addStretch()

    def _connect_refresh(self, layout: Any, widget: Any) -> None:
        """Subscribe this mount to the module-wide refresh signal.

        ``layout``/``widget`` stay referenced by the slot closure so neither
        the Python wrappers nor Qt's C++ objects die behind our back between
        signal emission and delivery.
        """
        notifier = _ensure_refresh_notifier()
        if notifier is None:  # headless/stub Qt: wiring compiled out
            return

        def rebuild() -> None:
            while layout.count():
                item = layout.takeAt(0)
                child = item.widget()
                if child is not None:
                    child.deleteLater()
            self._populate(layout)

        def on_refresh() -> None:
            # Stale queued events may arrive after the dock was destroyed;
            # a deleted C++ object makes PySide6 raise RuntimeError.
            try:
                rebuild()
            except RuntimeError:
                try:
                    notifier.sig.disconnect(on_refresh)
                except (RuntimeError, TypeError):
                    pass

        try:
            notifier.sig.connect(on_refresh, _Qt.ConnectionType.QueuedConnection)
        except (RuntimeError, TypeError):  # pragma: no cover - broken wiring
            pass


class Plugin:
    def register(self, host):
        host.register_class(TrackerPrefs)
        _load_history(host.plugin_context())
        host.register_class(DownloadParser)
        host.register_class(ImportHook)
        host.register_class(ClearHistory)
        host.register_class(HistoryPanel)

    def unregister(self, host):
        with _history_lock:
            _history.clear()
