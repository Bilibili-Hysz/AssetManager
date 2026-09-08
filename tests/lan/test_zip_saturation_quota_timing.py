"""ZIP saturation denies the second job before any ZIP or quota is spent.

Work package ``week-2026-09-14-lan-workpack``, implementation step 2 (ZIP
saturation and quota consumption timing).  Everything runs over real HTTP
through the composed LAN app; only policy seams (guest download settings)
and the established harness injection points are patched:

1. With an injected ``max_jobs=1`` process budget, the first admitted job is
   held inside response preparation.  A second real batch request must then
   receive ``503`` + ``Retry-After``, must not build a second archive, and
   must not consume the visitor's free-download quota — the quota window
   state is byte-identical before and after the denial.
2. Budget snapshots before/during/after pin the exclusive-measurement
   timing: ``active_jobs``/``reserved_bytes`` charge at admission and return
   to zero only after the first response finishes.
3. Once the first job completes, the follow-up job is admitted legitimately
   through a real request and delivers a correct archive.
4. A separate race test drives anonymous-cookie and authenticated-principal
   downloads of the same resource concurrently: per-identity successes never
   exceed the configured limit, every denial is ``429`` with the exhausted
   contract, and the recorded window usage equals the number of successful
   downloads — denials never record consumption.
"""
import asyncio
import io
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp.cookiejar import DummyCookieJar
from aiohttp.test_utils import TestClient, TestServer

from AssetsManager.lan import zip_resources
from AssetsManager.lan.temporary_file_response import TemporaryFileResponse
from AssetsManager.lan.zip_resources import MAX_ZIP_OUTPUT_BYTES, ZipResourceBudget
from tests.lan.support.api_helpers import _make_lan_app, _local_ui_headers

BATCH_URL = "/api/download/batch"
QUOTA_URL = "/api/quota"
# Only needs to survive ZIP building and a full body read; random bytes keep
# the archive size honest.
PAYLOAD_BYTES = 4 * 1024 * 1024
EMPTY_BUDGET = {"active_jobs": 0, "reserved_bytes": 0}
CHARGED_BUDGET = {"active_jobs": 1, "reserved_bytes": MAX_ZIP_OUTPUT_BYTES}


class _Settings:
    """Minimal AppSettings seam (same shape as the quota test settings)."""

    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def _patch_quota_settings(monkeypatch, *, limit):
    """Enable the real free-download quota for guests over real HTTP."""
    from AssetsManager.lan.routes import quota as quota_routes

    settings = _Settings({
        "lan_quota_enabled": True,
        "lan_quota_period": "daily",
        "lan_quota_limit": limit,
        "lan_quota_min_interval_seconds": 0,
        # The real require_permission path must admit guest downloads.
        "lan_guest_download": True,
    })
    monkeypatch.setattr(quota_routes.AppSettings, "instance", lambda: settings)
    return settings


def _init_quota_table(conn):
    """Create the quota window table the migration normally provides."""
    from AssetsManager.repositories.free_download_quota_repository import (
        FreeDownloadQuotaRepository,
    )

    FreeDownloadQuotaRepository(conn).init_tables()


async def _make_no_jar_client(app):
    """TestClient that never stores cookies; identities are passed explicitly."""
    client = TestClient(TestServer(app), cookie_jar=DummyCookieJar())
    await client.start_server()
    return client


async def _wait_until(predicate, timeout=10.0, interval=0.01):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("expected saturation state was not reached")
        await asyncio.sleep(interval)


def _install_zip_tracking(tmp_path, monkeypatch):
    """Track every archive creation and gate the first response prepare."""
    import tempfile

    tracked = SimpleNamespace(created=[], prepared=[], gate={})

    real_mkstemp = tempfile.mkstemp

    def tracking_mkstemp(*args, **kwargs):
        # Keep every archive inside the test's tmp_path.
        descriptor, path = real_mkstemp(*args, **kwargs, dir=tmp_path)
        tracked.created.append(Path(path))
        return descriptor, path

    monkeypatch.setattr(tempfile, "mkstemp", tracking_mkstemp)

    original_prepare = TemporaryFileResponse.prepare

    async def gated_prepare(self, request):
        first_prepare = not (self.prepared or self._eof_sent)
        if first_prepare:
            tracked.prepared.append(self)
            release = tracked.gate.get("release")
            if release is not None:
                tracked.gate["entered"].set()
                await release.wait()
        return await original_prepare(self, request)

    monkeypatch.setattr(TemporaryFileResponse, "prepare", gated_prepare)
    return tracked


