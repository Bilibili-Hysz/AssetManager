"""P1 measurement 2 — startup segment timing (offscreen probe).

Replicates the production startup path of ``AssetsManager.app.main`` segment
by segment and reports wall-clock time per segment.  Deviations from the real
``main()`` (documented, both performance-neutral to the measured segments):

* ``_bind_single_instance`` is skipped — a probe must never take the process
  lock or dialog-spam a live instance.
* ``app.exec()`` is replaced by ``processEvents()`` pumps; the deferred
  ``QTimer.singleShot(0, _deferred_startup)`` work (plugin discovery + GL
  warm-up) is invoked explicitly where the real timer would fire.

Cold vs warm: the driver deletes the library's RuntimeData slot (the SQLite
DB lives under the project ``RuntimeData/<slot>``, see path_resolver) before
run 1 and leaves it in place for later runs.

Usage (single run, JSON on stdout):
    QT_QPA_PLATFORM=offscreen python scripts/perf/p1_startup_segments.py \
        --library-root <dir> [--no-library]

Driver mode (medians across runs):
    python scripts/perf/p1_startup_segments.py --driver --runs 3 --library-root <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _p1_common import environment, project_root, write_json  # noqa: E402


def build_library(root: Path) -> None:
    """Small representative library (3 dirs, ~24 files) for the open path."""
    root.mkdir(parents=True, exist_ok=True)
    # 1x1 transparent PNG, 67 bytes — decodes fine for thumbnails.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080600000"
        "01f15c4890000000d49444154789c626001000000ffff030000060005"
        "57bfabd40000000049454e44ae426082"
    )
    for d in range(3):
        sub = root / f"dir_{d}"
        sub.mkdir(exist_ok=True)
        for f in range(8):
            (sub / f"img_{f:02d}.png").write_bytes(png)


def wipe_runtime_slot(library_root: Path) -> None:
    """Remove the RuntimeData slot this library maps to (cold-cache run)."""
    sys.path.insert(0, str(project_root()))
    from AssetsManager.core.path_resolver import library_data_dir

    slot = library_data_dir(str(library_root))
    if slot.exists():
        shutil.rmtree(slot, ignore_errors=True)
        print(f"[driver] wiped runtime slot {slot}")


def pass_runtime_root(runtime_root: Path) -> None:
    os.environ["AM_RUNTIME_ROOT"] = str(runtime_root / "RuntimeData")


def make_runtime_root() -> Path:
    """Isolated AM_RUNTIME_ROOT (same mechanism as tests/conftest.py) so the
    probe never reads or writes the project's real RuntimeData/settings."""
    import uuid

    base = Path(os.environ.get("AM_PROBE_RUNTIME_PARENT", tempfile.gettempdir()))
    root = base / f"p1_probe_runtime_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    (root / "RuntimeData").mkdir(parents=True, exist_ok=True)
    os.environ["AM_RUNTIME_ROOT"] = str(root / "RuntimeData")
    return root


