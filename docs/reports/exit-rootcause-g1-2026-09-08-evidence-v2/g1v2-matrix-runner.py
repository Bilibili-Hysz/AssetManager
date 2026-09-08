"""G1 v2 matrix runner: E/F/G/H x 5 cycles, one process per run.

Serializes GUI input delivery (workpack rule: real key sends must be
exclusive). Writes per-run results plus a runner log with timestamps and the
experiment driver hash at runner start.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "scripts" / "perf" / "w6_g1_input_v2.py"
EXE = ROOT / "artifacts" / "candidate.exe"
OUT = ROOT / "artifacts" / "g1v2"
LOG = ROOT / "artifacts" / "g1v2-runner-log.txt"
SUMMARY = ROOT / "artifacts" / "g1v2-summary.json"

driver_sha = hashlib.sha256(DRIVER.read_bytes()).hexdigest()
print(f"driver sha256: {driver_sha}")
OUT.mkdir(parents=True, exist_ok=True)

results = []
with LOG.open("w", encoding="utf-8") as log:
    log.write(f"driver_sha256 {driver_sha}\n")
    log.write(f"start {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    for cell in ("E", "F", "G", "H"):
        for i in range(1, 6):
            tag = f"{cell}{i}"
            t0 = time.perf_counter()
            proc = subprocess.run(
                [sys.executable, str(DRIVER), "--exe", str(EXE),
                 "--mode", "onefile", "--maximized", "--auto-open",
                 "--input-mode", cell, "--tag", tag],
                cwd=str(ROOT), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=420,
            )
            elapsed = round(time.perf_counter() - t0, 1)
            result = "PASS" if proc.returncode == 0 else f"FAIL rc={proc.returncode}"
            results.append({"tag": tag, "input_mode": cell, "exit": proc.returncode,
                            "elapsed_s": elapsed, "result": result,
                            "driver_sha256": driver_sha})
            line = f"{tag} mode={cell} {result} elapsed={elapsed}s"
            print(line, flush=True)
            log.write(line + "\n")
            log.flush()
            if proc.returncode != 0:
                log.write("stderr tail: " + "\n".join(proc.stderr.splitlines()[-4:]) + "\n")
                log.flush()
    log.write(f"end {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    log.write("RUNNER DONE\n")

SUMMARY.write_text(json.dumps({
    "driver_sha256": driver_sha,
    "design": {
        "E": {"interface": "keybd_event", "scan": "zero",
              "note": "historical failing form (archived drivers keybd_event scan=0, back-to-back)"},
        "F": {"interface": "keybd_event", "scan": "real"},
        "G": {"interface": "SendInput", "scan": "zero"},
        "H": {"interface": "SendInput", "scan": "real", "note": "= official bd8142 form"},
    },
    "cells": results,
}, ensure_ascii=False, indent=1), encoding="utf-8")
print("RUNNER DONE")
