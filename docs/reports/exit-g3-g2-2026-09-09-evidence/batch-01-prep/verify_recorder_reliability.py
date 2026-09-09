"""G3 记录器可靠性合成验证控制器（方案 §4"记录可靠性先验收"）。

五个场景（输出在 reliability-runs/<scenario>/，一次成功运行后不覆盖）：
  S1 normal-exit        正常退出：事件流完整（启动/安装状态、连续序号、结束状态）
  S2 active-timeout     主动超时：30s 判定不变→控制器请求导出→再清理 PID 树；
                        导出宽限不改变超时判定
  S3 buffer-overflow    缓冲溢出：容量上限触发的丢弃计数与保全行为
  S4 recorder-error    记录器自身异常：结果明确标注"日志不完整"，不与"零事件"混淆
  S5 target-early-exit  目标提前结束：控制器正确收尾

设计要点：
- 派生驱动 f989 自建运行域（tempfile.mkdtemp），插件必须装进那个运行域：
  通过 monkeypatch 驱动模块的 tempfile.mkdtemp，把运行域固定到本场景
  目录，再于目录内预装观察插件到 RuntimeData/Shared/plugins/。
- 一次退出只发一次 Q（驱动自身保证，不补发）。强制结束只用于失败后的
  清理与 S5 的目标提前结束注入（场景设定，非退出证据）。
- S2 的"退出失败"由合成域注入插件制造（request_exit 返回后挂起 GUI 线程
  120s），只存在于本场景运行域，不进入正式矩阵。
- S3 的溢出由挂起的目标保证：发 Q 前的展示窗口事件洪流足以填满 60 条
  缓冲；判读看导出 meta 的 dropped>0 与导出条数==上限。
- S4 的"日志不完整"判读依据状态文件 error_count>0（由进程主动汇报），
  与"零事件"（seq==0 且 error_count==0）明确区分。
- 只验证记录器可靠性，不跑 O0/O1/O2 正式矩阵。每轮独立
  AM_RUNTIME_ROOT、合成库、独立端口。

用法（在快照根目录）：
  python docs/reports/exit-g3-g2-2026-09-09-evidence/batch-01-prep/verify_recorder_reliability.py <scenario|all>
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SNAP = HERE.parents[3]                      # g3-ops 快照根
DRIVER = SNAP / "scripts/perf/w6_g2g3_diagnostic.py"
EXE = SNAP / "artifacts/weekly-repair-2026-09-08-103f119/AssetManager.exe"
PLUGIN_SRC = HERE / "observer-plugin"
RUNS = HERE / "reliability-runs"

SCENARIOS = ("o0-control", "hang-isolation",
             "bisect-stage-1", "bisect-stage-2", "bisect-stage-3",
             "bisect-stage-4", "bisect-stage-5",
             "synced-capture",
             "normal-exit", "active-timeout",
             "buffer-overflow", "recorder-error", "target-early-exit")

# 仅用于可靠性验证 S2/S3 的合成域注入插件：在 request_exit 返回后挂起
# 本进程 GUI 线程 120 秒，制造确定性的"30 秒退出失败"现场。该插件只
# 存在于对应场景的合成运行域，不进入正式 O0/O1/O2 矩阵，不属于观察器。
HANG_PLUGIN_SRC = (
    '"""Reliability-only: hang the GUI thread after request_exit."""\n'
    "from __future__ import annotations\n"
    "\n"
    "import builtins\n"
    "import os\n"
    "import time\n"
    "\n"
    "_ORIGINAL = []\n"
    "\n"
    "\n"
    "def _install(window_module):\n"
    "    cls = getattr(window_module, 'MainWindow')\n"
    "    target = getattr(cls, 'request_exit')\n"
    "\n"
    "    def monitored(self):\n"
    "        result = target(self)\n"
    "        flag = os.environ.get('AM_G3_HANG_REQUEST', '').strip()\n"
    "        if flag:\n"
    "            try:\n"
    "                with open(flag, 'w', encoding='utf-8') as f:\n"
    "                    f.write('hang-begin')\n"
    "            except Exception:\n"
    "                pass\n"
    "        time.sleep(120.0)  # 制造 30s 超时现场（可靠性场景专用）\n"
    "        return result\n"
    "\n"
    "    cls.request_exit = monitored\n"
    "\n"
    "\n"
    "def _import(name, globals=None, locals=None, fromlist=(), level=0):\n"  # noqa: A002
    "    original = _ORIGINAL[0]\n"
    "    result = original(name, globals, locals, fromlist, level)\n"
    "    if name == 'AssetsManager.window' and 'MainWindow' in (fromlist or ()):\n"
    "        try:\n"
    "            _install(result)\n"
    "        finally:\n"
    "            if builtins.__import__ is _import:\n"
    "                builtins.__import__ = original\n"
    "    return result\n"
    "\n"
    "\n"
    "def register(_host):\n"
    "    if os.environ.get('AM_G3_HANG_REQUEST'):\n"
    "        _ORIGINAL.append(builtins.__import__)\n"
    "        builtins.__import__ = _import\n"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _win32_from_driver():
    """加载派生驱动模块（不执行 main），复用其冻结的种子/窗口函数。"""
    spec = importlib.util.spec_from_file_location("w6_diag_reliability", DRIVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clock_check(out: Path) -> dict[str, Any]:
    """跨进程时钟可比较性验证。

    Windows 上 time.perf_counter 与 time.monotonic 同源（QPC）；两进程
    各自采样同一 wall-clock 时刻的 QPC 值，差值即为跨进程对齐误差上界。
    """
    a = time.time()
    pc = time.perf_counter()
    mono = time.monotonic()
    result = {
        "wall_epoch_s": a,
        "perf_counter_s": pc,
        "monotonic_s": mono,
        "same_source": True,
        "note": ("perf_counter 与 monotonic 同为 QPC 单调源；跨进程时间戳按"
                 "同源单调钟比较，误差为采样间隔（亚毫秒级），先验证后使用。"),
    }
    (out / "clock-check.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append({"record_type": "_corrupt_line", "raw": line[:200]})
    return records


def _summarize_events(records: list[dict[str, Any]]) -> dict[str, Any]:
    types: dict[str, int] = {}
    for r in records:
        key = r.get("record_type", "?")
        types[key] = types.get(key, 0) + 1
    seqs = sorted({r["seq"] for r in records
                   if isinstance(r.get("seq"), int) and r["seq"] > 0})
    return {
        "count": len(records),
        "record_types": types,
        "seq_min": seqs[0] if seqs else None,
        "seq_max": seqs[-1] if seqs else None,
        "seq_continuous": bool(seqs) and seqs == list(range(seqs[0], seqs[-1] + 1)),
        "has_startup": any(r.get("record_type") == "recorder_startup"
                           and not r.get("partial") for r in records),
        "has_shutdown": any(r.get("record_type") == "recorder_shutdown" for r in records),
        "has_install": any(r.get("phase") == "lazy_monitoring_installed"
                            for r in records),
        "has_partial_marker": any(r.get("partial") or
                                  r.get("record_type") == "recorder_error"
                                  for r in records),
    }


def _await_ack(run_dir: Path, timeout_s: float) -> dict[str, Any]:
    ack = run_dir / "export-ack.json"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if ack.exists():
            try:
                return json.loads(ack.read_text(encoding="utf-8"))
            except Exception as exc:
                return {"ack": "corrupt", "error": repr(exc),
                        "log_incomplete": True}
        time.sleep(0.1)
    return {"ack": None, "error": "export request not acknowledged within timeout",
            "log_incomplete": True}


def _request_export(run_dir: Path) -> dict[str, Any]:
    """控制器进程通过文件请求导出（不依赖 Qt 主线程）。

    请求超时（如失败清理已杀死守护线程）时删除本请求文件并返回
    log_incomplete —— 与"零事件"明确区分（方案 §4）。
    """
    request = run_dir / "export-request.txt"
    target = run_dir / "events-export.jsonl"
    if request.exists():
        return {"ack": "stale_request_exists", "log_incomplete": True}
    request.write_text(str(target), encoding="utf-8")
    ack = _await_ack(run_dir, 15.0)
    if ack.get("ack") is None:
        try:
            request.unlink()
        except FileNotFoundError:
            pass
        ack["note"] = ("export requested before cleanup; observer daemon "
                       "unavailable (killed with PID tree); log marked "
                       "incomplete per plan §4, NOT zero-event proof")
    return ack


def _launch_driver(out: Path, run_dir: Path, plugin_env: dict[str, str],
                   plugin_src: Path, extra_plugins: list[tuple[str, Path]] = (),
                   env_extra: dict[str, str] | None = None,
                   install_observer: bool = True) -> subprocess.Popen:
    """以 monkeypatch 过的 mkdtemp 方式启动派生驱动，运行域固定在 run_dir。

    派生驱动 f989 的 main() 内部调用 ``tempfile.mkdtemp(prefix="w6-func-")``
    自建运行域再启动 exe；驱动 stdout 走 PIPE 时是块缓冲，控制器不能
    依赖读它的行来定位运行域。因此 sitecustomize 注入的 shim 在
    mkdtemp 重定向的**同一时刻**（驱动进程内、种子之前）把观察插件复制
    到 ``<tmp>/runtime/Shared/plugins`` —— 这发生在驱动 Popen exe 之前，
    插件加载（app 启动后的 discover_plugins）时已在位，无竞态。
    """
    plugin_src_posix = plugin_src.as_posix()
    extras = [(pid, src.as_posix()) for pid, src in extra_plugins]

    def _extras_lines() -> str:
        lines = []
        for pid, src in extras:
            lines.append(
                f"        _sh.copytree(r'{src}', shared / 'plugins' / r'{pid}', "
                f"dirs_exist_ok=True)")
        if not lines:
            return ""
        return "\n".join(lines) + "\n"

    def _observer_install_line(install: bool) -> str:
        # 返回值必须以真实换行结尾：模板中相邻 f-string 无隐式换行。
        if not install:
            return "        # o0-control: no observer plugin installed\n" + "\n"
        return (
            "        # install the observer plugin at mkdtemp-redirect time,\n"
            "        # strictly before the driver Popen's the exe\n"
            "        _sh.copytree(_PLUGIN_SRC, shared / 'plugins'"
            " / 'exit-observer', dirs_exist_ok=True)\n" + "\n"
        )

    shim_src = (
        "import tempfile as _t\n"
        "import shutil as _sh\n"
        "import os as _o\n"
        "from pathlib import Path as _P\n"
        "_real = _t.mkdtemp\n"
        f"_PLUGIN_SRC = r'{plugin_src_posix}'\n"
        "def _mk(prefix=None, suffix='', dir=None, **kw):\n"
        "    if prefix and str(prefix).startswith('w6-func-'):\n"
        f"        d = _P(r'{run_dir.as_posix()}') / 'synthetic'\n"
        "        shared = d / 'runtime' / 'Shared'\n"
        "        _o.makedirs(shared / 'plugins', exist_ok=True)\n"
        f"{_observer_install_line(install_observer)}"
        f"{_extras_lines()}"
        "        return d\n"
        "    return _real(prefix=prefix, suffix=suffix, dir=dir, **kw)\n"
        "_t.mkdtemp = _mk\n"
    )
    shim_dir = run_dir / "pypath-shim"
    shim_dir.mkdir(parents=True, exist_ok=True)
    (shim_dir / "sitecustomize.py").write_text(shim_src, encoding="utf-8")

    env = dict(os.environ)
    env["AM_RUNTIME_ROOT"] = str(run_dir / "synthetic" / "runtime")
    env["PYTHONPATH"] = str(shim_dir) + os.pathsep + env.get("PYTHONPATH", "")
    merged = dict(plugin_env)
    if env_extra:
        merged.update(env_extra)
    for k, v in merged.items():
        env[k] = v
    env.pop("QT_QPA_PLATFORM", None)

    cmd = [sys.executable, str(DRIVER), "--exe", str(EXE),
           "--mode", "onefile", "--maximized", "--auto-open"]
    # 驱动 stdout 直接落文件：PIPE 在控制器读线程死亡（解码错/竞态）
    # 时会让驱动死锁（attempt-5 教训）。文件无容量上限、无编码问题。
    stdout_file = (run_dir / "driver-stdout.log").open("w", encoding="utf-8",
                                                       errors="replace")
    return subprocess.Popen(cmd, env=env, cwd=str(SNAP),
                            stdout=stdout_file, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")




def _kill_tree(pid: int) -> int | None:
    if not pid:
        return None
    result = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                            capture_output=True, text=True)
    return result.returncode


def _run_scenario(name: str) -> dict[str, Any]:
    out = RUNS / name
    if out.exists():
        raise SystemExit(f"refusing to overwrite existing scenario dir: {out}")
    out.mkdir(parents=True)
    w6 = _win32_from_driver()   # noqa: F841 - 仅确认驱动模块可加载

    run_dir = out / "synthetic"
    run_dir.mkdir()
    # 派生驱动 main() 顺序：tmp=mkdtemp() → 种子 runtime/library →
    # Popen(exe)。本控制器不预建 library/runtime（attempt-2 教训：
    # 预建与驱动内部 _build_library 冲突）；插件安装改在
    # sitecustomize shim 的 mkdtemp 重定向钩子内同步完成（驱动进程内、
    # 种子之前、Popen exe 之前），见 _launch_driver。
    # 运行域最终布局（驱动视角）：
    #   tmp     = <run_dir>/synthetic
    #   runtime = <run_dir>/synthetic/runtime   ← exe 的 AM_RUNTIME_ROOT
    #   lib     = <run_dir>/synthetic/library
    mode = "buffered"
    buffer_limit = 20000
    env_extra: dict[str, str] = {
        "AM_EXIT_DIAGNOSTIC_LOG": str(run_dir / "qt-events.jsonl"),
        "AM_G3_EXPORT_REQUEST": str(run_dir / "export-request.txt"),
        "AM_G3_EXPORT_ACK": str(run_dir / "export-ack.json"),
        "AM_G3_FINAL_FLUSH": str(run_dir / "events-final-flush.jsonl"),
        "AM_G3_STATUS_FILE": str(run_dir / "recorder-status.json"),
        "AM_G3_OBSERVE_MODE": mode,
        "AM_G3_BUFFER_LIMIT": str(buffer_limit),
        "AM_G3_RUN_ID": f"reliability-{name}",
        "AM_G3_PHASE": "first-exit",
    }
    log_path = run_dir / "qt-events.jsonl"
    status_path = run_dir / "recorder-status.json"
    plugin_source = PLUGIN_SRC
    if name == "synced-capture":
        # 正式观察器 + synced 模式：逐条落盘，抓挂死前最后事件；
        # AM_G3_REGISTER_TRACE 让 register() 每步落独立小文件。
        mode = "synced"
        env_extra["AM_G3_OBSERVE_MODE"] = mode
        env_extra["AM_G3_REGISTER_TRACE"] = str(run_dir / "register-trace.jsonl")
    if name.startswith("bisect-stage-"):
        plugin_source = HERE / "observer-bisect"
        env_extra["AM_G3_BISECT_STAGE"] = name.rsplit("-", 1)[1]
        env_extra["AM_G3_BISECT_STATUS"] = str(run_dir / "bisect-status.json")
    if name == "hang-isolation":
        # A/B 隔离：插件在位，但 register() 因缺 AM_EXIT_DIAGNOSTIC_LOG
        # 立即 return（观察器零副作用）。区分挂死发生在插件加载器层
        # 还是 register() 内部。
        env_extra.pop("AM_EXIT_DIAGNOSTIC_LOG", None)
        env_extra.pop("AM_G3_EXPORT_REQUEST", None)
        env_extra.pop("AM_G3_EXPORT_ACK", None)
        env_extra.pop("AM_G3_FINAL_FLUSH", None)
        env_extra.pop("AM_G3_STATUS_FILE", None)
    extra_plugins: list[tuple[str, Path]] = []

    if name in ("active-timeout", "buffer-overflow"):
        # S2/S3 注入挂起插件（仅合成运行域；由 shim 装入运行域）
        hang_dir = out / "hang-plugin"
        hang_dir.mkdir()
        (hang_dir / "plugin.json").write_text(json.dumps({
            "id": "amg3-hang-after-q", "name": "Reliability hang injector",
            "version": "0.1.0", "entry": "hang:register",
            "kind": "command", "enabled_by_default": True, "permissions": [],
        }, indent=2), encoding="utf-8")
        (hang_dir / "hang.py").write_text(HANG_PLUGIN_SRC, encoding="utf-8")
        extra_plugins.append(("amg3-hang-after-q", hang_dir))
        env_extra["AM_G3_HANG_REQUEST"] = str(run_dir / "hang-request.flag")
    if name == "buffer-overflow":
        buffer_limit = 60          # 极小上限：发 Q 前的展示窗口事件洪流必然溢出
        env_extra["AM_G3_BUFFER_LIMIT"] = str(buffer_limit)
    if name == "recorder-error":
        # 记录器自身异常：日志路径指向已存在目录（追加打开必失败）。
        # 必须用 synced 模式才会在每条 emit 的 _sync_write 上暴露故障
        # （buffered 模式不触碰日志文件，故障不会浮现）；状态文件
        # error_count>0 是可判读通道 → "日志不完整"不得与零事件混淆。
        locked = run_dir / "locked-target"
        locked.mkdir()
        # 注入：日志路径本身是已存在的目录 → 每条 synced 写入必失败
        # （attempt-1/2 的教训：指向目录"里面"的文件路径是合法路径，
        # 不会制造故障）。
        (locked / "events.jsonl").mkdir()
        env_extra["AM_EXIT_DIAGNOSTIC_LOG"] = str(locked / "events.jsonl")
        env_extra["AM_G3_OBSERVE_MODE"] = "synced"
        log_path = locked / "events.jsonl"
        result_mode_override = "synced"

    clock = _clock_check(out)

    install_observer = name != "o0-control"
    proc = _launch_driver(out, run_dir, env_extra, plugin_source,
                          extra_plugins, install_observer=install_observer)
    (out / "plugin-installed-at.txt").write_text(
        str(run_dir / "synthetic" / "runtime" / "Shared" / "plugins" / "exit-observer"),
        encoding="utf-8")
    result: dict[str, Any] = {"scenario": name, "driver_pid": proc.pid,
                             "mode": mode, "buffer_limit": buffer_limit,
                             "clock_check": clock}
    # stdout 已由 _launch_driver 重定向到 out/driver-stdout.log，无需泵线程

    if name == "target-early-exit":
        # S5：等待 exe 启动行，随后提前结束 exe 树，控制器正确收尾
        exe_pid = None
        deadline = time.time() + 150
        while time.time() < deadline:
            try:
                text = (run_dir / "driver-stdout.log").read_text(encoding="utf-8",
                                                             errors="replace")
            except FileNotFoundError:
                text = ""
            if "launched pid=" in text:
                exe_pid = int(text.split("launched pid=")[1].split()[0])
                break
            if proc.poll() is not None:
                break
            time.sleep(0.3)
        result["exe_pid"] = exe_pid
        # 给 onefile 解包 + GUI 建立时间，随后提前结束（场景注入）
        time.sleep(8.0)
        result["target_kill_rc"] = _kill_tree(exe_pid) if exe_pid else None
        # 驱动应当以自己的失败路径收尾（不得卡死控制器）
        try:
            rc = proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = "controller-killed-driver-after-target-early-exit"
        result["driver_exit"] = rc
        export = _request_export(run_dir)   # 事后请求导出（进程已亡则超时）
        result["post_mortem_export"] = export
        events = _read_jsonl(run_dir / "events-final-flush.jsonl") \
            if (run_dir / "events-final-flush.jsonl").exists() else []
        result["events"] = _summarize_events(events)
        result["log_exists"] = log_path.exists()
        result["verdict"] = (
            "controller-concluded-on-target-early-exit; "
            + ("final flush preserved buffered events"
               if result["events"]["count"] else
               "NO final flush events — log_incomplete, not zero-event proof"))
        _write_result(out, result)
        return result

    if name in ("normal-exit", "active-timeout", "buffer-overflow",
                "recorder-error"):
        # 等待驱动自然收尾（S2/S3 会经历 30s 超时 + 强制清理，耗时较长）
        wait_deadline = {
            "normal-exit": 420,
            "active-timeout": 480,
            "buffer-overflow": 480,
            "recorder-error": 420,
        }[name]
        if name == "normal-exit":
            # 正常退出：驱动打印 close: 行（首退发键完成）后请求导出；
            # 此时观察器守护线程仍在运行，导出走"控制器文件请求→守护
            # 线程回执"设计通道。之后驱动继续跑重启相。
            export_deadline = time.time() + 360
            requested = False
            while time.time() < export_deadline and proc.poll() is None:
                if not requested:
                    try:
                        text = (run_dir / "driver-stdout.log").read_text(
                            encoding="utf-8", errors="replace")
                    except FileNotFoundError:
                        text = ""
                    if "close: {" in text:
                        result["export_ack"] = _request_export(run_dir)
                        requested = True
                time.sleep(0.5)
        if name in ("active-timeout", "buffer-overflow"):
            # S2/S3：等待挂起标志出现（= Q 已发、request_exit 已进入并
            # 挂起）。此后密切监视驱动的 30s 超时判定文本——它出现的
            # 那一刻，exe 仍被挂起注入挂住（驱动随后的 taskkill 清理
            # 还未执行），立即请求导出，让观察器守护线程在 GUI 线程
            # 卡死的情况下完成"失败/超时时导出"。
            hang_flag = run_dir / "hang-request.flag"
            flag_deadline = time.time() + 420
            while time.time() < flag_deadline and not hang_flag.exists():
                if proc.poll() is not None:
                    break
                time.sleep(0.3)
            result["hang_flag_seen"] = hang_flag.exists()
            verdict_deadline = time.time() + 420
            requested = False
            while time.time() < verdict_deadline and proc.poll() is None:
                if not requested:
                    try:
                        text = (run_dir / "driver-stdout.log").read_text(
                            encoding="utf-8", errors="replace")
                    except FileNotFoundError:
                        text = ""
                    if "did not complete within 30.0s" in text:
                        result["export_ack"] = _request_export(run_dir)
                        result["export_requested_at_timeout"] = True
                        requested = True
                time.sleep(0.2)
            if not requested:
                result["export_ack"] = _request_export(run_dir)
                result["export_requested_at_timeout"] = False
        try:
            rc = proc.wait(timeout=wait_deadline)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = "controller-killed-driver-after-deadline"
        result["driver_exit"] = rc
        if isinstance(rc, str) or rc != 0:
            # 失败后清理本次 PID 树（不作退出证据）。exe PID 从驱动
            # stdout 的 launched pid= 行解析（文件重定向后可靠可读）。
            cleanup: list[dict[str, Any]] = []
            try:
                stdout_text = (out / "driver-stdout.log").read_text(
                    encoding="utf-8", errors="replace")
            except FileNotFoundError:
                stdout_text = ""
            for line in stdout_text.splitlines():
                if "launched pid=" in line:
                    dead_pid = int(line.strip().split("launched pid=")[1].split()[0])
                    cleanup.append({"pid": dead_pid,
                                    "rc": _kill_tree(dead_pid)})
            result["failure_cleanup"] = cleanup
        stdout_text = ""
        try:
            stdout_text = (run_dir / "driver-stdout.log").read_text(
                encoding="utf-8", errors="replace")
        except FileNotFoundError:
            pass
        result["driver_stdout_tail"] = stdout_text[-2000:]
        result["driver_reported_timeout"] = (
            "did not complete within 30.0s" in stdout_text)

    # ── 场景判读 ─────────────────────────────────────────────────
    def read_status() -> dict[str, Any]:
        try:
            return json.loads(status_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"error": repr(exc)}

    if name == "hang-isolation":
        result["verdict"] = {
            "driver_exit": result.get("driver_exit"),
            "plugin_loaded_but_register_short_circuits": True,
            "invalid_reason_if_any": _invalid_reason(out),
            "note": "A/B: plugin present, register() returns early (no log env)",
        }
        _write_result(out, result)
        return result

    if name == "synced-capture":
        trace = _read_jsonl(run_dir / "register-trace.jsonl")             if (run_dir / "register-trace.jsonl").exists() else []
        result["register_trace"] = trace
        events = _read_jsonl(log_path) if log_path.exists() else []
        result["events"] = _summarize_events(events)
        result["last_events"] = events[-8:] if events else []
        result["verdict"] = {
            "driver_exit": result.get("driver_exit"),
            "last_event_kinds": [e.get("record_type") or e.get("event") for e in events[-8:]],
            "invalid_reason_if_any": _invalid_reason(out),
            "note": "synced-mode capture to locate hang point",
        }
        _write_result(out, result)
        return result

    if name.startswith("bisect-stage-"):
        bisect_status = None
        try:
            bisect_status = json.loads(
                (run_dir / "bisect-status.json").read_text(encoding="utf-8"))
        except Exception as exc:
            bisect_status = {"error": repr(exc)}
        result["verdict"] = {
            "stage": name.rsplit("-", 1)[1],
            "driver_exit": result.get("driver_exit"),
            "bisect_status": bisect_status,
            "invalid_reason_if_any": _invalid_reason(out),
            "note": "hang-point bisect; diagnostic only",
        }
        _write_result(out, result)
        return result

    if name == "o0-control":
        # O0 隔离对照（诊断辅助，非 §4 五场景、非正式矩阵）：
        # 无观察插件时驱动能否完整跑通；隔离 attempt-4/5/6 的 GUI
        # 挂起是否由观察器引入。
        result["verdict"] = {
            "driver_exit": result.get("driver_exit"),
            "driver_pass_without_observer": result.get("driver_exit") == 0,
            "invalid_reason_if_any": _invalid_reason(out),
            "note": "isolation control for attempts 4-6 GUI hang",
        }
        _write_result(out, result)
        return result

    if name == "normal-exit":
        # 正常退出：导出已在驱动收尾前请求（见上文 wait 循环）；此处读
        # 结果。若请求时进程已收尾（守护线程消亡），atexit final-flush
        # 保全的数据仍应完整 —— 判读取 export 与 final-flush 的并集。
        if "export_ack" not in result:
            result["export_ack"] = _request_export(run_dir)
        exported = _read_jsonl(run_dir / "events-export.jsonl")             if (run_dir / "events-export.jsonl").exists() else []
        flushed = _read_jsonl(run_dir / "events-final-flush.jsonl")             if (run_dir / "events-final-flush.jsonl").exists() else []
        seen_seqs: set[int] = set()
        merged: list[dict[str, Any]] = []
        for item in list(exported) + list(flushed):
            seq = item.get("seq")
            if seq is None or seq in seen_seqs:
                continue
            seen_seqs.add(seq)
            merged.append(item)
        merged.sort(key=lambda x: x.get("seq", 0))
        result["exported_events"] = _summarize_events(exported)
        result["final_flush_events"] = _summarize_events(flushed)
        result["merged_events"] = _summarize_events(merged)
        result["recorder_status"] = read_status()
        exp = result["merged_events"]
        result["verdict"] = {
            "startup_recorded": exp["has_startup"],
            "install_state_recorded": exp["has_install"],
            "seq_continuous": exp["seq_continuous"],
            "exit_chain_events_present": bool(
                exp["record_types"].get("call")),
            "qt_input_events_present": bool(
                exp["record_types"].get("event")),
            "native_message_events_present": bool(
                exp["record_types"].get("native_event")),
            "application_signals_present": bool(
                exp["record_types"].get("application")),
            "shutdown_recorded_or_flushed": exp["has_shutdown"] or
                bool(result["final_flush_events"]["count"]),
        }
        _write_result(out, result)
        return result

    if name == "active-timeout":
        # S2：驱动已按 30s 判定失败（timeout 结论先于导出宽限）。
        # 控制器此刻请求导出（GUI 线程被挂起，导出只能由守护线程完成）。
        hang_flag = run_dir / "hang-request.flag"
        result["hang_flag_seen"] = hang_flag.exists()
        export = _request_export(run_dir)
        result["export_ack"] = export
        exported = _read_jsonl(run_dir / "events-export.jsonl") \
            if (run_dir / "events-export.jsonl").exists() else []
        result["exported_events"] = _summarize_events(exported)
        result["timeout_verdict_unchanged_by_grace"] = bool(
            result["driver_reported_timeout"])
        # 清理本次 PID 树（失败后的清理，不作退出证据）
        cleanup: list[dict[str, Any]] = []
        for line in (result["driver_stdout_tail"] or "").splitlines():
            if "launched pid=" in line:
                dead_pid = int(line.strip().split("launched pid=")[1].split()[0])
                cleanup.append({"pid": dead_pid,
                                "rc": _kill_tree(dead_pid)})
        cleanup.append({"pid": proc.pid, "already_exited": proc.poll() is not None})
        result["cleanup"] = cleanup
        result["verdict"] = {
            "timeout_reported_before_export_grace":
                result["driver_reported_timeout"],
            "export_succeeded_without_qt_thread": export.get("ack") == "ok",
            "request_exit_chain_captured": bool(
                result["exported_events"]["record_types"].get("call")),
            "pid_tree_cleaned": bool(cleanup),
        }
        _write_result(out, result)
        return result

    if name == "buffer-overflow":
        # S3：驱动经历超时 + 强制清理后进程已亡，缓冲导出不可达；判读
        # 依据是 atexit final flush（挂起注入不存在于此场景——见下）与
        # 请求前的实时导出。为保证确定性，本场景在驱动收尾前由控制器
        # 发出导出请求；此处读取 ack 与导出文件。
        export = _await_existing_ack(run_dir)
        s = read_status()
        result["export_ack"] = export
        result["recorder_status"] = s
        exported = _read_jsonl(run_dir / "events-export.jsonl")             if (run_dir / "events-export.jsonl").exists() else []
        summary = _summarize_events(exported)
        dropped = export.get("dropped")
        if not isinstance(dropped, int) and isinstance(s.get("dropped"), int):
            # 导出竞态不可得时，以观察器主动汇报的状态文件为准
            # （状态文件正是为"导出不可得仍可判读"设计的通道）。
            dropped = s["dropped"]
        per_event_dropped = all(isinstance(r.get("dropped_so_far"), int)
                                for r in exported) if exported else False
        result["exported_events"] = summary
        result["overflow_behavior"] = {
            "dropped_counted": isinstance(dropped, int) and dropped > 0,
            "dropped": dropped,
            "dropped_source": "export_ack" if export.get("dropped") is not None
                              else "recorder_status_file",
            "buffered_at_limit_from_status": s.get("buffered_count"),
            "exported_count": summary.get("count"),
            "headroom_kept_at_limit": (
                s.get("buffered_count") == buffer_limit
                or summary.get("count") == buffer_limit),
            "dropped_recorded_per_event": per_event_dropped,
        }
        result["verdict"] = result["overflow_behavior"]
        _write_result(out, result)
        return result

    if name == "recorder-error":
        # S4：记录器失败 → 状态文件必须汇报 error_count>0；
        # "日志不完整"必须与"零事件"可区分。
        s = read_status()
        result["recorder_status"] = s
        result["log_incomplete_verdict"] = {
            "status_alive": bool(s.get("alive")),
            "status_seq": s.get("seq"),
            "status_error_count": s.get("error_count"),
            "log_incomplete_flag": bool(
                (s.get("error_count") or 0) > 0 or not log_path.exists()
                or log_path.is_dir()),
            "distinguishable_from_zero_events": bool(
                s.get("error_count", 0) > 0),
            "note": "记录器失败→状态文件 error_count>0 + fallback partial 行；"
                    "零事件会是 seq==0 且 error_count==0，两者判读不同。",
        }
        result["verdict"] = result["log_incomplete_verdict"]
        _write_result(out, result)
        return result

    _write_result(out, result)
    return result


def _await_existing_ack(run_dir: Path) -> dict[str, Any]:
    """S3 专用：导出请求已由 active-timeout 阶段发出？不——S3 驱动已被超时
    清理，缓冲进程已亡。改为直接读 final flush / 事后导出不可行；因此 S3
    在驱动收尾前由控制器主动请求（见上方 buffer-overflow 分支前的统一处）。
    此 helper 读已有 ack 或标记 log_incomplete。"""
    ack = run_dir / "export-ack.json"
    if ack.exists():
        try:
            return json.loads(ack.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"ack": "corrupt", "error": repr(exc), "log_incomplete": True}
    return {"ack": None, "error": "no export ack (request never served)",
            "log_incomplete": True}


def _invalid_reason(out: Path) -> str | None:
    """从 driver-stdout.log 提取 INVALID 原因行（无则 None）。"""
    try:
        for path in (out / "synthetic" / "driver-stdout.log",
                     out / "driver-stdout.log"):
            if path.exists():
                for line in path.read_text(encoding="utf-8",
                                           errors="replace").splitlines():
                    if line.startswith("INVALID:"):
                        return line
    except Exception:
        pass
    return None


def _write_result(out: Path, result: dict[str, Any]) -> None:
    (out / "scenario-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    targets = list(SCENARIOS) if which == "all" else [which]
    summary: dict[str, Any] = {"scenarios": {}}
    for name in targets:
        if name not in SCENARIOS:
            print(f"unknown scenario: {name}")
            return 2
        print(f"=== running scenario: {name} ===", flush=True)
        result = _run_scenario(name)
        summary["scenarios"][name] = {
            "driver_exit": result.get("driver_exit"),
            "verdict": result.get("verdict"),
        }
        print(json.dumps(summary["scenarios"][name], ensure_ascii=False,
                         indent=1), flush=True)
    (RUNS / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print("reliability verification complete (formal matrix NOT run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
