"""Contract tests for LAN projection of application resource references."""

from AssetsManager.application.project_service import (
    ProjectDepthConfig,
    ProjectDetail,
    ProjectHome,
    ProjectListItem,
    ProjectListing,
)
from AssetsManager.application.search_service import SearchResult
from AssetsManager.lan.routes._resource_urls import (
    project_detail_response,
    project_home_response,
    project_listing_response,
    search_result_response,
)


def test_search_json_contract_keeps_thumbnail_url_at_lan_boundary():
    result = SearchResult(
        name="hero one.png",
        path="角色/hero one.png",
        extension=".png",
        category="images",
    )

    assert search_result_response(result) == {
        "name": "hero one.png",
        "path": "角色/hero one.png",
        "type": "file",
        "extension": ".png",
        "category": "images",
        "thumbnail_url": "/api/thumbnails/%E8%A7%92%E8%89%B2/hero%20one.png",
    }


def test_project_listing_json_contract_keeps_thumbnail_url_and_shape():
    listing = ProjectListing(
        current_path="",
        parent_path="",
        items=(ProjectListItem(
            name="alpha",
            path="alpha",
            is_project=True,
            thumbnail_path="alpha/cover one.png",
            tags=["hero"],
            total_size=3,
            file_count=1,
            notes="note",
            modified=12.5,
        ),),
        depth_config=ProjectDepthConfig(global_depth=1),
        current_depth=0,
        total_count=1,
    )

    response = project_listing_response(listing)

    assert response["items"] == [{
        "name": "alpha",
        "path": "alpha",
        "is_project": True,
        "thumbnail_url": "/api/thumbnails/alpha/cover%20one.png",
        "tags": ["hero"],
        "total_size": 3,
        "total_size_fmt": "3.0 B",
        "file_count": 1,
        "notes": "note",
        "modified": 12.5,
    }]
    assert list(response["items"][0]) == [
        "name", "path", "is_project", "thumbnail_url", "tags", "total_size",
        "total_size_fmt", "file_count", "notes", "modified",
    ]
    assert "thumbnail_path" not in response["items"][0]


def test_project_detail_json_contract_keeps_urls_and_image_shape():
    detail = ProjectDetail(
        name="alpha",
        path="alpha one",
        tags=["hero"],
        notes="note",
        urls=["https://example.test"],
        total_size=3,
        file_count=1,
        files=[{"name": "cover.png"}],
        images=[{"name": "cover.png", "path": "alpha one/cover.png"}],
        thumbnail_path="alpha one/cover.png",
        modified=12.5,
    )

    response = project_detail_response(detail)

    assert response["thumbnail_url"] == "/api/thumbnails/alpha%20one/cover.png"
    assert response["download_url"] == "/api/download/alpha%20one"
    assert response["images"] == [{
        "name": "cover.png",
        "url": "/api/thumbnails/alpha%20one/cover.png?size=1920",
        "thumb_url": "/api/thumbnails/alpha%20one/cover.png?size=512",
    }]
    assert list(response) == [
        "name", "path", "tags", "notes", "urls", "total_size",
        "total_size_fmt", "file_count", "files", "images", "thumbnail_url",
        "modified", "download_url",
    ]
    assert "thumbnail_path" not in response


def test_project_home_json_contract_preserves_optional_thumbnail_key():
    home = ProjectHome(
        recent_projects=[
            {"name": "alpha", "path": "alpha", "mtime": 2.0,
             "thumbnail_path": "alpha/cover.png"},
            {"name": "beta", "path": "beta", "mtime": 1.0},
        ],
        preview_pool=[
            {"name": "alpha", "path": "alpha", "thumbnail_path": "alpha/cover.png"},
        ],
        popular_tags=[],
        total_projects=2,
        total_size=0,
    )

    response = project_home_response(home)

    assert response["recent_projects"] == [
        {"name": "alpha", "path": "alpha", "mtime": 2.0,
         "thumbnail_url": "/api/thumbnails/alpha/cover.png"},
        {"name": "beta", "path": "beta", "mtime": 1.0},
    ]
    assert response["preview_pool"] == [{
        "name": "alpha", "path": "alpha",
        "thumbnail_url": "/api/thumbnails/alpha/cover.png",
    }]
