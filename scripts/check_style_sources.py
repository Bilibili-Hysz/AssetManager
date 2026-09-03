r"""D4 static gate — local QSS must source colors and font sizes from tokens.
Scanned surface:
    AssetsManager/panels, AssetsManager/widgets, AssetsManager/dialogs,
    AssetsManager/window.py, AssetsManager/window_coordinator.py,
    AssetsManager/dock_factory.py

Enforced rules for QSS-looking string literals / f-strings:
    1. No hex color literals (`#rgb` / `#rrggbb` / `#rrggbbaa`).
    2. No named CSS colors (`white`, `black`, `red`, ...).
    3. No numeric font sizes — neither `font-size: 12px` nor
       `font-size: {scaled_pt(12)}px`.
    4. No hex fallback defaults next to theme-token lookups
       (`t.get("danger", "#...")`, `themes.get().get(...)`).
    5. No unscaled pixel lengths — `\d+px` in the static text of a QSS
       string / f-string must come from an interpolation such as
       `{scaled_px(10)}px`. Literal `10px` (plain string or f-string
       literal part) fails; numbers inside `{...}` interpolations pass.

The only exemptions are the StyleKit generator itself (the single entry)
and core/ (the token source). Theme preview / tag chip / color picker
widgets are still scanned: their *data-driven* colors flow through
interpolated variables, which this gate deliberately allows.

Exit code 0 = clean, 1 = violations. CI runs it like
``python scripts/check_style_sources.py``.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCOPED_DIRS = [
    "AssetsManager/panels",
    "AssetsManager/widgets",
    "AssetsManager/dialogs",
]
SCOPED_FILES = [
    "AssetsManager/window.py",
    "AssetsManager/window_coordinator.py",
    "AssetsManager/dock_factory.py",
    # The central QSS generator joins the scan (audit E5): it is the token
    # source for colors, but its own template must not carry raw unscaled
    # pixel literals either. Legit hairlines are whitelisted below.
    "AssetsManager/core/themes.py",
]

# Single-entry generators and token sources are exempt; every panel,
# widget, dialog, and shell-window local QSS is checked.
EXEMPT_FILES = {
    "AssetsManager/widgets/stylekit.py",
}

HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
NAMED_COLOR_WORDS = (
    "white", "black", "gray", "grey", "red", "green", "blue",
    "yellow", "orange", "purple", "pink", "silver", "maroon",
    "navy", "teal", "brown", "cyan", "magenta", "gold",
)
NAMED_COLOR_RE = re.compile(
    r"\b(?:color|background|border(?:-[a-z]+)*|outline)\s*:\s*"
    r"[^;{}]*?\b(" + "|".join(NAMED_COLOR_WORDS) + r")\b",
    re.IGNORECASE,
)
FONT_SIZE_RAW_RE = re.compile(r"font-size\s*:\s*(\d+)\s*(?:px|pt)\b", re.IGNORECASE)
FONT_SIZE_INTERP_RE = re.compile(
    r"font-size\s*:\s*\{\s*"
    r"(?:(?:scaled_pt|sk\.pt|self\.pt|pt)\s*\(\s*)?(\d+)\s*\)?\s*\}\s*(?:px|pt)\b",
    re.IGNORECASE,
)
TOKEN_LOOKUP_HEX_RE = re.compile(r"\bt\.get\([^\n()]*#[0-9a-fA-F]{3,8}")
THEMES_LOOKUP_HEX_RE = re.compile(
    r"themes\.get\(\)\.get\([^\n()]*#[0-9a-fA-F]{3,8}")
QSS_HINT_RE = re.compile(
    r"\b(?:color|background|font-size|border(?:-[a-z]+)*|padding|"
    r"margin(?:-[a-z]+)*|min-width|max-width)\s*:\s*",
    re.IGNORECASE,
)
# Any `\d+px` in QSS static text must be interpolation-scaled. The
# lookbehind keeps `12px` from matching as `2px`.
RAW_PX_RE = re.compile(r"(?<![\w.])(\d+)px")
# `font-size: ...px` is owned by the dedicated font-size rules; strip
# those declarations before the pixel-length scan so one literal is not
# reported under both rules.
FONT_SIZE_DECL_RE = re.compile(r"font-size\s*:\s*[^;{}]*", re.IGNORECASE)

# Per-file allowances for pixel literals that must follow the pixel grid
# instead of ui_scale. Keys are repo-relative posix paths, values are the
# exact literal tokens (e.g. "1px") that stay legal in that file. Empty
# by default — add an entry only with a design justification.
_PX_WHITELIST: dict[str, set[str]] = {
    # Zero-length never scales (scaled_px(0) == 1 would change visuals).
    "AssetsManager/widgets/workspace_bar.py": {"0px"},
    # Central theme hairline borders ("1px solid") — a hairline stays one
    # device pixel at every ui_scale by design. "2px" covers the slider
    # groove/handle structural borders; whether they should scale is an M2
    # token decision (audit E5), not a M0 gate violation.
    "AssetsManager/core/themes.py": {"1px", "2px"},
}

# Per-file RULE exemptions: a file where a specific rule must not apply.
# themes.py is the token SOURCE — the hex fallbacks in its derived-token
# lambdas define the builtin fallback palette that the
# hex-fallback-in-theme-lookup rule guards against in consumers. Its pixel
# literals are still checked (see _PX_WHITELIST).
_RULE_EXEMPT: dict[str, set[str]] = {
    "AssetsManager/core/themes.py": {"hex-fallback-in-theme-lookup"},
}

# Hex string constants passed straight to QColor()/similar constructors in
# non-QSS positions escape the QSS-string rules above. Only files whose
# FUNCTION is editing colors (a color picker's default swatch) may list
# values here, with a justification.
_HEX_CONST_WHITELIST: dict[str, set[str]] = {
    # ColorPickerDialog's factory-default swatch: the whole dialog exists to
    # edit data-driven colors, so the default is data, not styling.
    "AssetsManager/dialogs/color_picker_dialog.py": {"#ff6b6b"},
}


@dataclass(frozen=True)
class Violation:
    """One style-source gate failure."""

    path: str
    line: int
    rule: str
    snippet: str

    def format(self) -> str:
        return (
            f"{self.path}:{self.line}: [{self.rule}] "
            f"{self.snippet.strip()[:160]}"
        )


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


def _is_exempt(relative: str) -> bool:
    return relative.replace("\\", "/") in EXEMPT_FILES


def _qss_static_text(node: ast.JoinedStr) -> str:
    """Reconstruct only the static text portions of an f-string."""
    return "".join(
        part.value for part in node.values if isinstance(part, ast.Constant)
        and isinstance(part.value, str)
    )


def _is_docstring(node: ast.AST) -> bool:
    """True when the Constant node is a module/class/function docstring."""
    parent = getattr(node, "_style_parent", None)
    if not isinstance(parent, ast.Expr):
        return False
    statement_parent = getattr(parent, "_style_parent", None)
    if isinstance(statement_parent, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
        return True
    return False


def _annotate_parents(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            setattr(child, "_style_parent", node)


def _check_px_literals(text: str, path: str, line: int,
                       violations: list[Violation]) -> None:
    """Flag literal ``Npx`` in QSS text unless whitelisted for ``path``."""
    text = FONT_SIZE_DECL_RE.sub(" ", text)
    allowed = _PX_WHITELIST.get(path, frozenset())
    for match in RAW_PX_RE.finditer(text):
        if match.group(0) in allowed:
            continue
        violations.append(Violation(
            path, line, "literal-px-in-qss",
            text[match.start():match.start() + 40]))


def _check_string(text: str, path: str, line: int,
                  violations: list[Violation]) -> None:
    if not text or not QSS_HINT_RE.search(text):
        return
    for match in HEX_RE.finditer(text):
        violations.append(Violation(
            path, line, "literal-hex-in-qss", text[match.start():match.start() + 40]))
    for match in NAMED_COLOR_RE.finditer(text):
        violations.append(Violation(
            path, line, "literal-named-color-in-qss",
            text[match.start():match.start() + 40]))
    for match in FONT_SIZE_RAW_RE.finditer(text):
        violations.append(Violation(
            path, line, "literal-font-size-in-qss",
            text[match.start():match.start() + 40]))
    for match in FONT_SIZE_INTERP_RE.finditer(text):
        violations.append(Violation(
            path, line, "literal-font-size-in-qss",
            text[match.start():match.start() + 40]))
    _check_px_literals(text, path, line, violations)


def _check_joined_str(node: ast.JoinedStr, source: str, relative: str,
                      violations: list[Violation]) -> None:
    static_text = _qss_static_text(node)
    if not static_text or not QSS_HINT_RE.search(static_text):
        return
    segment = ast.get_source_segment(source, node)
    if segment is None:
        segment = static_text
    line = node.lineno
    for match in HEX_RE.finditer(segment):
        violations.append(Violation(
            relative, line, "literal-hex-in-qss",
            segment[match.start():match.start() + 40]))
    for match in NAMED_COLOR_RE.finditer(segment):
        violations.append(Violation(
            relative, line, "literal-named-color-in-qss",
            segment[match.start():match.start() + 40]))
    for match in FONT_SIZE_RAW_RE.finditer(segment):
        violations.append(Violation(
            relative, line, "literal-font-size-in-qss",
            segment[match.start():match.start() + 40]))
    for match in FONT_SIZE_INTERP_RE.finditer(segment):
        violations.append(Violation(
            relative, line, "literal-font-size-in-qss",
            segment[match.start():match.start() + 40]))
    # Pixel lengths are checked against the static text only: numbers
    # inside `{...}` interpolations (e.g. `{scaled_px(10)}px`) are
    # scaled by construction, and interpolation *expressions* must not
    # leak into this scan.
    _check_px_literals(static_text, relative, line, violations)


def _check_token_lookup_lines(source_lines: list[str], relative: str,
                              violations: list[Violation]) -> None:
    rule_exempt = _RULE_EXEMPT.get(relative, frozenset())
    for index, line in enumerate(source_lines, start=1):
        for pattern, rule in (
            (TOKEN_LOOKUP_HEX_RE, "hex-fallback-in-theme-lookup"),
            (THEMES_LOOKUP_HEX_RE, "hex-fallback-in-theme-lookup"),
        ):
            if rule in rule_exempt:
                continue
            for _match in pattern.finditer(line):
                violations.append(Violation(
                    relative, index, rule, line.strip()[:160]))


def _check_qcolor_hex_constants(tree: ast.AST, relative: str,
                                violations: list[Violation]) -> None:
    """Flag hex string literals handed straight to QColor() constructors.

    A hex constant in ``QColor("#888888")`` is styling that bypasses both
    the QSS-string rules and the token system (audit F3/G2).
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = ""
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name != "QColor":
            continue
        for arg in node.args:
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                continue
            value = arg.value.strip()
            if not HEX_RE.fullmatch(value):
                continue
            if value in _HEX_CONST_WHITELIST.get(relative, frozenset()):
                continue
            violations.append(Violation(
                relative, node.lineno, "hex-literal-in-qcolor", value))


