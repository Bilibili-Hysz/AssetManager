"""HTTP contract and permission tests for the quick-search route."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import make_mocked_request

from AssetsManager.application.search_service import SearchService
from AssetsManager.lan.principal import principal_for_request
from AssetsManager.lan.routes._helpers import LAN_APP_KEY, PRINCIPAL_REQUEST_KEY
from AssetsManager.lan.routes.quicksearch import handle_quicksearch


def _request(root, query, *, principal=None, service=None):
    lan = SimpleNamespace(
        library_root=root,
        services=SimpleNamespace(search_service=service or SearchService()),
    )
    request = make_mocked_request(
        "GET",
        f"/api/quicksearch{query}",
        app={LAN_APP_KEY: lan},
    )
    if principal is not None:
        request[PRINCIPAL_REQUEST_KEY] = principal
    return request


def _payload(response):
    return json.loads(response.body)


@pytest.mark.anyio
async def test_quicksearch_requires_browse_permission_even_with_preview(tmp_path):
    request = _request(
        tmp_path,
        "?q=secret",
        principal=principal_for_request(
            "guest",
            settings={"lan_guest_list": False, "lan_guest_preview": True},
        ),
    )

    response = await handle_quicksearch(request)

    assert response.status == 403
    assert _payload(response) == {"error": "Browse access required"}


@pytest.mark.anyio
async def test_quicksearch_returns_safe_metadata_without_preview(tmp_path):
    (tmp_path / "Pictures").mkdir()
    (tmp_path / "Pictures" / "hero.png").write_bytes(b"png")
    (tmp_path / "Pictures" / "hero.svg").write_text("<svg />")
    (tmp_path / "hero-notes.txt").write_text("notes")
    principal = principal_for_request(
        "guest",
        settings={"lan_guest_list": True, "lan_guest_preview": False},
    )

    response = await handle_quicksearch(
        _request(tmp_path, "?q=hero&limit=3", principal=principal)
    )

    assert response.status == 200
    results = _payload(response)["results"]
    assert {item["name"] for item in results} == {"hero-notes.txt", "hero.png", "hero.svg"}
    assert all("thumbnail_url" not in item for item in results)


@pytest.mark.anyio
async def test_quicksearch_does_not_project_svg_thumbnail_url(tmp_path):
    (tmp_path / "hero.svg").write_text("<svg />")
    principal = principal_for_request("user", user={"role": "user"})

    response = await handle_quicksearch(
        _request(tmp_path, "?q=hero", principal=principal)
    )

    assert response.status == 200
    assert _payload(response)["results"] == [
        {
            "name": "hero.svg",
            "path": "hero.svg",
            "type": "file",
            "extension": ".svg",
            "category": "images",
        }
    ]


@pytest.mark.anyio
async def test_quicksearch_returns_compat_results_and_thumbnail_url(tmp_path):
    (tmp_path / "Pictures").mkdir()
    (tmp_path / "Pictures" / "hero.png").write_bytes(b"png")
    (tmp_path / "hero-notes.txt").write_text("notes")
    principal = principal_for_request("user", user={"role": "user", "username": "alice"})

    response = await handle_quicksearch(
        _request(tmp_path, "?q=hero&limit=2", principal=principal)
    )

    assert response.status == 200
    data = _payload(response)
    assert len(data["results"]) == 2
    assert data["results"][0]["name"] == "hero-notes.txt"
    image = next(item for item in data["results"] if item["name"] == "hero.png")
    assert image == {
        "name": "hero.png",
        "path": "Pictures/hero.png",
        "type": "file",
        "extension": ".png",
        "category": "images",
        "thumbnail_url": "/api/thumbnails/Pictures/hero.png",
    }
    assert all(str(tmp_path) not in item["path"] for item in data["results"])


@pytest.mark.anyio
async def test_quicksearch_empty_query_and_invalid_limit_contract(tmp_path):
    principal = principal_for_request("user", user={"role": "user"})

    empty = await handle_quicksearch(_request(tmp_path, "?q=%20%20", principal=principal))
    invalid = await handle_quicksearch(_request(tmp_path, "?q=asset&limit=101", principal=principal))
    malformed = await handle_quicksearch(_request(tmp_path, "?q=asset&limit=nope", principal=principal))

    assert empty.status == 200
    assert _payload(empty) == {"results": []}
    assert invalid.status == 400
    assert malformed.status == 400
    assert "limit" in _payload(invalid)["error"]


@pytest.mark.anyio
async def test_quicksearch_service_failure_uses_metadata_style_error_shape(tmp_path):
    class BrokenService:
        def quick_search(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    principal = principal_for_request("user", user={"role": "user"})
    response = await handle_quicksearch(
        _request(tmp_path, "?q=asset", principal=principal, service=BrokenService())
    )

    assert response.status == 500
    assert _payload(response) == {"error": "Quick search failed"}



