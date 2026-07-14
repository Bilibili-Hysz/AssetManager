"""JsonStore — base class for JSON file persistence with atomic writes.

Provides:
- Atomic disk writes via tempfile + os.replace (no partial writes on crash)
- Lazy loading with _ensure_loaded()
- Dirty flag to skip unnecessary writes
- Optional on_load hook for data migration/transform

Usage:
    class MyStore(JsonStore):
        def _default_data(self):
            return []
        def _on_loaded(self, data):
            self._items = data
"""
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


class JsonStore:
    """Base class for JSON file persistence."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._dirty = False
        self._loaded = False
        self._load_lock = threading.Lock()

    # ── Subclass hooks ──────────────────────────────────────────

    def _default_data(self) -> Any:
        """Return default data when file doesn't exist. Override in subclass."""
        return {}

    def _on_loaded(self, data: Any) -> None:
        """Called after data is loaded from disk. Override to populate internal state."""
        pass

    def _on_before_save(self) -> Any:
        """Called before saving. Override to prepare data for serialization.
        Return None to skip saving."""
        return None

    # ── Core API ────────────────────────────────────────────────

    def _ensure_loaded(self):
        """Lazy-load data from disk. Idempotent. Thread-safe via double-checked locking."""
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            try:
                if self._path.exists():
                    data = json.loads(self._path.read_text(encoding="utf-8"))
                    self._on_loaded(data)
                else:
                    self._on_loaded(self._default_data())
            except Exception:
                _log.exception("Failed to load %s", self._path)
                self._on_loaded(self._default_data())
            self._loaded = True

    def _save(self, data=None):
        """Atomically write data to disk.

        Args:
            data: The data to serialize. If None, calls _on_before_save().
        """
        if data is None:
            data = self._on_before_save()
        if data is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            content = json.dumps(data, indent=2, ensure_ascii=False)
            fd, tmp = tempfile.mkstemp(
                dir=str(self._path.parent),
                suffix=".tmp",
                prefix=f".{self._path.stem}_",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, str(self._path))
                self._dirty = False
            except OSError:
                # Clean up temp file on failure
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
        except OSError:
            _log.exception("Failed to save %s", self._path)

    def _mark_dirty(self):
        """Mark data as modified (needs save)."""
        self._dirty = True

    @property
    def _is_dirty(self) -> bool:
        return self._dirty

    @property
    def path(self) -> Path:
        return self._path
