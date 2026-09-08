"""Cancelled ZIP downloads keep ownership until cleanup actually completes.

Work package ``week-2026-09-14-lan-workpack``, "first implementable test":
the cancelled-ZIP ownership loop.  One real batch ZIP is driven through
client cancellation, a failing ``os.unlink`` barrier, and the process
cleanup retry clock, asserting at every stage that the response owner keeps
both the archive handle and the process budget reservation until deletion
really succeeds:

1. Start a real batch ZIP, read a small part of the body, then cancel the
   client task and abort the transport mid-transfer.
2. While the cleanup barrier still holds the response owner and its
   reservation, the second job must not be admitted.  Release is never
   inferred from the HTTP handler returning: with the unlink gate active the
   owner cannot complete, so a zeroed budget at that point would be a real
   leak.  A later stage proves a legitimately admitted follow-up job once
   cleanup has finished and returned the counters to zero.
3. Drive the cleanup retry clock: the ZIP path disappears, the owner handle
   is closed, the budget returns to ``active_jobs=0 / reserved_bytes=0``,
   and the next job is admitted through a real request with a correct body.
4. First ``os.unlink`` raises ``PermissionError``: the file remains, the
   reservation is not released, and the cleanup service reports a pending
   entry with increased retries and ``last_error_type == "PermissionError"``;
   only a later successful attempt releases the job.
5. Identity change: a retry must never delete a replacement file that reused
   the archive path, and must retain ``IdentityChangedError`` diagnostics
   with unfinished ownership instead of a false "cleanup succeeded".

Assertions read private in-process objects only; no new anonymous/public
state, paths, file names, or error text is introduced and the ``dto.py``
ZIP diagnostics boundary (counts, durations, exception type) is untouched.
"""
import asyncio
import io
import os
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from AssetsManager.lan import zip_cleanup
from AssetsManager.lan.routes import downloads
from AssetsManager.lan.routes._helpers import LAN_APP_KEY, ZIP_EXECUTOR_APP_KEY
from AssetsManager.lan.temporary_file_response import TemporaryFileResponse
from AssetsManager.lan.zip_resources import (
    MAX_ZIP_OUTPUT_BYTES,
    ZIP_BUDGET_APP_KEY,
    ZipResourceBudget,
)

BATCH_URL = "/api/download/batch"
# Incompressible body: the server must still be mid-send when the client
# disconnects after reading only a small prefix.
PAYLOAD_BYTES = 8 * 1024 * 1024
EMPTY_BUDGET = {"active_jobs": 0, "reserved_bytes": 0}
CHARGED_BUDGET = {"active_jobs": 1, "reserved_bytes": MAX_ZIP_OUTPUT_BYTES}


@pytest.fixture
def retry_clock(monkeypatch):
    """Deterministic cleanup retries: no worker, only manual clock advances."""
    now = [0.0]
    service = zip_cleanup.ZipCleanupService(
        base_delay=0.05, max_delay=0.2, clock=lambda: now[0], start_worker=False,
    )
    monkeypatch.setattr(zip_cleanup, "_PROCESS_ZIP_CLEANUP", service)
    yield now, service
    service.close()


async def _wait_until(predicate, timeout=10.0, interval=0.01):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("expected ownership state was not reached")
        await asyncio.sleep(interval)


def _install_harness(tmp_path, monkeypatch, payload):
    """Reuse the shared harness seams: app-injected budget, real routes."""
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "asset.txt").write_bytes(payload)
    monkeypatch.setattr(downloads, "require_permission", lambda *_args: True)
    monkeypatch.setattr(
        downloads, "get_free_download_quota_info", lambda _request: {"enabled": False}
    )
    consumed = []

    def consume(_request):
        consumed.append(True)
        return {"allowed": True, "info": {"enabled": False}}

    monkeypatch.setattr(downloads, "consume_free_download_quota", consume)

    created = []
    real_mkstemp = tempfile.mkstemp

    def track_mkstemp(*args, **kwargs):
        # Keep every archive inside the test's tmp_path.
        descriptor, path = real_mkstemp(*args, **kwargs, dir=tmp_path)
        created.append(Path(path))
        return descriptor, path

    monkeypatch.setattr(tempfile, "mkstemp", track_mkstemp)

    responses = []
    opened_files = []
    original_prepare = TemporaryFileResponse.prepare
    original_make_response = TemporaryFileResponse._make_response

    async def observing_prepare(self, request):
        if not (self.prepared or self._eof_sent):
            responses.append(self)
        return await original_prepare(self, request)

    def observing_make_response(self, request, accept_encoding):
        result = original_make_response(self, request, accept_encoding)
        if result[1] is not None:
            opened_files.append(result[1])
        return result

    monkeypatch.setattr(TemporaryFileResponse, "prepare", observing_prepare)
    monkeypatch.setattr(TemporaryFileResponse, "_make_response", observing_make_response)

    return SimpleNamespace(
        created=created,
        consumed=consumed,
        responses=responses,
        opened_files=opened_files,
        payload=payload,
    )


