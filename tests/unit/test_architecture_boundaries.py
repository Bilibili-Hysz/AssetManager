"""Architecture boundary regression tests.

These tests intentionally allow a small set of documented transitional imports.
New code should not expand those exceptions without updating the architecture ADR.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "AssetsManager"


def _module_name(path: Path) -> str:
    try:
        rel = path.relative_to(ROOT).with_suffix("")
    except ValueError:
        # Synthetic files created under tmp_path: with a debug temproot the
        # temp dir lives outside the repository, so fall back to the stem.
        return path.stem
    return ".".join(rel.parts)


def _python_files(package: str) -> list[Path]:
    return sorted((SRC / package).rglob("*.py"))


def _production_python_files() -> list[Path]:
    return sorted(path for path in SRC.rglob("*.py") if "__pycache__" not in path.parts)


def test_production_compatibility_gate_uses_entire_package() -> None:
    files = _production_python_files()

    assert SRC / "application" / "bootstrap.py" in files
    assert SRC / "core" / "database.py" in files


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


def _qualified_attribute_reads(path: Path) -> list[tuple[str, str, str, str, int, int]]:
    """Return conservative DatabaseManager.current syntax occurrences with locations.

    This is a syntax gate, not Python name resolution: direct
    DatabaseManager.current and obvious qualified .DatabaseManager.current
    chains are reported regardless of assignments, scopes, or control flow.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    manager_names = {"DatabaseManager"}
    database_module_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound_name = alias.asname or alias.name
                if (
                    node.module == "AssetsManager.core.database"
                    and alias.name == "DatabaseManager"
                ):
                    manager_names.add(bound_name)
                elif node.module == "AssetsManager.core" and alias.name == "database":
                    database_module_names.add(bound_name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "AssetsManager.core.database" and alias.asname:
                    database_module_names.add(alias.asname)

    found: list[tuple[str, str, str, str, int, int]] = []

    def chain(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = chain(node.value)
            return f"{parent}.{node.attr}" if parent else None
        return None

    def visit(node: ast.AST, scope: str) -> None:
        next_scope = (
            node.name
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            else scope
        )
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Load)
            and node.attr == "current"
        ):
            owner: str | None = None
            value_chain = chain(node.value)
            if isinstance(node.value, ast.Name) and node.value.id in manager_names:
                owner = "DatabaseManager"
            elif (
                isinstance(node.value, ast.Attribute)
                and node.value.attr == "DatabaseManager"
                and value_chain
            ):
                module_chain = chain(node.value.value)
                if (
                    module_chain == "AssetsManager.core.database"
                    or (
                        isinstance(node.value.value, ast.Name)
                        and node.value.value.id in database_module_names
                    )
                    or (module_chain is not None and "." in module_chain)
                ):
                    owner = "DatabaseManager"
            if owner and value_chain:
                found.append(
                    (scope, owner, node.attr, f"{value_chain}.{node.attr}", node.lineno, node.col_offset)
                )
        for child in ast.iter_child_nodes(node):
            visit(child, next_scope)

    visit(tree, "<module>")
    return found


def _database_manager_current_violations(files: list[Path]) -> list[str]:
    """Return location-preserving conservative DatabaseManager.current syntax violations."""
    violations: list[str] = []
    for path in files:
        module = _module_name(path)
        for scope, owner, attr, _chain, lineno, col_offset in sorted(
            _qualified_attribute_reads(path), key=lambda occurrence: occurrence[4:]
        ):
            if owner == "DatabaseManager" and attr == "current":
                violations.append(
                    f"{module}:{lineno}:{col_offset} {scope} reads DatabaseManager.current"
                )
    return violations


def _public_dto_files(root: Path = SRC) -> list[Path]:
    """Discover current and future public DTO modules without a fixed allowlist."""
    return sorted(
        path
        for path in root.rglob("*.py")
        if path.name in {"dto.py", "dtos.py"}
        or path.name.endswith("_dto.py")
        or path.name.endswith("_dtos.py")
    )


def _public_dto_qt_import_violations(paths: list[Path]) -> list[str]:
    """Return Qt imports found by the public-DTO AST boundary check."""
    violations: list[str] = []
    for path in paths:
        for imported in sorted(_imports(path)):
            if imported == "PySide6" or imported.startswith("PySide6."):
                violations.append(f"{path} imports {imported}")
    return violations


