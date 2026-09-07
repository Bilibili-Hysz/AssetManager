"""W3-1/W3-2: real-process startup matrix (plan W3 first two rows).

Child = 真实用户入口 `python main.py`（通过 runpy 复刻同一入口，见下），
隔离 AM_RUNTIME_ROOT + 种子化 settings.json：
  - mode "normal": window_maximized=False, recent_libraries 指向真实合成库
  - mode "maximized": window_maximized=True（PF-1/PF-5 崩溃触发器）
  - mode "missing_library": recent_libraries 指向不存在路径

Weekly-review 2026-09-07 缺陷修复：
  1. 矩阵此前只等 8 秒——入口先显示 StartupWindow，只有 library_opened 才构造
     MainWindow，因此 PF-1/PF-5 对应的 MainWindow 最大化恢复路径从未被执行。
     现在 normal/maximized 场景会创建真实存在的合成库（含文件）并写入
     recent_libraries；子进程 payload 在延迟插件发现完成后驱动 StartupWindow
     的 _accept（双击卡片路径）→ library_opened → _on_open →
     MainWindow(bootstrap) → _workspace.add_library → window.show() 完整构造。
  2. 就绪探针：monkeypatch MainWindow.show，在窗口可见后写入标记文件，内含
     show 时刻的 _pending_maximized（必须已被消费为 False）与 isMaximized()。
  3. faulthandler 路径：main.py 的 faulthandler 挂载是硬编码
     `Path(__file__).parent / "RuntimeData" / "Shared"`（main.py:12-20），
     不经过 path_resolver——AM_RUNTIME_ROOT 对它无效。因此崩溃栈永远写在
     源码根 RuntimeData/Shared/faulthandler.log（旧脚本误查
     AM_RUNTIME_ROOT/Shared/）。子进程串行运行且每次启动以 "w" 截断该文件，
     所以子进程退出后文件内容即该子进程的会话记录。
  4. 优雅关闭：offscreen 平台的原生窗口收不到 taskkill /PID 的 WM_CLOSE
     （实测 taskkill 报“已发送终止信号”但进程 20s 后仍存活），因此改为文件
     哨兵：子进程 200ms 轮询 close.request，出现后走应用真实退出路径
     （MainWindow.request_exit() / StartupWindow.close() → closeEvent →
     _shutdown_resources → 几何持久化 → 最后窗口关闭退出）。窗口关闭语义
     （closeEvent 持久化 + exit 0）不变，只是触发方式适配 offscreen。
     超时仍回退 taskkill /F（此时 graceful_close=False）。
  5. 单实例锁：跨进程用户便利锁与启动路径测试无关，且 offscreen 下的
     "已有实例" 模态框无法点击会卡死后续子进程（实测踩坑）；子进程 payload
     在入口运行前短路 _bind_single_instance。
  6. maximized 场景断言：进程存活 + 无 crash + window_maximized 持久化为
     True + _pending_maximized 在 show 时已消费（不再为 True）。
  7. 任何断言失败最终 sys.exit(1) 非零退出。

Usage: python scripts/perf/w3_process_matrix.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# main.py hardcodes its faulthandler target at the SOURCE root (main.py:12-20);
# it never consults path_resolver / AM_RUNTIME_ROOT.
FAULTHANDLER_LOG = ROOT / "RuntimeData" / "Shared" / "faulthandler.log"

ALIVE_WINDOW_S = 8.0
READY_TIMEOUT_S = 180.0
CLOSE_TIMEOUT_S = 45.0

CHILD = r'''
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ["AM_REPO_ROOT"])
sys.path.insert(0, str(ROOT))
sys.argv = [str(ROOT / "main.py")]

# ── Readiness probe: MainWindow fully constructed + visible ──────────────
# Patch BEFORE the real entry runs; MainWindow is our own Python class, so
# the monkeypatch is plain attribute assignment.  show() is called by
# app._on_open only AFTER MainWindow(bootstrap) finished (including the
# PF-5 deferred showMaximized inside __init__), so the marker proves the
# full construction path ran.
from AssetsManager.window import MainWindow  # noqa: E402

mw_marker = Path(os.environ["AM_MW_MARKER"])
_orig_mw_show = MainWindow.show


def _probed_mw_show(self, *args, **kwargs):
    result = _orig_mw_show(self, *args, **kwargs)
    try:
        mw_marker.write_text(json.dumps({
            # PF-1/PF-5 recovery contract: the deferred maximized flag must
            # already be consumed when the window becomes visible.
            "pending_maximized_at_show": bool(getattr(self, "_pending_maximized", False)),
            "is_maximized": bool(self.isMaximized()),
            "window_title": self.windowTitle(),
        }), encoding="utf-8")
    except Exception:
        import traceback
        mw_marker.write_text(
            json.dumps({"probe_error": traceback.format_exc()}), encoding="utf-8")
    return result


MainWindow.show = _probed_mw_show

# ── Graceful close via file sentinel ─────────────────────────────────────
# Offscreen platform windows never receive taskkill's WM_CLOSE (verified:
# taskkill reports the signal sent, the process keeps running).  The parent
# touches close.request; we then drive the app's REAL exit path —
# MainWindow.request_exit() (tray-exit semantics: _force_quit + close) or
# StartupWindow.close() — so closeEvent, geometry persistence and the
# last-window-closed quit all run exactly as in production.
close_request = Path(os.environ["AM_CLOSE_REQUEST"])


def _poll_close():
    if not close_request.exists():
        QTimer.singleShot(200, _poll_close)
        return
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        try:
            if isinstance(widget, MainWindow):
                widget.request_exit()
            elif isinstance(widget, StartupWindow):
                widget.close()
        except RuntimeError:
            pass  # already torn down


# ── Startup-window probe + auto-open driver ──────────────────────────────
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from AssetsManager.dialogs.startup import StartupWindow  # noqa: E402

startup_marker = Path(os.environ["AM_STARTUP_MARKER"])
target_lib = os.environ.get("AM_AUTO_OPEN_LIB", "")
_orig_startup_show = StartupWindow.show


def _probed_startup_show(self, *args, **kwargs):
    result = _orig_startup_show(self, *args, **kwargs)
    try:
        startup_marker.write_text("StartupWindow visible", encoding="utf-8")
    except Exception:
        pass
    # The QApplication now exists (main() created it), so the close-sentinel
    # poller can be scheduled here — NOT at payload import time (a timer
    # scheduled before QApplication never fires).
    QTimer.singleShot(200, _poll_close)
    if target_lib:
        # The real picker needs a double-click on a library card; drive the
        # same _accept path.  Defer until the deferred plugin discovery
        # (QTimer.singleShot(0) in app.main) has published
        # plugin_host_context, keeping app.py's documented ordering
        # guarantee (discovery completes before _on_open fires).
        state = {"attempts": 0}

        def _try_accept():
            state["attempts"] += 1
            app = QApplication.instance()
            if app is None:
                return
            if app.property("plugin_host_context") is None and state["attempts"] < 400:
                QTimer.singleShot(50, _try_accept)
                return
            if Path(target_lib).exists():
                self._accept(target_lib)

        QTimer.singleShot(50, _try_accept)
    return result


StartupWindow.show = _probed_startup_show

# ── Single-instance lock short-circuit ───────────────────────────────────
# The per-user convenience lock is unrelated to the startup paths under
# test, and its "already running" modal cannot be dismissed offscreen — a
# previous stuck child would wedge every later run (observed in practice).
import AssetsManager.app as _app_mod  # noqa: E402

_app_mod._bind_single_instance = lambda app: True

# ── Real user entry: main.py module body (faulthandler mount included) ──
import runpy  # noqa: E402

runpy.run_path(str(ROOT / "main.py"), run_name="__main__")
'''


def build_synthetic_library(lib_dir: Path) -> None:
    """A real, openable library root (a few files) for recent_libraries."""
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 64)
    (lib_dir / "scene.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"2" * 64)
    nested = lib_dir / "nested"
    nested.mkdir(exist_ok=True)
    (nested / "deep.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"3" * 64)


def seed_settings(runtime: Path, mode: str) -> Path | None:
    shared = runtime / "Shared"
    shared.mkdir(parents=True, exist_ok=True)
    settings: dict = {"language": "en", "theme": "Navy"}
    settings["window_maximized"] = mode == "maximized"
    lib_dir: Path | None = None
    if mode in ("normal", "maximized"):
        lib_dir = runtime / "synthetic_library"
        build_synthetic_library(lib_dir)
        settings["recent_libraries"] = [str(lib_dir)]
    elif mode == "missing_library":
        settings["recent_libraries"] = [str(runtime / "does_not_exist")]
    (shared / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    return lib_dir


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _crash_flag() -> bool:
    # See module docstring: main.py writes the faulthandler log at the source
    # root regardless of AM_RUNTIME_ROOT; each child truncates it at startup.
    if not FAULTHANDLER_LOG.exists():
        return False
    text = FAULTHANDLER_LOG.read_text(encoding="utf-8", errors="ignore")
    return "Current thread" in text


def run_child(mode: str) -> dict:
    runtime = Path(tempfile.mkdtemp(prefix=f"w3-{mode}-"))
    result: dict = {"mode": mode}
    keep_for_debug = False
    try:
        lib_dir = seed_settings(runtime, mode)
        mw_marker = runtime / "mainwindow_visible.json"
        startup_marker = runtime / "startup_visible.marker"
        close_request = runtime / "close.request"
        child_src = runtime / "w3_child.py"
        child_src.write_text(CHILD, encoding="utf-8")

        env = dict(os.environ)
        env.update({
            "AM_REPO_ROOT": str(ROOT),
            "AM_RUNTIME_ROOT": str(runtime),
            "QT_QPA_PLATFORM": "offscreen",
            "AM_MW_MARKER": str(mw_marker),
            "AM_STARTUP_MARKER": str(startup_marker),
            "AM_CLOSE_REQUEST": str(close_request),
        })
        if lib_dir is not None:
            env["AM_AUTO_OPEN_LIB"] = str(lib_dir)

        # Child output goes to files: logging output is large enough to fill
        # a subprocess PIPE and deadlock the startup.
        out_log = open(runtime / "child_stdout.log", "w", encoding="utf-8")
        err_log = open(runtime / "child_stderr.log", "w", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, str(child_src)],
            env=env, cwd=str(ROOT), stdout=out_log, stderr=err_log,
        )

        # 1) ALIVE 8s：PF-1 类构造崩溃在此窗口内即死
        deadline = time.perf_counter() + READY_TIMEOUT_S
        while time.perf_counter() < deadline:
            if proc.poll() is not None:
                break
            if mw_marker.exists() or (
                mode == "missing_library" and startup_marker.exists()
            ):
                elapsed = READY_TIMEOUT_S - (deadline - time.perf_counter())
                if elapsed < ALIVE_WINDOW_S:
                    time.sleep(ALIVE_WINDOW_S - elapsed)
                if proc.poll() is not None:
                    break
                result["alive_8s"] = True
                break
            time.sleep(0.2)
        else:
            result["alive_8s"] = proc.poll() is None
        if not result.get("alive_8s"):
            # Process died before proving readiness: native crash / traceback.
            out_log.close()
            err_log.close()
            result["alive_8s"] = False
            result["exit_code"] = proc.returncode
            result["crash_flag"] = _crash_flag()
            result["stderr_tail"] = _tail(runtime / "child_stderr.log")
            keep_for_debug = True
            return result

        # 2) 优雅关闭：文件哨兵 → 子进程走真实退出路径（closeEvent → 几何持久化
        #    → 最后窗口关闭退出）。offscreen 收不到 WM_CLOSE，见模块 docstring。
        close_request.write_text("close", encoding="utf-8")
        try:
            proc.wait(timeout=CLOSE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/F", "/PID", str(proc.pid)], capture_output=True)
            proc.wait(timeout=10)
        out_log.close()
        err_log.close()

        mw_probe = _read_json(mw_marker)
        settings_after = _read_json(runtime / "Shared" / "settings.json")
        result.update({
            "exit_code": proc.returncode,
            "graceful_close": proc.returncode == 0,
            "crash_flag": _crash_flag(),
            "startup_visible": startup_marker.exists(),
            "mainwindow_visible": mw_marker.exists(),
            "probe": mw_probe,
            "pending_maximized_consumed": (
                mw_marker.exists() and mw_probe.get("pending_maximized_at_show") is False
            ),
            "window_geometry_persisted": bool(settings_after.get("window_geometry")),
            "window_maximized_after": settings_after.get("window_maximized"),
        })
        if mode == "maximized":
            result["is_maximized_at_show"] = mw_probe.get("is_maximized") is True
            result["maximized_persisted"] = settings_after.get("window_maximized") is True
        return result
    finally:
        if keep_for_debug:
            print(f"[{mode}] runtime kept for debugging: {runtime}", flush=True)
        else:
            shutil.rmtree(runtime, ignore_errors=True)


def _tail(path: Path, limit: int = 800) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[-limit:]
    except OSError:
        return ""


def _row_ok(r: dict) -> bool:
    if not r.get("alive_8s") or not r.get("graceful_close") or r.get("crash_flag"):
        return False
    if r["mode"] == "missing_library":
        return r.get("startup_visible") and not r.get("mainwindow_visible")
    return (
        r.get("mainwindow_visible")
        and r.get("pending_maximized_consumed")
        and r.get("window_geometry_persisted")
        and (r.get("window_maximized_after") is False if r["mode"] == "normal" else True)
        and (r.get("maximized_persisted") and r.get("is_maximized_at_show")
             if r["mode"] == "maximized" else True)
    )


def main() -> int:
    results = []
    for mode in ("normal", "maximized", "maximized", "missing_library"):
        r = run_child(mode)
        r["ok"] = _row_ok(r)
        results.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    ok = all(r["ok"] for r in results)
    print("MATRIX:", "PASS" if ok else "FAIL")
    if not ok:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
