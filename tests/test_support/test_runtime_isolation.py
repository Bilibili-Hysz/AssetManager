"""Process-boundary contracts for pytest runtime isolation."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_nested_pytest_gets_new_runtime_but_ordinary_child_inherits():
    """Nested pytest must isolate; an application child must share its parent."""
    current = Path(os.environ["AM_RUNTIME_ROOT"]).resolve()
    inherited = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ['AM_RUNTIME_ROOT'])",
        ],
        text=True,
    ).strip()
    assert Path(inherited).resolve() == current

    environment = os.environ.copy()
    environment["AM_TEST_RUNTIME_PROBE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-s",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            "tests/test_support/test_runtime_isolation.py",
            "-k",
            "nested_pytest_child_probe",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    child_lines = [line.strip() for line in result.stdout.splitlines() if line.startswith("PROBE=")]
    assert len(child_lines) == 1, result.stdout + result.stderr
    child = Path(child_lines[0].split("=", 1)[1]).resolve()
    assert child != current
    assert child.parent.parent == current.parent.parent


def test_nested_pytest_child_probe():
    if os.environ.get("AM_TEST_RUNTIME_PROBE") == "1":
        print(f"PROBE={Path(os.environ['AM_RUNTIME_ROOT']).resolve()}")


@pytest.mark.parametrize("case", range(8))
def test_xdist_worker_root_probe(case):
    """When requested, leave one marker per worker for the parent to inspect."""
    del case
    marker_dir = os.environ.get("AM_XDIST_PROBE_DIR")
    if marker_dir:
        root = Path(os.environ["AM_RUNTIME_ROOT"]).resolve()
        marker = Path(marker_dir) / f"worker-{os.getpid()}"
        marker.write_text(str(root), encoding="utf-8")
