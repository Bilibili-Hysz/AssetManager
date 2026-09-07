"""W3-3: 切库 A/B 十轮往返（20 次真实切换 + 活动请求 + 旧会话失效）。

In-process：真实 MainWindow 装配 + 两个合成库 A/B。每轮执行 A→B→A 两次
真实切换（经 workspace.add_library），共 10 轮 = 20 次切换。每次切换：

  1. 切换前：当前库 LAN 服务器（真实 LanServer + 密码鉴权）必须应答
     /api/files 且列表含当前库的文件名标记；
  2. 发起一个在途 HTTP 请求，50ms 后执行切换 —— 请求必须跨越切换边界
     并有界应答（不许悬挂，也不许让进程崩溃）；
  3. 切换后：旧 session 有界等待进入 closed；canonical session 指向新库；
  4. 新库 LAN 服务器 /api/files 必须列出新库文件名标记 —— 旧库数据失效、
     不再被服务。

末尾断言线程数与事件总线监听数不随轮次增长（监听与任务回收）。
任何失败 → 退出码 1。``--self-check`` 注入一个必然失败的断言，验证失败
确实能被上层识别（自身必须以退出码 1 结束）——防止失败被吞掉后探针空转。

Usage:
  python scripts/perf/w3_switch_roundtrip.py              # 验收
  python scripts/perf/w3_switch_roundtrip.py --self-check # 失败注入验证
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 运行域隔离：必须在任何 AssetsManager 导入前生效，否则持久化设置会把
# 用户真实工作区（上次的库）卷进本次验收 —— 本探针只允许触碰合成库。
os.environ.setdefault(
    "AM_RUNTIME_ROOT", tempfile.mkdtemp(prefix="w3-switch-runtime-")
)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ROOT = Path(__file__).resolve().parents[2]

ROUNDS = 10
SWITCH_TIMEOUT = 2.0        # 旧 session 关闭的有界等待
INFLIGHT_JOIN_TIMEOUT = 15.0
HTTP_TIMEOUT = 15.0
SWITCH_STAGGER = 0.05       # 在途请求先于切换起跑的窗口


def make_lib(root: Path, name: str, files: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(files):
        (root / f"{name}_{i:03d}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return root


def thread_count() -> int:
    return threading.active_count()


class LanHarness:
    """One real LAN server bound to one live runtime, with auth preflight."""

    def __init__(self, runtime):
        from AssetsManager.application.security_preflight import SecurityPreflight
        from AssetsManager.lan import LanServer
        from AssetsManager.lan.utils import generate_auth_token

        preflight = SecurityPreflight()
        preflight.confirm_authenticated_lan()
        self._server = LanServer(
            runtime=runtime,
            password="W3Switch-Roundtrip!",
            blur_tags=["private"],
            preflight=preflight,
        )
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        self._server.start(port=port, bind="127.0.0.1")
        self._token = generate_auth_token(self._server.token_secret)
        self.base_url = f"http://127.0.0.1:{port}"

    def get(self, path: str) -> tuple[int, str]:
        """One bounded authenticated GET. Returns (status, body-text)."""
        request = urllib.request.Request(f"{self.base_url}{path}")
        request.add_header("Cookie", f"lan_token={self._token}")
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def list_names(self) -> tuple[int, set[str]]:
        status, body = self.get("/api/files?sort=name&order=asc&summaries=false&limit=500")
        if status != 200:
            return status, set()
        payload = json.loads(body)
        items = payload.get("items") or payload.get("files") or []
        return status, {item.get("name", "") for item in items if isinstance(item, dict)}

    def stop(self) -> None:
        try:
            self._server.stop()
        except Exception:
            pass


def _fire_inflight(harness: LanHarness, results: dict) -> None:
    """One in-flight request recorded into ``results``."""
    try:
        status, _body = harness.get("/api/files?sort=name&order=asc&summaries=false&limit=500")
        results["status"] = status
    except Exception as exc:  # timeout / connection reset both count as answered
        results["error"] = f"{type(exc).__name__}: {exc}"[:200]


def main() -> int:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged
    from AssetsManager.window import MainWindow

    self_check = "--self-check" in sys.argv
    # 失败注入：自检模式把切换前数据校验的标记换成必然不存在的文件名，
    # 正常的失败上报路径必须把它记为 failure —— 否则说明失败会被静默吞掉。
    injected_marker = "zz_missing_injected_"

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

    bus = get_event_bus()
    thread_baseline = thread_count()
    listener_baseline = bus.handler_count(FileSystemChanged)

    def current_harness() -> LanHarness:
        live = bootstrap.library_service
        runtime = bootstrap.runtime_for(live.current_session)
        harness = LanHarness(runtime)
        harnesses.append(harness)
        return harness

    harnesses: list[LanHarness] = []
    failures: list[str] = []
    inflight_log: list[str] = []
    current = lib_a
    harness = current_harness()

    for round_no in range(1, ROUNDS + 1):
        for _leg in (0, 1):  # A→B→A：每轮两次真实切换
            nxt = lib_b if current == lib_a else lib_a
            want_marker = "b_0" if nxt == lib_b else "a_0"
            stale_marker = "a_0" if nxt == lib_b else "b_0"
            old_session = session

            # (1) 切换前：当前库服务器必须服务当前库数据
            check_marker = injected_marker if self_check else stale_marker
            status, names = harness.list_names()
            if status != 200:
                failures.append(f"round {round_no}: pre-switch /api/files -> HTTP {status}")
            elif not any(n.startswith(check_marker) for n in names):
                failures.append(
                    f"round {round_no}: pre-switch listing missing current-library "
                    f"marker {check_marker!r} (got {sorted(names)[:3]}...)"
                )

            # (2) 在途请求跨越切换边界
            inflight: dict = {}
            worker = threading.Thread(
                target=_fire_inflight, args=(harness, inflight), daemon=True
            )
            worker.start()
            time.sleep(SWITCH_STAGGER)

            window._workspace.add_library(str(nxt))
            app.processEvents()

            worker.join(timeout=INFLIGHT_JOIN_TIMEOUT)
            if worker.is_alive():
                failures.append(f"round {round_no}: in-flight request hung >{INFLIGHT_JOIN_TIMEOUT}s")
            else:
                outcome = inflight.get("status") or inflight.get("error")
                inflight_log.append(f"round {round_no}: {outcome}")
                if "error" in inflight and "timeout" in str(inflight["error"]).lower():
                    failures.append(f"round {round_no}: in-flight request timed out")

            # (3) 旧 session 关闭 + 新 session 就位
            live = bootstrap.library_service
            new_session = live.current_session
            if new_session is None:
                failures.append(f"round {round_no}: no current session after switch")
            else:
                if Path(str(new_session.root)).resolve() != nxt.resolve():
                    failures.append(
                        f"round {round_no}: current session on {new_session.root}, "
                        f"want {nxt.name}"
                    )
                if not live.owns_live_session(new_session):
                    failures.append(f"round {round_no}: current session not live-owned")
                session = new_session
            wait_deadline = time.perf_counter() + SWITCH_TIMEOUT
            while old_session.is_closed is False and time.perf_counter() < wait_deadline:
                app.processEvents()
                time.sleep(0.05)
            if old_session.is_closed is False:
                failures.append(
                    f"round {round_no}: old session still open after {SWITCH_TIMEOUT}s wait"
                )

            # (4) 新库服务器就绪：旧库数据失效；随即停掉旧服务器，保证
            # 任一时刻只有一个存活 harness（否则线程基线断言失真）。
            new_harness = current_harness()
            status, names = new_harness.list_names()
            if status != 200:
                failures.append(f"round {round_no}: post-switch /api/files -> HTTP {status}")
            elif not any(n.startswith(want_marker) for n in names):
                failures.append(
                    f"round {round_no}: post-switch listing missing new-library "
                    f"marker {want_marker!r} (got {sorted(names)[:3]}...)"
                )
            elif any(n.startswith(stale_marker) for n in names):
                failures.append(
                    f"round {round_no}: post-switch listing still serves stale "
                    f"library files ({stale_marker!r})"
                )
            harness.stop()
            harness = new_harness
            current = nxt

    for harness in harnesses:
        harness.stop()
    window.close()
    window.deleteLater()
    # 回收计数在全部拆除之后进行：先等待短命收尾线程（executor/后台渲染）
    # 退出 —— 连续 1s 无变化或到达 5s 上限即认为已稳定。
    app.processEvents()
    settle_deadline = time.perf_counter() + 5.0
    settled = thread_count()
    while time.perf_counter() < settle_deadline:
        time.sleep(0.25)
        app.processEvents()
        count_now = thread_count()
        if count_now == settled:
            break
        settled = count_now

    thread_after = settled
    listener_after = bus.handler_count(FileSystemChanged)
    # 容忍 +2：单飞接口枚举工作线程按设计常驻 1 条（Windows 解析器可能
    # 长时间阻塞），外加 1 条尚未退出的一次性收尾线程。
    if thread_after > thread_baseline + 2:
        from collections import Counter
        name_counts = Counter(t.name for t in threading.enumerate())
        failures.append(
            f"thread accumulation: {thread_baseline} → {thread_after} :: "
            + ", ".join(f"{n}×{c}" for n, c in name_counts.most_common(12))
        )
    if listener_after > listener_baseline:
        failures.append(f"bus listener accumulation: {listener_baseline} → {listener_after}")

    switches = ROUNDS * 2
    print(f"rounds: {ROUNDS} ({switches} switches)")
    print(f"thread baseline/after: {thread_baseline}/{thread_after}")
    print(f"bus FileSystemChanged listeners baseline/after: {listener_baseline}/{listener_after}")
    print("in-flight outcomes:")
    for line in inflight_log:
        print("  -", line)
    print(f"failures: {len(failures)}")
    for f in failures:
        print("  -", f)
    print("ROUNDTRIP:", "PASS" if not failures else "FAIL")
    import shutil
    if self_check:
        detected = any(injected_marker in f for f in failures)
        shutil.rmtree(tmp, ignore_errors=True)
        if detected:
            print("SELF-CHECK: OK (injected failure was reported)")
            return 0
        print("SELF-CHECK: FAIL (injected failure was NOT reported)")
        return 1
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
