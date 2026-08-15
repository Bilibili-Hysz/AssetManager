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
    assert check_layers.ALLOWED_EXCEPTIONS
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


def test_layer_checker_has_no_core_to_repository_edge() -> None:
    violations = check_layers.collect_violations()
    assert all(
        not (
            violation.source.startswith("AssetsManager.core.")
            and violation.imported.startswith("AssetsManager.repositories")
        )
        for violation in violations
    )
