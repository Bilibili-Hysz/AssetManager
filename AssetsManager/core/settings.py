"""Application settings — singleton with atomic disk persistence."""
import atexit
import json
import logging
import os
import tempfile
import threading
from typing import Callable, cast

from AssetsManager.core.config_migrator import FutureConfigVersionError
from AssetsManager.core.constants import (
    AI_TAGGING_DEFAULT_ENDPOINT,
    AI_TAGGING_DEFAULT_MAX_TAGS,
    AI_TAGGING_DEFAULT_MODEL,
    AI_TAGGING_MAX_TAGS_LIMIT,
    AI_TAGGING_MIN_TAGS,
    THUMBNAIL_CACHE_DEFAULT_MAX_BYTES,
)
from AssetsManager.core.path_resolver import SHARED_DIR
from AssetsManager.core.singleton import ThreadSafeSingleton

_log = logging.getLogger(__name__)

# ── Settings validation ──────────────────────────────────────────

SHARE_SAFETY_ACK_VERSION_KEY = "lan_share_safety_ack_version"
TRUSTED_NETWORK_CONFIRMED_KEY = "lan_trusted_network_confirmed"
SHARE_LAST_SUCCESSFUL_BIND_KEY = "lan_share_last_successful_bind"
SHARE_LAST_SUCCESSFUL_AUTH_KEY = "lan_share_last_successful_auth"
LIBRARY_WATCHER_INTERVAL_KEY = "library_watcher_interval_seconds"
THUMBNAIL_CACHE_MAX_BYTES_KEY = "thumbnail_cache_max_bytes"
AI_TAGGING_ENABLED_KEY = "ai_tagging_enabled"
AI_TAGGING_ENDPOINT_KEY = "ai_tagging_endpoint"
AI_TAGGING_MODEL_KEY = "ai_tagging_model"
AI_TAGGING_MAX_TAGS_KEY = "ai_tagging_max_tags"
AI_TAGGING_FORCE_EXISTING_KEY = "ai_tagging_force_existing"
DEFAULT_LIBRARY_WATCHER_INTERVAL = 120.0
DEFAULT_SHARE_SAFETY_ACK_VERSION = 0
DEFAULT_TRUSTED_NETWORK_CONFIRMED = False
DEFAULT_SHARE_LAST_SUCCESSFUL_BIND = None
DEFAULT_SHARE_LAST_SUCCESSFUL_AUTH = None


def _valid_http_url(value) -> bool:
    """True for an absolute http(s) URL with a host."""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        from urllib.parse import urlparse
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)

_VALIDATORS: dict[str, Callable] = {
    "thumb_quality": lambda v: v in ("fast", "default", "high", "original"),
    "bg_panel_opacity": lambda v: isinstance(v, (int, float)) and 0.0 <= v <= 1.0,
    "bg_effect": lambda v: v in ("none", "blur", "mosaic", "kuwahara", "shader"),
    "bg_shader_preset": lambda v: isinstance(v, str) and bool(v),
    "search_history": lambda v: isinstance(v, list),
    # Thumbnail disk-cache cap in bytes; 0 = unlimited (H2-a2).
    THUMBNAIL_CACHE_MAX_BYTES_KEY: (
        lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 0
    ),
    # AI tagging (H2-c). The feature is off until explicitly enabled; the
    # endpoint must be an absolute http(s) URL; max_tags stays in 1-20 so a
    # corrupted value can never flood an asset with machine tags.
    AI_TAGGING_ENABLED_KEY: lambda v: isinstance(v, bool),
    AI_TAGGING_ENDPOINT_KEY: _valid_http_url,
    AI_TAGGING_MODEL_KEY: lambda v: isinstance(v, str) and bool(v.strip()),
    AI_TAGGING_MAX_TAGS_KEY: (
        lambda v: isinstance(v, int)
        and not isinstance(v, bool)
        and AI_TAGGING_MIN_TAGS <= v <= AI_TAGGING_MAX_TAGS_LIMIT
    ),
    AI_TAGGING_FORCE_EXISTING_KEY: lambda v: isinstance(v, bool),
    SHARE_SAFETY_ACK_VERSION_KEY: lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 0,
    TRUSTED_NETWORK_CONFIRMED_KEY: lambda v: isinstance(v, bool),
    SHARE_LAST_SUCCESSFUL_BIND_KEY: lambda v: isinstance(v, str) and bool(v),
    SHARE_LAST_SUCCESSFUL_AUTH_KEY: lambda v: (
        isinstance(v, dict)
        and set(v) == {"enabled", "mode"}
        and isinstance(v["enabled"], bool)
        and isinstance(v["mode"], str)
        and bool(v["mode"])
    ),
}


