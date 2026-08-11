"""Config migration — versioned schema with auto-upgrade.

Stores _cfg_version in settings.json. On version mismatch, applies
transformations to migrate old config to new schema.
"""
import logging

_log = logging.getLogger(__name__)

CURRENT_VERSION = 2


def _migrate_v0_to_v1(data: dict) -> dict:
    """Remove dead workspace keys leftover from earlier builds."""
    for dead in ("workspace_libraries", "workspace_active"):
        data.pop(dead, None)
    _log.info("v0→v1: removed dead workspace keys")
    return data


def _migrate_v1_to_v2(data: dict) -> dict:
    """Ensure search_history list exists for search completer."""
    data.setdefault("search_history", [])
    _log.info("v1→v2: added search_history default")
    return data


MIGRATIONS = {
    1: _migrate_v0_to_v1,
    2: _migrate_v1_to_v2,
}


def migrate(settings_data: dict) -> dict:
    ver = settings_data.get("_cfg_version", 0)
    if not isinstance(ver, int) or isinstance(ver, bool):
        raise ValueError(f"Invalid settings version: {ver!r}")
    if ver > CURRENT_VERSION:
        raise ValueError(
            f"Settings version {ver} is newer than supported version {CURRENT_VERSION}; "
            "refusing to downgrade configuration"
        )
    while ver < CURRENT_VERSION:
        ver += 1
        if ver in MIGRATIONS:
            _log.info("Config migration: v%s → v%s", ver - 1, ver)
            settings_data = MIGRATIONS[ver](settings_data)
    settings_data["_cfg_version"] = CURRENT_VERSION
    return settings_data
