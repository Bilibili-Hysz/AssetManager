"""Static contracts for the production packaging entrypoints."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINTS = (
    ROOT / "AssetManager.spec",
    ROOT / ".cython-nuitka" / "build_nuitka.py",
    ROOT / ".cython-nuitka" / "build_nuitka_simple.py",
    ROOT / ".cython-nuitka" / "build_nuitka_standalone.py",
)


def test_packaging_entrypoints_use_react_dist_and_not_legacy_static():
    for entrypoint in ENTRYPOINTS:
        # Named explicitly: a moved or renamed entrypoint should report itself
        # rather than surface as a bare FileNotFoundError traceback.
        assert entrypoint.is_file(), f"packaging entrypoint missing: {entrypoint}"
        source = entrypoint.read_text(encoding="utf-8")
        assert "AssetsManager/lan/static" not in source, entrypoint
        assert "AssetsManager' / 'lan' / 'static" not in source, entrypoint
        assert "webui" in source and "dist" in source, entrypoint


def test_pyinstaller_uses_tracked_canonical_icon_source():
    source = (ROOT / 'AssetManager.spec').read_text(encoding='utf-8')
    assert "(str(_root / 'assets' / 'icons'), 'assets/icons')" in source


def test_pyinstaller_uses_canonical_icon_file_source():
    source = (ROOT / 'AssetManager.spec').read_text(encoding='utf-8')
    assert "icon=str(_root / 'assets' / 'icons' / 'icon.ico')" in source

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


def test_pyinstaller_manifest_excludes_runtime_data_directory():
    source = (ROOT / "AssetManager.spec").read_text(encoding="utf-8")
    assert "RuntimeData/Shared" not in source


def test_pyinstaller_manifest_does_not_list_removed_hidden_imports():
    source = (ROOT / "AssetManager.spec").read_text(encoding="utf-8")
    assert "aiohttp.protocol" not in source
    assert "AssetsManager.application.thumbnail_repository" not in source
    assert "AssetsManager.repositories.thumbnail_repository" in source


def test_pyinstaller_keeps_qtsvg_for_the_svg_icon_registry():
    source = (ROOT / "AssetManager.spec").read_text(encoding="utf-8")
    assert "'PySide6.QtSvg'," in source
    excludes = source.split("excludes=[", 1)[1]
    assert "'PySide6.QtSvg'," not in excludes


def test_pyinstaller_keeps_qt_opengl_for_the_image_viewer():
    source = (ROOT / "AssetManager.spec").read_text(encoding="utf-8")
    assert "'PySide6.QtOpenGL'," in source
    assert "'PySide6.QtOpenGLWidgets'," in source
    excludes = source.split("excludes=[", 1)[1]
    assert "'PySide6.QtOpenGL'," not in excludes
    assert "'PySide6.QtOpenGLWidgets'," not in excludes


def test_pyinstaller_manifest_has_no_stale_async_timeout_hidden_import():
    source = (ROOT / "AssetManager.spec").read_text(encoding="utf-8")
    assert "'async_timeout'" not in source


def test_pyinstaller_spec_anchors_resources_to_its_own_directory():
    source = (ROOT / "AssetManager.spec").read_text(encoding="utf-8")
    assert "_root = Path(SPECPATH).resolve()" in source
    assert "_root = Path.cwd()" not in source


def test_launcher_reports_startup_errors_through_bundled_qt():
    source = (ROOT / "run.py").read_text(encoding="utf-8")
    assert "QMessageBox" in source
    assert "import tkinter" not in source
    assert "tkinter.messagebox" not in source


def test_launcher_has_noninteractive_frozen_package_smoke():
    source = (ROOT / "run.py").read_text(encoding="utf-8")
    assert "--package-smoke" in source
    assert "_run_package_smoke" in source
    assert "QSvgRenderer" in source


def test_dev_requirements_include_anyio_for_marked_async_tests():
    source = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "anyio>=4.0" in source



def test_ci_package_smoke_builds_from_foreign_cwd():
    source = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Build PyInstaller bundle from foreign cwd" in source
    assert "$env:GITHUB_WORKSPACE" in source
    assert "$env:RUNNER_TEMP" in source
    assert "check_package_contents.py $executable" in source


def test_ci_package_smoke_starts_frozen_runtime():
    source = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Smoke-test frozen runtime" in source
    assert "Start-Process -FilePath $executable" in source
    assert "Start-Sleep -Seconds 15" in source
    assert "if ($process.HasExited)" in source
    assert "if ($process.HasExited -and $process.ExitCode -ne 0)" not in source


def test_ci_package_smoke_runs_noninteractive_frozen_import_probe():
    source = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "--package-smoke" in source
    assert "Smoke-test frozen Qt imports and icon rendering" in source
    assert "$process.ExitCode -ne 0" in source


def test_ci_runs_python_realtime_acceptance_with_browser_dependencies():
    source = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "python-browser-e2e" in source
    assert 'pip install -r requirements-lan.txt -r requirements-dev.txt "playwright>=1.50"' in source
    assert "python -m playwright install chromium" in source
    assert "tests/e2e/test_webui_realtime_acceptance.py" in source


def test_ci_audits_webui_dependencies():
    source = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "npm audit --audit-level=moderate" in source