async def _quota_state(client, *, cookie_token=None, auth_headers=None):
    headers = {}
    if cookie_token is not None:
        from AssetsManager.lan.routes.quota import _QUOTA_ID_COOKIE

        headers["Cookie"] = f"{_QUOTA_ID_COOKIE}={cookie_token}"
    if auth_headers:
        headers.update(auth_headers)
    response = await client.get(QUOTA_URL, headers=headers)
    assert response.status == 200
    return await response.json()


@pytest.mark.anyio
async def test_zip_saturation_denies_second_job_without_zip_or_quota_cost(
    tmp_path, monkeypatch,
):
    """Steps 1-3: saturation denial costs no ZIP and no quota; then release."""
    _patch_quota_settings(monkeypatch, limit=3)
    payload = os.urandom(PAYLOAD_BYTES)
    app, library, conn = _make_lan_app(tmp_path)
    _init_quota_table(conn)
    folder = library / "folder"
    folder.mkdir()
    (folder / "asset.txt").write_bytes(payload)

    tracked = _install_zip_tracking(tmp_path, monkeypatch)
    budget = ZipResourceBudget(max_jobs=1)
    monkeypatch.setattr(zip_resources, "_PROCESS_ZIP_BUDGET", budget)
    tracked.gate.update(release=asyncio.Event(), entered=asyncio.Event())

    client = await _make_no_jar_client(app)
    try:
        # Before: an idle process carries no reservation at all.
        before = budget.snapshot()
        assert before == EMPTY_BUDGET

        # Establish the stable anonymous identity before any download.
        warmup = await client.get(QUOTA_URL)
        assert warmup.status == 200
        warm = await warmup.json()
        assert warm["enabled"] is True
        assert warm["limit"] == 3
        assert warm["used"] == 0 and warm["remaining"] == 3
        cookie_token = warmup.cookies["am_quota_id"].value
        download_headers = {"Cookie": f"am_quota_id={cookie_token}"}

        # Job one is admitted, builds its archive, consumes one quota unit,
        # and then blocks inside response preparation.
        first_task = asyncio.create_task(
            client.post(BATCH_URL, json={"paths": ["folder"]}, headers=download_headers)
        )
        await _wait_until(lambda: len(tracked.created) == 1, timeout=15)
        await asyncio.wait_for(tracked.gate["entered"].wait(), 10)

        # During: exactly one job charged with the full output reservation.
        during = budget.snapshot()
        assert during == CHARGED_BUDGET
        assert budget.try_acquire() is None
        mid_quota = await _quota_state(client, cookie_token=cookie_token)
        assert mid_quota["used"] == 1, (
            "the admitted job consumes its unit before the response is prepared"
        )

        # The saturated second request is denied without any side effect.
        denied = await asyncio.wait_for(
            client.post(BATCH_URL, json={"paths": ["folder"]}, headers=download_headers),
            10,
        )
        assert denied.status == 503
        assert denied.headers["Retry-After"] == "1"
        assert (await denied.json())["code"] == "zip_capacity_exhausted"
        assert len(tracked.created) == 1, "denied job must not build a second ZIP"
        assert len(tracked.prepared) == 1, "denied job must not prepare a response"
        assert budget.snapshot() == during
        after_denial_quota = await _quota_state(client, cookie_token=cookie_token)
        # Quota state is identical before and after the denial: a capacity
        # rejection never consumes the visitor's free-download window.
        assert after_denial_quota == mid_quota
        assert after_denial_quota["used"] == 1

        # After: the first job completes and returns every counter to zero.
        tracked.gate["release"].set()
        first = await asyncio.wait_for(first_task, 15)
        assert first.status == 200
        body = await first.read()
        with zipfile.ZipFile(io.BytesIO(body)) as archive_file:
            assert archive_file.namelist() == ["folder/asset.txt"]
            assert archive_file.read("folder/asset.txt") == payload
        await _wait_until(lambda: budget.snapshot() == EMPTY_BUDGET, timeout=10)
        after = budget.snapshot()
        assert after == EMPTY_BUDGET
        assert not tracked.created[0].exists()

        # Release timing: only now is the follow-up job legitimately admitted,
        # through a real request with a correct body.
        second = await asyncio.wait_for(
            client.post(BATCH_URL, json={"paths": ["folder"]}, headers=download_headers),
            15,
        )
        assert second.status == 200
        second_body = await second.read()
        with zipfile.ZipFile(io.BytesIO(second_body)) as archive_file:
            assert archive_file.read("folder/asset.txt") == payload
        assert len(tracked.created) == 2, "admitted job builds exactly one archive"
        final_quota = await _quota_state(client, cookie_token=cookie_token)
        assert final_quota["used"] == 2
        assert final_quota["remaining"] == 1
    finally:
        await client.close()