def _session_raw_resource_reads(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[tuple[str, str]] = set()

    def visit(node: ast.AST, scope: str) -> None:
        next_scope = scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            next_scope = node.name
        elif isinstance(node, ast.ClassDef):
            next_scope = node.name
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            value = node.value
            if node.attr in {"db_conn", "tag_store", "project_data"} and (
                isinstance(value, ast.Name) and value.id == "session"
                or isinstance(value, ast.Attribute) and value.attr == "session"
            ):
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


def test_presentation_service_locator_module_does_not_exist() -> None:
    assert not (SRC / "panels" / "_service_access.py").exists(), (
        "Presentation panels must receive scoped services from their composition root"
    )


def test_presentation_does_not_lookup_bootstrap_from_qapplication() -> None:
    violations: list[str] = []
    for package in ("dialogs", "panels", "widgets"):
        for path in _python_files(package):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "property"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "bootstrap"
                ):
                    violations.append(f"{_module_name(path)} looks up QApplication bootstrap")
    assert not violations, "Presentation must receive dependencies explicitly:\n" + "\n".join(violations)


def test_main_window_uses_panel_lifecycle_contracts() -> None:
    window_path = SRC / "window.py"
    tree = ast.parse(window_path.read_text(encoding="utf-8"), filename=str(window_path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, ast.Load):
            continue
        owner = node.value
        if (
            node.attr.startswith("_")
            and isinstance(owner, ast.Attribute)
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "self"
            and owner.attr in {"file_list", "info"}
        ):
            violations.append(f"MainWindow reads self.{owner.attr}.{node.attr}")
    assert not violations, "MainWindow must use public panel lifecycle methods:\n" + "\n".join(violations)


def test_presentation_db_store_access_stays_in_documented_fallbacks() -> None:
    forbidden_calls = {"get_store", "get_project_data"}
    allowed_calls = set()
    forbidden_imports = {
        "AssetsManager.core.database",
        "AssetsManager.core.tag_store",
        "AssetsManager.core.project_data",
    }
    allowed_imports = {
        ("AssetsManager.panels.info", "AssetsManager.core.project_data"),
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


@pytest.mark.parametrize(
    "removed_helper",
    [
        "def get_manager(",
        "def get_lib_db(",
        "def update_library_stats(",
    ],
)
def test_database_does_not_restore_removed_helpers(removed_helper: str) -> None:
    source = (SRC / "core" / "database.py").read_text(encoding="utf-8")

    assert removed_helper not in source


def test_production_path_metadata_migration_uses_explicit_resources() -> None:
    path = SRC / "application" / "file_operation_service.py"
    source = path.read_text(encoding="utf-8")
    assert "from AssetsManager.application.thumbnail_cache_lifecycle import cache_owner_lock" in source
    assert "with cache_owner_lock(self.session.thumb_dir):" in source
    assert "migrate_path_metadata(\n                self._connection(), self.session.thumb_dir" in source


def test_project_service_delegates_file_meta_cache_to_repository() -> None:
    source = (SRC / "application" / "project_service.py").read_text(encoding="utf-8")
    assert "from AssetsManager.repositories.metadata_repository import MetadataRepository" in source
    assert "db_conn.execute(" not in source
    assert "db_conn.executemany(" not in source


def test_tag_service_delegates_tag_counts_to_repository() -> None:
    source = (SRC / "application" / "tag_service.py").read_text(encoding="utf-8")
    assert "repo.list_tags_with_counts(" in source
    assert "conn.execute(" not in source


def test_thumbnail_service_delegates_tag_lookup_to_repository() -> None:
    source = (SRC / "application" / "thumbnail_service.py").read_text(encoding="utf-8")
    assert "tag_repository.get_tags" in source
    assert "db_conn.execute(" not in source


def test_search_service_delegates_tag_lookup_to_repository() -> None:
    source = (SRC / "application" / "search_service.py").read_text(encoding="utf-8")
    assert "get_files_by_tag_case_insensitive" in source
    assert "db_conn.execute(" not in source


def test_auth_service_does_not_own_share_link_operations() -> None:
    source = (SRC / "application" / "auth_service.py").read_text(encoding="utf-8")

    assert "share_repository" not in source
    assert "share_link" not in source
    assert "share_token" not in source


def test_auth_repository_does_not_initialize_share_schema() -> None:
    source = (SRC / "repositories" / "auth_repository.py").read_text(encoding="utf-8")

    assert "share_repository" not in source
    assert "ShareRepository" not in source


def test_lan_auth_does_not_compose_repository_schemas() -> None:
    source = (SRC / "lan" / "auth.py").read_text(encoding="utf-8")

    assert "AssetsManager.repositories" not in source
    assert "init_users_table" not in source


def test_lan_server_delegates_active_user_lookup_to_auth_service() -> None:
    source = (SRC / "lan" / "server.py").read_text(encoding="utf-8")
    start = source.index("    def _has_active_users(self) -> bool:")
    end = source.index("    def invalidate_user_cache", start)

    assert "self._auth_service.has_active_users(raise_on_error=True)" in source[start:end]
    assert "self._db_conn.execute(" not in source[start:end]


def test_lan_server_initializes_auth_and_share_through_services() -> None:
    bootstrap = (SRC / "application" / "bootstrap.py").read_text(encoding="utf-8")
    server = (SRC / "lan" / "server.py").read_text(encoding="utf-8")
    auth_routes = (SRC / "lan" / "routes" / "auth.py").read_text(encoding="utf-8")

    assert "auth_service.init_tables()" in bootstrap
    assert "share_service.init_table()" in bootstrap
    assert "self._auth_service.init_tables()" not in server
    assert "self._share_service.init_table()" not in server
    assert "auth_service.init_tables()" not in auth_routes
    assert "AssetsManager.repositories" not in server


def test_files_route_uses_scoped_metadata_service_for_cached_stats() -> None:
    source = (SRC / "lan" / "routes" / "files.py").read_text(encoding="utf-8")
    helpers = (SRC / "lan" / "routes" / "_helpers.py").read_text(encoding="utf-8")

    assert "get_metadata_service(request).get_cached_stats(" in source
    assert "batch_cached_stats" not in source
    assert "batch_cached_stats" not in helpers


def test_project_routes_do_not_inject_raw_lan_connections() -> None:
    source = (SRC / "lan" / "routes" / "metadata.py").read_text(encoding="utf-8")
    start = source.index("async def handle_home")
    end = source.index("async def handle_tree", start)
    project_source = source[source.index("async def handle_projects"):]

    assert "lan.db_conn" not in source[start:end]
    assert "lan.db_conn" not in project_source


def test_thumbnail_routes_use_scoped_connection_provider() -> None:
    source = (SRC / "lan" / "routes" / "thumbnails.py").read_text(encoding="utf-8")
    helpers = (SRC / "lan" / "routes" / "_helpers.py").read_text(encoding="utf-8")

    assert "lan.db_conn" not in source
    assert "library_root=lan.library_root" in source
    assert "ThumbnailService" not in helpers


def test_search_routes_use_scoped_connection_provider() -> None:
    source = (SRC / "lan" / "routes" / "metadata.py").read_text(encoding="utf-8")
    helpers = (SRC / "lan" / "routes" / "_helpers.py").read_text(encoding="utf-8")
    start = source.index("async def handle_search")
    # Boundary marker: the per-file telemetry helper was replaced by the
    # shared record_route_event helper, so the handler block now ends at
    # the next handler definition.
    end = source.index("async def handle_home", start)

    assert "lan.db_conn" not in source[start:end]
    assert "SearchService" not in helpers


def test_lan_helpers_do_not_assemble_application_services() -> None:
    source = (SRC / "lan" / "routes" / "_helpers.py").read_text(encoding="utf-8")

    for service in (
        "MetadataService", "ProjectService", "TagService", "SearchService",
        "ThumbnailService", "AssetService",
    ):
        assert service not in source
    assert "def _build_lan_services" not in source
    assert "_build_lan_services(" not in source


def test_lan_get_services_is_direct_eager_bundle_lookup() -> None:
    source = (SRC / "lan" / "routes" / "_helpers.py").read_text(encoding="utf-8")
    start = source.index("def get_services(")
    end = source.index("\ndef get_auth_service", start)
    lookup = source[start:end]

    assert "return lan.services" in lookup
    assert "_build_lan_services" not in lookup
    assert "LanScopedServices(" not in lookup



def test_lan_runtime_services_are_built_only_by_bootstrap() -> None:
    bootstrap = (SRC / "application" / "bootstrap.py").read_text(encoding="utf-8")
    eager_start = bootstrap.index("    def _build_services(")
    lazy_start = bootstrap.index("    def _build_lan_services(")
    lazy_end = bootstrap.index("    def _close_runtime(", lazy_start)
    eager_assembly = bootstrap[eager_start:lazy_start]
    lazy_assembly = bootstrap[lazy_start:lazy_end]

    assert "ThumbnailService(" in eager_assembly
    assert "partial(self._build_lan_services, connection_provider=provider)" in eager_assembly
    for constructor in ("AssetService(", "ProjectService(", "SearchService("):
        assert constructor not in eager_assembly
        assert constructor in lazy_assembly

    allowed = SRC / "application" / "bootstrap.py"
    for path in _production_python_files():
        if path == allowed:
            continue
        source = path.read_text(encoding="utf-8")
        assert "_build_lan_services(" not in source, path


def test_lan_server_projects_runtime_services_without_reassembly() -> None:
    source = (SRC / "lan" / "server.py").read_text(encoding="utf-8")
    # The canonical snapshot accessor moved to runtime_validation.py in the
    # server split (01c26b9); server.py must keep calling it and projecting
    # the snapshot instead of reassembling services.
    validation = (SRC / "lan" / "runtime_validation.py").read_text(encoding="utf-8")

    assert "runtime.services_snapshot" in validation
    assert "_runtime_services_snapshot(runtime)" in source
    assert "runtime_services.lan_services" in source
    assert "runtime_services.sharing_services" in source
    assert "runtime_services=runtime_services" in source
    for constructor in (
        "AssetService(", "ProjectService(", "SearchService(",
        "AuthService(", "ShareService(",
    ):
        assert constructor not in source
    assert "os.urandom" not in source


def test_runtime_is_constructed_only_by_bootstrap() -> None:
    source_root = SRC
    allowed = source_root / "application" / "bootstrap.py"
    for path in source_root.rglob("*.py"):
        if path == allowed or "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        assert "LibraryRuntime(" not in source, path


def test_lan_routes_use_canonical_principal_without_legacy_user_dict_adapter() -> None:
    for path in (SRC / "lan" / "routes").glob("*.py"):
        if path.name == "_helpers.py":
            continue
        source = path.read_text(encoding="utf-8")
        assert "get_request_user(" not in source, path


def test_page_components_do_not_consume_websocket_transport_directly() -> None:
    for root in (SRC / "webui" / "src" / "pages", SRC / "webui" / "src" / "components"):
        for path in root.rglob("*.tsx"):
            source = path.read_text(encoding="utf-8")
            assert "useWebSocket(" not in source, path


def test_desktop_uses_canonical_runtime_for_session() -> None:
    source = (SRC / "window.py").read_text(encoding="utf-8")
    assert "runtime_for(session)" in source
    assert "for_library(session)" not in source


def test_production_has_no_cleanup_library_compatibility_call() -> None:
    violations = []
    for path in _production_python_files():
        source = path.read_text(encoding="utf-8")
        if re.search(r"(?<![A-Za-z0-9_])cleanup_library\s*\(", source):
            violations.append(path)
    assert not violations, "production cleanup_library compatibility residue: " + ", ".join(map(str, violations))


def test_bootstrap_no_longer_exposes_removed_compatibility_api() -> None:
    source = (SRC / "application" / "bootstrap.py").read_text(encoding="utf-8")
    assert "def for_library(" not in source
    assert "def cleanup_library(" not in source


def test_production_has_no_for_library_compatibility_calls() -> None:
    violations = []
    for path in _production_python_files():
        source = path.read_text(encoding="utf-8")
        if re.search(r"(?<![A-Za-z0-9_])for_library\s*\(", source):
            violations.append(path)
    assert not violations, "production for_library compatibility residue: " + ", ".join(map(str, violations))


def test_realtime_transport_has_one_central_host_consumer() -> None:
    webui_src = ROOT / "webui" / "src"
    realtime = (webui_src / "stores" / "RealtimeContext.tsx").read_text(encoding="utf-8")
    assert "WebSocketTransportHost" in realtime
    consumers = []
    for path in webui_src.rglob("*.tsx"):
        if path.name.endswith(".test.tsx"):
            continue
        source = path.read_text(encoding="utf-8")
        if "WebSocketTransportHost" in source:
            consumers.append(path.relative_to(webui_src).as_posix())
    assert consumers == ["stores/RealtimeContext.tsx"]


def test_browser_auth_contract_has_no_bearer_token_state() -> None:
    files = (
        ROOT / "webui" / "src" / "types" / "api.ts",
        ROOT / "webui" / "src" / "stores" / "AuthContext.tsx",
        ROOT / "webui" / "src" / "pages" / "LoginPage.tsx",
    )
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert "setToken" not in source, path
    auth_types = files[0].read_text(encoding="utf-8")
    assert "token?:" not in auth_types
    assert "token:" not in auth_types


def test_lan_routes_do_not_construct_raw_connection_services() -> None:
    forbidden = (
        "MetadataService(", "ProjectService(", "TagService(",
        "SearchService(", "ThumbnailService(", "AssetService(",
    )
    for path in (ROOT / "AssetsManager" / "lan" / "routes").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for expression in forbidden:
            assert expression not in source, f"{expression} in {path}"


def test_service_provider_errors_are_single_explicit_messages() -> None:
    metadata = (SRC / "application" / "metadata_service.py").read_text(encoding="utf-8")
    tags = (SRC / "application" / "tag_service.py").read_text(encoding="utf-8")
    assert metadata.count("MetadataService requires an explicit ConnectionProvider.") == 1
    assert "MetadataService requires a ConnectionProvider." not in metadata
    assert tags.count("TagService requires an explicit db_conn or ConnectionProvider.") == 1
    assert "TagService requires either db_conn or a ConnectionProvider." not in tags


def test_public_types_are_backed_by_contract_fixture() -> None:
    api_types = (ROOT / "webui" / "src" / "types" / "api.ts").read_text(encoding="utf-8")
    contracts = (ROOT / "tests" / "contracts" / "lan_public_contracts.json").read_text(encoding="utf-8")
    generated = (ROOT / "webui" / "src" / "types" / "contracts.ts").read_text(encoding="utf-8")
    for field in ("connections", "requests", "bytes_transferred", "uptime"):
        assert f'"{field}"' in contracts
        assert field in generated
    # Since the 2026-08-29 api.ts/contracts.ts merge, StatsResponse is
    # re-exported from the generated contract types instead of being defined
    # inline — the structural backing replaces per-field text checks in api.ts.
    assert re.search(r"export type \{[^}]*StatsResponse[^}]*\} from ['\"]\./contracts['\"]", api_types, re.S)


def test_production_lan_entrypoints_have_no_legacy_factory_path() -> None:
    for relative in (
        "lan/__init__.py",
        "lan/manager.py",
        "widgets/lan_sharing.py",
    ):
        source = (SRC / relative).read_text(encoding="utf-8")
        assert "from_legacy_connection" not in source, relative
        assert "_legacy" not in source, relative


def test_file_list_plugin_actions_use_scoped_plugin_service() -> None:
    source = (SRC / "panels" / "file_list" / "_actions.py").read_text(encoding="utf-8")
    assert "PluginService(" not in source
    assert '"plugin_host_context"' not in source
    assert 'getattr(scoped, "plugin_service", None)' in source


def test_g3_app_settings_has_single_application_call_site() -> None:
    sites: list[Path] = []
    for path in (SRC / "application").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "AppSettings.instance()" in source:
            sites.append(path)
    assert sites == [SRC / "application" / "bootstrap.py"]


def test_g3_application_has_no_get_library_access() -> None:
    for path in (SRC / "application").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "get_library(" not in source, path


def test_g3_gallery_service_is_split_into_focused_mixins() -> None:
    facade = (SRC / "application" / "gallery_service.py").read_text(encoding="utf-8")
    assert "_GalleryPersistenceMixin" in facade
    assert "_GalleryProjectionMixin" in facade
    assert "_GalleryIncrementalMixin" in facade
    for name in ("_persistence.py", "_projection_builder.py", "_incremental.py"):
        assert (SRC / "application" / "gallery" / name).is_file(), name


def test_g3_sharing_settings_dialog_uses_tab_mixins() -> None:
    source = (SRC / "dialogs" / "sharing_settings_dialog.py").read_text(encoding="utf-8")
    for mixin in (
        "SharedUiMixin",
        "EndpointPageMixin",
        "LinksPageMixin",
        "AccessPageMixin",
        "ConfigurationPageMixin",
    ):
        assert mixin in source
    for name in (
        "_ui.py",
        "_endpoint_page.py",
        "_links_page.py",
        "_access_page.py",
        "_configuration_page.py",
    ):
        assert (SRC / "dialogs" / "sharing_settings" / name).is_file(), name


def test_d2_ui_state_persistence_flows_through_panel_state() -> None:
    ui_keys = ("info_panel_layout", "sidebar_depth_cfg", "dock_widths",
               "workspace_tabs", "file_list_view_state")
    for key in ui_keys:
        assert key in (SRC / "panels" / "panel_state.py").read_text(encoding="utf-8") or any(
            key in (SRC / relative).read_text(encoding="utf-8")
            for relative in (
                "panels/info.py",
                "panels/sidebar.py",
                "panels/file_list/_base.py",
                "window.py",
            )
        ), key
    for relative in ("panels/info.py", "panels/file_list/_base.py", "window.py"):
        source = (SRC / relative).read_text(encoding="utf-8")
        assert 'AppSettings.instance().set("info_panel_layout"' not in source, relative
        assert 'AppSettings.instance().set("workspace_tabs"' not in source, relative
        assert 'AppSettings.instance().set("dock_widths"' not in source, relative


def test_d2_clone_calls_are_wired_to_state_restore() -> None:
    for relative in (
        "panels/base.py",
        "panels/info.py",
        "panels/sidebar.py",
        "panels/file_list/_base.py",
        "widgets/tab_container.py",
        "dock_factory.py",
    ):
        source = (SRC / relative).read_text(encoding="utf-8")
        assert "clone" in source, relative
    factory = (SRC / "dock_factory.py").read_text(encoding="utf-8")
    assert 'clone = getattr(source, "clone", None)' in factory
    assert "cloned" in factory


def test_file_operation_service_delegates_deleted_projection_cleanup() -> None:
    source = (SRC / "application" / "file_operation_service.py").read_text(encoding="utf-8")
    start = source.index("    def _clear_deleted_projection(")
    end = source.index("\n\ndef unique_destination", start)
    cleanup = source[start:end]

    assert "TagRepository(" in cleanup
    assert "session=self.session" in cleanup
    assert ".delete_path(target, commit=False)" in cleanup
    assert "MetadataRepository(conn).delete_path(target, commit=False)" in cleanup
    assert "DELETE FROM file_tags" not in cleanup
    assert "DELETE FROM file_meta" not in cleanup


def test_asset_index_service_delegates_assets_sql_to_repository() -> None:
    source = (SRC / "application" / "asset_index_service.py").read_text(encoding="utf-8")

    assert "AssetIndexRepository(conn)" in source
    assert "SELECT " not in source
    assert "INSERT INTO assets" not in source
    assert "DELETE FROM assets" not in source
    assert "conn.execute(" not in source
    assert "conn.executemany(" not in source


def test_file_list_shutdown_releases_tracked_panel_subscriptions() -> None:
    # After the _base.py split, shutdown() stays in _base.py but closeEvent
    # moved to _base_events.py. The test verifies shutdown() calls super().
    source = (SRC / "panels" / "file_list" / "_base.py").read_text(encoding="utf-8")
    shutdown_match = source.index("    def shutdown(self):")
    # Find the next method def as the boundary (shutdown is the last method).
    next_def = source.find("\n\nif TYPE_CHECKING:", shutdown_match)
    if next_def == -1:
        next_def = len(source)
    assert "super().shutdown()" in source[shutdown_match:next_def]


def test_file_list_uses_session_scoped_file_events() -> None:
    # After the _base.py split, FileSystemChanged event handling moved to
    # _base_events.py. The panel must still check session token to ignore
    # events from other sessions.
    events = (SRC / "panels" / "file_list" / "_base_events.py").read_text(encoding="utf-8")
    assert "FileSystemChanged" in events
    assert "event.session_token != scoped.session.event_token" in events


def test_tag_panels_use_session_scoped_tag_events() -> None:
    info = (SRC / "panels" / "info.py").read_text(encoding="utf-8")
    tag_tree = (SRC / "panels" / "tag_tree.py").read_text(encoding="utf-8")
    assert "AssetTagsChanged" in info
    # Path-ownership check: legacy comparison or the resolve-normalized
    # _same_path helper introduced by P2 I-5 (junction-safe).
    assert (
        "event.file_path != self._current_path" in info
        or "self._same_path(event.file_path" in info
    )
    assert "TagCatalogChanged" in tag_tree
    assert "event.session_token != scoped.session.event_token" in tag_tree


def test_info_uses_session_scoped_metadata_events() -> None:
    source = (SRC / "panels" / "info.py").read_text(encoding="utf-8")
    assert "AssetNotesChanged" in source
    assert "AssetUrlsChanged" in source
    assert "event.session_token == scoped.session.event_token" in source


def test_panels_do_not_import_legacy_unscoped_mutation_events() -> None:
    legacy_events = {
        "FileCreated", "FileRenamed", "FileDeleted", "FileCopied",
        "TagsChanged", "NotesChanged", "UrlsChanged",
    }
    violations: list[str] = []
    for path in _python_files("panels"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "AssetsManager.domain.events":
                imported = legacy_events.intersection(alias.name for alias in node.names)
                if imported:
                    violations.append(f"{_module_name(path)} imports {', '.join(sorted(imported))}")
    assert not violations, (
        "Panels must refresh through session-scoped domain events, not legacy unscoped mutation events:\n"
        + "\n".join(violations)
    )


def test_lan_routes_do_not_import_repositories() -> None:
    _assert_no_import_prefixes(
        _files(SRC, "lan", "routes"),
        ("AssetsManager.repositories",),
    )


def test_lan_routes_do_not_read_database_manager_current() -> None:
    violations = _database_manager_current_violations(_files(SRC, "lan", "routes"))
    assert not violations, "LAN routes must use request-scoped services:\n" + "\n".join(violations)


def test_qualified_attribute_reads_flags_direct_database_manager_current_syntax(
    tmp_path: Path,
) -> None:
    route = tmp_path / "direct_database_manager_route.py"
    route.write_text(
        "DatabaseManager = object()\n"
        "\n"
        "def handle_request():\n"
        "    return DatabaseManager.current\n",
        encoding="utf-8",
    )

    assert _database_manager_current_violations([route]) == [
        f"{_module_name(route)}:4:11 handle_request reads DatabaseManager.current",
    ]


def test_qualified_attribute_reads_flags_known_database_manager_import_alias(
    tmp_path: Path,
) -> None:
    route = tmp_path / "database_manager_import_alias_route.py"
    route.write_text(
        "from AssetsManager.core.database import DatabaseManager as DB\n"
        "\n"
        "def handle_request():\n"
        "    return DB.current\n",
        encoding="utf-8",
    )

    assert _database_manager_current_violations([route]) == [
        f"{_module_name(route)}:4:11 handle_request reads DatabaseManager.current",
    ]


def test_qualified_attribute_reads_flags_database_module_and_full_qualified_chains(
    tmp_path: Path,
) -> None:
    route = tmp_path / "database_module_chains_route.py"
    route.write_text(
        "import AssetsManager.core.database as database\n"
        "from AssetsManager.core import database as db\n"
        "\n"
        "def handle_request():\n"
        "    first = database.DatabaseManager.current\n"
        "    second = db.DatabaseManager.current\n"
        "    return AssetsManager.core.database.DatabaseManager.current\n",
        encoding="utf-8",
    )

    assert _database_manager_current_violations([route]) == [
        f"{_module_name(route)}:5:12 handle_request reads DatabaseManager.current",
        f"{_module_name(route)}:6:13 handle_request reads DatabaseManager.current",
        f"{_module_name(route)}:7:11 handle_request reads DatabaseManager.current",
    ]


def test_qualified_attribute_reads_preserves_each_occurrence_location(tmp_path: Path) -> None:
    route = tmp_path / "duplicate_database_manager_current_reads_route.py"
    route.write_text(
        "def handle_request():\n"
        "    first = DatabaseManager.current\n"
        "    second = DatabaseManager.current\n"
        "    return first, second\n",
        encoding="utf-8",
    )

    occurrences = _qualified_attribute_reads(route)

    assert [(chain, lineno, col_offset) for _, _, _, chain, lineno, col_offset in occurrences] == [
        ("DatabaseManager.current", 2, 12),
        ("DatabaseManager.current", 3, 13),
    ]


def test_qualified_attribute_reads_ignores_unrelated_current_attribute(tmp_path: Path) -> None:
    route = tmp_path / "ordinary_current_route.py"
    route.write_text(
        "def handle_request():\n"
        "    return Other.current\n",
        encoding="utf-8",
    )

    assert _database_manager_current_violations([route]) == []


def test_future_public_dto_modules_do_not_import_qt() -> None:
    violations = _public_dto_qt_import_violations(_public_dto_files())
    assert not violations, "Public DTO modules must not depend on Qt:\n" + "\n".join(violations)


def test_public_dto_qt_gate_detects_a_synthetic_named_dto_module(tmp_path: Path) -> None:
    dto = tmp_path / "transport_dto.py"
    dto.write_text("from PySide6.QtCore import QObject\n", encoding="utf-8")

    discovered = _public_dto_files(tmp_path)

    assert discovered == [dto]
    assert _public_dto_qt_import_violations(discovered) == [
        f"{dto} imports PySide6.QtCore"
    ]


def test_startup_window_tracks_theme_and_language_connection_handles() -> None:
    source = (SRC / "dialogs" / "startup.py").read_text(encoding="utf-8")
    start = source.index("    def __init__(self, parent=None):")
    end = source.index("    def _center_on_parent", start)
    lifecycle = source[start:end]

    assert "self._theme_connection = bus().theme_changed.connect(self.refresh_theme)" in lifecycle
    assert "self._language_connection = bus().language_changed.connect(self._refresh_language)" in lifecycle
    assert "QObject.disconnect(self._theme_connection)" in lifecycle
    assert "QObject.disconnect(self._language_connection)" in lifecycle


def test_library_panels_bind_through_scoped_services_only() -> None:
    info = (SRC / "panels" / "info.py").read_text(encoding="utf-8")
    tag_tree = (SRC / "panels" / "tag_tree.py").read_text(encoding="utf-8")
    # Library-global events (share state) must not be bound by library panels.
    assert "_connect_domain_event(ShareChanged" not in info
    assert "_connect_domain_event(ShareChanged" not in tag_tree


def test_sidebar_storage_does_not_open_database_manager() -> None:
    for module in ("sidebar_favorites.py", "sidebar_recent.py"):
        source = (SRC / "dialogs" / module).read_text(encoding="utf-8")
        assert "get_library_dir" not in source
        assert "AssetsManager.core.database" not in source


def test_database_singleton_helpers_are_legacy_only() -> None:
    allowed = {
        "core/database.py",
        "core/project_data.py",
        "core/tag_store.py",
    }
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        relative = path.relative_to(SRC).as_posix()
        if relative in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        if "get_lib_db(" in source:
            violations.append(relative)

    assert not violations, "Database singleton helpers must stay legacy-only:\n" + "\n".join(violations)


def test_presentation_does_not_construct_unscoped_mutation_services() -> None:
    forbidden_calls = {"FileOperationService", "UndoService"}
    violations: list[str] = []
    for package in ("dialogs", "panels", "widgets"):
        for path in _python_files(package):
            module = _module_name(path)
            for scope, call in sorted(_direct_calls(path)):
                if call in forbidden_calls:
                    violations.append(f"{module}.{scope} constructs {call}()")
    assert not violations, "Unscoped mutation service construction in presentation:\n" + "\n".join(violations)


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
        ("AssetsManager.application.reconciliation_queue", "task_id"),
        ("tests.unit.test_reconciliation_queue", "test_transition_listener_reports_committed_states_and_eviction_once"),
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


def test_production_code_does_not_read_session_raw_resources() -> None:
    allowed_modules = {
        "AssetsManager.application.context",
        "AssetsManager.application.library_service",
    }
    violations: list[str] = []
    for package in ("application", "controllers", "panels", "widgets"):
        for path in _python_files(package):
            module = _module_name(path)
            if module in allowed_modules:
                continue
            for scope, attr in sorted(_session_raw_resource_reads(path)):
                violations.append(f"{module}.{scope} reads session raw resource .{attr}")
    assert not violations, (
        "Production code must use scoped services or session.connection_for(), "
        "not LibrarySession raw resources:\n" + "\n".join(violations)
    )


def test_repositories_only_depend_on_core_infrastructure_and_domain() -> None:
    allowed_prefixes = (
        "AssetsManager.core.database",
        "AssetsManager.core.path_resolver",
        "AssetsManager.core.schema_defs",
        "AssetsManager.core.session_contract",
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
    assert not violations, "Repositories must only depend on core infrastructure and domain:\n" + "\n".join(violations)


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
