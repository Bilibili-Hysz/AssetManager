"""S2 static gate — pages may not reach API factories/clients directly.

Data access in ``webui/src/pages`` must go through the shared layer
(``hooks/usePageApis`` / ``useCachedQuery`` / domain hooks), so fetch
boilerplate, cancellation, and cache invalidation stay in one place.

Forbidden in every page source file:
  - importing anything under ``api/`` except ``api/errors`` (error classes
    are not data factories);
  - calling ``createApiClient`` or another api factory directly;
  - calling ``fetch`` directly.

Exit code 0 = clean, 1 = violations. CI runs it like
``python scripts/check_frontend_data_fetch.py``.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES_DIR = ROOT / "webui" / "src" / "pages"

_IMPORT_RE = re.compile(
    r"""from\s+['"](?P<path>(?:\.\./)+(?:api/|client)|(?:src|@)/api/)[^'"]*['"]"""
)
_API_ERRORS_RE = re.compile(r"""from\s+['"](?:\.\./)+api/errors['"]""")
_CLIENT_CALL_RE = re.compile(r"\b(?:createApiClient|create[A-Z][A-Za-z]*Api)\s*\(")
_FETCH_CALL_RE = re.compile(r"\bfetch\s*\(")


@dataclass(frozen=True)
class Violation:
    relative: str
    line: int
    rule: str
    snippet: str

    def format(self) -> str:
        return (
            f"{self.relative}:{self.line}: [{self.rule}] "
            f"{self.snippet.strip()[:160]}"
        )


def _page_files(root: Path) -> list[Path]:
    if not PAGES_DIR.is_dir():
        return []
    return sorted(
        path for path in PAGES_DIR.rglob("*")
        if path.is_file() and path.suffix in {".ts", ".tsx"}
        and ".test." not in path.name
    )


def collect_violations(root: Path = ROOT) -> list[Violation]:
    violations: list[Violation] = []
    for path in _page_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for index, line in enumerate(lines, start=1):
            if _API_ERRORS_RE.search(line):
                continue
            if _IMPORT_RE.search(line):
                violations.append(Violation(
                    relative, index, "api-factory-import", line))
                continue
            if _CLIENT_CALL_RE.search(line):
                violations.append(Violation(
                    relative, index, "api-factory-call", line))
                continue
            if _FETCH_CALL_RE.search(line):
                violations.append(Violation(
                    relative, index, "direct-fetch", line))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Forbid direct api/fetch access from pages (S2 gate).")
    args = parser.parse_args(argv)
    del args
    violations = collect_violations()
    for violation in violations:
        print(violation.format())
    print(
        f"check_frontend_data_fetch: {len(violations)} violation(s) "
        f"across {len(_page_files(ROOT))} page file(s)",
    )
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
