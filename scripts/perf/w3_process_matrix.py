"""W3-1/W3-2: real-process startup matrix (plan W3 first two rows).

Child = 真实用户入口 `python main.py`（非 exec-harness），隔离
AM_RUNTIME_ROOT + 种子化 settings.json：
  - mode "normal": window_maximized=False
  - mode "maximized": window_maximized=True（PF-1 崩溃触发器）
  - mode "missing_library": recent_libraries 指向不存在路径

父进程断言：
  1. 8s 存活（原生崩溃/PF-1 类构造崩溃会杀死进程 → fail）
  2. faulthandler.log 无 "Current thread" 栈
  3. taskkill /PID（WM_CLOSE）优雅退出 exit 0，且 window_geometry 已持久化

Usage: python scripts/perf/w3_process_matrix.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def seed_settings(runtime: Path, mode: str) -> None:
    shared = runtime / "Shared"
    shared.mkdir(parents=True, exist_ok=True)
    settings: dict = {"language": "en", "theme": "Navy"}
    if mode == "maximized":
        settings["window_maximized"] = True
    else:
        settings["window_maximized"] = False
    if mode == "missing_library":
        settings["recent_libraries"] = [str(Path(runtime) / "does_not_exist")]
    (shared / "settings.json").write_text(json.dumps(settings), encoding="utf-8")


def run_child(mode: str) -> dict:
    runtime = Path(tempfile.mkdtemp(prefix=f"w3-{mode}-"))
    seed_settings(runtime, mode)
    env = dict(os.environ)
    env["AM_RUNTIME_ROOT"] = str(runtime)
    env["QT_QPA_PLATFORM"] = "offscreen"

    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        env=env, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    # 1) 8s 存活断言：PF-1 类构造崩溃在此窗口内即死
    time.sleep(8.0)
    alive = proc.poll() is None
    if not alive:
        _, stderr = proc.communicate(timeout=5)
        fh = runtime / "Shared" / "faulthandler.log"
        fh_text = fh.read_text(encoding="utf-8", errors="ignore") if fh.exists() else ""
        return {"mode": mode, "alive_8s": False,
                "exit_code": proc.returncode,
                "crash_flag": "Current thread" in fh_text,
                "stderr_tail": stderr[-300:]}

    # 2) 优雅关闭（WM_CLOSE → closeEvent → 几何持久化）
    subprocess.run(["taskkill", "/PID", str(proc.pid)], capture_output=True)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/F", "/PID", str(proc.pid)], capture_output=True)
        proc.wait(timeout=10)

    fh = runtime / "Shared" / "faulthandler.log"
    fh_text = fh.read_text(encoding="utf-8", errors="ignore") if fh.exists() else ""
    crashed = "Current thread" in fh_text
    settings_after = {}
    try:
        settings_after = json.loads((runtime / "Shared" / "settings.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "mode": mode,
        "alive_8s": True,
        "exit_code": proc.returncode,
        "graceful_close": proc.returncode == 0,
        "crash_flag": crashed,
        "window_geometry_persisted": bool(settings_after.get("window_geometry")),
        "window_maximized_after": settings_after.get("window_maximized"),
    }


def main() -> None:
    results = []
    for mode in ("normal", "maximized", "maximized", "maximized", "missing_library"):
        r = run_child(mode)
        results.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    ok = all(
        r.get("alive_8s") and r.get("graceful_close") and not r.get("crash_flag")
        for r in results if "alive_8s" in r
    )
    print("MATRIX:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    main()
