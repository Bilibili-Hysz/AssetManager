"""Tests for the distributable bundle resource checker."""
from __future__ import annotations

import subprocess
import sys
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
    (internal / "AssetsManager" / "i18n" / "en.json").touch()
    (internal / "Assets" / "Themes").mkdir(parents=True)
    (internal / "Assets" / "Themes" / "default.json").touch()
    (internal / "RuntimeData" / "Shared").mkdir(parents=True)
    (internal / "Plugins").mkdir(parents=True)


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
