"""Per-plugin preference bags persisted under RuntimeData/Shared/plugin_prefs."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_prefs_root_override: Path | None = None


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
        self._data[str(key)] = value
        self._save()

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)
