"""P1 measurement 1 — import-chain profile for ``import main``.

Runs ``python -X importtime -c "import main"`` N times as fresh subprocesses
(offscreen), parses the stderr import-time tree, and reports:

* total cumulative import time of the ``main`` root line (per run + median)
* top-N modules by median self (cumulative-excluding-children) time
* the heaviest subtrees (PySide6, PIL, aiohttp, ...) for deferral analysis

Evidence: docs/reports/performance-audit-2026-09-06/evidence/p1-import-chain.json

Usage:
    python scripts/perf/p1_import_chain.py [--runs 3] [--top 20]
"""
from __future__ import annotations

import argparse
import os
import re
import statistics
import subprocess
import sys

from _p1_common import environment, project_root, write_json

_LINE = re.compile(r"^import time:\s+(\d+)\s+\|\s+(\d+)\s+\|\s+(.+)$")


def parse_importtime(stderr: str) -> tuple[dict[str, tuple[int, int]], int]:
    """Return {module: (self_us, cumulative_us)} and the root total us."""
    modules: dict[str, tuple[int, int]] = {}
    total = 0
    for raw in stderr.splitlines():
        m = _LINE.match(raw.strip())
        if not m:
            continue
        self_us, cum_us, name = int(m.group(1)), int(m.group(2)), m.group(3).strip()
        modules[name] = (self_us, cum_us)
        if name == "main":
            total = cum_us
    return modules, total


def run_once() -> tuple[dict[str, tuple[int, int]], int]:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    proc = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", "import main"],
        cwd=str(project_root()),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"import main failed: {proc.stderr[-2000:]}")
    return parse_importtime(proc.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    runs: list[dict[str, tuple[int, int]]] = []
    totals: list[int] = []
    for i in range(args.runs):
        modules, total = run_once()
        runs.append(modules)
        totals.append(total)
        print(f"run {i + 1}/{args.runs}: total import = {total / 1000:.1f} ms")

    median_total_us = statistics.median(totals)

    # Median self-time per module across runs.
    all_names: set[str] = set()
    for mods in runs:
        all_names.update(mods)
    med_self: dict[str, float] = {}
    med_cum: dict[str, float] = {}
    for name in all_names:
        self_vals = [mods[name][0] for mods in runs if name in mods]
        cum_vals = [mods[name][1] for mods in runs if name in mods]
        med_self[name] = statistics.median(self_vals)
        med_cum[name] = statistics.median(cum_vals)

    top = sorted(med_self.items(), key=lambda kv: kv[1], reverse=True)[: args.top]

    # Heavy-subtree rollups (cumulative medians for interesting packages).
    interesting = [
        "PySide6.QtWidgets",
        "PySide6.QtGui",
        "PySide6.QtCore",
        "PySide6.QtNetwork",
        "PySide6.QtOpenGLWidgets",
        "PySide6",
        "PIL",
        "aiohttp",
        "numpy",
        "sqlite3",
        "json",
        "logging",
        "unittest",
    ]
    rollup = {name: med_cum[name] for name in interesting if name in med_cum}
    # Also sum every PySide6.* / PIL.* leaf self-time for a package-level view.
    pkg_self: dict[str, float] = {}
    for name, us in med_self.items():
        pkg = name.split(".")[0]
        pkg_self[pkg] = pkg_self.get(pkg, 0.0) + us
    top_pkgs = sorted(pkg_self.items(), key=lambda kv: kv[1], reverse=True)[:15]

    payload = {
        "measurement": "import-chain",
        "command": 'python -X importtime -c "import main"',
        "runs": args.runs,
        "totals_us_per_run": totals,
        "total_import_median_us": median_total_us,
        "top_modules_by_median_self_us": [
            {"module": name, "self_us": round(us, 1), "cum_us": round(med_cum[name], 1)}
            for name, us in top
        ],
        "package_rollup_median_self_us": [
            {"package": pkg, "self_us": round(us, 1)} for pkg, us in top_pkgs
        ],
        "interesting_subtrees_median_cum_us": {
            k: round(v, 1) for k, v in rollup.items()
        },
        "environment": environment(),
    }
    write_json("p1-import-chain.json", payload)

    print("\n== Top modules by median self time ==")
    for name, us in top:
        print(f"  {us / 1000:9.1f} ms self | {med_cum[name] / 1000:9.1f} ms cum | {name}")
    print("\n== Package rollup (sum of median self times) ==")
    for pkg, us in top_pkgs:
        print(f"  {us / 1000:9.1f} ms | {pkg}")
    print(f"\nTotal import median: {median_total_us / 1000:.1f} ms")
    return 0


if __name__ == "__main__":
    # Allow relative import of the helper when run as a plain script.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(main())
