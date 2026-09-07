"""Startup timing probe (performance audit P1): segments the boot path.

Usage: python scripts/perf/startup_probe.py [--files 1000]
Offscreen; segments: QApplication → MainWindow ctor → session open →
scoped services → UI ready (panel scanned). Run 3× and take medians.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def rss_mb() -> float:
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        import ctypes

        class PROC_MEM(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        pm = PROC_MEM()
        pm.cb = ctypes.sizeof(PROC_MEM)
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pm), pm.cb)
        return pm.WorkingSetSize / (1024 * 1024)


def run_once(file_count: int) -> dict:
    from PySide6.QtWidgets import QApplication

    t0 = time.perf_counter()
    app = QApplication.instance() or QApplication([])
    t1 = time.perf_counter()

    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.window import MainWindow
    t2 = time.perf_counter()
    t2_rss = rss_mb()

    root = Path(tempfile.mkdtemp(prefix="perf-startup-"))
    for i in range(file_count):
        (root / f"file_{i:04d}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 256)

    bootstrap = ApplicationBootstrap()
    t3 = time.perf_counter()
    session = bootstrap.library_service.open_session(root)
    t4 = time.perf_counter()

    window = MainWindow(bootstrap, None, lan_server_factory=None)
    window._workspace.add_library(str(root))
    t5 = time.perf_counter()
    window.show()
    app.processEvents()
    grid = window.file_list._grid_widget if hasattr(window, "file_list") else None
    if grid is not None:
        grid._model._wait_for_scan()  # 测试同款确定性就绪信号
    deadline = time.perf_counter() + 15.0
    while time.perf_counter() < deadline:
        app.processEvents()
        if grid is not None and not grid._animator.has_thumbnail_fades():
            break
        time.sleep(0.02)
    t6 = time.perf_counter()
    t6_rss = rss_mb()

    out = {
        "qapp_s": t1 - t0,
        "imports_s": t2 - t1,
        "bootstrap_s": t3 - t2,
        "open_session_s": t4 - t3,
        "mainwindow_plus_session_wire_s": t5 - t4,
        "scan_settle_s": t6 - t5,
        "total_s": t6 - t0,
        "rss_mb": rss_mb(),
        "rss_after_import_mb": round(t2_rss, 1),
        "rss_ready_mb": round(t6_rss, 1),
    }
    window.close()
    window.deleteLater()
    app.processEvents()
    bootstrap.library_service.close_session(session)
    app.processEvents()
    import shutil
    shutil.rmtree(root, ignore_errors=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=1000)
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    runs = [run_once(args.files) for _ in range(args.runs)]
    keys = runs[0].keys()
    print(f"files={args.files} runs={args.runs} rss_final={runs[-1]['rss_mb']:.0f}MB")
    for k in keys:
        vals = [r[k] for r in runs]
        unit = "MB" if k == "rss_mb" else "s"
        med = statistics.median(vals)
        print(f"  {k:32s} median {med:8.3f} {unit}   runs: {[round(v, 3) for v in vals]}")


if __name__ == "__main__":
    import sys

    main()
