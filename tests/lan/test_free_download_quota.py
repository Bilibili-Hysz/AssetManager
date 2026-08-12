import asyncio
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.routes._helpers import LAN_APP_KEY


class _Settings:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def _request(schema_db, root: Path, *, method="GET", path="/api/quota"):
    lan = SimpleNamespace(
        library_root=root,
        services=None,
        connection_for=lambda _root: schema_db,
    )
    return make_mocked_request(method, path, app={LAN_APP_KEY: lan}), lan


def test_public_quota_status_is_flat_and_delivery_quota_stays_separate(schema_db, tmp_path, monkeypatch):
    from AssetsManager.lan.routes import quota

    monkeypatch.setattr(
        quota.AppSettings,
        "instance",
        lambda: _Settings({"lan_quota_enabled": True, "lan_quota_limit": 2, "lan_quota_min_interval_seconds": 0}),
    )
    request, _lan = _request(schema_db, tmp_path)

    before = asyncio.run(quota.handle_free_quota(request))
    before_body = json.loads(before.text)
    assert before.status == 200
    assert before_body == {
        "enabled": True,
        "period": "daily",
        "limit": 2,
        "used": 0,
        "remaining": 2,
        "reset_at": before_body["reset_at"],
        "min_interval_seconds": 0,
    }

    assert quota.consume_free_download_quota(request)["allowed"] is True
    after = asyncio.run(quota.handle_free_quota(request))
    after_body = json.loads(after.text)
    assert after_body["used"] == 1
    assert after_body["remaining"] == 1


