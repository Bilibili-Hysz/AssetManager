r"""G1 ratchet gate — presentation-layer ``setStyleSheet`` calls may only decrease.

Design System audit 2026-09-03 (finding F3/G1): 253 ``setStyleSheet`` call
sites across 40 presentation files are the migration surface for the
"styles only from StyleKit / central QSS" goal.  This gate does not ban the
calls outright (that is the post-migration end state); it freezes the
baseline so the count can only move DOWN:

* every scoped file's actual ``setStyleSheet`` call count (AST-derived) must
  be <= its ledger allowance;
* a file absent from the ledger must have zero calls;
* ``--update`` rewrites the ledger from the tree, refusing any increase
  unless ``--force`` is passed (an increase is always a reviewable event).

``AssetsManager/app.py`` is exempt: ``app.setStyleSheet(themes.stylesheet())``
is the sanctioned central application point, exactly like
``widgets/stylekit.py`` is the sanctioned local-QSS generator for the D4
gate (``check_style_sources.py``).

Usage:
    python scripts/check_inline_styles.py            # gate (CI / pre-push)
    python scripts/check_inline_styles.py --update   # lower the ledger
    python scripts/check_inline_styles.py --update --force   # allow growth
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = Path(__file__).resolve().parent / "style_ledger.json"

SCOPED_DIRS = [
    "AssetsManager/panels",
    "AssetsManager/widgets",
    "AssetsManager/dialogs",
]
SCOPED_FILES = [
    "AssetsManager/window.py",
    "AssetsManager/window_coordinator.py",
    "AssetsManager/dock_factory.py",
]
# The central application point is the one legitimate setStyleSheet caller
# outside the migration surface.
EXEMPT_FILES = {
    "AssetsManager/app.py",
}


def _scoped_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for relative in SCOPED_DIRS:
        directory = root / relative
        if directory.is_dir():
            files.extend(sorted(directory.rglob("*.py")))
    for relative in SCOPED_FILES:
        path = root / relative
        if path.is_file():
            files.append(path)
    return sorted(set(files))


def _count_calls(path: Path) -> int:
    """Count ``*.setStyleSheet(...)`` calls via AST (comments excluded)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return 0
    return sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "setStyleSheet"
    )


def _actual_counts(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in _scoped_files(root):
        relative = path.relative_to(root).as_posix()
        if relative in EXEMPT_FILES:
            continue
        count = _count_calls(path)
        if count:
            counts[relative] = count
    return counts


def _load_ledger() -> dict:
    if not LEDGER_PATH.is_file():
        return {"entries": {}}
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def _write_ledger(entries: dict[str, int]) -> None:
    payload = {
        "_comment": (
            "G1 ratchet ledger (audit F3/G1): per-file setStyleSheet allowance "
            "in the presentation layer. Counts may only DECREASE via "
            "StyleKit/central-QSS migration; new calls fail "
            "check_inline_styles.py. Lower allowances with: python "
            "scripts/check_inline_styles.py --update. app.py (central "
            "application point) and core/ are exempt by design."
        ),
        "entries": dict(sorted(entries.items())),
    }
    LEDGER_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ratchet gate: presentation setStyleSheet counts may only decrease (G1).")
    parser.add_argument(
        "--update", action="store_true",
        help="Rewrite the ledger from the current tree (decreases only).")
    parser.add_argument(
        "--force", action="store_true",
        help="With --update, allow count increases (reviewable escape hatch).")
    args = parser.parse_args(argv)

    root = ROOT
    actual = _actual_counts(root)
    ledger = _load_ledger()
    entries: dict[str, int] = ledger.get("entries", {})

    if args.update:
        increases = {
            path: (entries.get(path, 0), count)
            for path, count in actual.items()
            if count > entries.get(path, 0)
        }
        if increases and not args.force:
            print("refusing --update: counts increased (use --force to override):",
                  file=sys.stderr)
            for path, (old, new) in sorted(increases.items()):
                print(f"  {path}: {old} -> {new}", file=sys.stderr)
            return 1
        _write_ledger(actual)
        total = sum(actual.values())
        print(f"style_ledger.json updated: {total} calls across {len(actual)} files")
        return 0

    violations: list[str] = []
    for path, count in sorted(actual.items()):
        allowed = entries.get(path, 0)
        if count > allowed:
            violations.append(
                f"{path}: {count} setStyleSheet call(s) > ledger allowance "
                f"{allowed} — new local QSS must go through StyleKit or the "
                f"central theme; lower the count via migration and run "
                f"`python scripts/check_inline_styles.py --update`.")
    total = sum(actual.values())
    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        print(
            f"check_inline_styles: {len(violations)} violation(s) "
            f"({total} calls across {len(actual)} files)",
            file=sys.stderr,
        )
        return 1
    print(
        f"check_inline_styles: clean — {total} calls across {len(actual)} files "
        f"(ratchet baseline held)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
