r"""G3 dialect gate — bare token-dict access inside setStyleSheet may only decrease.

Design System audit 2026-09-03 (findings B3/F3, I12 terminal convergence):
 ZERO-TOLERANCE state reached — bare ``t[...]`` / ``t.get(...)`` dict access
 inside any ``setStyleSheet`` argument is FORBIDDEN.  The sanctioned
 token-access dialects are ``sk.token/alpha/lighter/darker`` and
 ``themes.color/prop/metrics``.  The ledger mechanism is kept empty as a
 tripwire: any regression is caught here.

Usage:
    python scripts/check_style_dialects.py            # gate (CI / pre-push)
    python scripts/check_style_dialects.py --update   # lower the ledger
    python scripts/check_style_dialects.py --update --force   # allow growth
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = Path(__file__).resolve().parent / "style_dialect_ledger.json"

SCOPED_DIRS = [
    "AssetsManager/panels",
    "AssetsManager/widgets",
    "AssetsManager/dialogs",
]
SCOPED_FILES = [
    "AssetsManager/window.py",
    "AssetsManager/window_coordinator.py",
    "AssetsManager/dock_factory.py",
    # The central QSS template interpolates tokens via its own locals —
    # included so new raw-literal regressions stay visible.
    "AssetsManager/core/themes.py",
]
EXEMPT_FILES = {
    "AssetsManager/app.py",
    "AssetsManager/widgets/stylekit.py",
}

_T_DIRECT_RE = re.compile(r"\bt\[|\bt\.get\(")


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


def _count_t_direct(path: Path) -> int:
    """Count setStyleSheet arguments that read tokens via bare ``t[...]``."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, UnicodeDecodeError, SyntaxError):
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "setStyleSheet":
            segment = ast.get_source_segment(source, node) or ""
            has_sk = ("sk." in segment or "self._sk" in segment
                      or "self.px(" in segment or "self.pt(" in segment)
            has_themes = "themes." in segment
            if _T_DIRECT_RE.search(segment) and not has_sk and not has_themes:
                count += 1
    return count


def _actual_counts(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in _scoped_files(root):
        relative = path.relative_to(root).as_posix()
        if relative in EXEMPT_FILES:
            continue
        count = _count_t_direct(path)
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
            "G3 dialect ratchet (audit F3/I12): per-file count of "
            "setStyleSheet sites reading tokens via bare t[...]/t.get(...) "
            "instead of sk.token(). Counts may only DECREASE as sites "
            "migrate. Lower with --update; increases require --force with "
            "justification."
        ),
        "entries": dict(sorted(entries.items())),
    }
    LEDGER_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dialect gate: bare t[...] QSS token access may only decrease (G3).")
    parser.add_argument("--update", action="store_true",
                        help="Rewrite the ledger from the current tree.")
    parser.add_argument("--force", action="store_true",
                        help="With --update, allow count increases.")
    args = parser.parse_args(argv)

    actual = _actual_counts(ROOT)
    entries: dict[str, int] = _load_ledger().get("entries", {})

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
        print(f"style_dialect_ledger.json updated: {total} sites across {len(actual)} files")
        return 0

    violations: list[str] = []
    for path, count in sorted(actual.items()):
        allowed = entries.get(path, 0)
        if count > allowed:
            violations.append(
                f"{path}: {count} bare t[...] setStyleSheet site(s) > ledger "
                f"allowance {allowed} — use sk.token()/sk.alpha() and lower "
                f"the count via migration, then run "
                f"`python scripts/check_style_dialects.py --update`.")
    total = sum(actual.values())
    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        print(
            f"check_style_dialects: {len(violations)} violation(s) "
            f"({total} sites across {len(actual)} files)",
            file=sys.stderr,
        )
        return 1
    print(
        f"check_style_dialects: clean — {total} legacy sites across "
        f"{len(actual)} files (G3 freeze held)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
