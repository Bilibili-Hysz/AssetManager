"""Self-test for the document-maintenance gate (scripts/check_documents.py)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def run_gate(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "check_documents.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_documents_passes_on_current_tree() -> None:
    result = run_gate()
    assert result.returncode == 0, result.stderr


def test_check_documents_does_not_need_freshness_on_ci_archive() -> None:
    # --ignore-age must keep working as the CI flag for long-lived LIVING docs.
    result = run_gate("--ignore-age")
    assert result.returncode == 0, result.stderr