def single_run(library_root: str | None) -> dict:
    t0 = time.perf_counter()
    segments: dict[str, float] = {}

    def mark(name: str, t_start: float) -> None:
        segments[name] = round((time.perf_counter() - t_start) * 1000, 1)

    # ── segment: import chain (equivalent of `from AssetsManager.app import main`)
    t = time.perf_counter()
    import AssetsManager.app  # noqa: F401  (the real import chain under test)
    mark("import_app_chain", t)

    from PySide6.QtWidgets import QApplication

    # ── segment: crash handler install
    t = time.perf_counter()
    from AssetsManager.core.crash_handler import install as install_crash_handler

    install_crash_handler()
    mark("crash_handler_install", t)

    # ── segment: QApplication creation
    t = time.perf_counter()
    from PySide6.QtCore import Qt

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    app = QApplication(sys.argv)
    app.setApplicationName("AssetManager")
    mark("qapplication_create", t)

    # ── segment: i18n init
    t = time.perf_counter()
    from AssetsManager import i18n

    i18n.init()
    mark("i18n_init", t)

    # (single-instance bind skipped by design — see module docstring)

    # ── segment: theme stylesheet + font
    t = time.perf_counter()
    from AssetsManager.core import themes
    from AssetsManager.core.settings import AppSettings
    from PySide6.QtGui import QFont

    app.setStyleSheet(themes.stylesheet())
    font = app.font()
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    from AssetsManager.core.ui_scale import scaled_pt

    base_pt = font.pointSize()
    app.setProperty("base_font_size", base_pt)
    font.setPointSize(scaled_pt(base_pt))
    app.setFont(font)
    mark("theme_stylesheet_font", t)
    _ = AppSettings.instance()  # same singleton access main() does below

    # ── segment: ApplicationBootstrap
    t = time.perf_counter()
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer
    from AssetsManager.core.tag_library import get_library
    from AssetsManager.dock_factory import install_dock_refresh_handlers

    mark("application_bootstrap_imports", t)
    t = time.perf_counter()
    install_tag_canonicalizer(get_library().canonical)
    mark("tag_library_load", t)
    t = time.perf_counter()
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    mark("application_bootstrap_ctor", t)
    t = time.perf_counter()
    install_dock_refresh_handlers()
    mark("dock_refresh_handlers", t)

    # ── segment: tray
    t = time.perf_counter()
    from AssetsManager.widgets.tray import SystemTrayManager

    icon_path = str(project_root() / "assets" / "icons" / "icon.ico")
    tray = SystemTrayManager(icon_path)
    app.setProperty("has_tray", tray.is_available)
    mark("system_tray", t)

    # ── segment: startup window create + show
    t = time.perf_counter()
    from AssetsManager.dialogs.startup import StartupWindow

    startup = StartupWindow()
    mark("startup_window_create", t)
    t = time.perf_counter()
    startup.show()
    app.processEvents()
    mark("startup_window_show_first_paint", t)

    # ── segment: deferred startup (plugin discovery + GL warm-up); the real
    # app runs this in a zero-delay timer right after exec() starts.
    t = time.perf_counter()
    bootstrap.discover_plugins()
    try:
        from PySide6.QtOpenGLWidgets import QOpenGLWidget

        _gl = QOpenGLWidget()
        _gl.setVisible(False)
        _gl.resize(1, 1)
        _gl.grabFramebuffer()
        del _gl
    except Exception:
        pass
    mark("deferred_plugins_gl_warmup", t)

    total_to_startup_ui = time.perf_counter() - t0

    result: dict = {
        "segments_ms": segments,
        "total_to_startup_ui_ms": round(total_to_startup_ui * 1000, 1),
    }

    if not library_root:
        result["total_including_library_open_ms"] = None
        return result

    # ── segment: MainWindow create (app.py:241 real path, LAN lazy)
    t = time.perf_counter()
    from AssetsManager.window import MainWindow

    window = MainWindow(bootstrap, None, lan_server_factory=None)
    mark("mainwindow_create", t)
    # Sub-segment: which phase of MainWindow.__init__ is heavy?  Wrap the
    # known phases by re-timing a reconstruction is not possible, so instead
    # time the first-show/scan phases separately below.

    # ── segment: open library (session + migration + scoped services)
    t = time.perf_counter()
    window._workspace.add_library(library_root)
    mark("add_library_session_open", t)
    t = time.perf_counter()
    app.processEvents()
    mark("add_library_deferred_pump", t)

    # ── segment: background scan of the library
    t = time.perf_counter()
    window.file_list._model._wait_for_scan()
    app.processEvents()
    mark("library_scan_wait", t)

    # ── segment: main window show
    t = time.perf_counter()
    window.show()
    app.processEvents()
    mark("mainwindow_show_first_paint", t)

    result["total_including_library_open_ms"] = round(
        (time.perf_counter() - t0) * 1000, 1
    )

    # Teardown (same contract as tests/desktop _teardown_main_window).
    window._force_quit = True
    try:
        window.close()
    except RuntimeError:
        pass
    from AssetsManager.widgets.shortcut_manager import ShortcutManager

    ShortcutManager.instance()._shortcuts.clear()
    window.deleteLater()
    app.processEvents()

    # Drain background pools so the process can exit cleanly.
    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(5000)
    return result


