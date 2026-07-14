"""Architecture boundary regression tests.

These tests intentionally allow a small set of documented transitional imports.
New code should not expand those exceptions without updating the architecture ADR.
"""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "AssetsManager"


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    return ".".join(rel.parts)


def _python_files(package: str) -> list[Path]:
    return sorted((SRC / package).rglob("*.py"))


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
    return {name for name in _imports(path) if name == "AssetsManager" or name.startswith("AssetsManager.")}


def _direct_calls(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[tuple[str, str]] = set()

    def visit(node: ast.AST, scope: str) -> None:
        next_scope = scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            next_scope = node.name
        elif isinstance(node, ast.ClassDef):
            next_scope = node.name
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                found.add((next_scope, node.func.id))
            elif isinstance(node.func, ast.Attribute):
                found.add((next_scope, node.func.attr))
        for child in ast.iter_child_nodes(node):
            visit(child, next_scope)

    visit(tree, "<module>")
    return found


def _attribute_reads(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[tuple[str, str]] = set()

    def visit(node: ast.AST, scope: str) -> None:
        next_scope = scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            next_scope = node.name
        elif isinstance(node, ast.ClassDef):
            next_scope = node.name
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            found.add((next_scope, node.attr))
        for child in ast.iter_child_nodes(node):
            visit(child, next_scope)

    visit(tree, "<module>")
    return found


def _files(root: Path, *parts: str) -> list[Path]:
    return sorted((root.joinpath(*parts)).rglob("*.py"))


def _assert_no_import_prefixes(
    files: list[Path],
    forbidden_prefixes: tuple[str, ...],
    allowed: set[tuple[str, str]] | None = None,
) -> None:
    allowed = allowed or set()
    violations: list[str] = []
    for path in files:
        module = _module_name(path)
        for imported in sorted(_assetmanager_imports(path)):
            if (module, imported) in allowed:
                continue
            if any(imported == prefix or imported.startswith(prefix + ".") for prefix in forbidden_prefixes):
                violations.append(f"{module} imports {imported}")
    assert not violations, "Architecture boundary violations:\n" + "\n".join(violations)


def test_domain_does_not_depend_on_upper_layers() -> None:
    _assert_no_import_prefixes(
        _python_files("domain"),
        (
            "AssetsManager.application",
            "AssetsManager.controllers",
            "AssetsManager.dialogs",
            "AssetsManager.lan",
            "AssetsManager.panels",
            "AssetsManager.repositories",
            "AssetsManager.widgets",
        ),
    )


def test_domain_does_not_import_sqlite3() -> None:
    violations: list[str] = []
    for path in _python_files("domain"):
        module = _module_name(path)
        for imported in sorted(_imports(path)):
            if imported == "sqlite3" or imported.startswith("sqlite3."):
                violations.append(f"{module} imports {imported}")
    assert not violations, "Domain must not depend on sqlite3:\n" + "\n".join(violations)


def test_domain_does_not_import_core_infrastructure() -> None:
    forbidden = (
        "AssetsManager.core.database",
        "AssetsManager.core.db_migrations",
        "AssetsManager.core.tag_store",
        "AssetsManager.core.project_data",
        "AssetsManager.core.settings",
        "AssetsManager.core.singleton",
        "AssetsManager.core.signal_bus",
    )
    allowed = {
        ("AssetsManager.domain.asset", "AssetsManager.core.format_utils"),
    }
    violations: list[str] = []
    for path in _python_files("domain"):
        module = _module_name(path)
        for imported in sorted(_assetmanager_imports(path)):
            if (module, imported) in allowed:
                continue
            if any(imported == prefix or imported.startswith(prefix + ".") for prefix in forbidden):
                violations.append(f"{module} imports {imported}")
    assert not violations, "Domain must not import core infrastructure:\n" + "\n".join(violations)


def test_core_does_not_grow_upper_layer_dependencies() -> None:
    _assert_no_import_prefixes(
        _python_files("core"),
        (
            "AssetsManager.application",
            "AssetsManager.controllers",
            "AssetsManager.dialogs",
            "AssetsManager.lan",
            "AssetsManager.panels",
            "AssetsManager.widgets",
        ),
        allowed={
            (
                "AssetsManager.core.plugins.manager",
                "AssetsManager.application.asset_filters",
            ),
        },
    )


def test_non_presentation_layers_do_not_grow_qt_dependencies() -> None:
    violations: list[str] = []
    for package in ("application", "domain", "repositories", "di"):
        for path in _python_files(package):
            module = _module_name(path)
            for imported in sorted(_imports(path)):
                if imported == "PySide6" or imported.startswith("PySide6."):
                    violations.append(f"{module} imports {imported}")
    assert not violations, "Qt dependencies outside presentation:\n" + "\n".join(violations)


def test_lru_cache_module_does_not_exist() -> None:
    """LRUCache must live in core/cache.py, not a separate core/lru_cache.py."""
    lru_path = SRC / "core" / "lru_cache.py"
    assert not lru_path.exists(), (
        "core/lru_cache.py was removed — use core/cache.LRUCache instead"
    )


def test_no_imports_from_removed_lru_cache_module() -> None:
    violations: list[str] = []
    for path in _files(ROOT, "AssetsManager") + _files(ROOT, "tests"):
        module = _module_name(path)
        for imported in sorted(_imports(path)):
            if imported == "AssetsManager.core.lru_cache" or imported.startswith("AssetsManager.core.lru_cache."):
                violations.append(f"{module} imports {imported}")
    assert not violations, "core/lru_cache was removed — use core/cache:\n" + "\n".join(violations)


def test_lan_does_not_depend_on_desktop_presentation() -> None:
    _assert_no_import_prefixes(
        _python_files("lan"),
        (
            "AssetsManager.dialogs",
            "AssetsManager.panels",
            "AssetsManager.widgets",
            "AssetsManager.window",
            "AssetsManager.dock_factory",
        ),
    )


def test_presentation_db_store_access_stays_in_documented_fallbacks() -> None:
    forbidden_calls = {"get_lib_db", "get_manager", "get_store", "get_project_data", "get_library_dir", "close_all_dbs"}
    allowed_calls = {
        ("AssetsManager.panels.file_list._base", "_configure_library_runtime", "get_manager"),
        ("AssetsManager.panels.file_list._base", "_get_tag_store", "get_store"),
        ("AssetsManager.panels.info", "_resolve_project", "get_project_data"),
        ("AssetsManager.panels.info", "_resolve_store", "get_store"),
        ("AssetsManager.panels.tag_tree", "_resolve_tag_store", "get_store"),
        ("AssetsManager.dialogs.sidebar_favorites", "set_library_root", "get_library_dir"),
        ("AssetsManager.dialogs.sidebar_recent", "set_library_root", "get_library_dir"),
    }
    forbidden_imports = {
        "AssetsManager.core.database",
        "AssetsManager.core.tag_store",
        "AssetsManager.core.project_data",
    }
    allowed_imports = {
        ("AssetsManager.panels.info", "AssetsManager.core.tag_store"),
        ("AssetsManager.panels.info", "AssetsManager.core.project_data"),
        ("AssetsManager.panels.file_list._base", "AssetsManager.core.tag_store"),
        ("AssetsManager.panels.file_list._base", "AssetsManager.core.database"),
        ("AssetsManager.panels.tag_tree", "AssetsManager.core.tag_store"),
        ("AssetsManager.dialogs.sidebar_recent", "AssetsManager.core.database"),
        ("AssetsManager.dialogs.sidebar_favorites", "AssetsManager.core.database"),
    }
    violations: list[str] = []
    for package in ("dialogs", "panels", "widgets"):
        for path in _python_files(package):
            module = _module_name(path)
            # Check function calls
            for scope, call in sorted(_direct_calls(path)):
                if call not in forbidden_calls:
                    continue
                if (module, scope, call) in allowed_calls:
                    continue
                violations.append(f"{module}.{scope} calls {call}()")
            # Check imports
            for imported in sorted(_assetmanager_imports(path)):
                if not any(imported == p or imported.startswith(p + ".") for p in forbidden_imports):
                    continue
                if (module, imported) in allowed_imports:
                    continue
                violations.append(f"{module} imports {imported}")
    assert not violations, "Presentation DB/store access outside fallback allowlist:\n" + "\n".join(violations)


def test_open_library_calls_stay_in_documented_boundaries() -> None:
    allowed_modules = {
        "AssetsManager.application.library_service",
        "AssetsManager.core.database",
        "tests.core.test_path_resolver",
        "tests.integration.test_event_publishing",
        "tests.integration.test_library_service",
        "tests.mocks",
    }
    violations: list[str] = []
    for path in _files(ROOT, "AssetsManager") + _files(ROOT, "tests"):
        module = _module_name(path)
        for scope, call in sorted(_direct_calls(path)):
            if call != "open_library":
                continue
            if module in allowed_modules:
                continue
            violations.append(f"{module}.{scope} calls open_library()")
    assert not violations, "open_library() escaped its documented boundaries:\n" + "\n".join(violations)


def test_library_service_current_stays_legacy_only() -> None:
    allowed = {
        ("tests.integration.test_library_service", "test_current_context_remains_legacy_compatibility_api"),
        ("tests.integration.test_library_service", "test_current_property_emits_deprecation_warning"),
    }
    violations: list[str] = []
    for path in _files(ROOT, "AssetsManager") + _files(ROOT, "tests"):
        module = _module_name(path)
        for scope, attr in sorted(_attribute_reads(path)):
            if attr != "current":
                continue
            if module == "AssetsManager.application.library_service":
                continue
            if (module, scope) in allowed:
                continue
            violations.append(f"{module}.{scope} reads .current")
    assert not violations, "LibraryService.current should stay legacy-only:\n" + "\n".join(violations)


def test_application_does_not_import_lan_or_panels() -> None:
    _assert_no_import_prefixes(
        _python_files("application"),
        (
            "AssetsManager.lan",
            "AssetsManager.panels",
        ),
    )


def test_repositories_only_depend_on_core_database_and_domain() -> None:
    allowed_prefixes = (
        "AssetsManager.core.database",
        "AssetsManager.domain",
        "AssetsManager.repositories",
    )
    violations: list[str] = []
    for path in _python_files("repositories"):
        module = _module_name(path)
        for imported in sorted(_assetmanager_imports(path)):
            if any(imported == p or imported.startswith(p + ".") for p in allowed_prefixes):
                continue
            violations.append(f"{module} imports {imported}")
    assert not violations, "Repositories must only depend on core/database and domain:\n" + "\n".join(violations)


def test_lan_does_not_import_pyside6_or_controllers() -> None:
    violations: list[str] = []
    for path in _python_files("lan"):
        module = _module_name(path)
        for imported in sorted(_imports(path)):
            if imported == "PySide6" or imported.startswith("PySide6."):
                violations.append(f"{module} imports PySide6")
        for imported in sorted(_assetmanager_imports(path)):
            if imported == "AssetsManager.controllers" or imported.startswith("AssetsManager.controllers."):
                violations.append(f"{module} imports {imported}")
    assert not violations, "lan must not import PySide6 or controllers:\n" + "\n".join(violations)


def test_panels_does_not_directly_import_sqlite3() -> None:
    allowed = {
        "AssetsManager.panels.file_list._loader",
    }
    violations: list[str] = []
    for path in _python_files("panels"):
        module = _module_name(path)
        if module in allowed:
            continue
        for imported in sorted(_imports(path)):
            if imported == "sqlite3" or imported.startswith("sqlite3."):
                violations.append(f"{module} imports {imported}")
    assert not violations, "Panels must not directly import sqlite3:\n" + "\n".join(violations)
