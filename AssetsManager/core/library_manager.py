"""Library manager — lightweight CRUD for library records.

Stores {uid: {name, path, last_opened, created}} in AppSettings.
Provides query/upsert/remove operations with UID-based lookup.
"""
import uuid
import time
from pathlib import Path

from AssetsManager.core.settings import AppSettings

_KEY = "library_records"


def _all() -> dict:
    """Return {uid: record} dict from settings."""
    data = AppSettings.instance().get(_KEY, {})
    if not isinstance(data, dict):
        return {}
    return data


def _save(data: dict) -> None:
    s = AppSettings.instance()
    if s.is_write_blocked:
        return
    s.set(_KEY, data)
    s.save()


def record_visit(path_str: str) -> str:
    """Create or update a library record. Returns UID."""
    if AppSettings.instance().is_write_blocked:
        return ""
    data = _all()
    resolved = str(Path(path_str).resolve())
    name = Path(resolved).name or resolved

    # Try to find existing by path
    existing_uid = None
    for uid, rec in data.items():
        if rec.get("path") == resolved:
            existing_uid = uid
            break

    if existing_uid:
        data[existing_uid]["name"] = name
        data[existing_uid]["last_opened"] = time.time()
    else:
        uid = uuid.uuid4().hex[:12]
        data[uid] = {
            "name": name,
            "path": resolved,
            "last_opened": time.time(),
            "created": time.time(),
        }
        existing_uid = uid

    _save(data)
    return existing_uid


def remove(uid: str) -> None:
    if AppSettings.instance().is_write_blocked:
        return
    data = _all()
    data.pop(uid, None)
    _save(data)


def list_all() -> list[dict]:
    """Return sorted list of library records (newest first)."""
    data = _all()
    records = [
        {"uid": uid, **rec} for uid, rec in data.items()
    ]
    records.sort(key=lambda r: r.get("last_opened", 0), reverse=True)
    return records


def get_by_uid(uid: str) -> dict | None:
    data = _all()
    rec = data.get(uid)
    if rec:
        return {"uid": uid, **rec}
    return None
