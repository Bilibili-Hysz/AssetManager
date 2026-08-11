"""Unit tests for AssetsManager.lan.tunnel low-severity fixes (T5/T6/T7).

Covers:
- T5: dev-mode cloudflared path is exactly two levels up (project root),
      not three (which landed one directory above the project root).
- T6: trycloudflare.com URL extraction is boundary-anchored so it cannot
      match a prefix/suffix of a longer hostname token.
- T7: TunnelManager(local_port=...) type validation and idempotent,
      never-raising stop().
"""
import os
import sys
import threading

import pytest

from AssetsManager.lan.tunnel import (
    TunnelManager,
    _dev_mode_cloudflared_path,
    _extract_public_url,
)


def _exe_name() -> str:
    return "cloudflared-windows-amd64.exe" if sys.platform == "win32" else "cloudflared"


# ---------------------------------------------------------------------------
# T7: local_port type validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_port", ["8080", True, 8080.0, None, [8080]])
def test_local_port_type_validation_rejects_non_int(bad_port):
    with pytest.raises(ValueError):
        TunnelManager(local_port=bad_port)


def test_local_port_accepts_int_and_default():
    assert TunnelManager()._port == 8080
    assert TunnelManager(local_port=8765)._port == 8765


# ---------------------------------------------------------------------------
# T7: stop() is idempotent and never raises
# ---------------------------------------------------------------------------


class _FakeProcess:
    """Minimal subprocess.Popen stand-in with scriptable failure modes."""

    def __init__(self, *, poll_result=0, terminate_error=None, kill_error=None):
        self._poll_result = poll_result
        self.terminate_error = terminate_error
        self.kill_error = kill_error
        self.kill_called = False
        self.returncode = 1
        self.pid = 4242

    def poll(self):
        if callable(self._poll_result):
            return self._poll_result()
        return self._poll_result

    def terminate(self):
        if self.terminate_error is not None:
            raise self.terminate_error
        self._poll_result = 0

    def kill(self):
        self.kill_called = True
        if self.kill_error is not None:
            raise self.kill_error
        self._poll_result = 0

    def wait(self, timeout):
        self._poll_result = 0
        return self._poll_result


def _bare_tunnel(process=None) -> TunnelManager:
    """Build a TunnelManager without running __init__/start."""
    tunnel = TunnelManager.__new__(TunnelManager)
    tunnel._process = process
    tunnel._public_url = "https://abc.trycloudflare.com"
    tunnel._ready = threading.Event()
    tunnel._ready.set()
    tunnel._state_lock = threading.Lock()
    tunnel._stop_event = threading.Event()
    return tunnel


def test_stop_with_no_process_is_a_noop():
    tunnel = _bare_tunnel(process=None)
    tunnel.stop()  # must not raise
    assert tunnel._process is None
    assert tunnel.public_url is None
    assert not tunnel.is_running
    assert not tunnel._ready.is_set()


def test_stop_already_exited_process_is_swallowed():
    # poll() reports the process already dead; terminate would raise if
    # called — the fast path must avoid touching the handle entirely.
    process = _FakeProcess(poll_result=0, terminate_error=OSError("no such process"))
    tunnel = _bare_tunnel(process=process)

    tunnel.stop()  # must not raise

    assert tunnel._process is None
    assert tunnel.public_url is None
    assert not tunnel.is_running


def test_stop_invalid_handle_where_poll_raises_is_swallowed():
    def _invalid_handle():
        raise OSError("invalid handle")

    process = _FakeProcess(poll_result=_invalid_handle)
    tunnel = _bare_tunnel(process=process)

    tunnel.stop()  # must not raise

    assert tunnel._process is None
    assert not tunnel.is_running


def test_stop_terminate_and_kill_failure_is_swallowed():
    # Both graceful and forced termination fail (already dead / closed
    # handle) — stop() must swallow instead of raising RuntimeError.
    process = _FakeProcess(
        poll_result=None,
        terminate_error=OSError("no such process"),
        kill_error=RuntimeError("handle closed"),
    )
    tunnel = _bare_tunnel(process=process)

    tunnel.stop()  # must not raise

    assert process.kill_called
    assert tunnel._process is None
    assert not tunnel.is_running


