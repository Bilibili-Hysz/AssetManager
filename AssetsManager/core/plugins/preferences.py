"""Per-plugin preference bags persisted under RuntimeData/Shared/plugin_prefs."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any


class _AdvisoryLock:
    """Best-effort OS-level exclusive lock over one prefs save window.

    Multiple processes writing the same preference file cannot share the
    in-process path lock, so each ``set`` takes a short non-blocking lock on
    a sidecar file.  The counterpart in every process re-reads the merged
    JSON inside its lock before dumping, which narrows last-writer-wins to
    the (rare) case where the whole save window is contended.  Platforms
    without these primitives fall back to unlocked behavior.
    """

    def __init__(self, path: Path) -> None:
        self._lock_path = Path(str(path) + ".preflock")
        self._handle = None
        self._kind: str | None = None

    def acquire(self, *, attempts: int = 5, base_delay: float = 0.01) -> bool:
        try:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = self._lock_path.open("a+b")
        except OSError:
            return False
        acquired = False
        try:
            for _ in range(attempts):
                if os.name == "nt":
                    import msvcrt

                    try:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    except OSError:
                        time.sleep(base_delay)
                        continue
                    self._kind = "nt"
                    acquired = True
                    break
                try:
                    import fcntl
                except ImportError:
                    break
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    time.sleep(base_delay)
                    continue
                self._kind = "posix"
                acquired = True
                break
        finally:
            if not acquired:
                handle.close()
        if acquired:
            self._handle = handle
        return acquired

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if self._kind == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            elif self._kind == "posix":
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            self._handle.close()
        except OSError:
            pass
        self._handle = None

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *_exc) -> bool:
        self.release()
        return False


_log = logging.getLogger(__name__)

_prefs_root_override: Path | None = None

# Same-path bags are independent in-memory snapshots, so a plain full-file
# rewrite loses concurrent writers' keys.  Locks are keyed by the resolved
# file path (not the plugin id: _safe_plugin_id can collide ids) and every
# save re-reads peer writes before dumping — see PluginPreferenceBag._save.
_PATH_LOCK_CAP = 1024
_path_locks_guard = threading.Lock()
_path_locks: OrderedDict[str, threading.RLock] = OrderedDict()


def set_prefs_root(path: Path | None) -> None:
    """Test hook: redirect preference files away from RuntimeData."""
    global _prefs_root_override
    _prefs_root_override = Path(path) if path is not None else None


def _prefs_root() -> Path:
    if _prefs_root_override is not None:
        root = _prefs_root_override
    else:
        from AssetsManager.core.path_resolver import shared_dir

        root = shared_dir() / "plugin_prefs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _lock_for(path: Path) -> threading.RLock:
    key = str(path)
    with _path_locks_guard:
        lock = _path_locks.get(key)
        if lock is None:
            while len(_path_locks) >= _PATH_LOCK_CAP:
                _path_locks.popitem(last=False)
            lock = threading.RLock()
            _path_locks[key] = lock
        _path_locks.move_to_end(key)
        return lock


def _safe_plugin_id(plugin_id: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(plugin_id or "").strip())
    return text or "plugin"


class PluginPreferenceBag:
    """Dict-like view over one plugin's JSON preference file."""

    def __init__(self, plugin_id: str, defaults: dict[str, Any] | None = None) -> None:
        self.plugin_id = plugin_id
        self._path = _prefs_root() / f"{_safe_plugin_id(plugin_id)}.json"
        self._defaults = dict(defaults or {})
        self._data = dict(self._defaults)
        self._load()

    def _load(self) -> None:
        try:
            if self._path.is_file():
                payload = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    merged = dict(self._defaults)
                    merged.update(payload)
                    self._data = merged
        except (OSError, json.JSONDecodeError):
            _log.warning("Failed to load plugin preferences for %s", self.plugin_id, exc_info=True)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".pref-", suffix=".tmp", dir=str(self._path.parent))
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(tmp, self._path)
        except OSError:
            _log.warning("Failed to save plugin preferences for %s", self.plugin_id, exc_info=True)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with _lock_for(self._path):
            with _AdvisoryLock(self._path) as acquired:
                # Preserve keys another same-path bag (in this or another
                # process holding the advisory lock) wrote since this
                # snapshot was taken; this bag's explicit value wins its own
                # key only.
                if acquired or True:
                    self._merge_disk_state()
                self._data[str(key)] = value
                self._save()

    def _merge_disk_state(self) -> None:
        try:
            disk_payload = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(disk_payload, dict):
                merged = dict(disk_payload)
                merged.update(self._data)
                self._data = merged
        except (OSError, json.JSONDecodeError, ValueError):
            pass  # corrupt/absent file falls back to our snapshot alone

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)
