"""React/Vite SPA page routes."""
from pathlib import Path

from aiohttp import web


SPA_DIR = Path(__file__).parent.parent.parent.parent / "webui" / "dist"


def _spa_index() -> Path | None:
    """Return the SPA index.html path if it exists, else None."""
    idx = SPA_DIR / "index.html"
    return idx if idx.exists() else None


def _spa_response() -> web.StreamResponse:
    index = _spa_index()
    if index:
        return web.FileResponse(index)
    return web.Response(
        text="WebUI/build is unavailable. Build the React WebUI before starting the LAN server.",
        status=503,
    )


async def handle_index(request):
    return _spa_response()


async def handle_detail_page(request):
    return _spa_response()


async def handle_login_page(request):
    return _spa_response()


async def handle_browse_page(request):
    return _spa_response()


async def handle_gallery_page(request):
    return _spa_response()


async def handle_gallery_collection_page(request):
    return _spa_response()


async def handle_gallery_favorites_page(request):
    return _spa_response()
