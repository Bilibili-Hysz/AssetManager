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
