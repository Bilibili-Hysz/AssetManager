import asyncio
from pathlib import Path
from types import SimpleNamespace

from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.routes import system as system_routes


class _Settings:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_info_reports_effective_commerce_and_seller_flags(monkeypatch, tmp_path):
    settings = _Settings({
        "sidebar_depth_cfg": {},
        "lan_commerce_enabled": False,
        "lan_seller_enabled": True,
        "lan_quota_enabled": False,
    })
    lan = SimpleNamespace(
        share_name="Library",
        library_root=Path(tmp_path),
        auth_status=lambda: (False, "none"),
        runtime=SimpleNamespace(epoch="runtime-test-epoch"),
    )

    monkeypatch.setattr(system_routes, "AppSettings", SimpleNamespace(instance=lambda: settings))
    monkeypatch.setattr(system_routes, "get_lan", lambda _request: lan)
    monkeypatch.setattr(system_routes, "get_project_service", lambda _request: SimpleNamespace(
        count_projects=lambda *_args, **_kwargs: 0
    ))
    monkeypatch.setattr(system_routes, "get_metadata_service", lambda _request: SimpleNamespace(
        get_library_total_size=lambda _root: 0
    ))
    monkeypatch.setattr(system_routes, "get_request_principal", lambda _request: None)

    request = make_mocked_request("GET", "/api/info")
    response = asyncio.run(system_routes.handle_info(request))
    assert response.status == 200
    info = __import__("json").loads(response.text)
    assert info["thumbnail_cache_namespace"] == "runtime-test-epoch"
    assert info["feature_flags"] == {
        "commerce": False,
        "seller": False,
        "quota": False,
    }

    settings.values.update({"lan_commerce_enabled": True, "lan_seller_enabled": True})
    response = asyncio.run(system_routes.handle_info(request))
    assert __import__("json").loads(response.text)["feature_flags"] == {
        "commerce": True,
        "seller": True,
        "quota": False,
    }

    settings.values["lan_seller_enabled"] = "true"
    response = asyncio.run(system_routes.handle_info(request))
    assert __import__("json").loads(response.text)["feature_flags"]["seller"] is False