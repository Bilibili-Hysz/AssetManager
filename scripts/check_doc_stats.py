#!/usr/bin/env python3
"""Document-stats drift gate (D4/D6).

Keeps README.md's structural counts honest by measuring them instead of
maintaining them by hand. Two modes:

    python scripts/check_doc_stats.py            # verify: exit 1 on drift
    python scripts/check_doc_stats.py --fix      # rewrite the stats marker
    python scripts/check_doc_stats.py \
        --with-results python=3450/7 webui=683 e2e=51/2   # stamp run results

Structural counts (routes, file/test counts, e2e declarations) are always
measured. Run-dependent numbers (passed/skipped) are stamped explicitly via
--with-results because measuring them requires running the full suites; until
stamped they are carried through from the marker, not re-verified.

The script reads/writes one stats marker line in README.md:
    <!-- stats: routes=139 ts=217 python_test_files=229 ... -->
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
LAN_API = ROOT / "AssetsManager" / "lan" / "api.py"
WEBUI = ROOT / "webui"
TESTS = ROOT / "tests"

MARKER_RE = re.compile(r"<!-- stats:(?P<body>[^>]*) -->")
PAIR_RE = re.compile(r"(\w+)=([\w/.]+)")


def count_routes() -> int:
    src = LAN_API.read_text(encoding="utf-8")
    return sum(1 for line in src.splitlines() if "_add(app," in line and "def _add" not in line)


def count_files(pattern: str, base: pathlib.Path, exclude: tuple[str, ...] = ()) -> int:
    total = 0
    for p in base.rglob(pattern):
        parts = p.parts
        if any(part in exclude for part in parts):
            continue
        total += 1
    return total


def count_webui_parts() -> dict[str, int]:
    def production(directory: pathlib.Path) -> int:
        return sum(1 for p in directory.glob("*.ts*") if "test" not in p.stem)
    return {
        "pages": production(WEBUI / "src" / "pages"),
        "hooks": production(WEBUI / "src" / "hooks"),
        "stores": production(WEBUI / "src" / "stores"),
    }


def measured() -> dict[str, str]:
    parts = count_webui_parts()
    return {
        "routes": str(count_routes()),
        # production source files under webui/src (no tests)
        "ts": str(count_files("*.ts*", WEBUI / "src") - count_files("*.test.ts*", WEBUI / "src")),
        "python_test_files": str(count_files("test_*.py", TESTS)),
        "webui_test_files": str(count_files("*.test.ts*", WEBUI / "src")),
        "e2e_specs": str(len(list((WEBUI / "e2e").glob("*.spec.ts")))),
        "pages": str(parts["pages"]),
        "hooks": str(parts["hooks"]),
        "stores": str(parts["stores"]),
    }


def read_marker() -> tuple[str, dict[str, str]] | None:
    src = README.read_text(encoding="utf-8")
    m = MARKER_RE.search(src)
    if not m:
        return None
    return m.group(0), dict(PAIR_RE.findall(m.group("body")))


def write_marker(old: str, values: dict[str, str]) -> None:
    src = README.read_text(encoding="utf-8")
    body = " ".join(f"{k}={v}" for k, v in sorted(values.items()))
    new = f"<!-- stats: {body} -->"
    if old:
        assert old in src
        src = src.replace(old, new, 1)
    else:
        anchor = "> 当前审查证据"
        assert anchor in src
        src = src.replace(anchor, new + "\n" + anchor, 1)
    README.write_text(src, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--with-results", nargs="*", default=[],
                        help="run-dependent results, e.g. python=3450/7 webui=683 e2e=51/2")
    args = parser.parse_args()

    values = measured()
    for item in args.with_results:
        key, _, value = item.partition("=")
        if not value:
            print(f"bad --with-results item: {item!r}", file=sys.stderr)
            return 2
        values[key] = value

    marker = read_marker()
    stored = marker[1] if marker else {}
    drift = [f"{k}: README={stored.get(k)} measured={values[k]}"
             for k in sorted(values) if stored.get(k) != values[k]]

    if args.fix:
        write_marker(marker[0] if marker else "", values)
        print("README stats marker updated:", " ".join(f"{k}={v}" for k, v in sorted(values.items())))
        return 0

    if marker is None:
        print("no stats marker in README.md — run with --fix to create one", file=sys.stderr)
        return 1
    if drift:
        print("documentation drift detected:", file=sys.stderr)
        for line in drift:
            print("  " + line, file=sys.stderr)
        return 1
    print("README stats are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
