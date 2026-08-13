"""Project application references onto stable LAN API URLs."""
from __future__ import annotations

from urllib.parse import quote


def thumbnail_url(path: str, *, size: int | None = None) -> str:
    """Build a LAN thumbnail URL from a library-relative asset path."""
    url = f"/api/thumbnails/{quote(path, safe='/')}"
    return f"{url}?size={size}" if size is not None else url


def download_url(path: str) -> str:
    """Build a LAN download URL from a library-relative project path."""
    return f"/api/download/{quote(path, safe='/')}"


def image_url(path: str) -> str:
    """Build a LAN original-image preview URL from a library-relative path.

    The path is carried as a query parameter, so it is percent-encoded as a
    single opaque value (``/`` becomes ``%2F``) and decoded once by aiohttp.
    """
    return f"/api/image?path={quote(path, safe='')}"


def search_result_response(result) -> dict:
    return {
        "name": result.name,
        "path": result.path,
        "type": "file",
        "extension": result.extension,
        "category": result.category,
        "thumbnail_url": thumbnail_url(result.thumbnail_path),
    }


def project_listing_response(listing) -> dict:
    response = listing.to_response()
    response["items"] = [
        _project_summary_response(item, nullable_thumbnail=True)
        for item in response["items"]
    ]
    return response


def project_home_response(home) -> dict:
    response = home.to_response()
    response["recent_projects"] = [
        _project_summary_response(project) for project in response["recent_projects"]
    ]
    response["preview_pool"] = [
        _project_summary_response(project) for project in response["preview_pool"]
    ]
    return response


def project_detail_response(detail) -> dict:
    response = {}
    for key, value in detail.to_response().items():
        if key == "thumbnail_path":
            response["thumbnail_url"] = thumbnail_url(value) if value else None
        elif key == "images":
            response["images"] = [
                {
                    "name": image["name"],
                    "url": thumbnail_url(image["path"], size=1920),
                    "thumb_url": thumbnail_url(image["path"], size=512),
                }
                for image in value
            ]
        else:
            response[key] = value
    response["download_url"] = download_url(response["path"])
    return response


def _project_summary_response(project: dict, *, nullable_thumbnail: bool = False) -> dict:
    response = {}
    for key, value in project.items():
        if key != "thumbnail_path":
            response[key] = value
        elif value or nullable_thumbnail:
            response["thumbnail_url"] = thumbnail_url(value) if value else None
    return response


_GALLERY_THUMBNAIL_SIZE = 512


def gallery_entry_response(entry: dict) -> dict:
    """Attach transport URLs to one gallery entry (node or artwork summary).

    The application service emits only ``cover_path``/``path``; the LAN layer
    is the single place that projects those references onto preview URLs.
    Artwork entries get ``thumbnail_url`` + ``image_url``; collection/project
    nodes get ``cover_url`` (or ``None`` when they have no cover).
    """
    response = dict(entry)
    if entry.get("kind") == "artwork":
        response["thumbnail_url"] = thumbnail_url(entry["path"], size=_GALLERY_THUMBNAIL_SIZE)
        response["image_url"] = image_url(entry["path"])
    else:
        cover_path = entry.get("cover_path")
        response["cover_url"] = (
            thumbnail_url(cover_path, size=_GALLERY_THUMBNAIL_SIZE) if cover_path else None
        )
    return response


def gallery_home_response(home) -> dict:
    response = home.to_response()
    if response["featured"] is not None:
        response["featured"] = gallery_entry_response(response["featured"])
    response["collections"] = [gallery_entry_response(entry) for entry in response["collections"]]
    response["projects"] = [gallery_entry_response(entry) for entry in response["projects"]]
    response["recent"] = [gallery_entry_response(entry) for entry in response["recent"]]
    return response


def gallery_collection_response(collection) -> dict:
    response = collection.to_response()
    response["collection"] = gallery_entry_response(response["collection"])
    response["children"] = [gallery_entry_response(entry) for entry in response["children"]]
    response["entries"] = [gallery_entry_response(entry) for entry in response["entries"]]
    return response
