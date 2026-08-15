"""Layer DAG regression tests for the architecture gate."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_CHECK_LAYERS_PATH = ROOT / "scripts" / "check_layers.py"
_spec = importlib.util.spec_from_file_location("check_layers", _CHECK_LAYERS_PATH)
assert _spec is not None and _spec.loader is not None
check_layers = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = check_layers
_spec.loader.exec_module(check_layers)


def test_layer_dag_has_no_undocumented_violations() -> None:
    violations = check_layers.collect_violations()

    assert not violations, (
        "Layer DAG violations outside the documented transitional exceptions:\n"
        + "\n".join(violation.describe() for violation in violations)
    )


def test_transitional_exception_registry_shrinks() -> None:
    # Every exception must name an owning batch so removal stays trackable.
    assert check_layers.ALLOWED_EXCEPTIONS is not None
    assert all(batch for _source, _imported, batch in check_layers.ALLOWED_EXCEPTIONS)

    # G1 promised to remove core -> application/repositories edges.
    for source, imported, batch in check_layers.ALLOWED_EXCEPTIONS:
        assert not (
            source.startswith("AssetsManager.core.")
            and (
                imported.startswith("AssetsManager.application")
                or imported.startswith("AssetsManager.repositories")
            )
        ), f"G1 exception should be gone: {source} -> {imported} ({batch})"

    # G2 promised to remove presentation -> LAN edges via desktop ports.
    assert not any(
        batch == "G2"
        for _source, _imported, batch in check_layers.ALLOWED_EXCEPTIONS
    ), "G2 presentation -> LAN exceptions should be gone"

    # G4 promised to remove core -> domain and controller -> panel edges.
    assert not any(
        batch == "G4"
        for _source, _imported, batch in check_layers.ALLOWED_EXCEPTIONS
    ), "G4 core/domain and controller/panel exceptions should be gone"


def test_g2_sharing_presentation_has_no_lan_imports() -> None:
    for relative in (
        "widgets/lan_sharing.py",
        "dialogs/sharing_settings_dialog.py",
    ):
        source = (ROOT / "AssetsManager" / relative).read_text(encoding="utf-8")
        assert "AssetsManager.lan" not in source, relative
        assert "from AssetsManager import lan" not in source, relative


def test_g2_lan_server_has_single_production_assembly_point() -> None:
    ports = (ROOT / "AssetsManager" / "lan" / "ports.py").read_text(encoding="utf-8")
    assert "\n    return lan.LanServer(" in ports

    for relative in ("lan/manager.py", "widgets/lan_sharing.py"):
        source = (ROOT / "AssetsManager" / relative).read_text(encoding="utf-8")
        assert "lan.LanServer(" not in source, relative
        assert "LanServer(" not in source, relative


def test_layer_checker_has_no_core_to_repository_edge() -> None:
    violations = check_layers.collect_violations()
    assert all(
        not (
            violation.source.startswith("AssetsManager.core.")
            and violation.imported.startswith("AssetsManager.repositories")
        )
        for violation in violations
    )
