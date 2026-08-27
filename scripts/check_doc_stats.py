#!/usr/bin/env python3
"""Document-stats drift gate (D4/D6).

Keeps README.md's structural counts honest by measuring them instead of
maintaining them by hand. Two modes:

    python scripts/check_doc_stats.py            # verify: exit 1 on drift
    python scripts/check_doc_stats.py --fix      # rewrite the stats marker
    python scripts/check_doc_stats.py \
        --with-results python=3450/7 webui=683 e2e=51/2   # stamp run results

Structural counts (routes, file/test counts, e2e declarations, and the
code-derived numbers below) are always measured. Run-dependent numbers
(passed/skipped) are stamped explicitly via --with-results because measuring
them requires running the full suites; until stamped they are carried through
from the marker, not re-verified.

Code-derived numbers (added by the external-audit follow-up) are measured
from the source tree AND checked against their README prose anchors, so a
hand-edited sentence cannot drift away from the code again:

    schema_version    db_migrations.CURRENT_SCHEMA_VERSION   -> "迁移 v1-vN"
    repos             repositories/*.py (no __init__)        -> "**N 个 SQL 仓库**"
    routes_modules    lan/routes/*.py (no __init__)          -> "N 个路由模块"
    app_services      application/*.py (no __init__)         -> "应用服务层（N 模块"
    themes            assets/Themes/*.json                   -> "N 个主题 JSON"
    domain_events     domain/events.py DomainEvent subclasses-> "N 个领域事件"
    icons             core/icons.py registry keys            -> "（N 图标"
    i18n_en/zh/ja     i18n/*.json top-level keys             -> "en N / zh N / ja N keys"

The script reads/writes one stats marker line in README.md:
    <!-- stats: routes=139 ts=217 python_test_files=229 ... -->
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
LAN_API = ROOT / "AssetsManager" / "lan" / "api.py"
WEBUI = ROOT / "webui"
TESTS = ROOT / "tests"
DB_MIGRATIONS = ROOT / "AssetsManager" / "core" / "db_migrations.py"
EVENTS = ROOT / "AssetsManager" / "domain" / "events.py"
ICONS = ROOT / "AssetsManager" / "core" / "icons.py"
REPOSITORIES = ROOT / "AssetsManager" / "repositories"
LAN_ROUTES = ROOT / "AssetsManager" / "lan" / "routes"
APPLICATION = ROOT / "AssetsManager" / "application"
THEMES = ROOT / "assets" / "Themes"
WIDGETS = ROOT / "AssetsManager" / "widgets"
CORE = ROOT / "AssetsManager" / "core"
DIALOGS = ROOT / "AssetsManager" / "dialogs"
I18N = ROOT / "AssetsManager" / "i18n"
CONTROLLERS = ROOT / "AssetsManager" / "controllers"

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


def count_module_files(directory: pathlib.Path) -> int:
    return sum(1 for p in directory.glob("*.py") if p.name != "__init__.py")


def count_domain_events() -> int:
    src = EVENTS.read_text(encoding="utf-8")
    return len(re.findall(r"^class \w+\(DomainEvent\):", src, flags=re.MULTILINE))


def count_icons() -> int:
    src = ICONS.read_text(encoding="utf-8")
    return len(re.findall(r'^\s{4}"[a-z0-9_]+":', src, flags=re.MULTILINE))


def count_i18n_keys(lang: str) -> int:
    data = json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))
    return len(data)


def count_webui_parts() -> dict[str, int]:
    def production(directory: pathlib.Path) -> int:
        return sum(1 for p in directory.glob("*.ts*") if "test" not in p.stem)
    return {
        "pages": production(WEBUI / "src" / "pages"),
        "hooks": production(WEBUI / "src" / "hooks"),
        "stores": production(WEBUI / "src" / "stores"),
    }


def schema_version() -> int:
    src = DB_MIGRATIONS.read_text(encoding="utf-8")
    m = re.search(r"^CURRENT_SCHEMA_VERSION\s*=\s*(\d+)", src, flags=re.MULTILINE)
    if not m:
        raise RuntimeError("CURRENT_SCHEMA_VERSION not found in db_migrations.py")
    return int(m.group(1))


def measured() -> dict[str, str]:
    parts = count_webui_parts()
    i18n = {f"i18n_{lang}": count_i18n_keys(lang) for lang in ("en", "zh", "ja")}
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
        # code-derived numbers
        "schema_version": str(schema_version()),
        "repos": str(count_module_files(REPOSITORIES)),
        "routes_modules": str(count_module_files(LAN_ROUTES)),
        "app_services": str(count_module_files(APPLICATION)),
        "themes": str(count_files("*.json", THEMES)),
        "widgets": str(count_module_files(WIDGETS)),
        "core": str(count_module_files(CORE)),
        "dialogs": str(count_module_files(DIALOGS)),
        "domain_events": str(count_domain_events()),
        "icons": str(count_icons()),
        "controllers": str(count_module_files(CONTROLLERS)),
        **{k: str(v) for k, v in i18n.items()},
    }


# README prose anchors derived from the measured values.  Each entry maps a
# name to (find_pattern, build_template, value_key): verify requires every
# non-empty match of find_pattern to equal values[value_key], and --fix
# rewrites all matches via build_template.  A missing anchor is a drift
# error, not a silent pass.  Several anchors may share one value_key when
# the README phrases the same number more than one way.
_ANCHORS: dict[str, tuple[re.Pattern[str], str, str]] = {
    "routes": (re.compile(r"\d+ 条路由"), "{v} 条路由", "routes"),
    "schema_version": (re.compile(r"迁移 v1-v\d+"), "迁移 v1-v{v}", "schema_version"),
    "repos_bold": (re.compile(r"\*\*\d+ 个 SQL 仓库\*\*"), "**{v} 个 SQL 仓库**", "repos"),
    "repos_paren": (re.compile(r"（\d+ 个 SQL 仓库）"), "（{v} 个 SQL 仓库）", "repos"),
    "routes_modules": (re.compile(r"\d+ 个路由模块"), "{v} 个路由模块", "routes_modules"),
    "app_services_cn": (re.compile(r"应用服务层（\d+ 模块"), "应用服务层（{v} 模块", "app_services"),
    "app_services_ascii": (re.compile(r"Application Layer（\d+ 模块）"), "Application Layer（{v} 模块）", "app_services"),
    "themes": (re.compile(r"\d+ 个主题 JSON"), "{v} 个主题 JSON", "themes"),
    "widgets": (re.compile(r"可复用 Qt 组件（\d+ 个）"), "可复用 Qt 组件（{v} 个）", "widgets"),
    "core": (re.compile(r"基础设施层（\d+ 模块"), "基础设施层（{v} 模块", "core"),
    "dialogs": (re.compile(r"Qt 对话框（\d+ 个）"), "Qt 对话框（{v} 个）", "dialogs"),
    "domain_events": (re.compile(r"\d+ 个领域事件"), "{v} 个领域事件", "domain_events"),
    "icons": (re.compile(r"（\d+ 图标"), "（{v} 图标", "icons"),
    "e2e_specs": (re.compile(r"\d+ 个 spec"), "{v} 个 spec", "e2e_specs"),
    "routes_modules_tree": (re.compile(r"routes/ \d+ 模块"), "routes/ {v} 模块", "routes_modules"),
    "ts_tree": (re.compile(r"\d+ ts/tsx 生产源码"), "{v} ts/tsx 生产源码", "ts"),
    "hooks_tree": (re.compile(r"hooks\(\d+\)"), "hooks({v})", "hooks"),
    "pages_tree": (re.compile(r"pages\(\d+\)"), "pages({v})", "pages"),
    "stores_tree": (re.compile(r"stores\((\d+) Context\)"), "stores({v} Context)", "stores"),
    "controllers": (re.compile(r"\d+ 个无 Qt 控制器"), "{v} 个无 Qt 控制器", "controllers"),
}
_I18N_ANCHOR = re.compile(r"en \d+ / zh \d+ / ja \d+ keys")


def _flat_matches(pattern: re.Pattern[str], src: str) -> list[str]:
    """Return the meaningful number of every match; tuple groups are flattened.

    Anchors may legitimately contain several numbers (``迁移 v1-v27``), so the
    *last* number of each matched span is compared against the measured value.
    """
    flat: list[str] = []
    for match in pattern.findall(src):
        parts = match if isinstance(match, tuple) else (match,)
        for part in parts:
            if not part:
                continue
            nums = re.findall(r"\d+", part)
            if nums:
                flat.append(nums[-1])
    return flat


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


def body_drift(src: str, values: dict[str, str]) -> list[str]:
    """Return drift lines for README prose anchors vs measured values."""
    problems: list[str] = []
    for name, (pattern, _, value_key) in _ANCHORS.items():
        matches = _flat_matches(pattern, src)
        if not matches:
            problems.append(f"{name}: README prose anchor missing")
            continue
        expected = values[value_key]
        if any(m != expected for m in matches):
            problems.append(f"{name}: README={sorted(set(matches))} measured={expected}")
    i18n_match = _I18N_ANCHOR.search(src)
    if not i18n_match:
        problems.append("i18n: README prose anchor missing")
    else:
        expected = f"en {values['i18n_en']} / zh {values['i18n_zh']} / ja {values['i18n_ja']} keys"
        if i18n_match.group(0) != expected:
            problems.append(f"i18n: README={i18n_match.group(0)!r} measured={expected!r}")
    return problems


def fix_body(src: str, values: dict[str, str]) -> str:
    for name, (pattern, template, value_key) in _ANCHORS.items():
        replacement = template.format(v=values[value_key])
        src, count = pattern.subn(replacement, src)
        if count == 0:
            print(f"warning: no prose anchor replaced for {name}", file=sys.stderr)
    expected = f"en {values['i18n_en']} / zh {values['i18n_zh']} / ja {values['i18n_ja']} keys"
    src, count = _I18N_ANCHOR.subn(expected, src)
    if count == 0:
        print("warning: no i18n prose anchor replaced", file=sys.stderr)
    return src


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
    marker_drift = [f"{k}: README={stored.get(k)} measured={values[k]}"
                    for k in sorted(values) if stored.get(k) != values[k]]

    src = README.read_text(encoding="utf-8")
    prose_drift = body_drift(src, values)

    if args.fix:
        new_src = fix_body(src, values)
        if new_src != src:
            README.write_text(new_src, encoding="utf-8")
        write_marker(marker[0] if marker else "", values)
        print("README stats marker updated:", " ".join(f"{k}={v}" for k, v in sorted(values.items())))
        return 0

    if marker is None:
        print("no stats marker in README.md — run with --fix to create one", file=sys.stderr)
        return 1
    drift = marker_drift + prose_drift
    if drift:
        print("documentation drift detected:", file=sys.stderr)
        for line in drift:
            print("  " + line, file=sys.stderr)
        return 1
    print("README stats are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