def driver(runs: int, library_root: str | None) -> int:
    lib_dir: Path | None = None
    if library_root:
        lib_dir = Path(library_root)
        if lib_dir.exists():
            shutil.rmtree(lib_dir)
        build_library(lib_dir)

    runtime_root = make_runtime_root()
    print(f"[driver] isolated runtime: {runtime_root}")

    rows: list[dict] = []
    for i in range(runs):
        if lib_dir is not None and i == 0:
            pass_runtime_root(runtime_root)
            wipe_runtime_slot(lib_dir)  # cold: migration runs for real
            # warm runs reuse the slot created by run 1
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["PYTHONPATH"] = str(project_root()) + os.pathsep + env.get("PYTHONPATH", "")
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--single",
            "--library-root", library_root or "",
        ]
        proc = subprocess.run(cmd, cwd=str(project_root()), env=env,
                              capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            print(proc.stdout[-3000:])
            print(proc.stderr[-3000:])
            raise RuntimeError(f"probe run {i + 1} failed")
        row = json.loads(proc.stdout.strip().splitlines()[-1])
        row["run"] = i + 1
        row["cache"] = "cold" if i == 0 else "warm"
        rows.append(row)
        print(f"run {i + 1}/{runs} ({row['cache']}): "
              f"to startup UI {row['total_to_startup_ui_ms']} ms"
              + (f", incl. library {row['total_including_library_open_ms']} ms"
                 if row["total_including_library_open_ms"] else ""))

    seg_keys = sorted({k for r in rows for k in r["segments_ms"]})
    summary = {}
    for k in seg_keys:
        vals = [r["segments_ms"][k] for r in rows if k in r["segments_ms"]]
        summary[k] = {
            "median_ms": round(statistics.median(vals), 1),
            "min_ms": round(min(vals), 1),
            "max_ms": round(max(vals), 1),
        }
    totals_to_ui = [r["total_to_startup_ui_ms"] for r in rows]
    totals_lib = [r["total_including_library_open_ms"] for r in rows
                  if r["total_including_library_open_ms"]]
    payload = {
        "measurement": "startup-segments",
        "runs": runs,
        "totals_to_startup_ui_ms": totals_to_ui,
        "median_to_startup_ui_ms": round(statistics.median(totals_to_ui), 1),
        "totals_including_library_open_ms": totals_lib,
        "median_including_library_open_ms": (
            round(statistics.median(totals_lib), 1) if totals_lib else None
        ),
        "segments_median": summary,
        "rows": rows,
        "environment": environment(),
    }
    write_json("p1-startup-segments.json", payload)
    print("\n== segment medians (ms) ==")
    for k, v in summary.items():
        print(f"  {v['median_ms']:9.1f}  {k}")

    # Temp hygiene: remove the isolated runtime + sample library.
    shutil.rmtree(runtime_root, ignore_errors=True)
    if lib_dir is not None:
        shutil.rmtree(lib_dir, ignore_errors=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--single", action="store_true", help="internal: one probe run")
    ap.add_argument("--driver", action="store_true")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--library-root", default=None)
    ap.add_argument("--no-library", action="store_true")
    args = ap.parse_args()

    if args.driver:
        return driver(args.runs, None if args.no_library else args.library_root)
    if args.single:
        row = single_run(args.library_root or None)
        print(json.dumps(row))
        return 0
    # Default: behave like --single for direct manual invocation.
    print(json.dumps(single_run(args.library_root)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
