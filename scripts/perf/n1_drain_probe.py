"""N1 diagnosis: does the maximized onefile close self-complete after ~30s?

Manual harness — launches the candidate, waits for the window, sends the
registered Ctrl+Q via the probe's own helper, then polls WITHOUT any force
kill for up to 150s.  Outcome distinguishes:
  A. exits ~30-40s with code 0  → bounded session-close drain (probe 30s
     window too tight / drain slow)
  B. exits quickly (probe raced) → timing artifact
  C. still alive at 150s         → real close-path hang
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / ".pytest-tmp-lead-snapshots/f758725a/lifecycle/artifacts/dist-clean-process/AssetManager.exe"

spec = importlib.util.spec_from_file_location(
    "w6probe", ROOT / "scripts" / "perf" / "w6_package_functional.py")
w6 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w6)

tmp = Path(os.environ["W6_MANUAL_TMP"])
runtime_root = tmp / "runtime"
lib = w6._build_library(tmp)
port = w6._free_port()
w6._seed_runtime(runtime_root, lib, port, maximized=True)

env = dict(os.environ)
env["AM_RUNTIME_ROOT"] = str(runtime_root)
env["PYTHONIOENCODING"] = "utf-8"
proc = subprocess.Popen([str(CANDIDATE)], env=env, cwd=str(ROOT),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(f"launched pid={proc.pid}")

window = w6._wait_for_window(proc.pid, timeout_s=90)
hwnd = window["hwnd"]
print(f"window hwnd={hwnd} maximized={window['maximized']}")

# Library opens via the seeded single-card keyboard behavior: focus the
# StartupWindow and press Enter once.
w6._send_enter(hwnd)
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
    cur = w6._find_window(w6._descendant_pids(proc.pid))
    print(f"DIAG: api never up (last {status}); window={cur}; alive={proc.poll() is None}")
    sys.exit(1)
print("api up")

time.sleep(2.0)  # settle
window2 = w6._find_window(w6._descendant_pids(proc.pid))
print(f"pre-exit window maximized={window2['maximized'] if window2 else 'gone'}")

if window2 is None:
    print("DIAG: main window gone before Ctrl+Q")
    sys.exit(1)
main_hwnd = window2["hwnd"]
t0 = time.time()
w6._send_ctrl_q(main_hwnd)
print("Ctrl+Q sent to main window")

outcome = None
while time.time() - t0 < 150:
    rc = proc.poll()
    if rc is not None:
        outcome = f"exited code={rc} after {time.time()-t0:.1f}s"
        break
    time.sleep(2.0)
if outcome is None:
    hwnd3 = w6._find_window(w6._descendant_pids(proc.pid))
    outcome = f"STILL ALIVE at 150s (window={hwnd3})"
print("OUTCOME:", outcome)

if proc.poll() is None:
    print("leaving process running for further observation (no force kill)")
else:
    print("drain experiment complete")
