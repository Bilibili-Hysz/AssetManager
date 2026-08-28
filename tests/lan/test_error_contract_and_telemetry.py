"""Error-contract and route-telemetry unification tests.

Covers the batch that unified the LAN route layer on:

* the shared ``record_route_event`` telemetry helper (auth routes now record
  ``lan.auth.*`` events like every other instrumented route);
* the ``error_contract_middleware`` catch-all that converts unhandled
  exceptions and bare aiohttp HTTPExceptions into the shared JSON contract;
* ``validated_existing_key`` propagating domain errors instead of bare
  HTTPExceptions (status preserved, body shape unified);
* the thumbnails outcome/status telemetry invariant (409 must never be
  recorded as ``outcome="success"``).
"""
from __future__ import annotations

import pytest

from tests.lan.support.api_helpers import _local_ui_headers, _make_client, _make_lan_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ── a) 500 catch-all middleware ────────────────────────────────────────────


@pytest.mark.anyio
async def test_error_contract_middleware_converts_unhandled_exception_to_internal_error():
    from aiohttp import web

    from AssetsManager.lan.routes._errors import error_contract_middleware

    async def boom(request):
        raise RuntimeError("secret internals must not leak")

    app = web.Application(middlewares=[error_contract_middleware])
    app.router.add_get("/boom", boom)
    client = await _make_client(app)
    try:
        response = await client.get("/boom")
        assert response.status == 500
        assert response.content_type == "application/json"
        payload = await response.json()
        assert payload == {
            "error": "Internal server error",
            "code": "internal_error",
            "details": {},
        }
        assert "secret internals" not in str(payload)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_error_contract_middleware_normalizes_bare_http_exceptions_but_keeps_redirects():
    from aiohttp import web

    from AssetsManager.lan.routes._errors import error_contract_middleware

    async def bare_400(request):
        raise web.HTTPBadRequest(reason="Invalid path")

    async def bare_404(request):
        raise web.HTTPNotFound(reason="File not found")

    async def redirect(request):
        raise web.HTTPFound(location="/login")

    app = web.Application(middlewares=[error_contract_middleware])
    app.router.add_get("/bare-400", bare_400)
    app.router.add_get("/bare-404", bare_404)
    app.router.add_get("/redirect", redirect)
    client = await _make_client(app)
    try:
        bad = await client.get("/bare-400")
        assert bad.status == 400  # status preserved, body shape unified
        assert await bad.json() == {
            "error": "Invalid path",
            "code": "bad_request",
            "details": {},
        }
        missing = await client.get("/bare-404")
        assert missing.status == 404
        assert (await missing.json())["code"] == "not_found"
        # 3xx pass through untouched (redirect not followed here).
        moved = await client.get("/redirect", allow_redirects=False)
        assert moved.status == 302
    finally:
        await client.close()


# ── b) validated_existing_key domain errors carry the JSON contract ───────


