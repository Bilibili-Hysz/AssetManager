"""Contract tests for LAN projection of application resource references."""

from AssetsManager.application.gallery_service import GalleryCollection, GalleryHome
from AssetsManager.application.project_service import (
    ProjectDepthConfig,
    ProjectDetail,
    ProjectHome,
    ProjectListItem,
    ProjectListing,
)
from AssetsManager.application.search_service import SearchResult
from AssetsManager.lan.routes._resource_urls import (
    gallery_collection_response,
    gallery_entry_response,
    gallery_home_response,
    image_url,
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


def test_image_url_encodes_path_as_single_query_value():
    assert image_url("套件/hero image.png") == (
        "/api/image?path=%E5%A5%97%E4%BB%B6%2Fhero%20image.png"
    )


def test_gallery_entry_response_projects_node_and_artwork_urls():
    node = {
        "name": "hero", "path": "projects/hero", "kind": "project",
        "parent_path": "projects", "cover_path": "projects/hero/cover.png",
        "width": 1920, "height": 1080, "aspect_ratio": 1.7777777777777777,
        "modified": 100, "size": 2048, "size_fmt": "2.0 KB",
        "file_count": 3, "artwork_count": 2, "child_count": 0, "tags": [],
    }
    assert gallery_entry_response(node) == {
        **node,
        "cover_url": "/api/thumbnails/projects/hero/cover.png?size=512",
    }

    artwork = {
        "name": "hero image.png", "path": "套件/hero image.png", "kind": "artwork",
        "parent_path": "套件", "width": 32, "height": 16, "aspect_ratio": 2.0,
        "modified": 1, "size": 10, "size_fmt": "10 B", "extension": ".png", "tags": [],
    }
    assert gallery_entry_response(artwork) == {
        **artwork,
        "thumbnail_url": "/api/thumbnails/%E5%A5%97%E4%BB%B6/hero%20image.png?size=512",
        "image_url": "/api/image?path=%E5%A5%97%E4%BB%B6%2Fhero%20image.png",
    }

    coverless = dict(node, kind="collection", cover_path=None)
    assert gallery_entry_response(coverless)["cover_url"] is None


def test_gallery_home_and_collection_responses_attach_urls_without_mutating_input():
    node = {
        "name": "set", "path": "set", "kind": "project", "parent_path": "",
        "cover_path": "set/art.png", "width": 40, "height": 40,
        "aspect_ratio": 1.0, "modified": 1, "size": 1, "size_fmt": "1 B",
        "file_count": 1, "artwork_count": 1, "child_count": 0, "tags": [],
    }
    artwork = {
        "name": "art.png", "path": "set/art.png", "kind": "artwork",
        "parent_path": "set", "width": 40, "height": 40, "aspect_ratio": 1.0,
        "modified": 1, "size": 1, "size_fmt": "1 B", "extension": ".png", "tags": [],
    }
    home = GalleryHome(node, [node], [], [artwork], {
        "collections": 1, "projects": 0, "artworks": 1, "total_size_fmt": "1 B",
    })
    home_response = gallery_home_response(home)
    assert home_response["featured"]["cover_url"] == "/api/thumbnails/set/art.png?size=512"
    assert home_response["collections"][0]["cover_url"] == "/api/thumbnails/set/art.png?size=512"
    assert home_response["recent"][0]["thumbnail_url"] == "/api/thumbnails/set/art.png?size=512"
    assert home_response["recent"][0]["image_url"] == "/api/image?path=set%2Fart.png"
    # The service's cached projection is never mutated with URL keys.
    assert "cover_url" not in node
    assert "thumbnail_url" not in artwork

    collection = GalleryCollection(node, [node], [artwork])
    collection_response = gallery_collection_response(collection)
    assert collection_response["collection"]["cover_url"] == "/api/thumbnails/set/art.png?size=512"
    assert collection_response["children"][0]["cover_url"] == "/api/thumbnails/set/art.png?size=512"
    assert collection_response["entries"][0]["thumbnail_url"] == "/api/thumbnails/set/art.png?size=512"
    assert collection_response["entries"][0]["image_url"] == "/api/image?path=set%2Fart.png"
