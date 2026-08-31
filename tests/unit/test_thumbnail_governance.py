"""H2-a2/a3: startup governance scheduling and settings round-trip.

Covers the silent per-session startup pass (daemon thread, once per session,
swallow-on-error), the activity-retention branch, and the
``thumbnail_cache_max_bytes`` setting contract (default, 0 = unlimited,
validation).
"""
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

import AssetsManager.application.library_governance as governance
from AssetsManager.core.constants import THUMBNAIL_CACHE_DEFAULT_MAX_BYTES
from AssetsManager.core.settings import AppSettings


class _FakeThumbnailService:
    def __init__(self, result=(3, 1500)):
        self.calls = []
        self._result = result
        self.invoked = threading.Event()

    def enforce_cache_capacity(self, library_root, thumb_dir, *, max_bytes):
        self.calls.append((library_root, thumb_dir, max_bytes))
        self.invoked.set()
        return self._result


class _BoomThumbnailService:
    def enforce_cache_capacity(self, library_root, thumb_dir, *, max_bytes):
        raise RuntimeError("enforcement exploded")


class _StubSettings:
    """Stubbed settings seam; ``read`` doubles as a worker-sync event."""

    def __init__(self, max_bytes):
        self._max_bytes = max_bytes
        self.read = threading.Event()

    def get_thumbnail_cache_max_bytes(self):
        self.read.set()
        return self._max_bytes


def _scoped(token=None, *, closed=False, thumbnail_service=None):
    session = SimpleNamespace(
        root=Path("Z:/library"),
        thumb_dir=Path("Z:/data/.thumbnails"),
        event_token=token or uuid4().hex,
        is_closed=closed,
    )
    return SimpleNamespace(session=session, thumbnail_service=thumbnail_service)


# ── run_startup_governance ────────────────────────────────────────

def test_run_startup_governance_enforces_positive_cap():
    service = _FakeThumbnailService()
    governance.run_startup_governance(
        thumbnail_service=service,
        library_root=Path("Z:/library"),
        thumb_dir=Path("Z:/data/.thumbnails"),
        max_bytes=2048,
    )
    assert service.calls == [
        (Path("Z:/library"), Path("Z:/data/.thumbnails"), 2048)]


def test_run_startup_governance_unlimited_cap_is_noop():
    service = _FakeThumbnailService()
    governance.run_startup_governance(
        thumbnail_service=service,
        library_root=Path("Z:/library"),
        thumb_dir=Path("Z:/data/.thumbnails"),
        max_bytes=0,
    )
    assert service.calls == []


def test_run_startup_governance_swallows_enforcement_failure():
    # Must not raise — a governance failure may never surface as a library
    # open error.
    governance.run_startup_governance(
        thumbnail_service=_BoomThumbnailService(),
        library_root=Path("Z:/library"),
        thumb_dir=Path("Z:/data/.thumbnails"),
        max_bytes=2048,
    )


# ── H2-a3: activity retention branch of the startup pass ─────────

def test_run_startup_governance_prunes_activity_rows():
    recorder = SimpleNamespace(prune=Mock(return_value=4))
    governance.run_startup_governance(
        activity_recorder=recorder,
        library_root=Path("Z:/library"),
        thumb_dir=Path("Z:/data/.thumbnails"),
        max_bytes=0,
    )
    recorder.prune.assert_called_once_with(governance.ACTIVITY_RETENTION_DAYS)


def test_run_startup_governance_prune_failure_is_swallowed():
    recorder = SimpleNamespace(prune=Mock(side_effect=RuntimeError("boom")))
    # Must not raise.
    governance.run_startup_governance(
        activity_recorder=recorder,
        library_root=Path("Z:/library"),
        thumb_dir=Path("Z:/data/.thumbnails"),
        max_bytes=0,
    )
    recorder.prune.assert_called_once()


# ── schedule_startup_governance ───────────────────────────────────

def test_schedule_startup_governance_runs_once_per_session(monkeypatch):
    stub = _StubSettings(THUMBNAIL_CACHE_DEFAULT_MAX_BYTES)
    monkeypatch.setattr(governance, "get_app_settings", lambda: stub)
    service = _FakeThumbnailService()
    scoped = _scoped(thumbnail_service=service)

    assert governance.schedule_startup_governance(scoped) is True
    assert service.invoked.wait(timeout=5.0)
    # A second schedule for the same session is rejected (one-shot).
    assert governance.schedule_startup_governance(scoped) is False
    assert len(service.calls) == 1


def test_schedule_startup_governance_skips_closed_or_fake_sessions():
    assert governance.schedule_startup_governance(_scoped(closed=True)) is False
    assert governance.schedule_startup_governance(None) is False
    # No governable service (settings-dialog style fakes): nothing scheduled.
    bare = SimpleNamespace(
        session=SimpleNamespace(
            root=Path("Z:/library"), thumb_dir=Path("Z:/t"),
            event_token=uuid4().hex, is_closed=False),
    )
    assert governance.schedule_startup_governance(bare) is False


def test_schedule_startup_governance_reads_cap_from_settings(monkeypatch):
    stub = _StubSettings(0)
    monkeypatch.setattr(governance, "get_app_settings", lambda: stub)
    service = _FakeThumbnailService()
    scoped = _scoped(thumbnail_service=service)

    assert governance.schedule_startup_governance(scoped) is True
    # The worker provably ran and consulted the G3 settings seam...
    assert stub.read.wait(timeout=5.0)
    # ...and the unlimited cap kept it a no-op.
    assert service.calls == []


# ── AppSettings round-trip ────────────────────────────────────────

def _settings_at(path):
    settings = AppSettings.__new__(AppSettings)
    settings._path = path
    settings._data = {}
    settings._dirty = False
    settings._lock = threading.RLock()
    return settings


def test_thumbnail_cache_max_bytes_defaults_and_round_trips(tmp_path):
    path = tmp_path / "settings.json"
    settings = _settings_at(path)

    # Missing key → H2 default (2 GB), without mutating settings.
    assert settings.get_thumbnail_cache_max_bytes() == (
        THUMBNAIL_CACHE_DEFAULT_MAX_BYTES)
    assert not path.exists()

    settings.set_thumbnail_cache_max_bytes(5 * 1024 ** 3)
    settings.save()
    reloaded = _settings_at(path)
    reloaded.load()
    assert reloaded.get_thumbnail_cache_max_bytes() == 5 * 1024 ** 3

    # 0 = unlimited round-trips too.
    settings.set_thumbnail_cache_max_bytes(0)
    assert settings.get_thumbnail_cache_max_bytes() == 0


def test_thumbnail_cache_max_bytes_rejects_invalid_values(tmp_path):
    settings = _settings_at(tmp_path / "settings.json")
    with pytest.raises(ValueError):
        settings.set_thumbnail_cache_max_bytes(-1)
    with pytest.raises(ValueError):
        settings.set("thumbnail_cache_max_bytes", True)
    with pytest.raises(ValueError):
        settings.set("thumbnail_cache_max_bytes", "2gb")