def test_stop_falls_back_to_kill_when_terminate_fails():
    process = _FakeProcess(
        poll_result=None,
        terminate_error=OSError("terminate denied"),
        kill_error=None,
    )
    tunnel = _bare_tunnel(process=process)

    tunnel.stop()  # must not raise

    assert process.kill_called
    assert tunnel._process is None
    assert not tunnel.is_running


def test_stop_twice_is_idempotent():
    process = _FakeProcess(poll_result=None)
    tunnel = _bare_tunnel(process=process)

    tunnel.stop()
    tunnel.stop()  # second call hits the no-process fast path

    assert tunnel._process is None
    assert not tunnel.is_running


# ---------------------------------------------------------------------------
# T6: anchored trycloudflare.com URL extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line,expected_url",
    [
        ("https://abc.trycloudflare.com", "https://abc.trycloudflare.com"),
        ("https://abc-def123.trycloudflare.com", "https://abc-def123.trycloudflare.com"),
        # URL embedded mid-line with surrounding log output
        (
            "2026-08-11T10:00:00Z INF Registered tunnel connection conn=abc url=https://abc.trycloudflare.com",
            "https://abc.trycloudflare.com",
        ),
        (
            "some prefix https://abc.trycloudflare.com some suffix",
            "https://abc.trycloudflare.com",
        ),
        # trailing content after the URL is allowed
        (
            "https://abc.trycloudflare.com 2026-08-11T10:00:00Z INF remaining",
            "https://abc.trycloudflare.com",
        ),
    ],
)
def test_extract_public_url_matches_expected_lines(line, expected_url):
    assert _extract_public_url(line) == expected_url


@pytest.mark.parametrize(
    "line",
    [
        # hostname continuation: must not match a prefix of a longer host
        "https://abc.trycloudflare.com.evil.io",
        "https://abc.trycloudflare.comx",
        # word-char continuation before the scheme
        "xhttps://abc.trycloudflare.com",
        # wrong scheme / no scheme
        "ftp://abc.trycloudflare.com",
        "abc.trycloudflare.com",
        # wrong domain
        "https://abc.example.com",
        # truncated / malformed URL
        "https://abc.trycloudflare",
        "https://.trycloudflare.com",
    ],
)
def test_extract_public_url_rejects_anchor_violations(line):
    assert _extract_public_url(line) is None


def test_extract_public_url_empty_or_none():
    assert _extract_public_url("") is None
    assert _extract_public_url("no url here") is None


# ---------------------------------------------------------------------------
# T5: dev-mode path points at the project root (two levels up)
# ---------------------------------------------------------------------------


def test_dev_mode_path_points_at_project_root():
    import AssetsManager.lan.tunnel as tunnel_mod

    src_dir = os.path.dirname(os.path.abspath(tunnel_mod.__file__))
    expected = os.path.normpath(os.path.join(src_dir, "..", "..", _exe_name()))
    actual = os.path.normpath(_dev_mode_cloudflared_path(_exe_name()))
    assert actual == expected
    # the candidate sits at the checkout root (two levels up), not above it
    assert os.path.dirname(actual) == os.path.normpath(
        os.path.join(src_dir, "..", "..")
    )


def test_find_cloudflared_returns_project_root_dev_candidate(monkeypatch):
    import AssetsManager.lan.tunnel as tunnel_mod

    src_dir = os.path.dirname(os.path.abspath(tunnel_mod.__file__))
    dev_candidate = os.path.normpath(os.path.join(src_dir, "..", "..", _exe_name()))

    # Only the dev candidate "exists"; bundle/PATH/cache lookups must not win.
    monkeypatch.setattr(
        tunnel_mod.os.path,
        "isfile",
        lambda path: os.path.normpath(path) == dev_candidate,
    )
    monkeypatch.setattr(tunnel_mod.shutil, "which", lambda _name: None)

    found = tunnel_mod._find_cloudflared()
    assert found is not None
    assert os.path.normpath(found) == dev_candidate
