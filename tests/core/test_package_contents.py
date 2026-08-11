"""Tests for the distributable bundle resource checker."""
from __future__ import annotations

import shutil
import subprocess
import sys

import pytest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts" / "check_package_contents.py"


def _create_bundle(bundle: Path) -> None:
    bundle.mkdir()
    (bundle / "AssetManager.exe").touch()
    internal = bundle / "_internal"
    (internal / "webui" / "dist" / "assets").mkdir(parents=True)
    (internal / "webui" / "dist" / "index.html").write_text(
        '<script src="/assets/app.js"></script>', encoding="utf-8"
    )
    (internal / "webui" / "dist" / "assets" / "app.js").touch()
    (internal / "AssetsManager" / "i18n").mkdir(parents=True)
    for language in ("en", "zh", "ja"):
        (internal / "AssetsManager" / "i18n" / f"{language}.json").touch()
    (internal / "Assets" / "Themes").mkdir(parents=True)
    (internal / "Assets" / "Themes" / "default.json").touch()
    (internal / "Plugins" / "sample" ).mkdir(parents=True)
    (internal / "Plugins" / "sample" / "plugin.json").touch()
    (internal / "assets" / "icons").mkdir(parents=True)
    (internal / "assets" / "icons" / "icon.ico").touch()
    (internal / "PySide6").mkdir(parents=True)
    for module_name in ("QtSvg", "QtOpenGL", "QtOpenGLWidgets"):
        (internal / "PySide6" / f"{module_name}.pyd").touch()
    for library_stem in ("Qt6Svg", "Qt6OpenGL", "Qt6OpenGLWidgets"):
        (internal / "PySide6" / f"{library_stem}.dll").touch()


def test_checker_accepts_spa_only_bundle_without_legacy_static_index(tmp_path):
    bundle = tmp_path / "AssetManager"
    _create_bundle(bundle)

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(bundle)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Package contents verified" in result.stdout


def test_checker_rejects_bundle_without_spa_index(tmp_path):
    bundle = tmp_path / "AssetManager"
    _create_bundle(bundle)
    (bundle / "_internal" / "webui" / "dist" / "index.html").unlink()

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(bundle)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "webui/dist/index.html" in result.stderr


def test_checker_rejects_bundle_with_empty_spa_assets(tmp_path):
    bundle = tmp_path / "AssetManager"
    _create_bundle(bundle)
    (bundle / "_internal" / "webui" / "dist" / "assets" / "app.js").unlink()

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(bundle)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "webui/dist/assets" in result.stderr


def test_checker_rejects_bundle_missing_asset_referenced_by_spa_index(tmp_path):
    bundle = tmp_path / "AssetManager"
    _create_bundle(bundle)
    assets = bundle / "_internal" / "webui" / "dist" / "assets"
    (assets / "app.js").unlink()
    (assets / "unrelated.js").touch()

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(bundle)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "webui/dist/assets/app.js" in result.stderr


@pytest.mark.parametrize(
    ("relative_path", "error_fragment"),
    (
        ("AssetsManager/i18n/en.json", "AssetsManager/i18n/en.json"),
        ("AssetsManager/i18n/zh.json", "AssetsManager/i18n/zh.json"),
        ("AssetsManager/i18n/ja.json", "AssetsManager/i18n/ja.json"),
        ("Assets/Themes", "Assets/Themes"),
        ("Plugins", "Plugins"),
        ("assets/icons/icon.ico", "assets/icons/icon.ico"),
    ),
)
def test_checker_rejects_bundle_missing_stable_resource(
    tmp_path, relative_path, error_fragment
):
    bundle = tmp_path / "AssetManager"
    _create_bundle(bundle)
    target = bundle / "_internal" / relative_path
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(bundle)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert error_fragment in result.stderr


def test_checker_does_not_require_runtime_data_directory(tmp_path):
    bundle = tmp_path / "AssetManager"
    _create_bundle(bundle)

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(bundle)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "RuntimeData/Shared" not in result.stderr


@pytest.mark.parametrize("module_name", ("QtSvg", "QtOpenGL", "QtOpenGLWidgets"))
def test_checker_rejects_bundle_missing_required_qt_module(tmp_path, module_name):
    bundle = tmp_path / "AssetManager"
    _create_bundle(bundle)
    module_path = bundle / "_internal" / "PySide6" / f"{module_name}.pyd"
    module_path.unlink()

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(bundle)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert f"PySide6/{module_name}" in result.stderr


@pytest.mark.parametrize("library_stem", ("Qt6Svg", "Qt6OpenGL", "Qt6OpenGLWidgets"))
def test_checker_rejects_bundle_missing_required_qt_runtime_library(
    tmp_path, library_stem
):
    bundle = tmp_path / "AssetManager"
    _create_bundle(bundle)
    (bundle / "_internal" / "PySide6" / f"{library_stem}.dll").unlink()

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(bundle)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert f"PySide6/{library_stem}" in result.stderr


@pytest.mark.parametrize("relative_path", ("Assets/Themes", "Plugins"))
def test_checker_rejects_bundle_with_empty_stable_directory(tmp_path, relative_path):
    bundle = tmp_path / "AssetManager"
    _create_bundle(bundle)
    target = bundle / "_internal" / relative_path
    for child in target.rglob("*"):
        if child.is_file():
            child.unlink()

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(bundle)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert f"{relative_path} (no files)" in result.stderr

@pytest.mark.parametrize(
    "relative_path",
    (
        "AssetManager.exe",
        "webui/dist/index.html",
        "AssetsManager/i18n/en.json",
        "AssetsManager/i18n/zh.json",
        "AssetsManager/i18n/ja.json",
        "assets/icons/icon.ico",
    ),
)
def test_checker_rejects_file_resource_replaced_by_directory(tmp_path, relative_path):
    bundle = tmp_path / "AssetManager"
    _create_bundle(bundle)
    target = bundle / relative_path if relative_path == "AssetManager.exe" else bundle / "_internal" / relative_path
    target.unlink()
    target.mkdir()

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(bundle)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert relative_path in result.stderr


@pytest.mark.parametrize("relative_path", ("webui/dist/assets", "Assets/Themes", "Plugins"))
def test_checker_rejects_directory_resource_replaced_by_file(tmp_path, relative_path):
    bundle = tmp_path / "AssetManager"
    _create_bundle(bundle)
    target = bundle / "_internal" / relative_path
    shutil.rmtree(target)
    target.touch()

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(bundle)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert relative_path in result.stderr

@pytest.mark.parametrize("module_name", ("QtSvg", "QtOpenGL", "QtOpenGLWidgets"))
def test_checker_rejects_qt_module_stub_without_binary_suffix(tmp_path, module_name):
    bundle = tmp_path / "AssetManager"
    _create_bundle(bundle)
    module_dir = bundle / "_internal" / "PySide6"
    (module_dir / f"{module_name}.pyd").unlink()
    (module_dir / f"{module_name}.pyi").touch()

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(bundle)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert f"PySide6/{module_name}" in result.stderr
