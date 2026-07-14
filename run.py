"""AssetManager — click-to-run launcher with error display."""
import sys
import traceback
from pathlib import Path

project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

if __name__ == "__main__":
    try:
        from AssetsManager.app import main
        sys.exit(main())
    except Exception:
        msg = traceback.format_exc()
        print(msg)
        import tkinter.messagebox as mb
        mb.showerror("AssetManager — Startup Error", msg)
        sys.exit(1)
