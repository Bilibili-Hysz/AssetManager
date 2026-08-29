r"""WebUI static gate — every referenced CSS custom property must be defined.
Scanned surface:
    webui/src/**/*.{css,ts,tsx} (Tailwind arbitrary-value classes like
    ``bg-[var(--color-x)]`` are covered: they contain the same ``var(--x)``
    reference syntax).

Enforced rule:
    1. Every ``var(--name)`` reference must have at least one definition of
       ``--name`` somewhere under ``webui/src`` — either a CSS declaration
       (``--name: value;``, including the generated themes.generated.css and
       hand-written index.css / page stylesheets) or a TSX inline custom
       property (``'--name': value`` style-object keys and
       ``element.style.setProperty('--name', ...)`` calls). This is the gate
       for the class of bug where a token rename left references pointing at
       a name nothing defines, silently rendering transparent scrims and
       colorless panels.

Exemptions:
    - ``--tw-*``: owned and defined by Tailwind's runtime, not by our source.
    - Comments are not parsed; a custom-property-looking ``--name:`` inside a
      comment still counts as a definition. Over-counting definitions only
      weakens the gate for names that are (almost always) also defined for
      real, so a textual scan is the right cost/precision trade-off.

Exit code 0 = clean, 1 = violations. CI runs it like
``python scripts/check_web_token_usage.py``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNED_SUFFIXES = {".css", ".ts", ".tsx"}

# Tailwind-generated custom properties (`--tw-ring-color`, ...) are defined by
# the framework at build time, never in our source.
EXEMPT_PREFIXES = ("--tw-",)

REFERENCE_RE = re.compile(r"\bvar\(\s*(--[A-Za-z][A-Za-z0-9-]*)")
# CSS declarations: `--name: value;`
CSS_DEFINITION_RE = re.compile(r"(--[A-Za-z][A-Za-z0-9-]*)\s*:")
# TS/TSX inline styles: quoted object keys `'--name': value` and
# `setProperty('--name', value)` calls.
TS_DEFINITION_RE = re.compile(r"['\"](--[A-Za-z][A-Za-z0-9-]*)['\"]\s*:")
SET_PROPERTY_RE = re.compile(r"setProperty\(\s*['\"](--[A-Za-z][A-Za-z0-9-]*)['\"]")


@dataclass(frozen=True)
class Violation:
    """One undefined-token-reference gate failure."""

    path: str
    line: int
    rule: str
    snippet: str

    def format(self) -> str:
        return (
            f"{self.path}:{self.line}: [{self.rule}] "
            f"{self.snippet.strip()[:160]}"
        )


def _is_exempt(name: str) -> bool:
    return name.startswith(EXEMPT_PREFIXES)


def _scoped_files(root: Path = ROOT) -> list[Path]:
    scanned_dir = root / "webui" / "src"
    if not scanned_dir.is_dir():
        return []
    return sorted(
        path for path in scanned_dir.rglob("*")
        if path.is_file() and path.suffix in SCANNED_SUFFIXES
    )


def collect_violations(root: Path = ROOT) -> list[Violation]:
    """Return every undefined-token reference under ``webui/src``."""
    files = _scoped_files(root)
    definitions: set[str] = set()
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        definitions.update(SET_PROPERTY_RE.findall(source))
        # The TS pattern is a superset of plain `--name:` text, so running it
        # over CSS too is harmless and keeps one code path.
        for pattern in (CSS_DEFINITION_RE, TS_DEFINITION_RE):
            definitions.update(pattern.findall(source))

    violations: list[Violation] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for index, line in enumerate(source.splitlines(), start=1):
            for name in REFERENCE_RE.findall(line):
                if _is_exempt(name) or name in definitions:
                    continue
                violations.append(Violation(
                    relative, index, "undefined-css-token", line))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Forbid references to undefined WebUI CSS tokens.")
    parser.add_argument(
        "--json", action="store_true",
        help="Emit violations as JSON objects on stdout.")
    args = parser.parse_args(argv)

    violations = collect_violations()
    if args.json:
        payload = [{
            "path": v.path,
            "line": v.line,
            "rule": v.rule,
            "snippet": v.snippet,
        } for v in violations]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for violation in violations:
            print(violation.format())
        print(
            f"check_web_token_usage: {len(violations)} violation(s) "
            f"across {len(_scoped_files())} scoped file(s)",
        )
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
