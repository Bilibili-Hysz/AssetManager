"""Tunnel manager — expose local server to the internet via Cloudflare Tunnel.

Usage:
    tunnel = TunnelManager(local_port=8080)
    public_url = tunnel.start(timeout=30)
    print(public_url)  # https://xxx.trycloudflare.com
    tunnel.stop()

Requires: cloudflared CLI — auto-downloaded on first use if not found.
Manual install: winget install cloudflare.cloudflared

Supply-chain policy: the auto-download path pins an exact release tag and
verifies the binary against that release's own SHA-256 checksum asset before
the binary is ever executed; a missing or mismatching checksum fails closed
(the download is discarded and the tunnel stays unavailable).  Pre-existing
binaries (bundle, dev checkout, PATH) are trusted out-of-band by whoever
installed them — they are still smoke-tested via ``--version`` before use.
"""
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

_log = logging.getLogger(__name__)

# 08-P0 supply-chain gate: never resolve "latest" — a floating tag lets any
# future release silently replace the executed binary.  Bump the pin (and
# re-verify the tunnel once) deliberately, per release.
_CLOUDFLARED_VERSION = "2024.8.3"
_CLOUDFLARED_ASSET = "cloudflared-windows-amd64.exe"
_CLOUDFLARED_RELEASE_BASE = (
    "https://github.com/cloudflare/cloudflared/releases/download/"
    f"{_CLOUDFLARED_VERSION}"
)
_CLOUDFLARED_URL = f"{_CLOUDFLARED_RELEASE_BASE}/{_CLOUDFLARED_ASSET}"
_CLOUDFLARED_SHA256_URL = f"{_CLOUDFLARED_URL}.sha256"
_DOWNLOAD_TIMEOUT = 60.0
_download_lock = threading.Lock()


def _download_cloudflared(dest_dir: str) -> str | None:
    """Download cloudflared binary to dest_dir. Returns path or None on failure."""
    exe_name = "cloudflared-windows-amd64.exe" if sys.platform == "win32" else "cloudflared"
    dest = os.path.join(dest_dir, exe_name)
    fd, temporary = tempfile.mkstemp(dir=dest_dir, prefix=f".{exe_name}_", suffix=".tmp")
    os.close(fd)
    try:
        _log.info("Downloading cloudflared %s to %s ...", _CLOUDFLARED_VERSION, dest)
        with urllib.request.urlopen(_CLOUDFLARED_URL, timeout=_DOWNLOAD_TIMEOUT) as response:
            with open(temporary, "wb") as stream:
                shutil.copyfileobj(response, stream)
        expected = _fetch_expected_sha256()
        if expected is None:
            # Fail closed: without the release's checksum there is no
            # integrity basis for executing the download.
            _log.warning(
                "cloudflared checksum asset unavailable; discarding download (fail-closed)"
            )
            return None
        if _sha256_of(temporary) != expected:
            _log.warning("Downloaded cloudflared failed SHA-256 verification; discarding")
            return None
        if not _validate_cloudflared_binary(temporary):
            _log.warning("Downloaded cloudflared failed validation; discarding %s", temporary)
            return None
        os.replace(temporary, dest)
        _log.info("cloudflared downloaded successfully (SHA-256 verified)")
        return dest
    except Exception as e:
        _log.warning("Failed to download cloudflared: %s", e)
        return None
    finally:
        if os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _fetch_expected_sha256() -> str | None:
    """Fetch the pinned release's SHA-256 digest for the binary asset.

    The release ships a ``.sha256`` sidecar containing the hex digest (a few
    tools emit ``<digest>  <filename>``; both shapes are accepted).  Returns
    ``None`` when the asset is unreachable or malformed.
    """
    try:
        with urllib.request.urlopen(_CLOUDFLARED_SHA256_URL, timeout=_DOWNLOAD_TIMEOUT) as response:
            payload = response.read(1024).decode("ascii", errors="replace").strip()
    except Exception as e:
        _log.warning("Could not fetch cloudflared checksum asset: %s", e)
        return None
    parts = payload.split()
    digest = parts[0].lower() if parts else ""
    if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
        return digest
    _log.warning("cloudflared checksum asset has an unexpected shape; refusing it")
    return None


