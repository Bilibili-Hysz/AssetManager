#!/usr/bin/env python3
"""Document maintenance gate (docs three-state discipline, 2026-08-27).

Enforces the LIVING / FROZEN / ARCHIVED classification introduced by the
2026-08-27 documentation maintenance batch:

    1. LIVING docs carry an ``updated: YYYY-MM-DD`` header line and are not
       older than 30 days (``--ignore-age`` bypasses the age check).
    2. Every file under ``docs/archive/`` (except the INDEX itself) has a
       registration row inside ``docs/archive/INDEX.md``.
    3. FROZEN clusters carry a ``FROZEN`` marker in their entry README/head
       (docs/baseline-2026-08-01 (ex-DeepSeek Docs), deep-weakness-audit, Plugins/Docs manuals).
    4. Pre-2026-07-21 ``docs/compose/`` specs/plans (and the two undated plans)
       carry the ``ARCHIVED`` header line added by that batch.
    5. The navigation entries shared by README/overview point at existing files.

Exit code 1 on any drift; 0 when current.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

LIVING = [
    "README.md",
    "docs/README.md",
    "docs/perf-baseline-2026-08-29.md",
    "docs/architecture.md",
    "docs/architecture-diagram.md",
    "docs/lan-security.md",
    "docs/migrations.md",
    "docs/development.md",
    "docs/testing.md",
    "docs/adr/0001-architecture-governance.md",
    "docs/adr/0002-library-session.md",
    "docs/adr/0003-library-runtime.md",
    "docs/compose/README.md",
]

UPDATED_RE = re.compile(r"updated:\s*(\d{4}-\d{2}-\d{2})")

FROZEN_MARKERS = [
    "docs/baseline-2026-08-01/README.md",
    "docs/deep-weakness-audit-2026-08-22/README.md",
    "Plugins/Docs/API.md",
    "Plugins/Docs/MODULE_INTERFACES.md",
    "Plugins/Docs/PLUGIN_SYSTEM.md",
]

ARCHIVE_INDEX = ROOT / "docs" / "archive" / "INDEX.md"
COMPOSE_SPECS = ROOT / "docs" / "compose" / "specs"
COMPOSE_PLANS = ROOT / "docs" / "compose" / "plans"
NAVIGATION_TARGETS = [
    "docs/README.md",
    "docs/overview-2026-08-27.md",
    "docs/archive/INDEX.md",
    "docs/compose/README.md",
    "docs/architecture.md",
    "docs/migrations.md",
    "docs/lan-security.md",
    "docs/development.md",
    "docs/testing.md",
]


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def check_living(ignore_age: bool, problems: list[str]) -> None:
    today = _dt.datetime.now(tz=_dt.timezone.utc).date()
    for rel in LIVING:
        path = ROOT / rel
        if not path.exists():
            problems.append(f"LIVING missing: {rel}")
            continue
        m = UPDATED_RE.search(_read(path))
        if not m:
            problems.append(f"LIVING has no 'updated: YYYY-MM-DD' header: {rel}")
            continue
        if ignore_age:
            continue
        try:
            updated = _dt.date.fromisoformat(m.group(1))
        except ValueError:
            problems.append(f"LIVING 'updated:' is not a date: {rel}")
            continue
        if (today - updated).days > 30:
            problems.append(f"LIVING doc older than 30 days ({m.group(1)}): {rel}")


def check_archive_index(problems: list[str]) -> None:
    if not ARCHIVE_INDEX.exists():
        problems.append("docs/archive/INDEX.md missing")
        return
    index_text = _read(ARCHIVE_INDEX)
    for path in (ROOT / "docs" / "archive").rglob("*"):
        if path.is_file() and path.name != "INDEX.md":
            rel = path.relative_to(ROOT / "docs" / "archive")
            if rel.as_posix() not in index_text:
                problems.append(f"archive file not registered in INDEX.md: {rel.as_posix()}")


def check_frozen(problems: list[str]) -> None:
    for rel in FROZEN_MARKERS:
        path = ROOT / rel
        if not path.exists():
            problems.append(f"FROZEN marker target missing: {rel}")
            continue
        if "FROZEN" not in _read(path):
            problems.append(f"FROZEN marker missing in {rel}")


def check_compose_archived(problems: list[str]) -> None:
    for directory in (COMPOSE_SPECS, COMPOSE_PLANS):
        for path in directory.glob("*.md"):
            name = path.name
            prefix = name[:10]
            is_pre_recalibration = False
            try:
                is_pre_recalibration = _dt.date.fromisoformat(prefix) < _dt.date(2026, 7, 21)
            except ValueError:
                is_pre_recalibration = name in ("lan-error-audit.md", "p1-audit-findings.md")
            if not is_pre_recalibration:
                continue
            if "ARCHIVED" not in _read(path):
                problems.append(f"pre-07-21 compose doc missing ARCHIVED header: {path.relative_to(ROOT)}")


def check_navigation(problems: list[str]) -> None:
    for rel in NAVIGATION_TARGETS:
        if not (ROOT / rel).exists():
            problems.append(f"navigation target missing: {rel}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ignore-age", action="store_true",
                        help="skip the 30-day freshness check on LIVING docs")
    args = parser.parse_args()

    problems: list[str] = []
    check_living(args.ignore_age, problems)
    check_archive_index(problems)
    check_frozen(problems)
    check_compose_archived(problems)
    check_navigation(problems)

    if problems:
        print("documentation maintenance drift detected:", file=sys.stderr)
        for line in problems:
            print("  " + line, file=sys.stderr)
        return 1
    print("document maintenance state is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())