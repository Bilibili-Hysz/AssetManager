"""L1 static gate — every LAN write route must declare its capability.

Parses ``AssetsManager/lan/api.py`` without importing it (CI lint stage has
no aiohttp dependency). For each ``_add`` registration of POST/PUT/PATCH/
DELETE, the effective policy is resolved through the local policy constants
and method-scoped ``declare`` overrides; a missing ``capabilities`` tuple is
a violation, so a new public/public_optional write cannot slip in relying on
handler-level checks alone.

The known-capability vocabulary is read from
``AssetsManager/lan/route_policy.py`` (``KNOWN_CAPABILITIES``) so the gate
cannot drift from the runtime validation in ``RoutePolicy.__post_init__``.

Exit code 0 = clean, 1 = violations. CI runs it like
``python scripts/check_route_capabilities.py``.
"""
from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_PATH = ROOT / "AssetsManager" / "lan" / "api.py"
POLICY_PATH = ROOT / "AssetsManager" / "lan" / "route_policy.py"

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
DEFAULT_POLICY = {"auth": "required", "rate_limit": "general",
                  "capabilities": ()}


@dataclass(frozen=True)
class Violation:
    line: int
    rule: str
    message: str

    def format(self) -> str:
        return f"AssetsManager/lan/api.py:{self.line}: [{self.rule}] {self.message}"


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _tuple_strings(node: ast.AST) -> tuple[str, ...] | None:
    if isinstance(node, (ast.Tuple, ast.List)):
        values: list[str] = []
        for element in node.elts:
            value = _const_str(element)
            if value is None:
                return None
            values.append(value)
        return tuple(values)
    return None


def _resolve_capabilities(node: ast.AST | None, constants: dict) -> tuple | None:
    """Resolve a capabilities expression to a string tuple (or ()).

    Returns ``None`` when the expression cannot be resolved statically —
    the caller reports it as a violation rather than silently passing.
    """
    if node is None:
        return ()
    if isinstance(node, ast.Name):
        entry = constants.get(node.id)
        if entry is None:
            return None
        return entry.get("capabilities")
    return _tuple_strings(node)


def _parse_policy(node: ast.AST | None, constants: dict) -> dict | None:
    """Parse a RoutePolicy(...) call or a reference to a policy constant."""
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return None
    if node.func.id != "RoutePolicy":
        return None
    policy = dict(DEFAULT_POLICY)
    policy["line"] = node.lineno
    for keyword in node.keywords:
        if keyword.arg == "auth":
            auth = _const_str(keyword.value)
            if auth is not None:
                policy["auth"] = auth
        elif keyword.arg == "rate_limit":
            rate_limit = _const_str(keyword.value)
            if rate_limit is not None:
                policy["rate_limit"] = rate_limit
        elif keyword.arg == "capabilities":
            capabilities = _resolve_capabilities(keyword.value, constants)
            if capabilities is None:
                policy["capabilities"] = None
            else:
                policy["capabilities"] = capabilities
    return policy


def _known_capabilities(root: Path) -> set[str]:
    source = POLICY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(POLICY_PATH))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "KNOWN_CAPABILITIES":
                if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                    if node.value.func.id == "frozenset" and node.value.args:
                        inner = node.value.args[0]
                        if isinstance(inner, ast.Set):
                            found = {v.value for v in inner.elts
                                     if isinstance(v, ast.Constant) and isinstance(v.value, str)}
                            if found:
                                return found
    raise RuntimeError("KNOWN_CAPABILITIES not found in route_policy.py")


def collect_violations(root: Path = ROOT) -> list[Violation]:
    source = API_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(API_PATH))
    known = _known_capabilities(root)

    constants: dict[str, dict] = {}
    entries: dict[tuple[str, str], dict] = {}
    overrides: dict[tuple[str, str], dict] = {}

    setup = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "setup_routes"),
        None,
    )
    if setup is None:
        return [Violation(1, "setup-routes-missing", "setup_routes not found")]

    violations: list[Violation] = []
    for statement in setup.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if not isinstance(target, ast.Name) or not target.id.startswith("_"):
                    continue
                policy = _parse_policy(statement.value, constants)
                if policy is not None:
                    constants[target.id] = policy
                    continue
                # Capability tuples are plain tuple/list assignments.
                capabilities = _tuple_strings(statement.value)
                if capabilities is not None:
                    constants[target.id] = {
                        "auth": "required", "rate_limit": "general",
                        "capabilities": capabilities,
                    }
            continue
        if not isinstance(statement, ast.Expr) or not isinstance(
            statement.value, ast.Call
        ):
            continue
        call = statement.value
        if not isinstance(call.func, ast.Name):
            continue
        if call.func.id == "_add" and len(call.args) >= 3:
            method = _const_str(call.args[1])
            path = _const_str(call.args[2])
            if method is None or path is None:
                continue
            policy = dict(DEFAULT_POLICY)
            for keyword in call.keywords:
                if keyword.arg == "policy":
                    parsed = _parse_policy(keyword.value, constants)
                    if parsed is None:
                        violations.append(Violation(
                            call.lineno, "unresolved-policy",
                            "policy expression cannot be resolved statically",
                        ))
                    else:
                        policy = parsed
            policy["line"] = call.lineno
            entries[(method, path)] = policy
        elif call.func.id == "declare" and len(call.args) >= 3:
            path = _const_str(call.args[1])
            method = ""
            for keyword in call.keywords:
                if keyword.arg == "method":
                    method = _const_str(keyword.value) or ""
            if path is None:
                continue
            parsed = _parse_policy(call.args[2], constants)
            if parsed is None:
                violations.append(Violation(
                    call.lineno, "unresolved-policy",
                    "declare policy expression cannot be resolved statically",
                ))
                continue
            parsed["line"] = call.lineno
            overrides[(method, path)] = parsed

    for (method, path), policy in entries.items():
        if method not in WRITE_METHODS:
            continue
        effective = overrides.get((method, path), policy)
        line = effective.get("line", 0) or 0
        capabilities = effective.get("capabilities", ())
        if capabilities is None:
            violations.append(Violation(
                line, "unresolved-capability",
                f"{method} {path} capabilities reference cannot be resolved",
            ))
            continue
        if not capabilities:
            violations.append(Violation(
                line, "missing-capability",
                f"{method} {path} ({effective.get('auth', 'required')}) "
                f"declares no capability",
            ))
            continue
        unknown = sorted(set(capabilities) - known)
        if unknown:
            violations.append(Violation(
                line, "unknown-capability",
                f"{method} {path} declares unknown capability: {', '.join(unknown)}",
            ))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Forbid capability-less LAN write routes (L1 gate).")
    args = parser.parse_args(argv)
    del args
    violations = collect_violations()
    for violation in violations:
        print(violation.format())
    print(f"check_route_capabilities: {len(violations)} violation(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