def _sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_cloudflared_binary(path: str) -> bool:
    """Smoke-test a binary: non-empty and executable via --version."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return False
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            timeout=_DOWNLOAD_TIMEOUT,
        )
        return result.returncode == 0
    except Exception:
        return False


def _find_cloudflared() -> str | None:
    """Find the cloudflared binary — bundled, downloaded, or system-installed."""
    exe_name = "cloudflared-windows-amd64.exe" if sys.platform == "win32" else "cloudflared"

    # 1. PyInstaller bundle — sys._MEIPASS contains extracted files
    if getattr(sys, 'frozen', False):
        base = getattr(sys, "_MEIPASS", "")
        path = os.path.join(base, exe_name)
        if os.path.isfile(path):
            return path
        # Also check _internal subfolder (onedir mode)
        internal = os.path.join(os.path.dirname(sys.executable), '_internal', exe_name)
        if os.path.isfile(internal):
            return internal

    # 2. Project root (dev mode) — the source checkout keeps a prebuilt
    #    cloudflared binary at the project root, which is two directory
    #    levels above this file (AssetsManager/lan/tunnel.py).  Climbing
    #    three levels used to land one directory above the project root.
    path = _dev_mode_cloudflared_path(exe_name)
    if os.path.isfile(path):
        return path

    # 3. Downloaded cache (RuntimeData/Shared/)
    try:
        from AssetsManager.core.path_resolver import shared_dir
        cache_dir = str(shared_dir())
        cached = os.path.join(cache_dir, exe_name)
        if os.path.isfile(cached):
            return cached
    except Exception:
        pass

    # 4. System PATH
    found = shutil.which("cloudflared")
    if found:
        return found
    return shutil.which(exe_name)


def _dev_mode_cloudflared_path(exe_name: str) -> str:
    """Candidate path for a cloudflared binary kept in the source checkout.

    The prebuilt binary lives at the project root, i.e. two directory
    levels above this file (AssetsManager/lan/ -> AssetsManager/ -> root).
    """
    src_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(src_dir, "..", "..", exe_name)


def is_available() -> bool:
    """Check if cloudflared CLI is available (without downloading)."""
    return _find_cloudflared() is not None


def ensure_available() -> str | None:
    """Ensure cloudflared is available. Downloads if not found. Returns path or None."""
    found = _find_cloudflared()
    if found:
        return found
    with _download_lock:
        found = _find_cloudflared()
        if found:
            return found
        try:
            from AssetsManager.core.path_resolver import shared_dir
            return _download_cloudflared(str(shared_dir()))
        except Exception:
            return None


# Boundary-anchored URL pattern: the match must not be a prefix or suffix
# of a longer hostname token (e.g. "https://x.trycloudflare.com.evil.io"
# must not match), while still allowing the URL to appear anywhere inside a
# log line — which is how cloudflared emits it.
_CLOUDFLARED_URL_RE = re.compile(
    r"(?<![\w.-])(https://[a-z0-9-]+\.trycloudflare\.com)(?![\w.-])"
)


def _extract_public_url(line: str) -> str | None:
    """Return the trycloudflare.com public URL found in *line*, or None."""
    match = _CLOUDFLARED_URL_RE.search(line)
    return match.group(1) if match else None


class TunnelManager:
    """Manages a Cloudflare Tunnel subprocess."""

    def __init__(self, local_port: int = 8080, on_exit=None):
        if isinstance(local_port, bool) or not isinstance(local_port, int):
            raise ValueError(
                f"local_port must be an int, got {type(local_port).__name__}"
            )
        self._port = local_port
        self._process: subprocess.Popen | None = None
        self._public_url: str | None = None
        self._ready = threading.Event()
        self._state_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._on_exit = on_exit

    def start(self, timeout: int = 30) -> str | None:
        """Start tunnel. Returns public URL or None on failure."""
        with self._start_lock:
            return self._start_locked(timeout)

    def _start_locked(self, timeout: int = 30) -> str | None:
        with self._state_lock:
            process = self._process
        if process is not None and process.poll() is None:
            if not self._ready.is_set():
                if not self._ready.wait(timeout=timeout):
                    _log.warning(
                        "Cloudflare tunnel already running but not ready after %ds; stopping", timeout
                    )
                    self.stop()
                    return None
            return self._public_url

        cf = _find_cloudflared()
        if not cf:
            _log.error("cloudflared not found. Install: winget install cloudflare.cloudflared")
            return None
        if not _validate_cloudflared_binary(cf):
            _log.error(
                "cloudflared binary at %s failed validation; reinstall it "
                "(winget install cloudflare.cloudflared)", cf
            )
            return None

        try:
            with self._state_lock:
                self._process = subprocess.Popen(
                    [cf, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{self._port}"],
                    stderr=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    text=True,
                    # cloudflared writes UTF-8; text mode would otherwise decode
                    # through the locale codepage (GBK on a zh-CN host), where a
                    # non-ASCII log line raises inside the reader thread below --
                    # whose bare except would swallow it and leave the tunnel
                    # permanently un-ready with no public URL and no error.
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
                process = self._process
                self._public_url = None
                self._ready.clear()
                self._stop_event.clear()
                threading.Thread(
                    target=self._monitor_process, args=(process,), daemon=True,
                ).start()
        except FileNotFoundError:
            _log.error("cloudflared not found in PATH")
            return None
        except OSError as e:
            _log.error("Failed to start cloudflared: %s", e)
            return None

        # Parse stderr in a thread to find the public URL
        def _reader(process):
            if process is None or process.stderr is None:
                return
            try:
                for line in process.stderr:
                    public_url = _extract_public_url(line.strip())
                    if public_url:
                        with self._state_lock:
                            if self._process is not process:
                                return
                            self._public_url = public_url
                        self._ready.set()
                        _log.info("Cloudflare tunnel ready: %s", self._public_url)
            except Exception:
                # Best-effort reader: a dead pipe must not kill the thread
                # silently.  Without this log the only symptom is the generic
                # "timed out" warning below, which cannot distinguish "no URL
                # yet" from "the reader stopped reading".
                _log.warning(
                    "Cloudflare tunnel stderr reader stopped early", exc_info=True
                )

        t = threading.Thread(target=_reader, args=(process,), daemon=True)
        t.start()

        # Wait for URL with timeout
        if self._ready.wait(timeout=timeout):
            return self._public_url

        _log.warning("Cloudflare tunnel timed out after %ds", timeout)
        self.stop()
        return None

    def _monitor_process(self, process):
        while True:
            with self._state_lock:
                if self._process is not process:
                    return
            if process.poll() is not None:
                break
            time.sleep(1.0)
        with self._state_lock:
            if self._process is not process:
                return
            self._process = None
            self._public_url = None
            self._ready.clear()
        if self._stop_event.is_set():
            return
        _log.warning("cloudflared exited unexpectedly (code=%s)", process.returncode)
        if self._on_exit is not None:
            try:
                self._on_exit(process.returncode)
            except Exception:
                _log.exception("cloudflared exit callback failed")

    def stop(self):
        """Stop the tunnel subprocess. Idempotent cleanup: never raises, even
        if the process already exited or its handle became invalid — those
        cases are treated as already-stopped."""
        with self._state_lock:
            process = self._process
            if process is None:
                self._public_url = None
                self._ready.clear()
                return

        self._stop_event.set()
        try:
            if process.poll() is not None:
                _log.debug(
                    "cloudflared already exited (code=%s); nothing to stop",
                    process.returncode,
                )
            else:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception as terminate_error:
                    try:
                        process.kill()
                        process.wait(timeout=5)
                    except Exception as kill_error:
                        # Process already gone or handle invalid — swallow so
                        # stop() stays an idempotent cleanup.
                        _log.debug(
                            "cloudflared (pid=%s) could not be stopped: %s",
                            getattr(process, "pid", None),
                            kill_error,
                        )
                    else:
                        _log.warning(
                            "cloudflared required forced termination after graceful stop failed: %s",
                            terminate_error,
                        )
        except (RuntimeError, OSError):
            # Dead process / invalid handle — treat as already stopped.
            _log.debug(
                "cloudflared stop raised despite cleanup; ignoring", exc_info=True
            )

        with self._state_lock:
            # Only clear state when this stop call is the current owner; a
            # concurrently started tunnel must not be torn down by the stale
            # handle of a previous stop.
            if self._process is process:
                self._process = None
                self._public_url = None
                self._ready.clear()

    @property
    def public_url(self) -> str | None:
        return self._public_url

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None
