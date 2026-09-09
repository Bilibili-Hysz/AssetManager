"""G3 观察干扰对照正式矩阵周期 runner（batch-02-matrix）。

预登记（已获主代理批准）：docs/reports/exit-g3-g2-2026-09-09-evidence/
batch-01-prep/preregistration.md。区组顺序 1→2→3→4：
  区组 1: O0 → O1 → O2    区组 2: O1 → O2 → O0
  区组 3: O2 → O0 → O1    区组 4: O0 → O2 → O1
每周期 = 完整 W6 负载 + 首退 Ctrl+Q + 重启 + 重启退 Ctrl+Q（驱动内置）。
上限 12 周期 / 24 退出；独占 GUI ≤90 分钟（从第一周期启动算起，全局计时）。

主代理附加纪律（并入每轮记录）：
  a) 每周期开始前记录全系统前台进程快照（GetForegroundWindow PID+进程名），
     与该轮结果一并归档——用于区分"输入层缺失"与"前台竞争环境"。
  b) 任一轮目标失败：按预登记停止条件 1 立即停止批次保全证据，
     不自行启动第二阶段区分实验；整理现场交主代理与 G2 联合判读。

每轮结果分类：PASS / FAIL / INVALID（预登记 §4），NOT_RUN 由批次汇总
标记。一次退出只发一次 Q（驱动合同），不补发、不延长 30s、不强杀代替
正常退出断言；强制结束仅用于失败后的清理。

用法（在 g3-ops 快照根目录）：
  python docs/reports/exit-g3-g2-2026-09-09-evidence/batch-02-matrix/run_matrix_cycle.py \
      --block 1 --cond o1 --cycle 1 [--budget-start epoch_ms]
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SNAP = HERE.parents[3]                      # g3-ops 快照根
DRIVER = SNAP / "scripts/perf/w6_g2g3_diagnostic.py"   # f989 逐字节副本
EXE = SNAP / "artifacts/weekly-repair-2026-09-08-103f119/AssetManager.exe"
PLUGIN_SRC = HERE / "observer-plugin"        # batch-02 修订版观察器
RUNS = HERE / "runs"
BUDGET_FILE = HERE / "budget-clock.json"

CONDITIONS = {"o0", "o1", "o2"}

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _foreground_snapshot() -> dict[str, Any]:
    """纪律 a：全系统前台进程快照（PID+进程名+窗口标题）。

    记录 GetForegroundWindow 的 PID 与映像名；同时枚举可见顶层窗口的
    （pid, 映像名）集合作为"前台竞争环境"的完整登记。只采集进程身份
    与标题，不采集窗口内容。
    """
    u = _user32

    def _title(hwnd: int) -> str:
        n = u.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def _image(pid: int) -> str:
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter "
                 f"'ProcessId={pid}').Name"],
                capture_output=True, text=True, timeout=10)
            return out.stdout.strip()
        except Exception:
            return "<unresolved>"

    fg = int(u.GetForegroundWindow() or 0)
    snap: dict[str, Any] = {
        "taken_monotonic_ms": round(time.monotonic() * 1000.0, 3),
        "taken_wall_s": time.time(),
        "foreground_hwnd": fg,
    }
    if fg:
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        snap["foreground_pid"] = int(pid.value)
        snap["foreground_image"] = _image(int(pid.value))
        snap["foreground_title"] = _title(fg)[:120]
    # 可见顶层窗口的进程集合（前台竞争环境登记）
    seen: dict[int, str] = {}
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _l):
        if u.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            p = int(pid.value)
            if p not in seen:
                seen[p] = _image(p)
        return True

    u.EnumWindows(EnumProc(cb), 0)
    snap["visible_window_pids"] = {
        str(p): name for p, name in sorted(seen.items())}
    return snap


def _win32_from_driver():
    spec = importlib.util.spec_from_file_location("w6_matrix", DRIVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _launch_driver(run_dir: Path, env_extra: dict[str, str]) -> subprocess.Popen:
    """与可靠性控制器同机制：mkdtemp 重定向 shim 在驱动种子运行域的
    同时安装观察插件（Popen exe 之前）。o0 场景装空 plugins 目录。"""
    shim_src = (
        "import tempfile as _t\n"
        "import shutil as _sh\n"
        "import os as _o\n"
        "from pathlib import Path as _P\n"
        "_real = _t.mkdtemp\n"
        f"_PLUGIN_SRC = r'{PLUGIN_SRC.as_posix()}'\n"
        "def _mk(prefix=None, suffix='', dir=None, **kw):\n"
        "    if prefix and str(prefix).startswith('w6-func-'):\n"
        f"        d = _P(r'{run_dir.as_posix()}') / 'synthetic'\n"
        "        shared = d / 'runtime' / 'Shared'\n"
        "        _o.makedirs(shared / 'plugins', exist_ok=True)\n"
        "        # install the observer plugin at mkdtemp-redirect time,\n"
        "        # strictly before the driver Popen's the exe\n"
        "        _sh.copytree(_PLUGIN_SRC, shared / 'plugins'"
        " / 'exit-observer', dirs_exist_ok=True)\n"
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
    for k, v in env_extra.items():
        env[k] = v
    env.pop("QT_QPA_PLATFORM", None)

    cmd = [sys.executable, str(DRIVER), "--exe", str(EXE),
           "--mode", "onefile", "--maximized", "--auto-open"]
    stdout_file = (run_dir / "driver-stdout.log").open(
        "w", encoding="utf-8", errors="replace")
    return subprocess.Popen(cmd, env=env, cwd=str(SNAP),
                            stdout=stdout_file, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")


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


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
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
                           for r in records),
        "has_shutdown_or_flush": any(
            r.get("record_type") == "recorder_shutdown" for r in records),
    }


def _exit_codes_from_stdout(text: str) -> list[int]:
    """从驱动 stdout 提取首退正常退出码（close: 行的 'exit_code': N）。"""
    codes: list[int] = []
    for line in text.splitlines():
        if "'exit_code':" in line and "close:" in line:
            try:
                frag = line.split("'normal_exit'")[1]
                codes.append(int(frag.split("'exit_code':")[1]
                                 .split("}")[0].strip().rstrip(",")))
            except (IndexError, ValueError):
                pass
    return codes


def _restart_exit_code() -> int | None:
    """读驱动 evidence JSON 里的重启相退出码。

    驱动把 evidence 写到 cwd 相对路径 artifacts/perf/w6-functional/
    onefile-maximized.json（cwd=SNAP）；该文件在每轮 Popen 时被驱动
    覆盖，矩阵 runner 串行运行，读完即为本轮重启相。
    """
    ev = SNAP / "artifacts" / "perf" / "w6-functional" / "onefile-maximized.json"
    try:
        data = json.loads(ev.read_text(encoding="utf-8"))
        return data.get("restart", {}).get("normal_exit_code")
    except Exception:
        return None


def _classify(stdout_text: str, rc: int | None,
              input_outcomes: list[str]) -> tuple[str, list[str]]:
    """按预登记 §4 分类：PASS / FAIL / INVALID。"""
    reasons: list[str] = []
    if rc is None:
        return "INVALID", ["controller-killed-driver (no exit code)"]
    if rc == 0 and "W6 FUNCTIONAL" in stdout_text and "PASS" in stdout_text:
        return "PASS", ["driver exit 0; both Ctrl+Q exits code 0"]
    if "did not complete within 30.0s" in stdout_text:
        reasons.append("normal-exit timeout (30s) in driver stdout")
    if "invalid_input_delivery" in stdout_text or "shortcut was not sent" in stdout_text:
        reasons.append("input delivery invalid (driver refused to send Q)")
    if "process exited early" in stdout_text:
        reasons.append("process exited early before acceptance steps")
    if not reasons:
        reasons.append(f"driver exit {rc} without explicit W6 PASS line")
    return "FAIL", reasons


def _pid_from_status(run_dir: Path, phase_dir: Path) -> int | None:
    try:
        return int(json.loads((phase_dir / "recorder-status.json")
                             .read_text(encoding="utf-8")).get("pid"))
    except Exception:
        return None


def _request_export(run_dir: Path, pid: int,
                    timeout_s: float = 15.0) -> dict[str, Any]:
    """对指定 PID 的相请求导出（观察器路径已带 PID 后缀，请求文件同样
    需带后缀才能被对应守护线程识别——请求文件名含 PID，守护线程拼接
    自己的 PID 轮询同名文件）。"""
    request = run_dir / f"export-request.{pid}.txt"
    target = run_dir / f"events-export.{pid}.jsonl"
    ack = run_dir / f"export-ack.{pid}.json"
    try:
        request.write_text(str(target), encoding="utf-8")
    except Exception as exc:
        return {"ack": "failed_to_write_request", "error": repr(exc)[:200]}
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if ack.exists():
            try:
                return json.loads(ack.read_text(encoding="utf-8"))
            except Exception as exc:
                return {"ack": "corrupt", "error": repr(exc)[:200]}
        time.sleep(0.1)
    try:
        request.unlink()
    except FileNotFoundError:
        pass
    return {"ack": None,
            "error": "export request not acknowledged within timeout",
            "log_incomplete": True,
            "note": "export requested; observer daemon unavailable — "
                    "log marked incomplete per plan §4, NOT zero-event proof"}


def _collect_o0(run_dir: Path, stdout_text: str) -> dict[str, Any]:
    """O0 收集：无应用内日志是设计限制；只收驱动侧采样与退出码。"""
    codes = _exit_codes_from_stdout(stdout_text)
    return {
        "exit_codes": codes,
        "note": "O0: no in-app logging by design; driver-side 4-stage input "
                "sampling in driver-stdout.log is the input-receipt evidence",
        "log_completeness": "not_applicable_by_design",
    }


def _find_phase_files(run_dir: Path) -> dict[str, list[Path]]:
    """收集分相工件（观察器路径带 PID 后缀）。

    exe 有两个进程（onefile 父 + GUI 子），每个 GUI 子进程产生一组
    {status, final-flush, qt-events} 工件。按修改时间排序，第一组 =
    首退相，最后一组 = 重启相。
    """
    groups: dict[str, list[Path]] = {"status": [], "flush": [], "log": [],
                                     "ack": [], "export": []}
    for p in run_dir.glob("recorder-status.*.json"):
        groups["status"].append(p)
    for p in run_dir.glob("events-final-flush.*.jsonl"):
        groups["flush"].append(p)
    for p in run_dir.glob("qt-events.*.jsonl"):
        groups["log"].append(p)
    for p in run_dir.glob("export-ack.*.json"):
        groups["ack"].append(p)
    for p in run_dir.glob("events-export.*.jsonl"):
        groups["export"].append(p)
    for k in groups:
        groups[k].sort(key=lambda p: p.stat().st_mtime)
    return groups


def _collect_o1_o2(run_dir: Path, stdout_text: str) -> dict[str, Any]:
    """O1/O2 分相收集与判读。

    O1（buffered）：以 final-flush / 导出文件为相证据；状态文件提供
    完整性计数。O2（synced）：qt-events.<pid>.jsonl 即逐条落盘证据。
    事件链首落点判读：Shortcut(Qt)/native key/exit call 的 presence。
    """
    groups = _find_phase_files(run_dir)
    phases: list[dict[str, Any]] = []

    def _pid_of(path: Path) -> int:
        try:
            return int(path.name.rsplit(".", 2)[-2])
        except (IndexError, ValueError):
            return -1

    # 候选相集合：按 pid 聚合（一个 GUI pid = 一相）
    pids: list[int] = []
    for st in groups["status"]:
        p = _pid_of(st)
        if p > 0 and p not in pids:
            pids.append(p)
    for fl in groups["flush"]:
        p = _pid_of(fl)
        if p > 0 and p not in pids:
            pids.append(p)
    for lg in groups["log"]:
        p = _pid_of(lg)
        if p > 0 and p not in pids:
            pids.append(p)
    for ex in groups["export"]:
        p = _pid_of(ex)
        if p > 0 and p not in pids:
            pids.append(p)
    pids.sort()

    for pid in pids:
        st_file = run_dir / f"recorder-status.{pid}.json"
        flush_file = run_dir / f"events-final-flush.{pid}.jsonl"
        log_file = run_dir / f"qt-events.{pid}.jsonl"
        export_file = run_dir / f"events-export.{pid}.jsonl"
        ack_file = run_dir / f"export-ack.{pid}.json"
        merged: list[dict[str, Any]] = []
        seen: set[int] = set()
        for src in (export_file, flush_file, log_file):
            for item in _read_jsonl(src):
                seq = item.get("seq")
                if seq is None or seq in seen:
                    continue
                seen.add(seq)
                merged.append(item)
        merged.sort(key=lambda x: x.get("seq", 0))
        status = {}
        try:
            status = json.loads(st_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        rec = _summarize(merged)
        # 事件链首落点（预登记 §4 判读边界）
        call_methods = sorted({r.get("method") for r in merged
                               if r.get("record_type") == "call"})
        shortcut_events = [r for r in merged
                           if r.get("record_type") == "event"
                           and r.get("event") == "Shortcut"]
        key_events = [r for r in merged
                      if r.get("record_type") == "event"
                      and r.get("event") in ("KeyPress", "ShortcutOverride")]
        native_keys = [r for r in merged
                       if r.get("record_type") == "native_event"
                       and str(r.get("event", "")).startswith("WM_KEY")]
        chain = {
            "qt_key_or_override_present": bool(key_events),
            "qt_shortcut_present": bool(shortcut_events),
            "native_ctrl_q_messages_present": bool(native_keys),
            "exit_calls_captured": call_methods,
            "request_exit_enter": any(
                r.get("method", "").endswith("request_exit")
                and r.get("phase") == "enter" for r in merged),
            "application_signals": sorted({r.get("signal") for r in merged
                                            if r.get("record_type") ==
                                            "application"})},
        phases.append({
            "pid": pid,
            "status": status,
            "merged": rec,
            "chain": chain,
            "ack": (json.loads(ack_file.read_text(encoding="utf-8"))
                    if ack_file.exists() else None),
        })
    return {"phases": phases,
            "phase_count": len(phases),
            "note": "per-GUI-pid phase artifacts (PID-suffixed paths)"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--block", type=int, required=True, choices=(1, 2, 3, 4))
    parser.add_argument("--cond", required=True, choices=sorted(CONDITIONS))
    parser.add_argument("--cycle", type=int, required=True)
    args = parser.parse_args()

    out = RUNS / f"cycle-{args.cycle:02d}-{args.cond}"
    if out.exists():
        raise SystemExit(f"refusing to overwrite existing cycle dir: {out}")
    out.mkdir(parents=True)
    run_dir = out / "synthetic"
    run_dir.mkdir()

    # ── 开工核对：基线哈希（预登记固定条件）─────────────────────
    baselines = {
        "exe": _sha256(EXE),
        "driver": _sha256(DRIVER),
        "observer": _sha256(PLUGIN_SRC / "observer.py"),
    }
    expected = {
        "exe": "1d568fb80ef6dcb78f9d8001ea68c521367638938a3463cf2964e51960372c5a",
        "driver": "f989e271d1a6c7546b76f8a1aed513ae1cd87fcaca4616f8705380b60f435d6e",
    }
    for k, exp in expected.items():
        if baselines[k] != exp:
            raise SystemExit(f"baseline hash mismatch for {k}: "
                             f"{baselines[k]} != {exp}")

    # ── 纪律 a：周期开始前全系统前台快照 ───────────────────────
    fg_before = _foreground_snapshot()
    (out / "foreground-before.json").write_text(
        json.dumps(fg_before, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── 预算时钟（90 分钟全局，从第一周期启动算起）──────────────
    budget: dict[str, Any] = {}
    if BUDGET_FILE.exists():
        try:
            budget = json.loads(BUDGET_FILE.read_text(encoding="utf-8"))
        except Exception:
            budget = {}
    if not budget.get("started_epoch_ms"):
        budget = {"started_epoch_ms": int(time.time() * 1000),
                  "cycles_started": 0}
        BUDGET_FILE.write_text(json.dumps(budget, ensure_ascii=False),
                                encoding="utf-8")
    elapsed_min = (time.time() * 1000 - budget["started_epoch_ms"]) / 60000.0
    if elapsed_min > 90.0:
        raise SystemExit(f"budget exceeded ({elapsed_min:.1f} min > 90 min); "
                         "refusing to start new cycle")

    # ── 场景环境（O0/O1/O2；条件差异只在插件在场与观察模式）─────
    env_extra: dict[str, str] = {
        "AM_G3_RUN_ID": f"matrix-cycle{args.cycle:02d}-{args.cond}",
        "AM_G3_PHASE": "first-exit",   # 观察器按 exe 实际相位自记
        "AM_EXIT_DIAGNOSTIC_LOG": str(run_dir / "qt-events.jsonl"),
        "AM_G3_EXPORT_REQUEST": str(run_dir / "export-request.txt"),
        "AM_G3_EXPORT_ACK": str(run_dir / "export-ack.json"),
        "AM_G3_FINAL_FLUSH": str(run_dir / "events-final-flush.jsonl"),
        "AM_G3_STATUS_FILE": str(run_dir / "recorder-status.json"),
        "AM_G3_BUFFER_LIMIT": "20000",
    }
    if args.cond == "o1":
        env_extra["AM_G3_OBSERVE_MODE"] = "buffered"
        install_observer = True
    elif args.cond == "o2":
        env_extra["AM_G3_OBSERVE_MODE"] = "synced"
        install_observer = True
    else:
        install_observer = False
        # O0：不给观察器任何激活路径环境变量（插件在位但 register 直接
        # return），与 batch-01 hang-isolation 同构——应用内无日志是
        # 设计限制，不得推断 Qt 事件没有发生。
        for k in ("AM_EXIT_DIAGNOSTIC_LOG", "AM_G3_EXPORT_REQUEST",
                  "AM_G3_EXPORT_ACK", "AM_G3_FINAL_FLUSH",
                  "AM_G3_STATUS_FILE", "AM_G3_OBSERVE_MODE"):
            env_extra.pop(k, None)

    proc = _launch_driver(run_dir, env_extra)

    # ── O1 导出请求时机：等首退完成（close: 行）后请求一次 ───────
    # 观察器路径带 PID 后缀；我们尚不知道 exe GUI pid —— 先从状态文件
    # glob 轮询发现第一个 recorder-status.<pid>.json 再定向请求。
    export_ack: dict[str, Any] | None = None
    if args.cond == "o1":
        first_close_deadline = time.time() + 380
        pid_seen: list[int] = []
        requested_pids: set[int] = set()
        while time.time() < first_close_deadline and proc.poll() is None:
            for st in run_dir.glob("recorder-status.*.json"):
                try:
                    pid = int(st.name.rsplit(".", 2)[-2])
                except (IndexError, ValueError):
                    continue
                if pid > 0:
                    pid_seen.append(pid)
            # 首个 GUI pid 出现且驱动已过首退（stdout 有 close: 行）
            try:
                text = (run_dir / "driver-stdout.log").read_text(
                    encoding="utf-8", errors="replace")
            except FileNotFoundError:
                text = ""
            if pid_seen and "close: {" in text:
                for pid in dict.fromkeys(pid_seen):
                    if pid not in requested_pids:
                        _request_export(run_dir, pid)
                        requested_pids.add(pid)
                        export_ack = {"requested_pids": sorted(requested_pids)}
                # 重启相 pid 会在后续状态文件出现；继续循环直到驱动结束
            time.sleep(0.5)
        # 驱动结束后：对出现过的每个 pid 再请求一次（收尾保全）
        for st in run_dir.glob("recorder-status.*.json"):
            try:
                pid = int(st.name.rsplit(".", 2)[-2])
            except (IndexError, ValueError):
                continue
            if pid > 0 and pid not in requested_pids:
                _request_export(run_dir, pid)
                requested_pids.add(pid)
        export_ack = {"requested_pids": sorted(requested_pids)}

    # ── 等待驱动收尾（完整负载 + 首退 + 重启 + 重启退）──────────
    try:
        rc = proc.wait(timeout=430)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = None

    stdout_text = ""
    try:
        stdout_text = (run_dir / "driver-stdout.log").read_text(
            encoding="utf-8", errors="replace")
    except FileNotFoundError:
        pass

    status, reasons = _classify(stdout_text, rc, [])

    # 失败轮保全：若目标失败（FAIL），对每个出现过的 pid 请求导出
    # （可能在清理前已被执行；清理后再请求会超时并标注 log_incomplete）
    if status == "FAIL" and args.cond in ("o1", "o2"):
        for st in run_dir.glob("recorder-status.*.json"):
            try:
                pid = int(st.name.rsplit(".", 2)[-2])
            except (IndexError, ValueError):
                continue
            if pid > 0:
                _request_export(run_dir, pid)

    # 周期末前台快照（对照：失败时前台是否变化）
    fg_after = _foreground_snapshot()
    (out / "foreground-after.json").write_text(
        json.dumps(fg_after, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── 分条件收集 ──────────────────────────────────────────────
    codes = _exit_codes_from_stdout(stdout_text)
    restart_code = _restart_exit_code()
    if restart_code is not None:
        codes.append(restart_code)
    if args.cond == "o0":
        collect = _collect_o0(run_dir, stdout_text)
    else:
        collect = _collect_o1_o2(run_dir, stdout_text)

    result: dict[str, Any] = {
        "cycle": args.cycle,
        "block": args.block,
        "condition": args.cond,
        "status": status,
        "reasons": reasons,
        "driver_exit": rc,
        "exit_codes": codes,
        "baseline_hashes": baselines,
        "foreground_before": {k: fg_before.get(k) for k in
                              ("foreground_pid", "foreground_image",
                               "foreground_title")},
        "foreground_after": {k: fg_after.get(k) for k in
                             ("foreground_pid", "foreground_image",
                              "foreground_title")},
        "foreground_changed": (fg_before.get("foreground_pid")
                               != fg_after.get("foreground_pid")),
        "budget_elapsed_min_at_cycle_end": round(
            (time.time() * 1000 - budget["started_epoch_ms"]) / 60000.0, 1),
        "collect": collect,
        "stdout_tail": stdout_text[-1500:],
    }
    (out / "cycle-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps({
        "cycle": args.cycle, "cond": args.cond, "status": status,
        "reasons": reasons, "driver_exit": rc,
        "exit_codes": codes,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