def _validate_setting(key: str, value) -> None:
    """Validate a setting value. Raises ValueError if invalid."""
    validator = _VALIDATORS.get(key)
    if validator and not validator(value):
        raise ValueError(f"Invalid value for setting '{key}': {value!r}")



class AppSettings:
    # Set once the exit-time flush has been registered; guards against
    # duplicate atexit handlers from directly constructed instances.
    _atexit_registered = False

    def __init__(self):
        self._data: dict = {}
        self._dirty = False
        self._loaded = False
        self._future_config_version: int | None = None
        self._path = SHARED_DIR / "settings.json"
        self._lock = threading.RLock()
        # Register the exit-time flush at most once per process, and never
        # for a directly constructed duplicate of an existing singleton.
        # Both would otherwise save at interpreter exit, and the later flush
        # could overwrite the other's snapshot with stale in-memory data.
        if (
            getattr(type(self), "_singleton_instance", None) is not self
            and not type(self)._atexit_registered
        ):
            type(self)._atexit_registered = True
            atexit.register(self._atexit_save)

    @classmethod
    def instance(cls):
        obj = ThreadSafeSingleton.get(cls)
        obj._ensure_loaded_once()
        return obj

    def _ensure_loaded_once(self):
        """Load persisted settings on first singleton access.

        Without this, a ``set()`` + ``save()`` before any explicit ``load()``
        (e.g. a UI-scale read at startup) would overwrite the settings file
        with a near-empty dict, silently dropping user configuration.
        """
        with self._get_lock():
            if not getattr(self, "_loaded", False):
                self.load()
                self._loaded = True

    def _get_lock(self):
        lock = getattr(self, "_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._lock = lock
        return lock

    def _atexit_save(self):
        if self.is_write_blocked:
            return
        if self._dirty:
            self.save()

    @property
    def is_write_blocked(self) -> bool:
        return getattr(self, "_future_config_version", None) is not None

    def load(self):
        with self._get_lock():
            self._future_config_version = None
            try:
                if self._path.exists():
                    data = json.loads(self._path.read_text(encoding="utf-8"))
                    # A well-formed JSON file that is not an object (e.g. a
                    # bare list or string) is corrupt: migration would crash
                    # on it and the error would be swallowed without
                    # quarantining the file.
                    if not isinstance(data, dict):
                        _log.error(
                            "Settings root is not a JSON object (%s) — quarantining %s",
                            type(data).__name__, self._path,
                        )
                        self._quarantine_corrupt_settings()
                        return
                    from AssetsManager.core.config_migrator import migrate
                    old_version = data.get("_cfg_version")
                    data = migrate(data)
                    # A migration that upgraded the config must be persisted,
                    # otherwise the rewrite is re-derived (and re-logged) on
                    # every startup without ever being written back.
                    if data.get("_cfg_version") != old_version:
                        self._dirty = True
                    self._data.update(data)
                # Always try legacy migration if not yet done
                if not self._data.get("_legacy_migrated"):
                    self._migrate_legacy_settings()
            except json.JSONDecodeError:
                _log.exception("Failed to parse settings from %s", self._path)
                self._quarantine_corrupt_settings()
            except UnicodeDecodeError:
                # A file that cannot be decoded is corrupt regardless of
                # content, distinct from a well-formed future version that
                # migration rejects.
                _log.exception("Failed to decode settings from %s", self._path)
                self._quarantine_corrupt_settings()
            except FutureConfigVersionError as exc:
                self._data.clear()
                self._future_config_version = exc.version
                self._dirty = False
                _log.error(
                    "Settings version %s is newer than this application; "
                    "preserving %s as read-only",
                    exc.version,
                    self._path,
                )
            except (ValueError, TypeError):
                _log.exception("Settings rejected by migration at %s", self._path)
            except Exception:
                _log.exception("Failed to load settings from %s", self._path)

    def _quarantine_corrupt_settings(self):
        """Back up a corrupt settings file and fall back to defaults."""
        self._data.clear()
        try:
            if self._path.exists():
                corrupt = self._path.with_suffix(self._path.suffix + ".corrupt")
                os.replace(str(self._path), str(corrupt))
                _log.warning("Quarantined corrupt settings to %s", corrupt)
        except OSError:
            _log.exception("Failed to quarantine corrupt settings at %s", self._path)
        self._data["_legacy_migrated"] = True
        self._dirty = True

    def _migrate_legacy_settings(self):
        """Migrate settings from old .assetmanager/ location if present."""
        from pathlib import Path
        legacy_path = Path.home() / ".assetmanager" / "settings.json"
        if not legacy_path.exists():
            self._data["_legacy_migrated"] = True
            self._dirty = True
            return
        try:
            data = json.loads(legacy_path.read_text(encoding="utf-8"))
            from AssetsManager.core.config_migrator import migrate
            data = migrate(data)
            # The current settings file is authoritative. Legacy values only
            # fill keys absent from it so an old profile cannot overwrite a
            # user change that was already persisted in the new location.
            for key, value in data.items():
                self._data.setdefault(key, value)
            self._data["_legacy_migrated"] = True
            self._dirty = True
            self.save()
            _log.info("Migrated legacy settings from %s", legacy_path)
        except Exception:
            self._data["_legacy_migrated"] = True
            self._dirty = True
            self.save()
            _log.exception("Failed to migrate legacy settings from %s", legacy_path)

    def save(self) -> bool:
        with self._get_lock():
            if self.is_write_blocked:
                return False
            if not self._dirty:
                return True
            tmp = None
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                snapshot = dict(self._data)
                data = json.dumps(snapshot, indent=2, ensure_ascii=False)
                fd, tmp = tempfile.mkstemp(dir=str(self._path.parent),
                                            suffix=".tmp",
                                            prefix="settings_")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, str(self._path))
                self._dirty = False
                return True
            except (OSError, TypeError, ValueError):
                if tmp is not None:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                _log.exception("Failed to save settings")
                return False

    def get(self, key, default=None):
        with self._get_lock():
            return self._data.get(key, default)

    def set(self, key, value):
        with self._get_lock():
            if self.is_write_blocked:
                return
        _validate_setting(key, value)
        with self._get_lock():
            if self.is_write_blocked:
                return
            self._data[key] = value
            self._dirty = True

    def get_list(self, key, default=None):
        with self._get_lock():
            val = self._data.get(key)
            if isinstance(val, list):
                return list(val)
            return default if default is not None else []

    def get_share_safety_ack_version(self) -> int:
        """Return the persisted share-safety acknowledgement version.

        Missing or malformed legacy values deliberately mean ``0``.  This is
        fail-closed and does not mutate settings or infer confirmation.
        """
        value = self.get(SHARE_SAFETY_ACK_VERSION_KEY, DEFAULT_SHARE_SAFETY_ACK_VERSION)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    def get_thumbnail_cache_max_bytes(self) -> int:
        """Return the thumbnail disk-cache cap in bytes; ``0`` = unlimited.

        Missing or malformed legacy values fall back to the H2 default
        (2 GB) without mutating settings — the same fail-closed read shape
        as :meth:`get_share_safety_ack_version`.
        """
        value = self.get(
            THUMBNAIL_CACHE_MAX_BYTES_KEY, THUMBNAIL_CACHE_DEFAULT_MAX_BYTES
        )
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return THUMBNAIL_CACHE_DEFAULT_MAX_BYTES

    def set_thumbnail_cache_max_bytes(self, max_bytes: int) -> None:
        self.set(THUMBNAIL_CACHE_MAX_BYTES_KEY, int(max_bytes))

    # ── AI tagging (H2-c) — fail-closed reads like the cap above ──

    def get_ai_tagging_enabled(self) -> bool:
        """Return whether AI tagging is on; missing/malformed means off."""
        value = self.get(AI_TAGGING_ENABLED_KEY, False)
        return value if isinstance(value, bool) else False

    def set_ai_tagging_enabled(self, enabled: bool) -> None:
        # No bool() coercion: the validator must see the raw value so a
        # truthy non-bool cannot silently enable the feature.
        self.set(AI_TAGGING_ENABLED_KEY, enabled)

    def get_ai_tagging_endpoint(self) -> str:
        """Return the OpenAI-compatible endpoint; malformed falls to default."""
        value = self.get(AI_TAGGING_ENDPOINT_KEY, AI_TAGGING_DEFAULT_ENDPOINT)
        if _valid_http_url(value):
            return str(value).strip()
        return AI_TAGGING_DEFAULT_ENDPOINT

    def set_ai_tagging_endpoint(self, endpoint: str) -> None:
        self.set(AI_TAGGING_ENDPOINT_KEY, str(endpoint).strip())

    def get_ai_tagging_model(self) -> str:
        """Return the vision model name; missing/malformed falls to default."""
        value = self.get(AI_TAGGING_MODEL_KEY, AI_TAGGING_DEFAULT_MODEL)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return AI_TAGGING_DEFAULT_MODEL

    def set_ai_tagging_model(self, model: str) -> None:
        self.set(AI_TAGGING_MODEL_KEY, str(model).strip())

    def get_ai_tagging_max_tags(self) -> int:
        """Return the per-image tag cap, clamped to 1-20."""
        value = self.get(AI_TAGGING_MAX_TAGS_KEY, AI_TAGGING_DEFAULT_MAX_TAGS)
        if isinstance(value, int) and not isinstance(value, bool) \
                and AI_TAGGING_MIN_TAGS <= value <= AI_TAGGING_MAX_TAGS_LIMIT:
            return value
        return AI_TAGGING_DEFAULT_MAX_TAGS

    def set_ai_tagging_max_tags(self, max_tags: int) -> None:
        # No int() coercion: True would otherwise become 1 and slip past
        # the validator's bool exclusion.
        self.set(AI_TAGGING_MAX_TAGS_KEY, max_tags)

    def get_ai_tagging_force_existing(self) -> bool:
        """Return whether model output must converge to existing tags.

        Missing or malformed values default to ``True`` (whitelist-only)
        so a legacy/corrupt profile can never loosen the write boundary.
        """
        value = self.get(AI_TAGGING_FORCE_EXISTING_KEY, True)
        return value if isinstance(value, bool) else True

    def set_ai_tagging_force_existing(self, force_existing: bool) -> None:
        # No bool() coercion — same raw-value rule as the enabled setter.
        self.set(AI_TAGGING_FORCE_EXISTING_KEY, force_existing)

    def set_share_safety_ack_version(self, version: int) -> None:
        self.set(SHARE_SAFETY_ACK_VERSION_KEY, version)

    def get_trusted_network_confirmed(self) -> bool:
        """Return the persisted trusted-LAN confirmation, defaulting safely."""
        value = self.get(TRUSTED_NETWORK_CONFIRMED_KEY, DEFAULT_TRUSTED_NETWORK_CONFIRMED)
        return value if isinstance(value, bool) else False

    def set_trusted_network_confirmed(self, confirmed: bool) -> None:
        self.set(TRUSTED_NETWORK_CONFIRMED_KEY, confirmed)

    def commit_share_safety_confirmation(self, ack_version: int, trusted: bool) -> bool:
        """Persist the share-safety confirmation only if saving succeeds."""
        if self.is_write_blocked:
            return False
        _validate_setting(SHARE_SAFETY_ACK_VERSION_KEY, ack_version)
        _validate_setting(TRUSTED_NETWORK_CONFIRMED_KEY, trusted)
        with self._get_lock():
            keys = (SHARE_SAFETY_ACK_VERSION_KEY, TRUSTED_NETWORK_CONFIRMED_KEY)
            old_values = {key: self._data.get(key) for key in keys}
            old_present = {key: key in self._data for key in keys}
            old_dirty = self._dirty
            self._data[SHARE_SAFETY_ACK_VERSION_KEY] = ack_version
            self._data[TRUSTED_NETWORK_CONFIRMED_KEY] = trusted
            self._dirty = True
            try:
                if self.save():
                    return True
            except Exception:
                _log.exception("Failed to commit share-safety confirmation")

            for key in keys:
                if old_present[key]:
                    self._data[key] = old_values[key]
                else:
                    self._data.pop(key, None)
            self._dirty = old_dirty
            return False

    def get_share_security_history(self) -> tuple[str | None, dict[str, object] | None]:
        """Return the last successful LAN bind and effective auth posture.

        Any missing or malformed value invalidates the complete history so a
        stale or tampered record cannot be used as a security signal.
        """
        with self._get_lock():
            bind = self._data.get(SHARE_LAST_SUCCESSFUL_BIND_KEY, DEFAULT_SHARE_LAST_SUCCESSFUL_BIND)
            auth_status = self._data.get(SHARE_LAST_SUCCESSFUL_AUTH_KEY, DEFAULT_SHARE_LAST_SUCCESSFUL_AUTH)
            if not _VALIDATORS[SHARE_LAST_SUCCESSFUL_BIND_KEY](bind):
                return None, None
            if not _VALIDATORS[SHARE_LAST_SUCCESSFUL_AUTH_KEY](auth_status):
                return None, None
            return cast(str, bind), dict(cast(dict[str, object], auth_status))

    def set_share_security_history(self, bind: str, auth_status: dict[str, object]) -> None:
        """Persist only a bind string and the effective auth posture."""
        if self.is_write_blocked:
            return
        _validate_setting(SHARE_LAST_SUCCESSFUL_BIND_KEY, bind)
        _validate_setting(SHARE_LAST_SUCCESSFUL_AUTH_KEY, auth_status)
        with self._get_lock():
            self._data[SHARE_LAST_SUCCESSFUL_BIND_KEY] = bind
            self._data[SHARE_LAST_SUCCESSFUL_AUTH_KEY] = dict(auth_status)
            self._dirty = True

    def commit_share_security_history(self, bind: str, auth_status: dict[str, object]) -> bool:
        """Persist LAN security history only if the settings save succeeds."""
        if self.is_write_blocked:
            return False
        _validate_setting(SHARE_LAST_SUCCESSFUL_BIND_KEY, bind)
        _validate_setting(SHARE_LAST_SUCCESSFUL_AUTH_KEY, auth_status)
        with self._get_lock():
            old_values = {
                SHARE_LAST_SUCCESSFUL_BIND_KEY: self._data.get(SHARE_LAST_SUCCESSFUL_BIND_KEY),
                SHARE_LAST_SUCCESSFUL_AUTH_KEY: self._data.get(SHARE_LAST_SUCCESSFUL_AUTH_KEY),
            }
            old_present = {
                SHARE_LAST_SUCCESSFUL_BIND_KEY: SHARE_LAST_SUCCESSFUL_BIND_KEY in self._data,
                SHARE_LAST_SUCCESSFUL_AUTH_KEY: SHARE_LAST_SUCCESSFUL_AUTH_KEY in self._data,
            }
            old_dirty = self._dirty
            self._data[SHARE_LAST_SUCCESSFUL_BIND_KEY] = bind
            self._data[SHARE_LAST_SUCCESSFUL_AUTH_KEY] = dict(auth_status)
            self._dirty = True
            try:
                if self.save():
                    return True
            except Exception:
                _log.exception("Failed to commit LAN security history")

            for key in (SHARE_LAST_SUCCESSFUL_BIND_KEY, SHARE_LAST_SUCCESSFUL_AUTH_KEY):
                if old_present[key]:
                    self._data[key] = old_values[key]
                else:
                    self._data.pop(key, None)
            self._dirty = old_dirty
            return False

    def set_list(self, key, values, max_items=None):
        with self._get_lock():
            if self.is_write_blocked:
                return
            result = list(values)
            if max_items is not None and len(result) > max_items:
                result = result[:max_items]
            self._data[key] = result
            self._dirty = True

    def prepend_list(self, key, value, max_items=50):
        """Atomically move ``value`` to the front of the list at ``key``.

        The read-modify-write happens under a single lock acquisition so a
        concurrent ``prepend_list``/``remove_from_list`` cannot interleave
        and lose an update.
        """
        with self._get_lock():
            if self.is_write_blocked:
                return
            items = self._data.get(key)
            items = list(items) if isinstance(items, list) else []
            if value in items:
                items.remove(value)
            items.insert(0, value)
            if max_items is not None and len(items) > max_items:
                items = items[:max_items]
            self._data[key] = items
            self._dirty = True

    def remove_from_list(self, key, value):
        """Atomically remove ``value`` from the list at ``key`` if present."""
        with self._get_lock():
            if self.is_write_blocked:
                return
            items = self._data.get(key)
            if isinstance(items, list) and value in items:
                items = list(items)
                items.remove(value)
                self._data[key] = items
                self._dirty = True

    @property
    def path(self):
        return self._path