def test_download_route_returns_429_with_quota_headers_after_preparation(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import downloads

    target = tmp_path / "asset.txt"
    target.write_text("asset", encoding="utf-8")
    request = make_mocked_request(
        "GET",
        "/api/download/asset.txt",
        app={LAN_APP_KEY: SimpleNamespace()},
        match_info={"path": "asset.txt"},
    )
    monkeypatch.setattr(downloads, "require_permission", lambda _request, _capability: True)
    monkeypatch.setattr(downloads, "validate_path", lambda _lan, _path: target)
    monkeypatch.setattr(
        downloads,
        "consume_free_download_quota",
        lambda _request: {
            "allowed": False,
            "reason": "exhausted",
            "retry_after_seconds": 0,
            "info": {
                "enabled": True,
                "period": "daily",
                "limit": 1,
                "used": 1,
                "remaining": 0,
                "reset_at": 2_000_000_000,
                "min_interval_seconds": 0,
            },
        },
    )
    monkeypatch.setattr(downloads, "quota_retry_after_seconds", lambda _info, _result: 0)

    with pytest.raises(web.HTTPTooManyRequests) as exc_info:
        asyncio.run(downloads.handle_download(request))
    response = exc_info.value
    assert response.status == 429
    assert response.headers["X-Quota-Remaining"] == "0"
    assert response.headers["X-Quota-Limit"] == "1"
    assert response.headers["X-Quota-Period"] == "daily"
    body = json.loads(response.text)
    assert body["error"] == "Free download quota exhausted"


def test_download_route_does_not_consume_when_file_response_preparation_fails(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import downloads

    target = tmp_path / "asset.txt"
    target.write_text("asset", encoding="utf-8")
    request = make_mocked_request(
        "GET",
        "/api/download/asset.txt",
        app={LAN_APP_KEY: SimpleNamespace()},
        match_info={"path": "asset.txt"},
    )
    monkeypatch.setattr(downloads, "require_permission", lambda _request, _capability: True)
    monkeypatch.setattr(downloads, "validate_path", lambda _lan, _path: target)

    def failing_file_response(*_args, **_kwargs):
        raise OSError("simulated preparation failure")

    monkeypatch.setattr(downloads.web, "FileResponse", failing_file_response)
    consumed = []
    monkeypatch.setattr(
        downloads,
        "consume_free_download_quota",
        lambda _request: consumed.append(True)
        or {"allowed": True, "reason": None, "info": {}, "retry_after_seconds": 0},
    )

    response = asyncio.run(downloads.handle_download(request))
    assert response.status == 404
    assert json.loads(response.text)["error"] == "File not found"
    assert consumed == []


def test_directory_download_does_not_consume_when_zip_preparation_fails(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import downloads

    target = tmp_path / "folder"
    target.mkdir()
    (target / "asset.txt").write_text("asset", encoding="utf-8")
    request = make_mocked_request(
        "GET",
        "/api/download/folder",
        app={LAN_APP_KEY: SimpleNamespace()},
        match_info={"path": "folder"},
    )
    monkeypatch.setattr(downloads, "require_permission", lambda _request, _capability: True)
    monkeypatch.setattr(downloads, "validate_path", lambda _lan, _path: target)
    monkeypatch.setattr(downloads, "build_zip_async", _fail_zip)
    consumed = []
    monkeypatch.setattr(
        downloads,
        "consume_free_download_quota",
        lambda _request: consumed.append(True)
        or {"allowed": True, "reason": None, "info": {}, "retry_after_seconds": 0},
    )

    response = asyncio.run(downloads.handle_download(request))
    assert response.status == 500
    assert json.loads(response.text)["error"] == "Failed to create ZIP"
    assert consumed == []


def test_directory_download_429_cleans_up_prepared_zip(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import downloads

    target = tmp_path / "folder"
    target.mkdir()
    (target / "asset.txt").write_text("asset", encoding="utf-8")
    request = make_mocked_request(
        "GET",
        "/api/download/folder",
        app={LAN_APP_KEY: SimpleNamespace()},
        match_info={"path": "folder"},
    )
    monkeypatch.setattr(downloads, "require_permission", lambda _request, _capability: True)
    monkeypatch.setattr(downloads, "validate_path", lambda _lan, _path: target)

    created = []
    original_mkstemp = tempfile.mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, path = original_mkstemp(*args, **kwargs)
        created.append(path)
        return fd, path

    monkeypatch.setattr("tempfile.mkstemp", tracking_mkstemp)
    monkeypatch.setattr(downloads, "build_zip_async", _ok_zip)
    monkeypatch.setattr(
        downloads,
        "consume_free_download_quota",
        lambda _request: {
            "allowed": False,
            "reason": "exhausted",
            "retry_after_seconds": 0,
            "info": {
                "enabled": True,
                "period": "daily",
                "limit": 1,
                "used": 1,
                "remaining": 0,
                "reset_at": 2_000_000_000,
                "min_interval_seconds": 0,
            },
        },
    )
    monkeypatch.setattr(downloads, "quota_retry_after_seconds", lambda _info, _result: 0)

    with pytest.raises(web.HTTPTooManyRequests):
        asyncio.run(downloads.handle_download(request))
    assert len(created) == 1
    assert not os.path.exists(created[0])


async def _fail_zip(*_args, **_kwargs):
    return None


async def _ok_zip(*_args, **_kwargs):
    return "ok"


def _quota_settings(enabled=True):
    return _Settings({
        "lan_quota_enabled": enabled,
        "lan_quota_period": "daily",
        "lan_quota_limit": 2,
        "lan_quota_min_interval_seconds": 0,
    })


def test_anonymous_quota_identity_uses_signed_cookie_and_rejects_tampering(schema_db, tmp_path, monkeypatch):
    from AssetsManager.lan.routes import quota

    monkeypatch.setattr(quota.AppSettings, "instance", lambda: _quota_settings())
    request, lan = _request(schema_db, tmp_path)

    identity, issued = quota.resolve_free_download_quota_identity(request)
    assert issued is not None
    assert identity.startswith("anon:")
    assert identity == f"anon:{quota._quota_cookie_id(issued)}"
    assert len(quota._quota_cookie_id(issued)) == 32

    # The same token carried by a later request maps to the same identity
    # without reissuing a cookie.
    second = make_mocked_request(
        "GET",
        "/api/quota",
        headers={"Cookie": f"{quota._QUOTA_ID_COOKIE}={issued}"},
        app={LAN_APP_KEY: lan},
    )
    identity2, issued2 = quota.resolve_free_download_quota_identity(second)
    assert identity2 == identity
    assert issued2 is None

    # A tampered cookie is rejected and a fresh identity is minted.
    # Flip one hex character of the identity segment: the last base64
    # character of the HMAC only contributes 4 bits, so mutating it can be
    # ignored by the decoder (~1/16 of the time) and the signature still
    # verifies — flip the hex id instead, which always changes the payload.
    id_parts = issued.split(".")
    flipped = "0" if id_parts[1][5] != "0" else "1"
    tampered = f"{id_parts[0]}.{id_parts[1][:5]}{flipped}{id_parts[1][6:]}.{id_parts[2]}"
    third = make_mocked_request(
        "GET",
        "/api/quota",
        headers={"Cookie": f"{quota._QUOTA_ID_COOKIE}={tampered}"},
        app={LAN_APP_KEY: lan},
    )
    identity3, issued3 = quota.resolve_free_download_quota_identity(third)
    assert issued3 is not None
    assert identity3 != identity
    assert identity3 == f"anon:{quota._quota_cookie_id(issued3)}"


def test_anonymous_quota_handler_issues_cookie_and_consumes_one_bucket(schema_db, tmp_path, monkeypatch):
    from AssetsManager.lan.routes import quota

    monkeypatch.setattr(quota.AppSettings, "instance", lambda: _quota_settings())
    request, lan = _request(schema_db, tmp_path)

    first = asyncio.run(quota.handle_free_quota(request))
    assert first.status == 200
    assert quota._QUOTA_ID_COOKIE in first.cookies
    issued = first.cookies[quota._QUOTA_ID_COOKIE].value
    morsel = first.cookies[quota._QUOTA_ID_COOKIE]
    assert morsel["httponly"]
    assert morsel["samesite"] == "Lax"

    # A returning visitor is not reissued a cookie.
    second = asyncio.run(
        quota.handle_free_quota(
            make_mocked_request(
                "GET",
                "/api/quota",
                headers={"Cookie": f"{quota._QUOTA_ID_COOKIE}={issued}"},
                app={LAN_APP_KEY: lan},
            )
        )
    )
    assert second.status == 200
    assert quota._QUOTA_ID_COOKIE not in second.cookies

    # The bucket is stable across requests: two consumes exhaust the limit.
    consuming = make_mocked_request(
        "GET",
        "/api/download/asset.txt",
        headers={"Cookie": f"{quota._QUOTA_ID_COOKIE}={issued}"},
        app={LAN_APP_KEY: lan},
    )
    assert quota.consume_free_download_quota(consuming)["allowed"] is True
    assert quota.consume_free_download_quota(consuming)["allowed"] is True
    assert quota.consume_free_download_quota(consuming)["allowed"] is False
    body = json.loads(asyncio.run(quota.handle_free_quota(consuming)).text)
    assert body["used"] == 2
    assert body["remaining"] == 0


def test_authenticated_quota_identity_ignores_anonymous_cookie(schema_db, tmp_path, monkeypatch):
    from AssetsManager.lan.principal import principal_for_request
    from AssetsManager.lan.routes import quota
    from AssetsManager.lan.routes._helpers import set_request_principal

    monkeypatch.setattr(quota.AppSettings, "instance", lambda: _quota_settings())
    request, _lan = _request(schema_db, tmp_path)
    set_request_principal(request, principal_for_request("local_ui"))

    identity, issued = quota.resolve_free_download_quota_identity(request)
    assert identity == "principal:local_ui:local_ui"
    assert issued is None
