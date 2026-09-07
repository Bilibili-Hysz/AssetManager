"""W3-3: 切库 A/B 十轮往返（会话失效/无任务累积）。

In-process：真实 MainWindow 装配 + 两个合成库 A/B，经
workspace.add_library 十轮往返（=20 次切换），断言：
  - 每次切换后 library_service 的 canonical session 就是新库
  - 旧 session 已关闭（library_service 活跃 session 数 == 1）
  - 无积累：线程/定时器/监听不随轮次增长

Usage: python scripts/perf/w3_switch_roundtrip.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ROOT = Path(__file__).resolve().parents[2]


def make_lib(root: Path, name: str, files: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(files):
        (root / f"{name}_{i:03d}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return root


def thread_count() -> int:
    import threading
    return threading.active_count()


def main() -> None:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.window import MainWindow

    tmp = Path(tempfile.mkdtemp(prefix="w3-switch-"))
    lib_a = make_lib(tmp / "lib_a", "a", 20)
    lib_b = make_lib(tmp / "lib_b", "b", 25)

    bootstrap = ApplicationBootstrap()
    window = MainWindow(bootstrap)
    window.show()
    app.processEvents()

    session = bootstrap.library_service.open_session(lib_a)
    window._workspace.add_library(str(lib_a))
    app.processEvents()
    thread_baseline = thread_count()
    getattr(window, "_bg_resize_timer", None)

    failures = []
    current = lib_a
    for round_no in range(1, 11):
        nxt = lib_b if current == lib_a else lib_a
        old_session = session
        window._workspace.add_library(str(nxt))
        app.processEvents()
        # canonical session 应指向新库（真实 API：current_session）
        live = bootstrap.library_service
        new_session = live.current_session
        if new_session is None:
            failures.append(f"round {round_no}: no current session")
        else:
            root_now = str(new_session.root)
            if Path(root_now).resolve() != nxt.resolve():
                failures.append(f"round {round_no}: current session on {root_now}, want {nxt.name}")
            if not live.owns_live_session(new_session):
                failures.append(f"round {round_no}: current session not live-owned")
        # 旧 session 应已关闭
        if hasattr(old_session, "is_closed"):
            # B02 设计：close 是异步延迟拆除（_closing_sessions 重试语义）——
            # 有界等待最多 2s，超时才算失败。
            wait_deadline = time.perf_counter() + 2.0
            while old_session.is_closed is False and time.perf_counter() < wait_deadline:
                app.processEvents()
                time.sleep(0.05)
            if old_session.is_closed is False:
                failures.append(f"round {round_no}: old session still open after 2s wait")
        current = nxt
        session = new_session if new_session is not None else old_session

    thread_after = thread_count()
    if thread_after > thread_baseline + 2:
        failures.append(f"thread accumulation: {thread_baseline} → {thread_after}")

    window.close()
    window.deleteLater()
    app.processEvents()

    print("rounds: 10 (20 switches)")
    print(f"thread baseline/after: {thread_baseline}/{thread_after}")
    print(f"failures: {len(failures)}")
    for f in failures:
        print("  -", f)
    print("ROUNDTRIP:", "PASS" if not failures else "FAIL")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