def _gate_unlink(monkeypatch, holder):
    """Fail ``os.unlink`` for the archive while ``fail`` is set, then spy."""
    state = {"fail": True, "archive_attempts": []}
    real_unlink = os.unlink

    def gated_unlink(path, *args, **kwargs):
        archive = holder["archive"]
        if archive is not None and Path(path) == archive:
            state["archive_attempts"].append(Path(path))
            if state["fail"]:
                raise PermissionError("temporary sharing violation")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(zip_cleanup.os, "unlink", gated_unlink)
    return state


async def _disconnect_after_first_bytes(client, state, holder):
    """Step 1: real batch ZIP, read a little, then cancel and disconnect."""
    response = await asyncio.wait_for(
        client.post(BATCH_URL, json={"paths": ["folder"]}), 10
    )
    assert response.status == 200
    assert state.responses, "server did not prepare the temporary ZIP response"
    server_response = state.responses[0]
    holder["archive"] = Path(server_response._path)
    first = await asyncio.wait_for(response.content.read(4096), 5)
    assert first, "client must receive the beginning of the ZIP body"
    reader = asyncio.create_task(response.content.read(1024 * 1024))
    try:
        await asyncio.wait_for(asyncio.shield(reader), 0.1)
    except asyncio.TimeoutError:
        pass
    if not reader.done():
        reader.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reader
    # The requester is gone mid-transfer; aiohttp must observe the abort.
    response.close()
    return server_response


def _make_app(state_budget, tmp_path, executor):
    app = web.Application()
    app[LAN_APP_KEY] = SimpleNamespace(library_root=tmp_path)
    app[ZIP_BUDGET_APP_KEY] = state_budget
    app[ZIP_EXECUTOR_APP_KEY] = executor
    app.router.add_post(BATCH_URL, downloads.handle_batch_download)
    return app