@pytest.mark.anyio
async def test_path_escape_and_missing_path_use_json_contract(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    (library / "asset.txt").write_text("x", encoding="utf-8")
    headers = _local_ui_headers(app)
    client = await _make_client(app)
    try:
        escape = await client.put(
            "/api/notes/%2E%2E%2Foutside.txt",
            json={"notes": "blocked"},
            headers=headers,
        )
        assert escape.status == 400  # status preserved, body shape unified
        assert await escape.json() == {
            "error": "Path escape detected",
            "code": "path_escape_detected",
            "field": "path",
            "details": {},
        }

        missing = await client.post(
            "/api/tags",
            json={"tag": "hero", "file_path": "ghost/missing.txt"},
            headers=headers,
        )
        assert missing.status == 404  # status preserved, body shape unified
        payload = await missing.json()
        assert payload["code"] == "not_found"
        assert payload["error"].startswith("Path not found")
        assert payload["details"] == {}
    finally:
        await client.close()


# ── c) thumbnails telemetry: status=409 never records outcome=success ─────


@pytest.mark.anyio
async def test_thumbnail_source_change_records_error_outcome_not_success(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from AssetsManager.application.thumbnail_service import ThumbnailSourceChangedError
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.lan.routes import thumbnails
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, _conn = _make_lan_app(tmp_path)
    (library / "image.png").write_bytes(b"\x89PNG" + b"\x00" * 100)
    recorder = PerformanceRecorder(enabled=True)
    lan = app[LAN_APP_KEY]
    lan.performance_recorder = recorder
    lan.session_token = "session-409"

    resolved = SimpleNamespace(
        found=True,
        source_path=library / "image.png",
        should_blur=False,
        cache_hit=True,
        source_identity=None,
    )

    def _raise_source_changed(*_args, **_kwargs):
        raise ThumbnailSourceChangedError(resolved.source_path)

    monkeypatch.setattr(
        thumbnails, "get_thumbnail_service", lambda _request: SimpleNamespace(
            resolve=lambda *args, **kwargs: resolved,
        )
    )
    monkeypatch.setattr(thumbnails, "validate_thumbnail_source", _raise_source_changed)

    client = await _make_client(app)
    try:
        response = await client.get(
            "/api/thumbnails/image.png", headers=_local_ui_headers(app)
        )
        assert response.status == 409
        assert (await response.json())["code"] == "source_changed"

        event = next(event for event in recorder.recent() if event.name == "lan.thumbnail")
        assert event.session_token == "session-409"
        # The regression this locks: outcome must agree with status.
        assert event.attributes["status"] == 409
        assert event.attributes["outcome"] != "success"
        assert event.attributes["outcome"] == "error"
    finally:
        await client.close()


# ── d) auth telemetry and activity records ─────────────────────────────────


def _recorder_for(app):
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    recorder = PerformanceRecorder(enabled=True)
    app[LAN_APP_KEY].performance_recorder = recorder
    return recorder


def _activity(app):
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    return app[LAN_APP_KEY].services.activity_log


@pytest.mark.anyio
async def test_failed_login_records_telemetry_and_login_failed_activity(tmp_path):
    app, _library, _conn = _make_lan_app(tmp_path)
    recorder = _recorder_for(app)
    client = await _make_client(app)
    try:
        response = await client.post(
            "/api/auth/login",
            json={"username": "ghost", "password": "super-secret-pw"},
        )
        assert response.status == 401

        event = next(event for event in recorder.recent() if event.name == "lan.auth.login")
        assert event.attributes == {"outcome": "error", "status": 401}

        entries = _activity(app).recent(10)
        failures = [entry for entry in entries if entry["action"] == "login_failed"]
        assert len(failures) == 1
        assert failures[0]["username"] == "ghost"
        # Credential material must never reach the activity log.
        assert "super-secret-pw" not in failures[0]["details"]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_register_records_telemetry_and_success_activity(tmp_path):
    app, _library, _conn = _make_lan_app(tmp_path)
    recorder = _recorder_for(app)
    client = await _make_client(app)
    try:
        created = await client.post(
            "/api/auth/register",
            json={"username": "alice", "password": "Test@1234"},
        )
        assert created.status == 200

        success_event = next(
            event for event in recorder.recent() if event.name == "lan.auth.register"
        )
        assert success_event.attributes == {"outcome": "success", "status": 200}
        assert any(
            entry["action"] == "register" and entry["username"] == "alice"
            for entry in _activity(app).recent(10)
        )

        recorder.clear()
        rejected = await client.post(
            "/api/auth/register",
            json={"username": "x", "password": "Test@1234"},
        )
        assert rejected.status == 400
        failure_event = next(
            event for event in recorder.recent() if event.name == "lan.auth.register"
        )
        assert failure_event.attributes == {"outcome": "error", "status": 400}
    finally:
        await client.close()


@pytest.mark.anyio
async def test_logout_and_verify_key_failures_record_telemetry(tmp_path):
    from AssetsManager.lan.auth import hash_key
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, _library, _conn = _make_lan_app(tmp_path)
    recorder = _recorder_for(app)
    client = await _make_client(app)
    try:
        logout = await client.post("/api/auth/logout")
        assert logout.status == 200
        logout_event = next(
            event for event in recorder.recent() if event.name == "lan.auth.logout"
        )
        assert logout_event.attributes == {"outcome": "success", "status": 200}

        app[LAN_APP_KEY].access_key_hash = hash_key("right-key")
        recorder.clear()
        denied = await client.post("/api/auth/verify_key", json={"key": "wrong-key"})
        assert denied.status == 401
        key_event = next(
            event for event in recorder.recent() if event.name == "lan.auth.verify_key"
        )
        assert key_event.attributes == {"outcome": "error", "status": 401}
        # The presented key must not be logged.
        entries = _activity(app).recent(10)
        assert all("wrong-key" not in entry["details"] for entry in entries)
    finally:
        await client.close()
