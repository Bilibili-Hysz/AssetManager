"""AssetManager — click-to-run launcher with error display."""
import sys
import traceback
from pathlib import Path

project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

def _show_startup_error(message: str) -> None:
    """Display a startup failure without depending on tkinter.

    The packaged application already ships Qt and intentionally excludes
    tkinter.  Prefer a Qt message box, but always retain a stderr fallback for
    environments where Qt itself cannot initialize.
    """
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "AssetManager — Startup Error", message)
        app.quit()
    except Exception:
        print(message, file=sys.stderr)


def _run_package_smoke() -> int:
    """Verify frozen Qt imports and SVG icon rendering without opening UI."""
    from PySide6.QtCore import QByteArray
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication

    # Import the same dock path that previously failed through the sidebar.
    from AssetsManager import dock_factory  # noqa: F401
    from AssetsManager.core.icons import icon

    app = QApplication([])
    renderer = QSvgRenderer(
        QByteArray(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>')
    )
    if not renderer.isValid():
        raise RuntimeError("QtSvg renderer failed to load the smoke-test SVG")
    if icon("settings").isNull():
        raise RuntimeError("QtSvg icon rendering returned a null QIcon")
    app.quit()
    return 0


if __name__ == "__main__":
    if "--package-smoke" in sys.argv[1:]:
        try:
            sys.exit(_run_package_smoke())
        except Exception:
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)
    try:
        from AssetsManager.app import main
        sys.exit(main())
    except Exception:
        msg = traceback.format_exc()
        _show_startup_error(msg)
        sys.exit(1)
