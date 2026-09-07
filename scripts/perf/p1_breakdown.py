"""P1 one-off breakdown — cProfile the three dominant startup segments.

Segments profiled (mirroring p1_startup_segments.single_run):
  A. ApplicationBootstrap() construction
  B. MainWindow() construction
  C. add_library() cold session open

Usage:
    QT_QPA_PLATFORM=offscreen python scripts/perf/p1_breakdown.py
"""
from __future__ import annotations

import cProfile
import io
import os
import pstats
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _p1_common import project_root  # noqa: E402
from p1_startup_segments import build_library, make_runtime_root  # noqa: E402


def profiled(fn, label: str, limit: int = 18) -> None:
    pr = cProfile.Profile()
    pr.enable()
    fn()
    pr.disable()
    buf = io.StringIO()
    st = pstats.Stats(pr, stream=buf).sort_stats("cumulative")
    st.print_stats(limit)
    print(f"\n{'=' * 30} {label} {'=' * 30}")
    # Trim the pstats header noise for the report.
    lines = buf.getvalue().splitlines()
    for line in lines:
        if line.strip() and not line.startswith(("Ordered by", "List reduced")):
            print(line)


def main() -> int:
    make_runtime_root()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    from AssetsManager.core import themes

    app.setStyleSheet(themes.stylesheet())

    lib_root = Path(tempfile.mkdtemp(prefix="p1_breakdown_lib_"))
    build_library(lib_root)

    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer
    from AssetsManager.core.tag_library import get_library
    from AssetsManager.dock_factory import install_dock_refresh_handlers

    install_tag_canonicalizer(get_library().canonical)
    bootstrap_holder = {}

    def build_bootstrap():
        bootstrap_holder["b"] = ApplicationBootstrap()

    profiled(build_bootstrap, "A. ApplicationBootstrap()")

    install_dock_refresh_handlers()

    from AssetsManager.window import MainWindow

    window_holder = {}

    def build_window():
        window_holder["w"] = MainWindow(bootstrap_holder["b"], None,
                                        lan_server_factory=None)

    profiled(build_window, "B. MainWindow()")

    window = window_holder["w"]

    def open_library():
        window._workspace.add_library(str(lib_root))
        window.file_list._model._wait_for_scan()
        app.processEvents()

    profiled(open_library, "C. add_library (cold session open)")
    print(f"\nlibrary session after open: {window._library_session}")

    window._force_quit = True
    window.close()
    app.processEvents()
    from AssetsManager.widgets.shortcut_manager import ShortcutManager

    ShortcutManager.instance()._shortcuts.clear()
    shutil.rmtree(lib_root, ignore_errors=True)
    shutil.rmtree(os.environ["AM_RUNTIME_ROOT"], ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(project_root()))
    raise SystemExit(main())
