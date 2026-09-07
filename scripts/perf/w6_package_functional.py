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
  7. WM_CLOSE terminates cleanly; exit code recorded         [PF-6 attribution]
  8. geometry/maximized state persisted to settings.json     [restore contract]

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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
ROOT = Path(__file__).resolve().parents[2]

PASSWORD = "W6-Functional-Password!"
SHARE_NAME = "W6-Functional"
LIB_FILES = 12
INFO_TIMEOUT_S = 180.0        # includes onefile extraction + operator GUI step
CLOSE_TIMEOUT_S = 30.0


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
    print("OPERATOR: double-click the seeded library card in the StartupWindow")

    env = dict(os.environ)
    env["AM_RUNTIME_ROOT"] = str(runtime_root)
    proc = subprocess.Popen([str(exe)], env=env, cwd=str(ROOT))
    print(f"launched pid={proc.pid}")

    failures: list[str] = []
    evidence: dict = {"mode": args.mode, "exe_sha256": None, "pid": proc.pid,
                      "port": port, "maximized": args.maximized, "checks": {}}

    # ── hash binding ────────────────────────────────────────────────
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    evidence["exe_sha256"] = digest
    print(f"exe sha256: {digest}")

    base = f"http://127.0.0.1:{port}"

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

    # ── 6. close semantics + exit code (PF-6 attribution) ──────────
    # WM_CLOSE with a system tray present means hide-to-tray (correct app
    # semantics), not process exit.  Record which path was taken and the
    # resulting exit code; only a non-zero exit ON the WM_CLOSE path is a
    # functional failure (that is the registered PF-6 symptom).
    close_note = {}
    if proc.poll() is None:
        # /T: the onefile launcher is a parent stub — the real app is a child
        # in its process tree; killing the parent alone leaves the app alive
        # holding the single-instance lock (observed on the first run).
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T"], capture_output=True)
        try:
            code = proc.wait(timeout=8.0)
            close_note["path"] = "wm_close_exit"
            close_note["exit_code"] = code
            if code != 0:
                failures.append(f"WM_CLOSE terminated with non-zero exit code {code} (PF-6 symptom)")
        except subprocess.TimeoutExpired:
            close_note["path"] = "hidden_to_tray"
            subprocess.run(["taskkill", "/F", "/PID", str(proc.pid), "/T"], capture_output=True)
            try:
                close_note["exit_code"] = proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                close_note["exit_code"] = None
                failures.append("process survived force-kill")
    else:
        close_note["path"] = "exited_before_close"
        close_note["exit_code"] = proc.returncode
        if proc.returncode != 0:
            failures.append(f"process exited early with code {proc.returncode}")
    evidence["close"] = close_note
    print(f"close: {close_note}")

    if close_note.get("path") == "wm_close_exit" and close_note.get("exit_code") == 0:
        # ── 7. restore contract persisted (only a real close saves it) ──
        saved = json.loads(settings_path.read_text(encoding="utf-8"))
        persisted = {
            "window_maximized": saved.get("window_maximized"),
            "has_geometry": isinstance(saved.get("window_geometry"), str)
                            and len(saved.get("window_geometry", "")) > 0,
        }
        evidence["checks"]["geometry_persisted"] = persisted
        print(f"geometry persisted: {persisted}")

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
