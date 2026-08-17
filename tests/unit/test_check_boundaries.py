"""Smoke test for the static boundary gate script (plan-B acceptance gates)."""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "check_boundaries.py"


def test_check_boundaries_passes_on_current_tree():
    """The committed tree satisfies the static boundary gates (1/2/3/5)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr
    assert "boundary checks passed" in result.stdout


def test_check_boundaries_covers_all_static_gates():
    """The four static gates (1/2/3/5) are wired into the script."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import check_boundaries  # noqa: E402

    assert {gate for gate, _dirs, _needle, _desc in check_boundaries._CHECKS} == {
        "1", "2", "3", "5",
    }
