"""Real Chromium acceptance tests for LAN WebUI realtime recovery."""

from __future__ import annotations

import socket
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e  # opt in with `pytest -m e2e` (real Chromium)

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, sync_playwright  # noqa: E402

from AssetsManager.application import ApplicationBootstrap  # noqa: E402
from AssetsManager.application.security_preflight import SecurityPreflight  # noqa: E402
from AssetsManager.lan import LanServer  # noqa: E402
from AssetsManager.lan.utils import generate_auth_token  # noqa: E402


_CHROMIUM_UNSAFE_PORTS = frozenset(
    {
        1,
        7,
        9,
        11,
        13,
        15,
        17,
        19,
        20,
        21,
        22,
        23,
        25,
        37,
        42,
        43,
        53,
        69,
        77,
        79,
        87,
        95,
        101,
        102,
        103,
        104,
        109,
        110,
        111,
        113,
        115,
        117,
        119,
        123,
        135,
        139,
        143,
        179,
        389,
        427,
        465,
        512,
        513,
        514,
        515,
        548,
        554,
        556,
        563,
        587,
        601,
        636,
        989,
        990,
        993,
        995,
        1719,
        1720,
        1723,
        2049,
        3659,
        4045,
        5060,
        5061,
        6000,
        6566,
        6665,
        6666,
        6667,
        6668,
        6669,
        6697,
        10080,
    }
)


def _find_browser_safe_port() -> int:
    """Reserve a high ephemeral candidate outside Chromium's blocked ports."""
    for _ in range(20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            candidate = int(probe.getsockname()[1])
        if candidate not in _CHROMIUM_UNSAFE_PORTS:
            return candidate
    raise RuntimeError("Could not find a Chromium-compatible ephemeral port")


def _start_server(runtime, *, port: int | None = None) -> LanServer:
    preflight = SecurityPreflight()
    preflight.confirm_authenticated_lan()
    server = LanServer(
        runtime=runtime,
        password="Task14-Password!",
        preflight=preflight,
    )
    server.start(
        port=_find_browser_safe_port() if port is None else port,
        bind="127.0.0.1",
    )
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
        context = browser.new_context(locale="en-US")
        page = context.new_page()
        try:
            yield page
        finally:
            browser.close()


@pytest.fixture
def lan_runtime(tmp_path: Path):
    # Windows CI runners expose pytest's tmp_path through the 8.3 alias
    # (C:\Users\RUNNER~1\...) while PathGuard/Path.resolve() expand it to the
    # long form (C:\Users\runneradmin\...) mid-request. Anchor the library on
    # the resolved long path so the managed connection identity matches every
    # downstream request.
    library = tmp_path.resolve() / "library"
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


def test_browser_logout_redirects_and_closes_realtime(browser_page, lan_runtime):
    _bootstrap, _session, _runtime, server = lan_runtime
    page = browser_page
    _open_browse(page, server)
    _wait_for_connection_count(server, 1)

    page.get_by_role("button", name="Admin", exact=True).click()
    page.get_by_role("button", name="Logout", exact=True).click()

    page.wait_for_url("**/login")
    page.locator("input[type='password']").wait_for()
    _wait_for_connection_count(server, 0)

    response = page.evaluate(
        """async () => (await fetch('/api/files', {credentials: 'same-origin'})).status"""
    )
    assert response == 401


def test_browser_401_resets_identity_and_closes_realtime(browser_page, lan_runtime):
    _bootstrap, _session, _runtime, server = lan_runtime
    page = browser_page
    _open_browse(page, server)
    _wait_for_connection_count(server, 1)

    server._impl._token_secret = "rotated-token-secret"
    page.reload(wait_until="networkidle")

    page.wait_for_url("**/login")
    page.locator("input[type='password']").wait_for()
    _wait_for_connection_count(server, 0)


def test_real_lan_server_restarts_on_same_port(lan_runtime):
    _bootstrap, _session, _runtime, server = lan_runtime
    port = server._port
    initial = server.status()
    assert initial["lifecycle_state"] == "running"
    assert initial["owner_thread_alive"] is True
    assert initial["loop_active"] is True
    assert initial["runner_retained"] is True
    assert initial["restart_ready"] is False

    _stop_server_cleanly(server)
    stopped = server.status()
    assert stopped["running"] is False
    assert stopped["lifecycle_state"] == "stopped"
    assert stopped["cleanup_complete"] is True
    assert stopped["owner_thread_alive"] is False
    assert stopped["loop_active"] is False
    assert stopped["runner_retained"] is False
    assert stopped["restart_ready"] is True

    server.start(port=port, bind="127.0.0.1")
    try:
        restarted = server.status()
        assert restarted["running"] is True
        assert restarted["lifecycle_state"] == "running"
        assert restarted["owner_thread_alive"] is True
        assert restarted["loop_active"] is True
        assert restarted["runner_retained"] is True
        assert restarted["restart_ready"] is False
        assert restarted["port"] == port
    finally:
        _stop_server_cleanly(server)
        assert server.status()["restart_ready"] is True


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