def collect_violations(root: Path = ROOT) -> list[Violation]:
    """Return every style-source violation under ``root``."""
    violations: list[Violation] = []
    for path in _scoped_files(root):
        relative = path.relative_to(root).as_posix()
        if _is_exempt(relative):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        source_lines = source.splitlines()
        _check_token_lookup_lines(source_lines, relative, violations)
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        _annotate_parents(tree)
        _check_qcolor_hex_constants(tree, relative, violations)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # Skip f-string static parts — `_check_joined_str` covers
                # them via the JoinedStr node; visiting them here would
                # report every f-string finding twice.
                if isinstance(getattr(node, "_style_parent", None), ast.JoinedStr):
                    continue
                if _is_docstring(node):
                    continue
                _check_string(node.value, relative, node.lineno, violations)
            elif isinstance(node, ast.JoinedStr):
                _check_joined_str(node, source, relative, violations)
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Forbid literal colors/font sizes in local QSS (D4 gate).")
    parser.add_argument(
        "--json", action="store_true",
        help="Emit violations as JSON objects on stdout.")
    args = parser.parse_args(argv)

    violations = collect_violations()
    if args.json:
        import json
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
            f"check_style_sources: {len(violations)} violation(s) "
            f"across {len(_scoped_files(ROOT))} scoped file(s)",
        )
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
