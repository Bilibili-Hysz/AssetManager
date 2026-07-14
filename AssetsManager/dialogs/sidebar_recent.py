"""Sidebar recent folders — time-ordered per-library history."""
import logging
import tempfile
import time
from pathlib import Path

from AssetsManager.core.database import get_library_dir
from AssetsManager.core.json_store import JsonStore
from AssetsManager import i18n

_log = logging.getLogger(__name__)
tr = i18n.tr

MAX_RECENT = 5


class SidebarRecentFolders(JsonStore):
    def __init__(self, library_root: str = ""):
        self._items: list[dict] = []
        path = Path(tempfile.gettempdir()) / "AssetsManager_recent.json"
        super().__init__(path)
        if library_root:
            self.set_library_root(library_root)

    def set_library_root(self, library_root: str):
        if not library_root or library_root == ".":
            return
        old_data = list(self._items) if self._loaded else None
        self._path = get_library_dir(library_root) / "recent.json"
        self._loaded = False
        self._ensure_loaded()
        if old_data and not self._items:
            self._items = old_data
            self._save()

    # ── JsonStore hooks ─────────────────────────────────────────

    def _default_data(self):
        return []

    def _on_loaded(self, data):
        if isinstance(data, list):
            self._items = data
        else:
            self._items = []
        self._prune_missing()

    def _on_before_save(self):
        kept = sorted(self._items, key=lambda i: i.get("opened_at", 0), reverse=True)
        return kept[:MAX_RECENT * 2]

    # ── Internal helpers ────────────────────────────────────────

    def _prune_missing(self):
        before = len(self._items)
        self._items = [i for i in self._items if Path(i.get("path", "")).exists()]
        if len(self._items) != before:
            self._save()

    # ── Public API ──────────────────────────────────────────────

    def record_visit(self, path: str):
        self._ensure_loaded()
        path = str(Path(path).resolve())
        now = time.time()
        for item in self._items:
            if item.get("path") == path:
                item["opened_at"] = now
                self._save()
                return
        self._items.append({"path": path, "opened_at": now})
        self._save()

    def list_all(self) -> list[dict]:
        self._ensure_loaded()
        now = time.time()
        items = sorted(self._items, key=lambda i: i.get("opened_at", 0), reverse=True)
        result = []
        for item in items[:MAX_RECENT]:
            age_hours = (now - item.get("opened_at", 0)) / 3600
            result.append({**item, "_time_label": _time_label(age_hours)})
        return result

    def remove(self, path: str):
        self._ensure_loaded()
        path = str(Path(path).resolve())
        self._items = [i for i in self._items if i.get("path") != path]
        self._save()

    def clear(self):
        self._items = []
        self._save()


def _time_label(age_hours: float) -> str:
    if age_hours < 0.016:
        return tr("recent.just_now")
    if age_hours < 1:
        return tr("recent.minutes_ago").format(n=int(age_hours * 60))
    if age_hours < 2:
        return tr("recent.hour_ago")
    if age_hours < 24:
        return tr("recent.hours_ago").format(n=int(age_hours))
    days = age_hours / 24
    if days < 2:
        return tr("recent.yesterday")
    if days < 7:
        return tr("recent.days_ago").format(n=int(days))
    weeks = days / 7
    if weeks < 2:
        return tr("recent.week_ago")
    if weeks < 4:
        return tr("recent.weeks_ago").format(n=int(weeks))
    months = days / 30
    if months < 2:
        return tr("recent.month_ago")
    if months < 12:
        return tr("recent.months_ago").format(n=int(months))
    return tr("recent.years_ago").format(n=int(months / 12))
