"""Layer DAG regression tests for the architecture gate."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

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
                imported.startswith(("AssetsManager.application", "AssetsManager.repositories"))
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


def test_domain_shared_kernel_whitelist_is_pinned() -> None:
    # domain -> core is a whole-layer edge, but only the Qt-free shared
    # kernel modules may actually be imported; keep the set explicit so
    # additions are a conscious decision.
    assert check_layers.DOMAIN_CORE_SHARED_KERNEL == frozenset(
        {
            "AssetsManager.core.constants",
            "AssetsManager.core.event_contracts",
            "AssetsManager.core.format_utils",
        }
    )


def _stage_domain_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    text: str,
) -> None:
    """Synthesize a one-module AssetsManager tree for a targeted gate run."""
    package = tmp_path / "AssetsManager" / "domain"
    package.mkdir(parents=True)
    (package / f"{name}.py").write_text(text, encoding="utf-8")
    monkeypatch.setattr(check_layers, "ROOT", tmp_path)
    monkeypatch.setattr(check_layers, "SRC", tmp_path / "AssetsManager")


def test_domain_core_import_outside_shared_kernel_violates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # core.themes is Qt-coupled and not part of the shared kernel: the
    # domain -> core edge is allowed by the DAG, but the refinement must
    # still flag the import.
    _stage_domain_module(
        tmp_path,
        monkeypatch,
        "offender",
        "from AssetsManager.core.themes import ThemeLoader\n",
    )

    violations = check_layers.collect_violations()

    assert [
        (violation.source, violation.imported) for violation in violations
    ] == [("AssetsManager.domain.offender", "AssetsManager.core.themes")]
    assert "shared kernel" in violations[0].describe()


def test_domain_core_import_within_shared_kernel_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stage_domain_module(
        tmp_path,
        monkeypatch,
        "clean",
        "from AssetsManager.core.constants import ASSET_ROOT\n",
    )

    assert not check_layers.collect_violations()
