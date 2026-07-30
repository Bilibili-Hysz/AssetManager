"""Static contracts for the production packaging entrypoints."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINTS = (
    ROOT / "AssetManager.spec",
    ROOT / ".Cython&Noikta" / "build_nuitka.py",
    ROOT / ".Cython&Noikta" / "build_nuitka_simple.py",
    ROOT / ".Cython&Noikta" / "build_nuitka_standalone.py",
)


def test_packaging_entrypoints_use_react_dist_and_not_legacy_static():
    for entrypoint in ENTRYPOINTS:
        source = entrypoint.read_text(encoding="utf-8")
        assert "AssetsManager/lan/static" not in source, entrypoint
        assert "AssetsManager' / 'lan' / 'static" not in source, entrypoint
        assert "webui" in source and "dist" in source, entrypoint


def test_webui_entrypoint_does_not_reference_legacy_favicon():
    source = (ROOT / "webui" / "index.html").read_text(encoding="utf-8")
    assert "/static/favicon.svg" not in source


def test_vite_cache_is_ignored_at_workspace_root():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/.vite/" in gitignore
    assert "/webui/.vite/" in gitignore


def test_pyinstaller_manifest_contains_canonical_runtime_and_public_contract_modules():
    source = (ROOT / "AssetManager.spec").read_text(encoding="utf-8")
    for module in (
        "AssetsManager.application.runtime",
        "AssetsManager.application.runtime_events",
        "AssetsManager.lan.dto",
        "AssetsManager.lan.principal",
    ):
        assert repr(module) in source
