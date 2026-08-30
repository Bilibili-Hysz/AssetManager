"""Unit tests for the C1 contracts generator (scripts/gen_ts_types.py).

Verifies that the checked-in ``webui/src/types/contracts.ts`` matches what the
generator produces from the dto source of truth, and that the emitted TypeScript
carries the expected interface names and key field signatures.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import gen_ts_types  # noqa: E402

CONTRACTS_PATH = gen_ts_types.CONTRACTS_PATH


def test_check_reports_up_to_date() -> None:
    """The generator's --check mode exits 0 against the checked-in file."""
    import subprocess

    script = ROOT / "scripts" / "gen_ts_types.py"
    result = subprocess.run(
        [sys.executable, str(script), "--check"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr


def test_disk_matches_generated_bytes() -> None:
    """The on-disk file is byte-identical to the in-memory generation."""
    on_disk = CONTRACTS_PATH.read_text(encoding="utf-8")
    generated = gen_ts_types.generate_contracts_ts()
    assert generated == on_disk


def test_generated_contains_expected_interfaces_and_fields() -> None:
    """The nine interfaces and the key narrowed/overridden fields are present."""
    text = gen_ts_types.generate_contracts_ts()

    for name in (
        "Capabilities",
        "SessionPrincipal",
        "UserResponse",
        "InviteResponse",
        "Tag",
        "TreeItem",
        "StatsResponse",
        "RuntimeCursor",
        "InvalidationEvent",
    ):
        assert f"export interface {name} " in text

    assert "role: 'admin' | 'user';" in text
    assert "children: TreeItem[];" in text
    assert "type: 'projection_invalidated';" in text
    assert "role: 'admin' | 'user' | 'guest';" in text
    assert "kind: 'user' | 'password' | 'access_key' | 'local_ui' | 'guest' | 'share';" in text
    assert "user_profile?: UserResponse;" in text
    assert "export interface InvalidationEvent extends RuntimeCursor" in text
    assert "export type ProjectionDomain =" in text
    assert "'quota'" in text
    assert "'collections';" in text  # last enum member terminates the union
