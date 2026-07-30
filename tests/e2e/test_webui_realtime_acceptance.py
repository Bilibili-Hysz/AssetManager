"""Real Chromium acceptance tests for LAN WebUI realtime recovery."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, sync_playwright  # noqa: E402

from AssetsManager.application import ApplicationBootstrap  # noqa: E402
from AssetsManager.lan import LanServer  # noqa: E402
from AssetsManager.lan.utils import generate_auth_token  # noqa: E402


def _start_server(runtime, *, port: int | None = None) -> LanServer:
    server = LanServer(runtime=runtime, password="Task14-Password!")
    server.start(port=0 if port is None else port, bind="127.0.0.1")
    assert server._port > 0
    return server


def _stop_server_cleanly(server: LanServer) -> None:
    thread = server._impl._thread
    server.stop()
    assert thread is None or not thread.is_alive()


def _login_cookie(server: LanServer) -> dict[str, str]:
    return {
        "name": "lan_token",
        "value": generate_auth_token(server.token_secret),
        "url": f"http://127.0.0.1:{server._port}",
    }


def _open_browse(page: Page, server: LanServer) -> None:
    page.context.add_cookies([_login_cookie(server)])
    page.goto(f"http://127.0.0.1:{server._port}/browse", wait_until="networkidle")
    page.get_by_test_id("browse-workspace").wait_for()


def _wait_for_connection_count(server: LanServer, expected: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.status()["connections"] == expected:
            return
        time.sleep(0.01)
    pytest.fail(
        f"WebSocket connection count did not become {expected}; "
        f"last count was {server.status()['connections']}"
    )


@pytest.fixture
def browser_page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            yield page
        finally:
            browser.close()


@pytest.fixture
def lan_runtime(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    runtime = bootstrap.runtime_for(session)
    server = _start_server(runtime)
    try:
        yield bootstrap, session, runtime, server
    finally:
        _stop_server_cleanly(server)
        bootstrap.library_service.close_session(session)


def _wait_for_name(page: Page, name: str) -> None:
    page.get_by_role("button", name=name, exact=True).wait_for(state="visible", timeout=10_000)


def test_browser_realtime_refreshes_after_desktop_mutation(browser_page, lan_runtime):
    _bootstrap, _session, runtime, server = lan_runtime
    page = browser_page
    _open_browse(page, server)

    _wait_for_connection_count(server, 1)
    runtime.services.file_operation_service.create_folder(runtime.session.root, "desktop-created")

    _wait_for_name(page, "desktop-created")


def test_real_lan_server_restarts_on_same_port(lan_runtime):
    _bootstrap, _session, _runtime, server = lan_runtime
    port = server._port
    first_loop = server._impl._loop

    _stop_server_cleanly(server)
    assert first_loop is not None and first_loop.is_closed()
    server.start(port=port, bind="127.0.0.1")
    second_loop = server._impl._loop

    try:
        assert server.is_running()
        assert server._port == port
    finally:
        _stop_server_cleanly(server)
        assert second_loop is not None and second_loop.is_closed()


def test_browser_recovers_revision_gap_after_websocket_disconnect(browser_page, lan_runtime):
    _bootstrap, _session, runtime, server = lan_runtime
    page = browser_page
    _open_browse(page, server)
    _wait_for_connection_count(server, 1)
    _stop_server_cleanly(server)
    runtime.services.file_operation_service.create_folder(runtime.session.root, "gap-one")
    runtime.services.file_operation_service.create_folder(runtime.session.root, "gap-two")
    replacement = _start_server(runtime, port=server._port)
    page.context.add_cookies([_login_cookie(replacement)])

    try:
        _wait_for_name(page, "gap-two")
    finally:
        _stop_server_cleanly(replacement)


def test_browser_recovers_epoch_after_same_root_server_restart(browser_page, lan_runtime):
    bootstrap, session, runtime, server = lan_runtime
    page = browser_page
    _open_browse(page, server)
    _wait_for_connection_count(server, 1)
    first_epoch = runtime.epoch
    _stop_server_cleanly(server)
    bootstrap.library_service.close_session(session)

    new_session = bootstrap.library_service.open_session(session.root)
    new_runtime = bootstrap.runtime_for(new_session)
    new_server = _start_server(new_runtime, port=server._port)
    try:
        assert new_runtime.epoch != first_epoch
        page.context.add_cookies([_login_cookie(new_server)])
        new_runtime.services.file_operation_service.create_folder(new_runtime.session.root, "after-restart")
        _wait_for_name(page, "after-restart")
    finally:
        _stop_server_cleanly(new_server)
        bootstrap.library_service.close_session(new_session)
