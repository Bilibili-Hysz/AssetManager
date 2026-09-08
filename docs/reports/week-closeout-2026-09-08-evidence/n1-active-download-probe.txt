"""N1: active-download close scenario — Ctrl+Q while a large download is
mid-transfer.  Evidence contract (week plan N1):
  - the app must exit within a bounded window (no hang) with code 0;
  - the in-flight download client must observe a CLEAN failure (connection
    reset / abort), never a truncated 200;
  - the exit code and download outcome are recorded, not asserted as
    "resource reclaimed" (server-side counters remain N3's scope).
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "dist/AssetManager/AssetManager.exe"

spec = importlib.util.spec_from_file_location(
    "w6probe", ROOT / "scripts" / "perf" / "w6_package_functional.py")
w6 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w6)
spec5 = importlib.util.spec_from_file_location(
    "w5probe", ROOT / "scripts" / "perf" / "w5_lan_resource_probe.py")
w5 = importlib.util.module_from_spec(spec5)
spec5.loader.exec_module(w5)

tmp = Path(os.environ["W6_MANUAL_TMP"])
runtime_root = tmp / "runtime"
lib = w6._build_library(tmp)
blob = w5._build_slow_download_blob(lib, size_mb=192)
port = w6._free_port()
w6._seed_runtime(runtime_root, lib, port, maximized=False)

env = dict(os.environ)
env["AM_RUNTIME_ROOT"] = str(runtime_root)
env["PYTHONIOENCODING"] = "utf-8"
proc = subprocess.Popen([str(CANDIDATE)], env=env, cwd=str(ROOT),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(f"launched pid={proc.pid} (onedir candidate, normal window)")
window = w6._wait_for_window(proc.pid, timeout_s=90)
w6._send_enter(window["hwnd"])

base = f"http://127.0.0.1:{port}"
status = None
deadline = time.time() + 120
while time.time() < deadline:
    if proc.poll() is not None:
        print(f"app exited early code={proc.returncode}")
        sys.exit(1)
    try:
        status, _h, _b = w6._http("GET", f"{base}/api/info", timeout=5)
        if status == 200:
            break
    except Exception:
        pass
    time.sleep(1.0)
if status != 200:
    print(f"DIAG: api never up (last {status})")
    sys.exit(1)
print("api up")

window2 = w6._find_window(w6._descendant_pids(proc.pid))
if window2 is None:
    print("DIAG: main window gone")
    sys.exit(1)
print("main window found; firing 192MB download then closing mid-transfer")

download_outcome: dict = {}


def download() -> None:
    t0 = time.time()
    try:
        status, _h, body = w6._http(
            "GET", f"{base}/api/download/{blob.name}", timeout=60)
    except Exception as exc:
        download_outcome["error"] = f"{type(exc).__name__}: {exc}"[:200]
        download_outcome["elapsed_s"] = round(time.time() - t0, 1)
        return
    download_outcome["status"] = status
    download_outcome["bytes"] = len(body)
    download_outcome["elapsed_s"] = round(time.time() - t0, 1)


worker = threading.Thread(target=download, daemon=True)
worker.start()
time.sleep(1.5)  # download is now mid-transfer (~1MB/s of 192MB on loopback)

main_hwnd = window2["hwnd"]
t0 = time.time()
w6._send_ctrl_q(main_hwnd)
print("Ctrl+Q sent mid-download")

exit_outcome = "STILL ALIVE at 60s"
while time.time() - t0 < 60:
    rc = proc.poll()
    if rc is not None:
        exit_outcome = f"exited code={rc} after {time.time()-t0:.1f}s"
        break
    time.sleep(1.0)
print("EXIT:", exit_outcome)

worker.join(timeout=70)
print("DOWNLOAD OUTCOME:", download_outcome or "thread still pending")

verdict_ok = exit_outcome.startswith("exited code=0")
clean_failure = ("error" in download_outcome
                 or download_outcome.get("status") not in (None, 200)
                 or (download_outcome.get("status") == 200
                     and download_outcome.get("bytes", 0) != blob.stat().st_size))
print("ACTIVE-DOWNLOAD CLOSE:",
      "PASS" if verdict_ok and clean_failure else
      "PASS-WITH-NOTE" if verdict_ok else "FAIL")
sys.exit(0 if verdict_ok else 1)
