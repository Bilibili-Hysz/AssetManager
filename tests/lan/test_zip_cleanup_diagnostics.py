"""Admin-only ZIP resource and deferred-cleanup diagnostics."""
from types import SimpleNamespace

import pytest

from AssetsManager.lan.zip_resources import ZIP_BUDGET_APP_KEY, ZipResourceBudget


@pytest.mark.anyio
async def test_admin_stats_exposes_safe_zip_cleanup_diagnostics(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import system as system_routes
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY
    from tests.lan.support.api_helpers import _local_ui_headers, _make_client, _make_lan_app

    app, _library, _conn = _make_lan_app(tmp_path)
    monkeypatch.setattr(app[LAN_APP_KEY], "status", lambda: {
        "connections": 0,
        "requests": 0,
        "bytes_transferred": None,
        "uptime": 0,
    }, raising=False)
    budget = ZipResourceBudget(max_jobs=7, max_reserved_bytes=321)
    reservation = budget.try_acquire(123)
    assert reservation is not None
    app[ZIP_BUDGET_APP_KEY] = budget
    cleanup = SimpleNamespace(snapshot=lambda: {
        "pending_count": 2,
        "retry_attempts": 5,
        "completed_count": 11,
        "oldest_pending_seconds": 3.5,
        "last_error_type": "PermissionError",
    })
    monkeypatch.setattr(system_routes, "get_process_zip_cleanup", lambda: cleanup)
    client = await _make_client(app)
    try:
        response = await client.get("/api/stats", headers=_local_ui_headers(app))
        assert response.status == 200
        payload = await response.json()
        assert payload["zip_resources"] == {
            "active_jobs": 1,
            "reserved_bytes": 123,
            "max_jobs": 7,
            "max_reserved_bytes": 321,
            "cleanup": {
                "pending_count": 2,
                "retry_attempts": 5,
                "completed_count": 11,
                "oldest_pending_seconds": 3.5,
                "last_error_type": "PermissionError",
            },
        }
        assert set(payload["zip_resources"]["cleanup"]) == {
            "pending_count",
            "retry_attempts",
            "completed_count",
            "oldest_pending_seconds",
            "last_error_type",
        }
        assert str(tmp_path) not in str(payload["zip_resources"]["cleanup"])
    finally:
        reservation.release()
        await client.close()


@pytest.mark.anyio
async def test_non_admin_stats_rejects_before_reading_zip_cleanup_service(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import system as system_routes
    from tests.lan.support.api_helpers import _make_client, _make_lan_app

    app, _library, _conn = _make_lan_app(tmp_path)

    def forbidden_service_access():
        raise AssertionError("non-admin stats must not read cleanup diagnostics")

    monkeypatch.setattr(system_routes, "get_process_zip_cleanup", forbidden_service_access)
    client = await _make_client(app)
    try:
        response = await client.get("/api/stats")
        assert response.status == 403
        assert (await response.json())["code"] == "forbidden"
    finally:
        await client.close()
