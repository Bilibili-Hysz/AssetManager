"""Static boundary checks for the front/back separation acceptance gates.

Verifies the static-scan acceptance criteria from
``DeepSeek Docs/前后端分离改造计划/03-验收标准与风险预案.md``:

    1. ``application/`` emits no ``/api/`` transport URLs.
    2. ``panels/`` and ``widgets/`` construct no ``Repository(...)``.
    3. ``panels/`` and ``widgets/`` call no ``connection_for(...)``.
    5. ``dialogs/`` embed no ``http://localhost`` business call.

Gate 4 (share creation works without a running LAN server) is a runtime
integration test, and gate 6 (the generated ``contracts.ts`` has no drift)
is enforced by ``scripts/gen_ts_types.py --check`` — neither is a static
grep, so both live outside this script.

Exit 0 when every check passes; exit 1 with a report otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_layers import collect_violations  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APPLICATION = ROOT / "AssetsManager" / "application"
PANELS = ROOT / "AssetsManager" / "panels"
WIDGETS = ROOT / "AssetsManager" / "widgets"
DIALOGS = ROOT / "AssetsManager" / "dialogs"

# (gate, directories, needle, description)
_CHECKS = (
    (
        "1",
        (APPLICATION,),
        "/api/",
        "application layer must not emit transport URLs",
    ),
    (
        "2",
        (PANELS, WIDGETS),
        "Repository(",
        "presentation layer must not construct repositories",
    ),
    (
        "3",
        (PANELS, WIDGETS),
        "connection_for",
        "presentation layer must not call session.connection_for()",
    ),
    (
        "5",
        (DIALOGS,),
        "http://localhost",
        "dialogs must not embed http://localhost business calls",
    ),
)


def _scan(directory: Path, needle: str) -> list[str]:
    """Return ``path:line`` spans under *directory* containing *needle*."""
    violations: list[str] = []
    for path in sorted(directory.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            if needle in line:
                violations.append(f"{path.relative_to(ROOT).as_posix()}:{lineno}")
    return violations


def main() -> int:
    problems: list[str] = []
    for gate, directories, needle, description in _CHECKS:
        for directory in directories:
            for span in _scan(directory, needle):
                problems.append(f"gate {gate} ({description}): {span}")

    for violation in collect_violations():
        problems.append(f"layer DAG: {violation.describe()}")

    if problems:
        print("boundary violations detected:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1

    print("boundary checks passed (gates 1/2/3/5 + layer DAG)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