@pytest.mark.anyio
async def test_quota_race_between_anonymous_cookie_and_authenticated_principal(
    tmp_path, monkeypatch,
):
    """Concurrent identities: successes stay within the limit, denials at 429.

    Pinned to the ``free_download_quota_service`` contract as implemented:
    a consume whose ``now`` was captured before another winner's write can
    lose the CAS and be denied as ``rate_limited`` even with a zero interval,
    so the exact success count is timing-dependent.  The hard bounds are what
    the matrix demands: no more successes than the limit, every denial is a
    ``429`` whose headers and body describe the same window state, and the
    recorded usage equals the number of successful downloads exactly.
    """
    _patch_quota_settings(monkeypatch, limit=4)
    payload = b"race-payload"
    app, library, conn = _make_lan_app(tmp_path)
    _init_quota_table(conn)
    (library / "asset.txt").write_bytes(payload)

    client = await _make_no_jar_client(app)
    try:
        # The anonymous visitor keeps one stable signed-cookie identity.
        warmup = await client.get(QUOTA_URL)
        assert warmup.status == 200
        cookie_token = warmup.cookies["am_quota_id"].value
        anon_headers = {"Cookie": f"am_quota_id={cookie_token}"}
        auth_headers = _local_ui_headers(app)

        auth_warm = await _quota_state(client, auth_headers=auth_headers)
        assert auth_warm["enabled"] is True
        assert auth_warm["used"] == 0, "the principal starts with an empty window"

        per_identity = 6  # limit 4 -> at most 4 successes per identity

        async def download(headers):
            return await client.get("/api/download/asset.txt", headers=headers)

        outcomes = await asyncio.gather(
            *[download(anon_headers) for _ in range(per_identity)],
            *[download(auth_headers) for _ in range(per_identity)],
        )
        identities = (
            ("anonymous cookie", anon_headers, outcomes[:per_identity],
             lambda: _quota_state(client, cookie_token=cookie_token)),
            ("authenticated principal", auth_headers, outcomes[per_identity:],
             lambda: _quota_state(client, auth_headers=auth_headers)),
        )

        for name, _headers, group, read_state in identities:
            statuses = sorted(response.status for response in group)
            assert all(status in (200, 429) for status in statuses), (name, statuses)
            successes = [r for r in group if r.status == 200]
            denials = [r for r in group if r.status == 429]
            assert len(successes) >= 1, (name, "the first consume must be admitted")
            assert len(successes) <= 4, (name, "successes must never exceed the limit")
            for response in successes:
                assert await response.read() == payload
            for response in denials:
                body = await response.json()
                assert body["code"] in (
                    "download_quota_exhausted", "download_rate_limited",
                ), (name, body)
                # Headers and body must describe the same window state.
                assert (
                    int(response.headers["X-Quota-Remaining"])
                    == body["details"]["quota"]["remaining"]
                )
                assert response.headers["X-Quota-Limit"] == "4"

            # Denials never record consumption: the window usage equals the
            # number of successful downloads exactly.
            window = await read_state()
            assert window["used"] == len(successes), (name, window)
            assert window["remaining"] == 4 - len(successes), (name, window)

        # Sequential recovery: the window state alone decides the next
        # consume — admitted while budget remains, exhausted at the limit.
        for _name, headers, _group, read_state in identities:
            state = await read_state()
            followup = await client.get("/api/download/asset.txt", headers=headers)
            if state["used"] < 4:
                assert followup.status == 200
                assert await followup.read() == payload
                assert (await read_state())["used"] == state["used"] + 1
            else:
                assert followup.status == 429
                assert (await followup.json())["code"] == "download_quota_exhausted"
                assert (await read_state())["used"] == 4
    finally:
        await client.close()