@pytest.mark.anyio
async def test_cancelled_batch_zip_ownership_loop(tmp_path, monkeypatch, retry_clock):
    """Steps 1-4: cancel, barrier, PermissionError diagnostics, release."""
    now, service = retry_clock
    payload = os.urandom(PAYLOAD_BYTES)
    state = _install_harness(tmp_path, monkeypatch, payload)
    budget = ZipResourceBudget(max_jobs=1)
    holder = {"archive": None}
    gate = _gate_unlink(monkeypatch, holder)

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-zip-http") as executor:
        async with TestClient(TestServer(_make_app(budget, tmp_path, executor))) as client:
            response = await _disconnect_after_first_bytes(client, state, holder)
            archive = holder["archive"]
            assert archive == state.created[0]
            assert Path(response._path) == archive
            owner = response._owner

            # Step 2: the cleanup barrier holds the owner and the reservation.
            # The unlink gate keeps the owner unfinished, so a zeroed budget
            # here could only mean a leak; the client task is already gone,
            # which by itself must never release the job.
            await _wait_until(lambda: service.snapshot()["pending_count"] >= 1, timeout=15)
            assert budget.snapshot() == CHARGED_BUDGET
            assert budget.try_acquire() is None
            assert archive.exists()
            assert owner._cleanup_requested and not owner._cleanup_complete
            assert owner._on_cleanup is not None, "release callback must be retained"
            assert service.snapshot()["pending_count"] == 1

            denied = await asyncio.wait_for(
                client.post(BATCH_URL, json={"paths": ["folder"]}), 5
            )
            assert denied.status == 503
            assert denied.headers["Retry-After"] == "1"
            assert (await denied.json())["code"] == "zip_capacity_exhausted"
            assert len(state.created) == 1, "denied job must not build a ZIP"
            assert len(state.consumed) == 1, "denied job must not consume quota"
            assert budget.snapshot() == CHARGED_BUDGET

            # Step 4: the first retry attempt still fails with PermissionError.
            now[0] += 10.0
            assert service.run_due() == 1
            snapshot = service.snapshot()
            assert snapshot["pending_count"] == 1
            assert snapshot["retry_attempts"] == 1
            assert snapshot["completed_count"] == 0
            assert snapshot["last_error_type"] == "PermissionError"
            assert archive.exists(), "file must survive a failed unlink"
            assert budget.snapshot() == CHARGED_BUDGET
            assert budget.try_acquire() is None

            # Steps 3+4: the second attempt succeeds and releases everything.
            gate["fail"] = False
            now[0] += 10.0
            assert service.run_due() == 1
            snapshot = service.snapshot()
            assert snapshot["pending_count"] == 0
            assert snapshot["completed_count"] == 1
            assert snapshot["last_error_type"] == "PermissionError"
            assert not archive.exists()
            assert owner._file is None
            assert state.opened_files[0].closed, "owner handle must be closed"
            assert budget.snapshot() == EMPTY_BUDGET

            # Step 3: with the counters back to zero the next job is admitted
            # legitimately — through a real request with a correct body.
            recovered = await asyncio.wait_for(
                client.post(BATCH_URL, json={"paths": ["folder"]}), 15
            )
            assert recovered.status == 200
            body = await recovered.read()
            with zipfile.ZipFile(io.BytesIO(body)) as archive_file:
                assert archive_file.namelist() == ["folder/asset.txt"]
                assert archive_file.read("folder/asset.txt") == payload
            assert len(state.created) == 2
            assert len(state.consumed) == 2
            second_archive = state.created[1]

            await _wait_until(
                lambda: budget.snapshot() == EMPTY_BUDGET and not second_archive.exists(),
                timeout=10,
            )
            assert state.opened_files[1].closed


@pytest.mark.anyio
async def test_identity_change_keeps_ownership_and_spares_replacement(
    tmp_path, monkeypatch, retry_clock
):
    """Step 5: a replaced archive path is never deleted by a retry."""
    now, service = retry_clock
    payload = os.urandom(PAYLOAD_BYTES)
    state = _install_harness(tmp_path, monkeypatch, payload)
    budget = ZipResourceBudget(max_jobs=1)
    holder = {"archive": None}
    gate = _gate_unlink(monkeypatch, holder)

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-zip-http") as executor:
        async with TestClient(TestServer(_make_app(budget, tmp_path, executor))) as client:
            response = await _disconnect_after_first_bytes(client, state, holder)
            archive = holder["archive"]
            await _wait_until(lambda: service.snapshot()["pending_count"] >= 1, timeout=15)
            assert response._owner._failed_unlink_identity_known
            assert archive.exists()
            assert budget.snapshot() == CHARGED_BUDGET

            # Replace the archive at the same path with different content.
            replacement = b"replacement payload with a different size"
            archive.write_bytes(replacement)
            attempts_before = len(gate["archive_attempts"])
            gate["fail"] = False

            now[0] += 10.0
            assert service.run_due() == 1
            snapshot = service.snapshot()
            assert snapshot["last_error_type"] == "IdentityChangedError"
            assert snapshot["pending_count"] == 1, "ownership must stay unfinished"
            assert snapshot["completed_count"] == 0, "no false cleanup success"
            assert snapshot["retry_attempts"] == 1
            assert archive.read_bytes() == replacement
            assert len(gate["archive_attempts"]) == attempts_before, (
                "retry must not even attempt to unlink a replaced archive"
            )
            assert budget.snapshot() == CHARGED_BUDGET
            assert budget.try_acquire() is None

            # Repeated retries keep the ownership unresolved while the path
            # still identifies a different file.
            now[0] += 10.0
            assert service.run_due() == 1
            snapshot = service.snapshot()
            assert snapshot["pending_count"] == 1
            assert snapshot["completed_count"] == 0
            assert snapshot["last_error_type"] == "IdentityChangedError"
            assert archive.read_bytes() == replacement
            assert state.opened_files[0].closed
            assert response._owner._cleanup_complete is False
            assert response._owner._on_cleanup is not None

            denied = await asyncio.wait_for(
                client.post(BATCH_URL, json={"paths": ["folder"]}), 5
            )
            assert denied.status == 503
