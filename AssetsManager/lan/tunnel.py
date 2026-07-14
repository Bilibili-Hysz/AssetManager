"""Tunnel manager — expose local server to the internet via Cloudflare Tunnel.

Usage:
    tunnel = TunnelManager(local_port=8080)
    public_url = tunnel.start(timeout=30)
    print(public_url)  # https://xxx.trycloudflare.com
    tunnel.stop()

Requires: cloudflared CLI — auto-downloaded on first use if not found.
Manual install: winget install cloudflare.cloudflared
"""
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.request

_log = logging.getLogger(__name__)

_CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"


def _download_cloudflared(dest_dir: str) -> str | None:
    """Download cloudflared binary to dest_dir. Returns path or None on failure."""
    exe_name = "cloudflared-windows-amd64.exe" if sys.platform == "win32" else "cloudflared"
    dest = os.path.join(dest_dir, exe_name)
    try:
        _log.info("Downloading cloudflared to %s ...", dest)
        urllib.request.urlretrieve(_CLOUDFLARED_URL, dest)
        _log.info("cloudflared downloaded successfully")
        return dest
    except Exception as e:
        _log.warning("Failed to download cloudflared: %s", e)
        return None


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

    # 2. Same directory as this source file (dev mode)
    src_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(src_dir, "..", "..", "..", exe_name)
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


def is_available() -> bool:
    """Check if cloudflared CLI is available (without downloading)."""
    return _find_cloudflared() is not None


def ensure_available() -> str | None:
    """Ensure cloudflared is available. Downloads if not found. Returns path or None."""
    found = _find_cloudflared()
    if found:
        return found
    try:
        from AssetsManager.core.path_resolver import shared_dir
        return _download_cloudflared(str(shared_dir()))
    except Exception:
        return None


class TunnelManager:
    """Manages a Cloudflare Tunnel subprocess."""

    def __init__(self, local_port: int = 8080):
        self._port = local_port
        self._process: subprocess.Popen | None = None
        self._public_url: str | None = None
        self._ready = threading.Event()

    def start(self, timeout: int = 30) -> str | None:
        """Start tunnel. Returns public URL or None on failure."""
        if self.is_running:
            return self._public_url

        cf = _find_cloudflared()
        if not cf:
            _log.error("cloudflared not found. Install: winget install cloudflare.cloudflared")
            return None

        try:
            self._process = subprocess.Popen(
                [cf, "tunnel", "--url", f"http://127.0.0.1:{self._port}"],
                stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            _log.error("cloudflared not found in PATH")
            return None
        except OSError as e:
            _log.error("Failed to start cloudflared: %s", e)
            return None

        # Parse stderr in a thread to find the public URL
        def _reader():
            process = self._process
            if process is None or process.stderr is None:
                return
            try:
                for line in process.stderr:
                    line = line.strip()
                    match = re.search(r"(https://[a-z0-9-]+\.trycloudflare\.com)", line)
                    if match:
                        self._public_url = match.group(1)
                        self._ready.set()
                        _log.info("Cloudflare tunnel ready: %s", self._public_url)
            except Exception:
                pass

        t = threading.Thread(target=_reader, daemon=True)
        t.start()

        # Wait for URL with timeout
        if self._ready.wait(timeout=timeout):
            return self._public_url

        _log.warning("Cloudflare tunnel timed out after %ds", timeout)
        self.stop()
        return None

    def stop(self):
        """Stop the tunnel subprocess."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        self._public_url = None
        self._ready.clear()

    @property
    def public_url(self) -> str | None:
        return self._public_url

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None
