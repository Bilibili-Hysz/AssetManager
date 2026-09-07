"""W6: frozen-package functional acceptance — hash-bound, GUI-assisted.

Closes the W6 downgrade (weekly-recheck 2026-09-08 R5): a packaged exe must
prove more than "8s ALIVE".  This probe seeds an isolated runtime domain
(synthetic library + sharing auto-start settings), launches the real frozen
binary, and — after the operator double-clicks the seeded library card on the
StartupWindow — verifies IN-PACKAGE:

  1. library opens (MainWindow up, StartupWindow gone)      [operator + probe]
  2. LAN auto-start binds 127.0.0.1 and /api/info answers   [aiohttp lazy import,
     session binding — the PF-2 first-latency dependency]
  3. password login issues the lan_token cookie             [auth contract]
  4. /fonts serves the SPA font byte-identical to webui/dist [font asset]
  5. /api/thumbnails renders a real PNG; batch works         [thumbnail pipeline]
  6. a file added mid-run appears in /api/files              [live change]
   7. registered Ctrl+Q exit terminates cleanly; exit code recorded [PF-6]
   8. geometry/maximized state persists through a relaunch    [restore contract]

``--observe-hide`` is a separate diagnostic: Win32 visibility after a
hide-to-tray WM_CLOSE does not prove Qt-widget or tray restoration, so that
mode always returns ``INVALID`` and never supplies a W6 acceptance result.

Every failure prints ``INVALID`` and exits non-zero.

Usage:
  python scripts/perf/w6_package_functional.py --exe dist/AssetManager.exe \
      --mode onefile [--maximized]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

if os.name == "nt":
    import ctypes as _ctypes
    from ctypes import wintypes as _wintypes

    _ENUM_WINDOWS_PROC = _ctypes.WINFUNCTYPE(
        _ctypes.c_bool, _wintypes.HWND, _wintypes.LPARAM,
    )
else:  # pragma: no cover - the probe itself reports INVALID off Windows
    _ENUM_WINDOWS_PROC = None

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
ROOT = Path(__file__).resolve().parents[2]

PASSWORD = "W6-Functional-Password!"
SHARE_NAME = "W6-Functional"
LIB_FILES = 12
INFO_TIMEOUT_S = 180.0        # includes onefile extraction + operator GUI step
CLOSE_TIMEOUT_S = 30.0


def _invalid(message: str) -> RuntimeError:
    """Mark an observation gap as an acceptance failure, never as a pass."""
    return RuntimeError(message)


def _win32():
    """Return the small, dependency-free Win32 surface used by this probe.

    This deliberately avoids coordinate clicks and image matching.  A frozen
    package can spawn a child process (onefile), so all window observations are
    tied to the launched process tree rather than to a guessed title.
    """
    if os.name != "nt":
        raise _invalid("W6 functional GUI acceptance requires Windows")
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.argtypes = ()
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    user32 = ctypes.windll.user32
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsZoomed.argtypes = (wintypes.HWND,)
    user32.IsZoomed.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.PostMessageW.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = (wintypes.HWND,)
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.SetFocus.argtypes = (wintypes.HWND,)
    user32.SetFocus.restype = wintypes.HWND
    user32.GetForegroundWindow.argtypes = ()
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.keybd_event.argtypes = (ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_size_t)
    user32.keybd_event.restype = None
    if _ENUM_WINDOWS_PROC is None:
        raise _invalid("Win32 EnumWindows callback is unavailable")
    user32.EnumWindows.argtypes = (_ENUM_WINDOWS_PROC, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL

    return ctypes, wintypes, PROCESSENTRY32W


def _descendant_pids(root_pid: int) -> set[int]:
    """Read the current Windows process tree rooted at ``root_pid``."""
    ctypes, wintypes, entry_type = _win32()
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == wintypes.HANDLE(-1).value:
        raise _invalid("CreateToolhelp32Snapshot failed")
    try:
        entry = entry_type()
        entry.dwSize = ctypes.sizeof(entry)
        parents: dict[int, list[int]] = {}
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            raise _invalid("Process32FirstW failed")
        while True:
            parents.setdefault(int(entry.th32ParentProcessID), []).append(int(entry.th32ProcessID))
            entry.dwSize = ctypes.sizeof(entry)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
        result = {root_pid}
        pending = [root_pid]
        while pending:
            parent = pending.pop()
            for pid in parents.get(parent, []):
                if pid not in result:
                    result.add(pid)
                    pending.append(pid)
        return result
    finally:
        kernel32.CloseHandle(snapshot)


def _find_window(pids: set[int]) -> dict[str, Any] | None:
    """Find the sole visible, titled top-level app window for ``pids``.

    We run this only after the LAN server reports ready, which means the
    operator has already opened the synthetic library and the StartupWindow is
    gone.  Multiple candidates are an observation ambiguity, never a reason to
    select the first Qt helper/dialog window.
    """
    ctypes, wintypes, _entry_type = _win32()
    user32 = ctypes.windll.user32
    found: list[dict[str, Any]] = []
    assert _ENUM_WINDOWS_PROC is not None

    @_ENUM_WINDOWS_PROC
    def collect(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) not in pids:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        if title.value:
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_name, len(class_name))
            found.append({
                "hwnd": int(hwnd), "pid": int(pid.value), "title": title.value,
                "class": class_name.value,
                "owner": int(user32.GetWindow(hwnd, 4) or 0),  # GW_OWNER
                "visible": bool(user32.IsWindowVisible(hwnd)),
                "maximized": bool(user32.IsZoomed(hwnd)),
            })
        return True

    if not user32.EnumWindows(collect, 0):
        raise _invalid("EnumWindows failed")
    # A QMainWindow is an unowned top-level window; exclude owned Qt dialogs
    # and hidden helper windows before deciding whether the result is unique.
    visible = [item for item in found if item["visible"] and item["owner"] == 0]
    if not visible:
        return None
    if len(visible) != 1:
        raise _invalid(f"ambiguous visible package windows: {visible}")
    return visible[0]


def _wait_for_window(root_pid: int, timeout_s: float) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        window = _find_window(_descendant_pids(root_pid))
        if window is not None:
            return window
        time.sleep(0.25)
    raise _invalid(f"no top-level package window found for PID tree {root_pid}")


def _is_window_visible(hwnd: int) -> bool:
    ctypes, _wintypes, _entry_type = _win32()
    return bool(ctypes.windll.user32.IsWindowVisible(hwnd))


def _post_close(hwnd: int) -> None:
    ctypes, _wintypes, _entry_type = _win32()
    if not ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0):  # WM_CLOSE
        raise _invalid("PostMessageW(WM_CLOSE) failed")


def _restore_window(hwnd: int) -> None:
    """Restore the hidden real window without assuming taskbar/tray coordinates."""
    ctypes, _wintypes, _entry_type = _win32()
    user32 = ctypes.windll.user32
    # SW_SHOW preserves the existing maximized state; SW_RESTORE would alter
    # the very geometry state this acceptance test is meant to observe.
    user32.ShowWindow(hwnd, 5)  # SW_SHOW
    user32.SetForegroundWindow(hwnd)


def _focus_window(hwnd: int, *, purpose: str, timeout_s: float = 5.0) -> None:
    """Bring one known test window to the foreground, or fail without input.

    Windows legitimately rejects a plain ``SetForegroundWindow`` when the
    console and GUI processes have different input queues.  Temporarily
    attaching only our own thread, the target window thread and the current
    foreground thread is a bounded focus request; the caller still sends no
    key until ``GetForegroundWindow`` proves the target owns foreground.
    """
    ctypes, wintypes, _entry_type = _win32()
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    deadline = time.perf_counter() + timeout_s
    target_pid = wintypes.DWORD()
    target_thread = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid)))
    if not target_thread:
        raise _invalid(f"could not resolve target thread for {purpose}")
    while time.perf_counter() < deadline:
        user32.ShowWindow(hwnd, 5)  # SW_SHOW preserves any maximized state.
        foreground = int(user32.GetForegroundWindow() or 0)
        if foreground == hwnd:
            return
        foreground_pid = wintypes.DWORD()
        foreground_thread = (
            int(user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid)))
            if foreground else 0
        )
        current_thread = int(kernel32.GetCurrentThreadId())
        attached_target = False
        attached_foreground = False
        try:
            if target_thread != current_thread:
                attached_target = bool(user32.AttachThreadInput(current_thread, target_thread, True))
            if foreground_thread and foreground_thread != current_thread:
                attached_foreground = bool(
                    user32.AttachThreadInput(current_thread, foreground_thread, True))
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            if attached_foreground:
                user32.AttachThreadInput(current_thread, foreground_thread, False)
            if attached_target:
                user32.AttachThreadInput(current_thread, target_thread, False)
        if int(user32.GetForegroundWindow() or 0) == hwnd:
            return
        time.sleep(0.1)
    raise _invalid(f"could not focus {purpose} within {timeout_s:.1f}s; no key was sent")


def _send_ctrl_q(hwnd: int) -> None:
    """Invoke the application's registered Ctrl+Q exit action via keyboard input.

    Foreground is re-verified immediately before the keystrokes and the
    focus/verify cycle is retried once: on a busy desktop another window can
    legally steal foreground between verification and send, and keys that go
    to the wrong window must never be scored as a product exit failure
    (N1: the historical onefile-maximized exit timeouts).
    """
    ctypes, _wintypes, _entry_type = _win32()
    user32 = ctypes.windll.user32
    last_error = "foreground never settled on the package window"
    for attempt in (1, 2):
        _focus_window(hwnd, purpose="package window for Ctrl+Q")
        # Foreground activation is asynchronous from the target Qt event loop.
        # Do not queue the shortcut in the same scheduling turn that activated it.
        time.sleep(0.15)
        if int(user32.GetForegroundWindow() or 0) == hwnd:
            break
        last_error = f"attempt {attempt}: package window lost foreground before Ctrl+Q"
    else:
        raise _invalid(f"{last_error}; shortcut was not sent")
    # keybd_event sends the registered application shortcut; no menu geometry
    # or untranslated action text is assumed.
    user32.keybd_event(0x11, 0, 0, 0)       # VK_CONTROL down
    time.sleep(0.03)
    user32.keybd_event(ord("Q"), 0, 0, 0)  # Q down
    time.sleep(0.03)
    user32.keybd_event(ord("Q"), 0, 2, 0)  # KEYEVENTF_KEYUP
    user32.keybd_event(0x11, 0, 2, 0)


def _send_enter(hwnd: int) -> None:
    """Activate the single seeded StartupWindow library card once via Enter."""
    ctypes, _wintypes, _entry_type = _win32()
    user32 = ctypes.windll.user32
    _focus_window(hwnd, purpose="StartupWindow for Enter")
    user32.keybd_event(0x0D, 0, 0, 0)  # VK_RETURN down
    user32.keybd_event(0x0D, 0, 2, 0)  # KEYEVENTF_KEYUP


def _wait_for_exit(proc: subprocess.Popen[bytes], timeout_s: float) -> int:
    try:
        return proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise _invalid(f"normal Ctrl+Q exit did not complete within {timeout_s:.1f}s") from exc


def _exit_timeout_observation(hwnd: int, base_url: str, proc: subprocess.Popen[bytes]) -> dict[str, Any]:
    """Capture state after a normal-exit timeout without changing the app."""
    ctypes, _wintypes, _entry_type = _win32()
    user32 = ctypes.windll.user32
    observation: dict[str, Any] = {
        "process_poll": proc.poll(),
        "window_visible": bool(user32.IsWindowVisible(hwnd)),
        "window_maximized": bool(user32.IsZoomed(hwnd)),
        "foreground_is_target": int(user32.GetForegroundWindow() or 0) == hwnd,
    }
    try:
        status, _headers, _body = _http("GET", f"{base_url}/api/info", timeout=5)
        observation["api_info_status"] = status
    except Exception as exc:
        observation["api_info_error"] = f"{type(exc).__name__}: {exc}"
    return observation


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _build_library(root: Path) -> Path:
    from PIL import Image

    lib = root / "library"
    lib.mkdir(parents=True)
    for i in range(LIB_FILES):
        img = Image.new("RGB", (512, 512), ((i * 23) % 256, (i * 57) % 256, (i * 91) % 256))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        (lib / f"pkg_{i:03d}.png").write_bytes(buf.getvalue())
    return lib


def _seed_runtime(runtime_root: Path, lib: Path, port: int, maximized: bool) -> Path:
    shared = runtime_root / "Shared"
    shared.mkdir(parents=True, exist_ok=True)
    settings = {
        "_cfg_version": 2,
        "_legacy_migrated": True,
        "recent_libraries": [str(lib)],
        "theme": "Navy",
        "window_maximized": bool(maximized),
        "lan_auto_start": True,
        "lan_auth_mode": "password",
        "lan_password": PASSWORD,
        "lan_port": port,
        "lan_bind": "127.0.0.1",
        "lan_share_name": SHARE_NAME,
        # ack version 1 + loopback bind => preflight returns local_active with
        # no confirmation dialog (confirmation_failure_reason contract).
        "lan_share_safety_ack_version": 1,
        "lan_trusted_network_confirmed": False,
    }
    path = shared / "settings.json"
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _http(method: str, url: str, *, data: dict | None = None,
          cookie: str | None = None, timeout: float = 20.0):
    request = urllib.request.Request(url, method=method)
    if cookie:
        request.add_header("Cookie", cookie)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, data=body, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True)
    parser.add_argument("--mode", required=True, choices=("onefile", "onedir"))
    parser.add_argument("--maximized", action="store_true")
    parser.add_argument(
        "--observe-hide", action="store_true",
        help="diagnose WM_CLOSE native visibility only; always INVALID, never acceptance",
    )
    parser.add_argument(
        "--auto-open", action="store_true",
        help="focus the one seeded StartupWindow card and press Enter once",
    )
    args = parser.parse_args()

    exe = Path(args.exe).resolve()
    if not exe.is_file():
        print(f"INVALID: exe not found: {exe}")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="w6-func-"))
    runtime_root = tmp / "runtime"
    lib = _build_library(tmp)
    port = _free_port()
    settings_path = _seed_runtime(runtime_root, lib, port, args.maximized)

    print(f"bundle: {args.mode} ({exe})")
    print(f"runtime: {runtime_root}")
    print(f"library: {lib} ({LIB_FILES} files)")
    print(f"lan: http://127.0.0.1:{port} (password auth)")
    print(f"settings seeded: {settings_path}")
    print("OPERATOR: double-click the seeded library card in the StartupWindow"
          if not args.auto_open else "AUTO-OPEN: will focus the sole seeded StartupWindow and press Enter once")

    env = dict(os.environ)
    env["AM_RUNTIME_ROOT"] = str(runtime_root)
    proc = subprocess.Popen([str(exe)], env=env, cwd=str(ROOT))
    print(f"launched pid={proc.pid}")

    failures: list[str] = []
    restarted: subprocess.Popen[bytes] | None = None
    evidence: dict = {"mode": args.mode, "exe_sha256": None, "pid": proc.pid,
                       "port": port, "maximized": args.maximized, "checks": {}}

    # ── hash binding ────────────────────────────────────────────────
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    evidence["exe_sha256"] = digest
    print(f"exe sha256: {digest}")

    base = f"http://127.0.0.1:{port}"

    if args.auto_open:
        try:
            _send_enter(_wait_for_window(proc.pid, 15.0)["hwnd"])
        except RuntimeError as exc:
            failures.append(str(exc))

    # ── 1. /api/info healthy (library open + LAN auto-start) ────────
    deadline = time.perf_counter() + INFO_TIMEOUT_S
    info_status = None
    info_body = b""
    while time.perf_counter() < deadline:
        if proc.poll() is not None:
            failures.append(f"process exited early with code {proc.returncode}")
            break
        try:
            info_status, _h, info_body = _http("GET", f"{base}/api/info", timeout=5)
            if info_status == 200:
                break
        except Exception:
            pass
        time.sleep(1.0)
    if info_status != 200:
        failures.append(f"/api/info never returned 200 (last {info_status}) within {INFO_TIMEOUT_S}s")
    else:
        info = json.loads(info_body)
        evidence["checks"]["info"] = {
            "share_name": info.get("share_name"),
            "auth_mode": info.get("auth_mode"),
            "thumbnail_cache_namespace": bool(info.get("thumbnail_cache_namespace")),
        }
        print(f"info OK: share_name={info.get('share_name')!r} auth={info.get('auth_mode')!r}")
        if info.get("share_name") != SHARE_NAME:
            failures.append(f"share_name mismatch: {info.get('share_name')!r}")

    # LAN is ready only after the synthetic library has opened.  Therefore the
    # sole visible package window is the MainWindow, not StartupWindow, and its
    # Win32 maximized state is meaningful acceptance evidence.
    if not failures:
        try:
            window = _wait_for_window(proc.pid, 15.0)
            evidence["window_initial"] = window
            if window["maximized"] != args.maximized:
                failures.append(
                    f"window maximized={window['maximized']}, expected {args.maximized}")
            else:
                print(f"window OK: hwnd={window['hwnd']} pid={window['pid']} "
                      f"class={window['class']!r} maximized={window['maximized']}")
        except RuntimeError as exc:
            failures.append(str(exc))

    cookie = ""
    if not failures:
        # ── 2. login ────────────────────────────────────────────────
        status, headers, _body = _http("POST", f"{base}/api/auth/login",
                                       data={"password": PASSWORD})
        set_cookie = headers.get("Set-Cookie", "")
        if status != 200 or "lan_token=" not in set_cookie:
            failures.append(f"login failed: HTTP {status}, set-cookie={set_cookie[:60]!r}")
        else:
            cookie = set_cookie.split(";", 1)[0]
            evidence["checks"]["login"] = "ok"
            print("login OK (lan_token cookie issued)")

    if not failures:
        # ── 3. font asset byte-identical to webui/dist ──────────────
        font_name = "inter-var-latin.woff2"
        status, _h, font_body = _http("GET", f"{base}/fonts/{font_name}")
        src = ROOT / "webui" / "dist" / "fonts" / font_name
        if status != 200:
            failures.append(f"font fetch HTTP {status}")
        elif not src.is_file():
            failures.append(f"webui/dist font missing for comparison: {src}")
        elif font_body != src.read_bytes():
            failures.append(
                f"font bytes differ from webui/dist ({len(font_body)} vs {src.stat().st_size})")
        else:
            evidence["checks"]["font"] = f"{len(font_body)} bytes, byte-identical"
            print(f"font OK ({len(font_body)} bytes, byte-identical to webui/dist)")

    if not failures:
        # ── 4. thumbnail single + batch ─────────────────────────────
        # The single-thumbnail route content-negotiates: with a generic
        # Accept header it serves WebP (RIFF container).  The contract is
        # "a real decodable image", not a specific container.
        from PIL import Image
        status, _h, thumb = _http("GET", f"{base}/api/thumbnails/pkg_000.png?size=256",
                                  cookie=cookie)
        fmt = None
        if status == 200:
            try:
                img = Image.open(io.BytesIO(thumb))
                img.load()
                fmt = img.format
            except Exception:
                fmt = None
        if fmt not in {"PNG", "WEBP", "JPEG"} or max(img.size) > 256:
            failures.append(
                f"single thumbnail failed: HTTP {status}, format={fmt!r}, size={getattr(img, 'size', None)}")
        else:
            evidence["checks"]["thumbnail_single"] = f"{len(thumb)} bytes {fmt}"
            print(f"thumbnail single OK ({len(thumb)} bytes {fmt})")
        status, _h, batch_body = _http(
            "POST", f"{base}/api/thumbnails/batch", cookie=cookie,
            data={"paths": [f"pkg_{i:03d}.png" for i in range(LIB_FILES)], "size": 256})
        delivered = len(json.loads(batch_body).get("thumbnails", {})) if status == 200 else 0
        if status != 200 or delivered != LIB_FILES:
            failures.append(
                f"thumbnail batch: HTTP {status}, delivered {delivered}/{LIB_FILES}")
        else:
            evidence["checks"]["thumbnail_batch"] = f"{delivered}/{LIB_FILES}"
            print(f"thumbnail batch OK ({delivered}/{LIB_FILES})")

    if not failures:
        # ── 4b. notes + rating (metadata write path, round-3 F1 end-to-end) ──
        status, _h, _b = _http("PUT", f"{base}/api/notes/pkg_000.png",
                               cookie=cookie, data={"notes": "W6 functional note"})
        status_r, _h, _b = _http("PUT", f"{base}/api/rating/pkg_000.png",
                                 cookie=cookie, data={"rating": 4})
        status_m, _h, meta_body = _http("GET", f"{base}/api/meta/pkg_000.png", cookie=cookie)
        meta = json.loads(meta_body) if status_m == 200 else {}
        if (status, status_r, status_m) != (200, 200, 200):
            failures.append(
                f"notes/rating save failed: notes HTTP {status}, rating HTTP {status_r}, "
                f"meta HTTP {status_m}")
        elif meta.get("notes") != "W6 functional note" or meta.get("rating") != 4:
            failures.append(
                f"notes/rating round-trip mismatch: notes={meta.get('notes')!r} "
                f"rating={meta.get('rating')!r}")
        else:
            evidence["checks"]["notes_rating"] = "saved and read back (notes + rating=4)"
            print("notes/rating OK (saved via LAN, read back identical)")

    if not failures:
        # ── 5. live change: new file appears in /api/files ──────────
        from PIL import Image
        img = Image.new("RGB", (256, 256), (10, 200, 10))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        (lib / "live_added.png").write_bytes(buf.getvalue())
        appeared = False
        for _ in range(20):
            status, _h, files_body = _http("GET", f"{base}/api/files?limit=100", cookie=cookie)
            if status == 200 and "live_added.png" in files_body.decode("utf-8", "replace"):
                appeared = True
                break
            time.sleep(0.5)
        if not appeared:
            failures.append("live-added file never appeared in /api/files")
        else:
            evidence["checks"]["live_change"] = "live_added.png listed"
            print("live change OK (live_added.png listed in /api/files)")

    # ── 6. Normal application exit, persisted state, and relaunch ─────────
    # Do not precede the main acceptance path with WM_CLOSE.  Qt's hide-to-tray
    # handler calls QWidget.hide(); a later Win32 ShowWindow can make its HWND
    # visible while the Qt widget remains hidden, so it cannot prove tray
    # restoration or provide a valid shortcut target.
    close_note: dict[str, Any] = {}
    app_hwnd = evidence.get("window_initial", {}).get("hwnd")
    if failures:
        close_note["status"] = "not_attempted_after_prior_failure"
    elif proc.poll() is not None or not isinstance(app_hwnd, int):
        failures.append("process/window unavailable before close acceptance")
        close_note["status"] = "unavailable"
    elif args.observe_hide:
        try:
            _post_close(app_hwnd)
            deadline = time.perf_counter() + 8.0
            while time.perf_counter() < deadline and _is_window_visible(app_hwnd):
                time.sleep(0.1)
            close_note["wm_close_hidden"] = not _is_window_visible(app_hwnd)
            close_note["process_alive"] = proc.poll() is None
            _restore_window(app_hwnd)
            time.sleep(0.2)
            close_note["native_visible_after_showwindow"] = _is_window_visible(app_hwnd)
            close_note["diagnostic_limit"] = (
                "Win32 visibility does not prove QWidget/tray restoration; "
                "this mode cannot pass W6 acceptance"
            )
            failures.append("--observe-hide is diagnostic-only and cannot pass W6 acceptance")
        except RuntimeError as exc:
            failures.append(str(exc))
    else:
        try:
            _send_ctrl_q(app_hwnd)
            try:
                code = _wait_for_exit(proc, CLOSE_TIMEOUT_S)
            except RuntimeError:
                close_note["normal_exit_timeout_observation"] = _exit_timeout_observation(
                    app_hwnd, base, proc)
                raise
            close_note["normal_exit"] = {"entry": "Ctrl+Q", "exit_code": code}
            close_note["hide_observation"] = "not_run (use --observe-hide; diagnostic only)"
            if code != 0:
                raise _invalid(f"normal Ctrl+Q exit returned {code}")
        except RuntimeError as exc:
            failures.append(str(exc))
    evidence["close"] = close_note
    print(f"close: {close_note}")

    if not failures:
        # Persisted state is an assertion, not an informational JSON field.
        saved = json.loads(settings_path.read_text(encoding="utf-8"))
        persisted = {
            "window_maximized": saved.get("window_maximized"),
            "has_geometry": isinstance(saved.get("window_geometry"), str)
                            and len(saved.get("window_geometry", "")) > 0,
        }
        evidence["checks"]["geometry_persisted"] = persisted
        if persisted["window_maximized"] != args.maximized or not persisted["has_geometry"]:
            failures.append(f"geometry persistence contract failed: {persisted}")
        else:
            print(f"geometry persisted: {persisted}")

    if not failures:
        # Relaunch from the same isolated runtime domain.  The second process
        # must restore the actual window state and serve the metadata written
        # before the normal application exit.
        restarted = subprocess.Popen([str(exe)], env=env, cwd=str(ROOT))
        restart_evidence: dict[str, Any] = {"pid": restarted.pid}
        evidence["restart"] = restart_evidence
        try:
            print("OPERATOR: reopen the seeded library card in the restarted StartupWindow"
                  if not args.auto_open else "AUTO-OPEN: reopening the sole seeded library card")
            if args.auto_open:
                _send_enter(_wait_for_window(restarted.pid, 15.0)["hwnd"])
            deadline = time.perf_counter() + INFO_TIMEOUT_S
            status = None
            while time.perf_counter() < deadline:
                if restarted.poll() is not None:
                    break
                try:
                    status, _headers, _body = _http("GET", f"{base}/api/info", timeout=5)
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(1.0)
            if status != 200:
                raise _invalid(f"restarted LAN /api/info never returned 200 (last {status})")
            restart_window = _wait_for_window(restarted.pid, 15.0)
            restart_evidence["window"] = restart_window
            if restart_window["maximized"] != args.maximized:
                raise _invalid(
                    f"restarted window maximized={restart_window['maximized']}, expected {args.maximized}")
            status, headers, _body = _http("POST", f"{base}/api/auth/login", data={"password": PASSWORD})
            restart_cookie = headers.get("Set-Cookie", "").split(";", 1)[0]
            if status != 200 or not restart_cookie.startswith("lan_token="):
                raise _invalid(f"restarted login failed: HTTP {status}")
            status, _headers, body = _http("GET", f"{base}/api/meta/pkg_000.png", cookie=restart_cookie)
            restored_meta = json.loads(body) if status == 200 else {}
            restart_evidence["notes_rating"] = restored_meta
            if (status != 200 or restored_meta.get("notes") != "W6 functional note"
                    or restored_meta.get("rating") != 4):
                raise _invalid(f"notes/rating not persisted after restart: HTTP {status}, {restored_meta}")
            _send_ctrl_q(restart_window["hwnd"])
            try:
                restart_code = _wait_for_exit(restarted, CLOSE_TIMEOUT_S)
            except RuntimeError:
                restart_evidence["normal_exit_timeout_observation"] = _exit_timeout_observation(
                    restart_window["hwnd"], base, restarted)
                raise
            restart_evidence["normal_exit_code"] = restart_code
            if restart_code != 0:
                raise _invalid(f"restarted Ctrl+Q exit returned {restart_code}")
            print("restart OK (window state + notes/rating persisted)")
        except RuntimeError as exc:
            failures.append(str(exc))

    # A forced termination is cleanup for an already-invalid isolated run.  It
    # is never used to infer tray behaviour or a successful application exit.
    if failures:
        cleanup: list[dict[str, Any]] = []
        for label, candidate in (("initial", proc), ("restart", restarted)):
            if candidate is not None and candidate.poll() is None:
                result = subprocess.run(
                    ["taskkill", "/F", "/PID", str(candidate.pid), "/T"],
                    capture_output=True, text=True,
                )
                cleanup.append({"process": label, "pid": candidate.pid,
                                "returncode": result.returncode})
        evidence["invalid_run_cleanup"] = cleanup

    out = Path("artifacts/perf/w6-functional")
    out.mkdir(parents=True, exist_ok=True)
    evidence["valid"] = not failures
    evidence["failures"] = failures
    (out / f"{args.mode}{'-maximized' if args.maximized else ''}.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8")

    if failures:
        print(f"INVALID: {'; '.join(failures)}")
        return 1
    print(f"W6 FUNCTIONAL ({args.mode}{' maximized' if args.maximized else ''}): PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
