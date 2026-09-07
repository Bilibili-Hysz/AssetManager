"""P1 measurement 4 — module-level cache inventory (static scan).

AST-scans every module under ``AssetsManager/`` (plus ``main.py``) for
module-level mutable containers (dict / set / list / OrderedDict / Counter /
defaultdict) and ``functools.lru_cache``/``cache`` decorators, then classifies
each cache-like binding by its eviction mechanism:

* ``bounded``   — an explicit cap constant, a length-checked trim, popitem,
                  or a ``.clear()`` on the binding within the same module
* ``session``   — keyed by library/session/process lifetime and explicitly
                  cleared on teardown (the module calls ``.clear()`` on it)
* ``unbounded`` — grows with input, no cap or eviction found in the module

Static classification only: the JSON records the evidence lines so a human
can re-check each verdict.  Files under ``AssetsManager/lan/`` are scanned
read-only (another audit stream owns that package).

Evidence: docs/reports/performance-audit-2026-09-06/evidence/p1-cache-inventory.json

Usage:
    python scripts/perf/p1_cache_inventory.py
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _p1_common import project_root, write_json  # noqa: E402

_MUTABLE_LITERALS = (ast.Dict, ast.Set, ast.List)
_MUTABLE_CALLS = {"dict", "set", "list", "OrderedDict", "Counter", "defaultdict"}
_CACHE_NAME_HINT = re.compile(r"cache|memo|registry|_instances|_pool|_loaded|_lockup", re.I)


def _call_name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Name):
            return fn.id
        if isinstance(fn, ast.Attribute):
            return fn.attr
    return None


def scan_module(path: Path, rel: str) -> list[dict]:
    """Return inventory entries for one module."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return [{"file": rel, "error": str(exc)}]

    lines = source.splitlines()
    entries: list[dict] = []

    # functools.lru_cache / cache decorated functions (module-wide).
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            name = _call_name(dec)
            if name is None:
                d = dec
                if isinstance(d, ast.Attribute) and d.attr in ("lru_cache", "cache"):
                    name = d.attr
                elif isinstance(d, ast.Name) and d.id in ("lru_cache", "cache"):
                    name = d.id
            if name in ("lru_cache", "cache"):
                maxsize = None
                if isinstance(dec, ast.Call):
                    for kw in dec.keywords:
                        if kw.arg == "maxsize":
                            try:
                                maxsize = ast.literal_eval(kw.value)
                            except Exception:
                                maxsize = kw.value.__class__.__name__
                    if not dec.keywords:
                        maxsize = "default(128)"
                else:
                    maxsize = "default(128)"
                entries.append({
                    "file": rel,
                    "line": node.lineno,
                    "name": f"{node.name}()",
                    "kind": f"functools.{name}",
                    "capacity": maxsize,
                    "verdict": "bounded" if maxsize not in (None, "None") else "unbounded",
                    "evidence": f"maxsize={maxsize}",
                })

    # Module-level mutable bindings.
    for node in tree.body:  # module level only
        targets: list[tuple[str, int]] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            value = node.value
            targets = [(t.id, node.lineno) for t in node.targets
                       if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            value = node.value
            if isinstance(node.target, ast.Name):
                targets = [(node.target.id, node.lineno)]

        for name, lineno in targets:
            kind = None
            if isinstance(value, _MUTABLE_LITERALS):
                kind = type(value).__name__.lower()
            else:
                call = _call_name(value)
                if call in _MUTABLE_CALLS:
                    kind = call
            if kind is None:
                continue

            # How is this name used elsewhere in the module?  Eviction hints.
            uses = re.findall(
                rf"\b{re.escape(name)}\.(clear|popitem|pop)\b", source)
            cap_consts = sorted(set(re.findall(
                r"\b(_?[A-Z][A-Z0-9_]*(?:MAX|LIMIT|CAP|SIZE|TTL)[A-Z0-9_]*)\b",
                source)))

            entries.append({
                "file": rel,
                "line": lineno,
                "name": name,
                "kind": kind,
                "cache_like": bool(_CACHE_NAME_HINT.search(name)),
                "eviction_calls": sorted(set(uses)),
                "cap_constants": cap_consts,
                "evidence": lines[lineno - 1].strip()[:120],
            })
    return entries


def classify(entry: dict) -> str:
    """Human-reviewed verdict helper: bounded / session-cleared / unbounded / review."""
    if "error" in entry:
        return "error"
    if "functools" in entry.get("kind", ""):
        return entry["verdict"]
    if entry.get("eviction_calls"):
        return "eviction-in-module"
    if entry.get("cap_constants"):
        return "cap-const-present"
    if entry.get("cache_like"):
        return "review"
    return "plain-state"


def main() -> int:
    root = project_root()
    entries: list[dict] = []
    for base in [root / "AssetsManager", root / "main.py"]:
        files = ([base] if base.is_file()
                 else sorted(base.rglob("*.py")))
        for path in files:
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(root).as_posix()
            entries.extend(scan_module(path, rel))

    for e in entries:
        e["verdict"] = classify(e)

    cache_like = [e for e in entries if e.get("cache_like") or "functools" in e.get("kind", "")]
    by_verdict: dict[str, list[dict]] = {}
    for e in cache_like:
        by_verdict.setdefault(e["verdict"], []).append(e)

    payload = {
        "measurement": "cache-inventory",
        "scope": "AssetsManager/** + main.py (lan/ read-only)",
        "mutable_bindings_total": len([e for e in entries if "functools" not in e.get("kind", "")]),
        "cache_like_total": len(cache_like),
        "by_verdict": {k: len(v) for k, v in sorted(by_verdict.items())},
        "cache_like_entries": cache_like,
        "all_mutable_bindings": [e for e in entries if "functools" not in e.get("kind", "")],
    }
    write_json("p1-cache-inventory.json", payload)

    print(f"cache-like bindings: {len(cache_like)}")
    for verdict, items in sorted(by_verdict.items()):
        print(f"\n== {verdict} ({len(items)}) ==")
        for e in items:
            print(f"  {e['file']}:{e['line']}  {e['name']}  ({e.get('kind')})"
                  f"  caps={e.get('cap_constants') or e.get('capacity') or '-'}"
                  f"  evict={e.get('eviction_calls') or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
