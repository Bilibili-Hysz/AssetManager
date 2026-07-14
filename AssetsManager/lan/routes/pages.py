"""Index and static page routes.

When the new SPA build exists at webui/dist/, page routes serve the SPA index.html
so React Router can handle client-side routing. Falls back to the old static HTML
when the SPA is not built.
"""
from pathlib import Path

from aiohttp import web


STATIC_DIR = Path(__file__).parent.parent / "static"
SPA_DIR = Path(__file__).parent.parent.parent.parent / "webui" / "dist"


def _spa_index() -> Path | None:
    """Return the SPA index.html path if it exists, else None."""
    idx = SPA_DIR / "index.html"
    return idx if idx.exists() else None


async def handle_index(request):
    spa = _spa_index()
    if spa:
        return web.FileResponse(spa)
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_detail_page(request):
    spa = _spa_index()
    if spa:
        return web.FileResponse(spa)
    detail_file = STATIC_DIR / "detail.html"
    if detail_file.exists():
        return web.FileResponse(detail_file)
    return web.Response(text="Detail page not found", status=404)


async def handle_login_page(request):
    spa = _spa_index()
    if spa:
        return web.FileResponse(spa)
    return web.FileResponse(STATIC_DIR / "login.html")


async def handle_browse_page(request):
    spa = _spa_index()
    if spa:
        return web.FileResponse(spa)
    return web.FileResponse(STATIC_DIR / "index.html")
