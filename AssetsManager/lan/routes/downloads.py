"""Download routes: /api/download/{path}, /api/download/batch."""
import os
from pathlib import Path
from urllib.parse import unquote

from aiohttp import web

from AssetsManager.lan.routes._helpers import build_zip_async, get_lan, require_permission, sanitize_filename, validate_path

MAX_BATCH_DOWNLOAD_PATHS = 100
MAX_BATCH_DOWNLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


def _file_response_with_cleanup(path: str, *, filename: str, write_eof=None) -> web.FileResponse:
    response = web.FileResponse(
        path,
        headers={"Content-Disposition": f'attachment; filename="{sanitize_filename(filename)}"'},
    )
    original_write_eof = write_eof or response.write_eof

    async def _write_eof_and_cleanup(data: bytes = b""):
        try:
            return await original_write_eof(data)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    response.write_eof = _write_eof_and_cleanup
    return response


def _estimate_download_size(target: Path) -> int:
    if target.is_file():
        return target.stat().st_size
    if target.is_dir():
        total = 0
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fname in filenames:
                if fname.startswith("."):
                    continue
                try:
                    total += (Path(dirpath) / fname).stat().st_size
                except OSError:
                    pass
        return total
    return 0


async def handle_download(request):
    if not require_permission(request, "download"):
        return web.json_response({"error": "Forbidden"}, status=403)

    lan = get_lan(request)
    rel_path = unquote(request.match_info["path"])
    target = validate_path(lan, rel_path)

    if target.is_file():
        return web.FileResponse(
            target,
            headers={"Content-Disposition": f'attachment; filename="{sanitize_filename(target.name)}"'},
        )

    if target.is_dir():
        try:
            total_bytes = _estimate_download_size(target)
        except OSError:
            total_bytes = 0
        if total_bytes > MAX_BATCH_DOWNLOAD_BYTES:
            return web.json_response({
                "error": f"Total size exceeds limit ({MAX_BATCH_DOWNLOAD_BYTES // (1024*1024)} MB)",
                "total_bytes": total_bytes,
                "limit_bytes": MAX_BATCH_DOWNLOAD_BYTES,
            }, status=413)

        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
        os.close(tmp_fd)
        result = await build_zip_async([(target, None)], tmp_path)
        if result is None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return web.json_response({"error": "Failed to create ZIP"}, status=500)
        zip_name = f"{target.name}.zip"
        return _file_response_with_cleanup(tmp_path, filename=zip_name)

    return web.json_response({"error": "File not found"}, status=404)


async def handle_batch_download(request):
    if not require_permission(request, "download"):
        return web.json_response({"error": "Forbidden"}, status=403)

    lan = get_lan(request)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid request body"}, status=400)

    paths = body.get("paths", [])
    if not paths:
        return web.json_response({"error": "No paths provided"}, status=400)
    if not isinstance(paths, list):
        return web.json_response({"error": "Invalid paths format"}, status=400)
    if len(paths) > MAX_BATCH_DOWNLOAD_PATHS:
        return web.json_response({"error": f"Too many paths (max {MAX_BATCH_DOWNLOAD_PATHS})"}, status=400)

    targets = []
    for rel_path in paths:
        if not isinstance(rel_path, str):
            continue
        try:
            target = validate_path(lan, rel_path)
            if target.exists():
                targets.append((rel_path, target))
        except web.HTTPException:
            raise
        except Exception:
            continue

    if not targets:
        return web.json_response({"error": "No valid paths"}, status=400)

    # Enforce total-size limit
    total_bytes = 0
    for _, target in targets:
        try:
            total_bytes += _estimate_download_size(target)
        except OSError:
            pass
    if total_bytes > MAX_BATCH_DOWNLOAD_BYTES:
        return web.json_response({
            "error": f"Total size exceeds limit ({MAX_BATCH_DOWNLOAD_BYTES // (1024*1024)} MB)",
            "total_bytes": total_bytes,
            "limit_bytes": MAX_BATCH_DOWNLOAD_BYTES,
        }, status=413)

    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(tmp_fd)
    result = await build_zip_async([(target, None) for _, target in targets], tmp_path)
    if result is None:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return web.json_response({"error": "Failed to create ZIP"}, status=500)

    if len(targets) == 1:
        zip_name = f"{targets[0][1].name}.zip"
    else:
        zip_name = f"download_{len(targets)}_items.zip"

    return _file_response_with_cleanup(tmp_path, filename=zip_name)
