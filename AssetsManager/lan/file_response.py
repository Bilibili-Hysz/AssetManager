"""Bounded HTTP transfers from an already admitted, owned file handle."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from aiohttp import web

from AssetsManager.lan.safe_open import FileIdentity, SafeOpenError, SafeOpenedFile, safe_open_under_root

TRANSFER_CHUNK_BYTES = 1024 * 1024


async def open_download_file(root: str | Path, target: Path) -> SafeOpenedFile:
    """Offload final-open and retain ownership even if its caller is cancelled."""
    task = asyncio.create_task(asyncio.to_thread(safe_open_under_root, root, target))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        def close_result(done):
            if not done.cancelled() and done.exception() is None:
                done.result().close()
        task.add_done_callback(close_result)
        raise


class SafeFileResponse(web.StreamResponse):
    """Stream an owned descriptor without reopening its mutable pathname.

    Sending starts in prepare so response middleware can still add headers.
    A transfer failure closes the connection: partial bytes cannot be replaced
    with a JSON error once headers have been sent. Download admission counts
    remain consumed for transfers interrupted after admission.
    """

    def __init__(self, request, opened: SafeOpenedFile, *, headers: dict[str, str]):
        super().__init__(headers=headers)
        self._opened = opened
        self.content_length = opened.size
        self.content_type = "application/octet-stream"
        task = getattr(request, "task", None)
        if task is not None:
            task.add_done_callback(lambda _done: self.close())

    def close(self) -> None:
        self._opened.close()

    def _read_chunk(self, remaining: int) -> bytes:
        opened = self._opened
        if FileIdentity.from_stat(os.fstat(opened.file.fileno())) != opened.identity:
            raise SafeOpenError("file changed during download")
        chunk = opened.file.read(min(TRANSFER_CHUNK_BYTES, remaining))
        if not chunk and remaining:
            raise SafeOpenError("file truncated during download")
        # Check before writing the last chunk, so an unstable source cannot
        # appear to complete successfully under Content-Length framing.
        if len(chunk) == remaining:
            if FileIdentity.from_stat(os.fstat(opened.file.fileno())) != opened.identity:
                raise SafeOpenError("file changed during download")
        return chunk

    async def prepare(self, request):
        if self.prepared or self._eof_sent:
            return await super().prepare(request)
        try:
            remaining = self._opened.size
            # Detect failures before committing the response headers.
            chunk = await asyncio.to_thread(self._read_chunk, 0 if request.method == "HEAD" else remaining)
            writer = await super().prepare(request)
            if request.method != "HEAD":
                while remaining:
                    await self.write(chunk)
                    remaining -= len(chunk)
                    if remaining:
                        chunk = await asyncio.to_thread(self._read_chunk, remaining)
            await self.write_eof()
            return writer
        except BaseException:
            self.force_close()
            if self.prepared and request.transport is not None:
                request.transport.close()
            raise
        finally:
            # Buffered file close serializes with an in-flight worker read,
            # including when cancellation interrupted the await above.
            await asyncio.to_thread(self.close)
