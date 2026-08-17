"""Layer DAG checker for AssetsManager packages.

This complements ``check_boundaries.py``'s needle scans with a
direction-aware import graph: every ``AssetsManager.*`` import must travel
along the allowed edges below.  Documented transitional exceptions are
listed with the owning batch; they must shrink, not grow.
"""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "AssetsManager"

# Package -> allowed dependency layers.  Panels/widgets/dialogs form one
# presentation layer in the graph (they are allowed to reuse each other),
# while application/domain/repositories must not reach presentation.
ALLOWED_EDGES: dict[str, set[str]] = {
    "plugin_api": {"plugin_api"},
    "core": {"core", "plugin_api"},
    "di": {"core", "di", "plugin_api"},
    "domain": {"core", "domain"},
    "repositories": {"core", "domain", "repositories"},
    "application": {"core", "di", "domain", "repositories", "application", "plugin_api"},
    "controllers": {"core", "application", "domain", "repositories", "controllers", "plugin_api"},
    "lan": {"core", "di", "domain", "repositories", "application", "lan", "plugin_api"},
    "panels": {
        "core",
        "application",
        "controllers",
        "domain",
        "i18n",
        "panels",
        "widgets",
        "dialogs",
        "plugin_api",
    },
    "widgets": {
        "core",
        "application",
        "domain",
        "i18n",
        "panels",
        "widgets",
        "dialogs",
        "plugin_api",
    },
    "dialogs": {
        "core",
        "application",
        "controllers",
        "domain",
        "i18n",
        "panels",
        "widgets",
        "dialogs",
        "plugin_api",
    },
    "i18n": {"core", "i18n"},
    "presentation_top": {
        "core",
        "application",
        "controllers",
        "domain",
        "i18n",
        "lan",
        "panels",
        "widgets",
        "dialogs",
        "plugin_api",
        "presentation_top",
    },
}

# Transitional exceptions: (source module, imported module, owner batch).
# Batch G1 removed core -> application/repositories edges; G2 removed
# presentation -> LAN via injected desktop ports; G3 removed application
# settings/tag-library escapes; G4 removed the last core -> domain and
# controller -> panel edges.  The registry is now empty.
ALLOWED_EXCEPTIONS: set[tuple[str, str, str]] = set()

TOP_LEVEL_LAYER = "presentation_top"


@dataclass(frozen=True)
class Violation:
    source: str
    imported: str
    source_layer: str
    imported_layer: str

    def describe(self) -> str:
        return (
            f"{self.source} ({self.source_layer}) imports "
            f"{self.imported} ({self.imported_layer})"
        )


def _layer_for(module: str) -> str | None:
    if module == "AssetsManager":
        return None
    parts = module.split(".")
    if len(parts) < 2:
        return None
    head = parts[1]
    if head in ALLOWED_EDGES:
        return head
    # Top-level modules (window, dock_factory, ...) coordinate presentation.
    if len(parts) == 2:
        return TOP_LEVEL_LAYER
    return None


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _assetmanager_imports(path: Path) -> set[str]:
    return {
        name
        for name in _imports(path)
        if name == "AssetsManager" or name.startswith("AssetsManager.")
    }


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    return ".".join(rel.parts)


def _is_exception(source: str, imported: str) -> bool:
    return any(
        source == exc_source
        and (
            imported == exc_imported
            or imported.startswith(exc_imported + ".")
        )
        for exc_source, exc_imported, _batch in ALLOWED_EXCEPTIONS
    )


def collect_violations() -> list[Violation]:
    violations: list[Violation] = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = _module_name(path)
        source_layer = _layer_for(source)
        if source_layer is None:
            continue
        for imported in sorted(_assetmanager_imports(path)):
            imported_layer = _layer_for(imported)
            if imported_layer is None:
                continue
            if _is_exception(source, imported):
                continue
            if imported_layer not in ALLOWED_EDGES[source_layer]:
                violations.append(
                    Violation(source, imported, source_layer, imported_layer)
                )
    return violations


def main() -> int:
    violations = collect_violations()
    if violations:
        print("layer DAG violations detected:", file=sys.stderr)
        for violation in violations:
            print(f"  {violation.describe()}", file=sys.stderr)
        return 1
    print("layer DAG checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
