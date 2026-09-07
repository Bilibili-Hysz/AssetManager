"""P1 measurement 3 — RSS memory profile across the app lifecycle.

Sampling points (offscreen), each recorded with psutil RSS:

  1  bare process (before any app import)
  2  after `import AssetsManager.app` (import chain resident)
  3  after QApplication + theme stylesheet
  4  after ApplicationBootstrap
  5  after StartupWindow shown
  6  after MainWindow constructed
  7  after library session open (add_library; incl. SQLite migrate)
  8  after background scan of a 1k-file library completes
  9  after grid view switched on
  10 after simulated browsing (directory navigation x N)
  11 after scroll-driven thumbnail loading in a 200-file directory
  12 after library close (window closed + session torn down)
  13 final after GC + event drain

Evidence: docs/reports/performance-audit-2026-09-06/evidence/p1-memory-profile.json

Usage:
    QT_QPA_PLATFORM=offscreen python scripts/perf/p1_memory_profile.py \
        --library-root <dir> [--browse-dirs 20]
"""
from __future__ import annotations

import argparse
import gc
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _p1_common import environment, project_root, rss_bytes, write_json  # noqa: E402

sys.path.insert(0, str(project_root()))


def build_1k_library(root: Path, dirs: int = 20, per_dir: int = 50) -> None:
    """1k-file library: `dirs` x `per_dir` real 64x64 PNG images.

    A handful of distinct source images are painted with QImage after the
    QApplication exists, then copied — realistic decodable payloads without
    1000 individual paints.
    """
    root.mkdir(parents=True, exist_ok=True)
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtCore import Qt

    sources: list[bytes] = []
    for i in range(8):
        img = QImage(64, 64, QImage.Format.Format_RGB32)
        img.fill(QColor.fromHsv((i * 40) % 360, 180, 220))
        p = QPainter(img)
        p.setPen(Qt.GlobalColor.black)
        p.drawRect(8 + i, 8 + i, 40, 40)
        p.end()
        # QImage.save needs a path; reuse saveToBuffer via QBuffer-free trick:
        # save to the first target file directly, keep bytes for copying.
        first = root / f"_src_{i}.png"
        img.save(str(first), "PNG")
        sources.append(first.read_bytes())
        first.unlink()

    for d in range(dirs):
        sub = root / f"album_{d:03d}"
        sub.mkdir(exist_ok=True)
        for f in range(per_dir):
            data = sources[(d + f) % len(sources)]
            (sub / f"asset_{f:03d}.png").write_bytes(data)


