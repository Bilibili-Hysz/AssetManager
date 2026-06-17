"""Application settings — singleton with atomic disk persistence."""
import atexit
import json
import logging
import os
import tempfile
import threading
from typing import Callable

from AssetsManager.core.database import SHARED_DIR
from AssetsManager.core.singleton import ThreadSafeSingleton

_log = logging.getLogger(__name__)

# ── Settings validation ──────────────────────────────────────────

_VALIDATORS: dict[str, Callable] = {
    "thumb_quality": lambda v: v in ("fast", "default", "high", "original"),
    "bg_panel_opacity": lambda v: isinstance(v, (int, float)) and 0.0 <= v <= 1.0,
    "search_history": lambda v: isinstance(v, list),
}


def _validate_setting(key: str, value) -> None:
    """Validate a setting value. Raises ValueError if invalid."""
    validator = _VALIDATORS.get(key)
    if validator and not validator(value):
        raise ValueError(f"Invalid value for setting '{key}': {value!r}")


class AppSettings:
    _instance = None

    def __init__(self):
        self._data: dict = {}
        self._dirty = False
        self._path = SHARED_DIR / "settings.json"
        self._lock = threading.RLock()
        atexit.register(self._atexit_save)

    @classmethod
    def instance(cls):
        return ThreadSafeSingleton.get(cls)

    def _get_lock(self):
        lock = getattr(self, "_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._lock = lock
        return lock

    def _atexit_save(self):
        if self._dirty:
            self.save()

    def load(self):
        with self._get_lock():
            try:
                if self._path.exists():
                    data = json.loads(self._path.read_text(encoding="utf-8"))
                    from AssetsManager.core.config_migrator import migrate
                    data = migrate(data)
                    self._data.update(data)
            except Exception:
                _log.exception("Failed to load settings from %s", self._path)

    def save(self):
        with self._get_lock():
            if not self._dirty:
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            try:
                snapshot = dict(self._data)
                data = json.dumps(snapshot, indent=2, ensure_ascii=False)
                fd, tmp = tempfile.mkstemp(dir=str(self._path.parent),
                                            suffix=".tmp",
                                            prefix="settings_")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(data)
                os.replace(tmp, str(self._path))
                self._dirty = False
            except OSError:
                _log.exception("Failed to save settings")

    def get(self, key, default=None):
        with self._get_lock():
            return self._data.get(key, default)

    def set(self, key, value):
        _validate_setting(key, value)
        with self._get_lock():
            self._data[key] = value
            self._dirty = True

    def get_list(self, key, default=None):
        with self._get_lock():
            val = self._data.get(key)
            if isinstance(val, list):
                return list(val)
            return default if default is not None else []

    def set_list(self, key, values, max_items=None):
        with self._get_lock():
            result = list(values)
            if max_items is not None and len(result) > max_items:
                result = result[:max_items]
            self._data[key] = result
            self._dirty = True

    def prepend_list(self, key, value, max_items=50):
        items = self.get_list(key)
        if value in items:
            items.remove(value)
        items.insert(0, value)
        self.set_list(key, items, max_items)

    def remove_from_list(self, key, value):
        items = self.get_list(key)
        if value in items:
            items.remove(value)
            self.set_list(key, items)

    @property
    def path(self):
        return self._path
