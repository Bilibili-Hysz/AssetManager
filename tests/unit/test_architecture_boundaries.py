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
    forbidden_calls = {"get_store", "get_project_data", "get_library_dir", "close_all_dbs"}
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


def test_database_does_not_restore_removed_get_manager_wrapper() -> None:
    source = (SRC / "core" / "database.py").read_text(encoding="utf-8")

    assert "def get_manager(" not in source


def test_database_does_not_restore_removed_get_lib_db_helper() -> None:
    source = (SRC / "core" / "database.py").read_text(encoding="utf-8")

    assert "def get_lib_db(" not in source


def test_database_does_not_restore_removed_update_library_stats_helper() -> None:
    source = (SRC / "core" / "database.py").read_text(encoding="utf-8")

    assert "def update_library_stats(" not in source


def test_production_path_metadata_migration_uses_explicit_resources() -> None:
    path = SRC / "application" / "file_operation_service.py"
    source = path.read_text(encoding="utf-8")
    assert "migrate_path_metadata(\n            self._connection(), self.session.thumb_dir" in source


def test_project_service_delegates_file_meta_cache_to_repository() -> None:
    source = (SRC / "application" / "project_service.py").read_text(encoding="utf-8")
    assert "from AssetsManager.repositories.metadata_repository import MetadataRepository" in source
    assert "db_conn.execute(" not in source
    assert "db_conn.executemany(" not in source


def test_tag_service_delegates_tag_counts_to_repository() -> None:
    source = (SRC / "application" / "tag_service.py").read_text(encoding="utf-8")
    assert "repo.list_tags_with_counts()" in source
    assert "conn.execute(" not in source


def test_thumbnail_service_delegates_tag_lookup_to_repository() -> None:
    source = (SRC / "application" / "thumbnail_service.py").read_text(encoding="utf-8")
    assert "TagRepository(db_conn).get_tags" in source
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
    source = (SRC / "lan" / "server.py").read_text(encoding="utf-8")
    start = source.index("    async def _startup(self):")
    end = source.index("    async def _shutdown", start)

    assert "self._auth_service.init_tables()" in source[start:end]
    assert "self._share_service.init_table()" in source[start:end]
    assert "AssetsManager.repositories" not in source


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
    assert "ThumbnailService(connection_provider=provider)" in helpers


def test_search_routes_use_scoped_connection_provider() -> None:
    source = (SRC / "lan" / "routes" / "metadata.py").read_text(encoding="utf-8")
    helpers = (SRC / "lan" / "routes" / "_helpers.py").read_text(encoding="utf-8")
    start = source.index("async def handle_search")
    end = source.index("def _record_search_route", start)

    assert "lan.db_conn" not in source[start:end]
    assert "SearchService(\n            connection_provider=provider," in helpers


def test_file_operation_service_delegates_deleted_projection_cleanup() -> None:
    source = (SRC / "application" / "file_operation_service.py").read_text(encoding="utf-8")
    start = source.index("    def _clear_deleted_projection(self, path: Path) -> None:")
    end = source.index("\n\ndef unique_destination", start)
    cleanup = source[start:end]

    assert "TagRepository(conn).delete_path(target, commit=False)" in cleanup
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
    source = (SRC / "panels" / "file_list" / "_base.py").read_text(encoding="utf-8")
    start = source.index("    def shutdown(self):")
    end = source.index("    def closeEvent", start)
    assert "super().shutdown()" in source[start:end]


def test_file_list_uses_session_scoped_file_events() -> None:
    source = (SRC / "panels" / "file_list" / "__init__.py").read_text(encoding="utf-8")
    assert "FileSystemChanged" in source
    assert "event.session_token != scoped.session.event_token" in source


def test_tag_panels_use_session_scoped_tag_events() -> None:
    info = (SRC / "panels" / "info.py").read_text(encoding="utf-8")
    tag_tree = (SRC / "panels" / "tag_tree.py").read_text(encoding="utf-8")
    assert "AssetTagsChanged" in info
    assert "event.file_path != self._current_path" in info
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
    assert "_connect_domain_event(LibraryOpened" not in info
    assert "_connect_domain_event(LibraryOpened" not in tag_tree


def test_sidebar_storage_does_not_open_database_manager() -> None:
    for module in ("sidebar_favorites.py", "sidebar_recent.py"):
        source = (SRC / "dialogs" / module).read_text(encoding="utf-8")
        assert "get_library_dir" not in source
        assert "AssetsManager.core.database" not in source


def test_legacy_library_dir_helper_is_path_only() -> None:
    source = (SRC / "core" / "database.py").read_text(encoding="utf-8")
    start = source.index("def get_library_dir")
    end = source.index("def migrate_path_metadata", start)
    helper = source[start:end]
    assert "ThreadSafeSingleton" not in helper
    assert "library_data_dir" in helper


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
        if "get_lib_db(" in source or "close_all_dbs(" in source:
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
