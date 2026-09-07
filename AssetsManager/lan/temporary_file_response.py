"""FileResponse compatibility with explicit ownership of temporary archives."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import threading
from collections.abc import Callable

from aiohttp import web

from AssetsManager.lan.zip_cleanup import IdentityChangedError

_log = logging.getLogger(__name__)


class _TemporaryFileOwner:
    """Coordinate the opener worker and request cleanup without blocking open.

    The lock protects only registration and disposal, never stat/open itself.
    Once cleanup is requested, a late opener disposes its own result. Deletion
    waits for both the opener and the owned handle to finish, as Windows needs.
    """

    def __init__(self, path: str, on_cleanup: Callable[[], None] | None = None) -> None:
        self._path = path
        self._on_cleanup = on_cleanup
        self._lock = threading.Lock()
        self._opening = False
        self._cleanup_requested = False
        self._cleanup_complete = False
        self._file: io.BufferedReader | None = None
        self._failed_unlink_identity: tuple[int, int, int, int] | None = None
        self._failed_unlink_identity_known = False
        self._cleanup_failure: Exception | None = None

    def begin_open(self) -> None:
        with self._lock:
            if self._cleanup_requested:
                raise FileNotFoundError(self._path)
            self._opening = True

    def finish_open(self, file: io.BufferedReader | None) -> bool:
        callback: Callable[[], None] | None = None
        retry_cleanup = False
        with self._lock:
            self._opening = False
            self._file = file
            if self._cleanup_requested:
                callback = self._dispose_locked()
                retry_cleanup = not self._cleanup_complete
                accepted = False
            else:
                accepted = True
        self._run_callback(callback)
        if retry_cleanup:
            self._queue_retry_cleanup()
        return accepted

    def cleanup(self, *, schedule_retry: bool = True) -> bool:
        """Close and remove the archive, returning whether cleanup completed.

        A failed close or unlink deliberately retains both the file handle and
        completion callback.  The process retry service owns subsequent
        attempts; its callback disables nested scheduling while it is running.
        """
        callback: Callable[[], None] | None = None
        retry_cleanup = False
        with self._lock:
            self._cleanup_requested = True
            if not self._opening:
                callback = self._dispose_locked()
                retry_cleanup = not self._cleanup_complete
            complete = self._cleanup_complete
        self._run_callback(callback)
        if retry_cleanup and schedule_retry:
            self._queue_retry_cleanup()
        return complete

    def request_cleanup(self) -> None:
        """Prevent a concurrent opener from handing an archive to aiohttp."""
        with self._lock:
            self._cleanup_requested = True

    def retry_cleanup(self) -> bool:
        """Retry hook invoked by ``ZipCleanupService`` outside its lock."""
        if self.cleanup(schedule_retry=False):
            return True
        with self._lock:
            failure = self._cleanup_failure
        if failure is not None:
            # Preserve exceptions whose constructors require arguments while
            # ensuring repeated retries do not retain growing tracebacks.
            raise failure.with_traceback(None)
        # An opener still owns the handle.  It will finish cleanup itself.
        return False

    def queue_retry_cleanup(self) -> None:
        """Expose retry registration for executor-rejection recovery."""
        self._queue_retry_cleanup()

    def _dispose_locked(self) -> Callable[[], None] | None:
        if self._cleanup_complete:
            return None
        # aiohttp may also schedule close on this BufferedReader. Its close
        # operation is idempotent and synchronizes with an in-flight read.
        if self._file is not None:
            try:
                self._file.close()
            except Exception as exc:
                self._record_cleanup_failure_locked(exc)
                _log.exception("Failed to close temporary download: %s", self._path)
                return None
            self._file = None
        if self._failed_unlink_identity_known:
            try:
                current_identity = self._path_identity()
            except OSError as exc:
                self._record_cleanup_failure_locked(exc)
                _log.exception("Failed to inspect temporary download: %s", self._path)
                return None
            if current_identity is None:
                return self._finish_cleanup_locked()
            if (
                self._failed_unlink_identity is None
                or current_identity != self._failed_unlink_identity
            ):
                # A retry must never delete an archive that reused this path.
                # Retain the callback until the original identity can be
                # resolved by a safe cleanup path.
                self._record_cleanup_failure_locked(IdentityChangedError())
                _log.warning("Temporary download path changed before cleanup: %s", self._path)
                return None
            identity = current_identity
        else:
            try:
                identity = self._path_identity()
            except OSError as exc:
                # Without a stable identity, a later retry cannot safely take
                # ownership of whichever file happens to occupy this path.
                self._failed_unlink_identity_known = True
                self._record_cleanup_failure_locked(exc)
                _log.exception("Failed to inspect temporary download: %s", self._path)
                return None
        if identity is None:
            return self._finish_cleanup_locked()
        try:
            os.unlink(self._path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            self._failed_unlink_identity = identity
            self._failed_unlink_identity_known = True
            self._record_cleanup_failure_locked(exc)
            _log.exception("Failed to remove temporary download: %s", self._path)
            return None
        return self._finish_cleanup_locked()

    def _finish_cleanup_locked(self) -> Callable[[], None] | None:
        self._cleanup_complete = True
        self._cleanup_failure = None
        callback = self._on_cleanup
        self._on_cleanup = None
        return callback

    def _record_cleanup_failure_locked(self, exc: Exception) -> None:
        """Keep the failure type without retaining its original traceback."""
        self._cleanup_failure = exc.with_traceback(None)

    def _path_identity(self) -> tuple[int, int, int, int] | None:
        """Return a conservative identity for retrying a failed unlink."""
        try:
            stat = os.lstat(self._path)
        except FileNotFoundError:
            return None
        except OSError:
            raise
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)

    def _queue_retry_cleanup(self) -> None:
        """Register one retry without holding the ownership lock."""
        try:
            from AssetsManager.lan.zip_cleanup import get_process_zip_cleanup

            get_process_zip_cleanup().schedule(self, self.retry_cleanup)
        except Exception:
            # Cleanup must never turn a request-completion callback into an
            # unhandled exception.  The owner still retains the handle and
            # callback, so a later explicit cleanup can recover it.
            _log.exception("Failed to queue temporary download cleanup: %s", self._path)

    def _run_callback(self, callback: Callable[[], None] | None) -> None:
        """Run a completed-cleanup callback after releasing the owner lock."""
        if callback is None:
            return
        try:
            callback()
        except Exception:
            _log.exception("Temporary download cleanup callback failed: %s", self._path)


class TemporaryFileResponse(web.FileResponse):
    """Retain aiohttp's Range/HEAD/conditional handling, then close and delete.

    ``_make_response`` is the one aiohttp internal hook used here: it performs
    final stat/open in an executor. Register there, before returning to the
    coroutine, so cancellation cannot lose an already opened file. HTTP
    compatibility and cancellation tests guard this hook on aiohttp upgrades.
    """

    def __init__(
        self,
        request,
        path: str,
        *,
        headers: dict[str, str],
        on_cleanup: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(path, headers=headers)
        self._owner = _TemporaryFileOwner(path, on_cleanup)
        self._cleanup_futures: set[asyncio.Future] = set()
        task = getattr(request, "task", None)
        if task is not None:
            task.add_done_callback(lambda _done: self._schedule_cleanup())

    def _schedule_cleanup(self) -> None:
        # Also cover an abandoned response which never reached prepare().
        self._owner.request_cleanup()
        try:
            future = asyncio.get_running_loop().run_in_executor(None, self._owner.cleanup)
        except RuntimeError:
            # Interpreter shutdown can reject the default executor.  Keep the
            # owner alive and move the work to the process cleanup service.
            self._owner.queue_retry_cleanup()
            return
        self._cleanup_futures.add(future)
        future.add_done_callback(self._cleanup_futures.discard)

    def _make_response(self, request, accept_encoding: str):
        self._owner.begin_open()
        try:
            result = super()._make_response(request, accept_encoding)
        except BaseException:
            self._owner.finish_open(None)
            raise
        if not self._owner.finish_open(result[1]):
            raise FileNotFoundError("temporary download was cancelled")
        return result

    async def prepare(self, request):
        if self.prepared or self._eof_sent:
            return await web.StreamResponse.prepare(self, request)
        try:
            return await super().prepare(request)
        finally:
            # Even if aiohttp queued a separate close, explicitly complete
            # ours before unlink. Cancellation during open marks ownership
            # finished; the opener then closes and deletes its late result.
            self._owner.request_cleanup()
            try:
                await asyncio.to_thread(self._owner.cleanup)
            except RuntimeError:
                # Do not let executor shutdown hide the original HTTP error.
                self._owner.queue_retry_cleanup()
