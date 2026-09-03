#!/usr/bin/env python
"""AssetManager — QDockWidget-based entry."""
import faulthandler
import logging
import sys
from pathlib import Path

# 诊断：segfault 等 C++ 级硬崩绕过 crash_handler 的 excepthook，无法留下
# crash.log——faulthandler 把崩溃瞬间的全线程 Python 栈写入
# RuntimeData/Shared/faulthandler.log（覆盖式，每次启动重建）。
# 必须在任何 Qt/扩展导入之前挂载。
_diag_dir = Path(__file__).resolve().parent / "RuntimeData" / "Shared"
try:
    _diag_dir.mkdir(parents=True, exist_ok=True)
    faulthandler.enable(
        file=open(_diag_dir / "faulthandler.log", "w", encoding="utf-8"),
        all_threads=True,
    )
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S')
logging.getLogger("PIL").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
logging.getLogger("PIL").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from AssetsManager.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
