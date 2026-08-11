"""Low-priority batch: cookie Secure flag (Bug 21) + scanner stop (Bug 20)."""
import os
import time

from aiohttp import web

from AssetsManager.lan.routes._helpers import set_auth_cookie, set_share_cookie
from AssetsManager.lan.scanner import DirectoryScanner


# ── Cookie Secure flag (Bug 21) ───────────────────────────────

def test_set_auth_cookie_defaults_secure_false():
    resp = web.Response()
    set_auth_cookie(resp, "token-123")
    cookie = resp.cookies["lan_token"]
    assert cookie["secure"] is False
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"
    assert cookie["path"] == "/"
    assert cookie["max-age"] == "86400"


def test_set_auth_cookie_secure_true():
    resp = web.Response()
    set_auth_cookie(resp, "token-123", secure=True)
    assert resp.cookies["lan_token"]["secure"] is True
    assert resp.cookies["lan_token"]["httponly"] is True


def test_set_share_cookie_defaults_secure_false():
    resp = web.Response()
    set_share_cookie(resp, "share-1", "stoken")
    cookie = resp.cookies["share_token"]
    assert cookie["secure"] is False
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"
    assert cookie["path"] == "/api/shares/share-1"
    assert cookie["max-age"] == "3600"


def test_set_share_cookie_secure_true():
    resp = web.Response()
    set_share_cookie(resp, "share-1", "stoken", secure=True)
    assert resp.cookies["share_token"]["secure"] is True


# ── Scanner stop (Bug 20) ────────────────────────────────────

def _make_tree(root, files_per_dir=40, depth=2):
    """Create a small tree of files; returns expected (non-hidden) count."""
    count = 0
    current = [root]
    for level in range(depth):
        nxt = []
        for d in current:
            for i in range(3):
                sub = os.path.join(d, f"dir-{level}-{i}")
                os.makedirs(sub, exist_ok=True)
                nxt.append(sub)
                for j in range(files_per_dir):
                    with open(os.path.join(sub, f"f{j}.txt"), "w", encoding="utf-8") as f:
                        f.write("x")
                    count += 1
        current = nxt
    # hidden entries must be skipped by the scanner
    os.makedirs(os.path.join(root, ".hidden"), exist_ok=True)
    with open(os.path.join(root, ".hidden", "skip.txt"), "w", encoding="utf-8") as f:
        f.write("x")
    return count


def test_scanner_stop_before_completion_is_safe(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    _make_tree(root)

    scanner = DirectoryScanner(str(root), None)
    scanner.start_background_scan()
    # Cancel immediately — the walk may be mid-flight or not started.
    scanner.stop()
    # Repeated stop must not raise.
    scanner.stop()
    # The worker must finish and clear the scanning flag shortly.
    deadline = time.monotonic() + 3
    while scanner.is_scanning() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert scanner.is_scanning() is False


def test_scanner_completes_and_indexes_files(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    expected = _make_tree(root)

    scanner = DirectoryScanner(str(root), None)
    scanner.start_background_scan()
    deadline = time.monotonic() + 5
    while scanner.is_scanning() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert scanner.is_scanning() is False
    assert scanner.file_count() == expected
    # stop after completion is a no-op
    scanner.stop()
    assert scanner.file_count() == expected


def test_scanner_stop_without_scan_is_noop(tmp_path):
    scanner = DirectoryScanner(str(tmp_path / "lib"), None)
    scanner.stop()
    assert scanner.is_scanning() is False