def pump(app, ms: int) -> None:
    """Process events for roughly *ms* milliseconds."""
    deadline = time.perf_counter() + ms / 1000
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--library-root", required=True)
    ap.add_argument("--browse-dirs", type=int, default=10)
    ap.add_argument("--rebuild", action="store_true",
                    help="delete and rebuild the sample library first")
    args = ap.parse_args()

    lib_root = Path(args.library_root)
    if args.rebuild and lib_root.exists():
        shutil.rmtree(lib_root)
    if not lib_root.exists():
        # QApplication must exist before QImage painting, so defer building:
        # record bare RSS now, build later.
        pass

    # Isolated AM_RUNTIME_ROOT (same mechanism as tests/conftest.py): the
    # probe must not read/write the project's real RuntimeData or settings.
    runtime_parent = Path(tempfile.mkdtemp(prefix="p1_probe_runtime_"))
    os.environ["AM_RUNTIME_ROOT"] = str(runtime_parent / "RuntimeData")
    (runtime_parent / "RuntimeData").mkdir(parents=True, exist_ok=True)

    samples: list[dict] = []

    def sample(step: str) -> None:
        samples.append({
            "step": step,
            "rss_mb": round(rss_bytes() / (1024 * 1024), 1),
            "t_ms": round((time.perf_counter() - t0) * 1000, 1),
        })
        print(f"  [{samples[-1]['t_ms']:8.0f} ms] {step:42s} "
              f"RSS {samples[-1]['rss_mb']:8.1f} MB")

    t0 = time.perf_counter()
    sample("1_bare_process")

    import AssetsManager.app  # noqa: F401
    sample("2_after_import_app")

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    from AssetsManager.core import themes

    app.setStyleSheet(themes.stylesheet())
    sample("3_after_qapplication_theme")

    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer
    from AssetsManager.core.tag_library import get_library
    from AssetsManager.dock_factory import install_dock_refresh_handlers

    install_tag_canonicalizer(get_library().canonical)
    bootstrap = ApplicationBootstrap()
    install_dock_refresh_handlers()
    sample("4_after_bootstrap")

    if not lib_root.exists():
        build_1k_library(lib_root)
    n_files = sum(1 for _ in lib_root.rglob("*.png"))
    print(f"[probe] library: {lib_root} ({n_files} png files)")

    from AssetsManager.dialogs.startup import StartupWindow

    startup = StartupWindow()
    startup.show()
    app.processEvents()
    sample("5_startup_window_shown")

    from AssetsManager.window import MainWindow

    window = MainWindow(bootstrap, None, lan_server_factory=None)
    sample("6_mainwindow_constructed")

    window._workspace.add_library(str(lib_root))
    sample("7_library_session_open")

    window.file_list._model._wait_for_scan()
    app.processEvents()
    sample("8_scan_complete_1k")

    # Grid view on, thumbnail loads begin for visible rows.
    window.file_list._set_view_mode_by_name("Grid")
    pump(app, 500)
    sample("9_grid_view_on")

    # Browsing: navigate through directories (history + scans + thumbs).
    dirs = sorted(d for d in lib_root.iterdir() if d.is_dir())
    for i, d in enumerate(dirs[: args.browse_dirs]):
        window.file_list.navigate_to(str(d))
        window.file_list._model._wait_for_scan()
        pump(app, 300)
        if (i + 1) % 5 == 0:
            sample(f"10_browse_after_{i + 1}_dirs")
    if args.browse_dirs and args.browse_dirs % 5:
        sample(f"10_browse_after_{min(args.browse_dirs, len(dirs))}_dirs")

    # Scroll-driven thumbnail load in the last directory (50 files).
    grid = window.file_list._grid_widget
    bar = getattr(grid, "_scrollbar", None)
    if bar is not None:
        window.file_list.navigate_to(str(dirs[0]))
        window.file_list._model._wait_for_scan()
        pump(app, 300)
        lo, hi = bar.minimum(), bar.maximum()
        steps = 20
        for s in range(steps + 1):
            bar.setValue(lo + (hi - lo) * s // steps)
            pump(app, 150)
        sample("11_scroll_thumbnails_dir50")

    pump(app, 1000)
    sample("11b_settle_after_scroll")

    # Close the library window (same teardown contract as tests/desktop).
    window._force_quit = True
    window.close()
    app.processEvents()
    sample("12_library_window_closed")

    gc.collect()
    pump(app, 500)
    sample("13_after_gc_and_drain")

    from AssetsManager.widgets.shortcut_manager import ShortcutManager

    ShortcutManager.instance()._shortcuts.clear()
    startup.close()
    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(5000)

    # Second open/close cycle on the same library: distinguishes one-time
    # process warm-up retention (plateau) from per-cycle growth (leak).
    window2 = MainWindow(bootstrap, None, lan_server_factory=None)
    window2._workspace.add_library(str(lib_root))
    window2.file_list._model._wait_for_scan()
    app.processEvents()
    sample("14_second_open_scan_complete")

    window2._force_quit = True
    window2.close()
    app.processEvents()
    ShortcutManager.instance()._shortcuts.clear()
    gc.collect()
    pump(app, 500)
    sample("15_second_close_after_gc")

    deltas = []
    base = samples[0]["rss_mb"]
    prev = base
    for s in samples:
        deltas.append({"step": s["step"], "delta_prev_mb": round(s["rss_mb"] - prev, 1),
                       "delta_from_bare_mb": round(s["rss_mb"] - base, 1)})
        prev = s["rss_mb"]

    payload = {
        "measurement": "memory-profile-rss",
        "library_files": n_files,
        "browse_dirs": min(args.browse_dirs, len(dirs)) if dirs else 0,
        "samples": samples,
        "deltas": deltas,
        "environment": environment(),
    }
    write_json("p1-memory-profile.json", payload)
    print("\n== RSS growth table ==")
    print(f"  {'step':44s} {'RSS MB':>9s} {'d_prev':>9s} {'d_bare':>9s}")
    for s, d in zip(samples, deltas, strict=False):
        print(f"  {s['step']:44s} {s['rss_mb']:9.1f} "
              f"{d['delta_prev_mb']:9.1f} {d['delta_from_bare_mb']:9.1f}")

    # Temp hygiene: remove the isolated runtime (sample library kept — it is
    # the caller-provided root; pass --rebuild to regenerate it).
    shutil.rmtree(runtime_parent, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
