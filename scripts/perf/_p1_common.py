"""Shared helpers for the P1 startup/memory performance probes (2026-09-06).

Placement note: these probes live under ``scripts/perf/`` — NOT ``tests/`` —
so the regular pytest run (``testpaths = tests``) never collects them.  They
are driven manually (or by the report workflow) and print their results;
``ruff.toml`` already whitelists ``print`` for ``scripts/**``.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = PROJECT_ROOT / "docs" / "reports" / "performance-audit-2026-09-06" / "evidence"


def project_root() -> Path:
    return PROJECT_ROOT


def ensure_evidence_dir() -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    return EVIDENCE_DIR


def write_json(name: str, payload: dict) -> Path:
    ensure_evidence_dir()
    path = EVIDENCE_DIR / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[evidence] wrote {path}")
    return path


def median(values: list[float]) -> float:
    return statistics.median(values)


def environment() -> dict:
    import platform

    env: dict = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor(),
        "qt_qpa_platform": os.environ.get("QT_QPA_PLATFORM", ""),
    }
    try:
        import PySide6

        env["pyside6"] = PySide6.__version__
    except Exception:
        env["pyside6"] = "unavailable"
    try:
        import psutil

        env["psutil"] = psutil.__version__
        vm = psutil.virtual_memory()
        env["total_ram_gb"] = round(vm.total / (1024**3), 1)
        cpu = psutil.cpu_freq()
        env["cpu_max_ghz"] = round(cpu.max / 1000, 2) if cpu else None
    except Exception:
        env["psutil"] = "unavailable"
    return env


def rss_bytes(pid: int | None = None) -> int:
    """Current process (or given pid) RSS in bytes via psutil."""
    import psutil

    proc = psutil.Process(pid) if pid else psutil.Process()
    return proc.memory_info().rss
