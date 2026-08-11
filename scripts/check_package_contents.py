"""Validate resources required by the PyInstaller onedir bundle."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_PATHS = (
    "AssetManager.exe",
    "webui/dist/index.html",
    "webui/dist/assets",
    "AssetsManager/i18n/en.json",
    "AssetsManager/i18n/zh.json",
    "AssetsManager/i18n/ja.json",
    "Assets/Themes",
    "Plugins",
    "assets/icons/icon.ico",
)
REQUIRED_FILE_PATHS = frozenset(
    {
        "AssetManager.exe",
        "webui/dist/index.html",
        "AssetsManager/i18n/en.json",
        "AssetsManager/i18n/zh.json",
        "AssetsManager/i18n/ja.json",
        "assets/icons/icon.ico",
    }
)
REQUIRED_DIRECTORY_PATHS = frozenset(
    {
        "webui/dist/assets",
        "Assets/Themes",
        "Plugins",
    }
)
REQUIRED_QT_MODULES = (
    "QtSvg",
    "QtOpenGL",
    "QtOpenGLWidgets",
)
REQUIRED_QT_RUNTIME_LIBRARIES = (
    "Qt6Svg",
    "Qt6OpenGL",
    "Qt6OpenGLWidgets",
)
REQUIRED_QT_BINARY_SUFFIXES = frozenset({".pyd", ".so", ".dylib"})
REQUIRED_QT_RUNTIME_SUFFIXES = frozenset({".dll", ".so", ".dylib"})
NON_EMPTY_DIRECTORIES = (
    "Assets/Themes",
    "Plugins",
)
ASSET_REFERENCE = re.compile(r"(?:src|href)=[\"']/?(assets/[^\"']+)[\"']")


def _resource_root(bundle_dir: Path) -> Path:
    """Return the PyInstaller data directory for a one-directory bundle."""
    internal_dir = bundle_dir / "_internal"
    return internal_dir if internal_dir.is_dir() else bundle_dir


def _has_qt_module_binary(resource_root: Path, module_name: str) -> bool:
    """Return whether a PySide6 extension binary is present in the bundle."""
    module_dir = resource_root / "PySide6"
    if not module_dir.is_dir():
        return False
    prefix = f"{module_name}."
    return any(
        path.is_file()
        and path.name.startswith(prefix)
        and path.suffix.lower() in REQUIRED_QT_BINARY_SUFFIXES
        for path in module_dir.iterdir()
    )


def _has_qt_runtime_library(resource_root: Path, library_stem: str) -> bool:
    """Return whether a Qt extension's companion runtime library is present."""
    module_dir = resource_root / "PySide6"
    if not module_dir.is_dir():
        return False
    prefixes = (f"{library_stem}.", f"lib{library_stem}.")
    for path in module_dir.iterdir():
        if not path.is_file() or not path.name.startswith(prefixes):
            continue
        name = path.name.lower()
        if any(
            name.endswith(suffix) or f"{suffix}." in name
            for suffix in REQUIRED_QT_RUNTIME_SUFFIXES
        ):
            return True
    return False


def check_bundle(bundle_dir: Path) -> list[str]:
    """Return all missing resource paths from a built application bundle."""
    resource_root = _resource_root(bundle_dir)
    missing: list[str] = []
    for relative_path in REQUIRED_PATHS:
        path = bundle_dir / relative_path if relative_path == "AssetManager.exe" else resource_root / relative_path
        if relative_path in REQUIRED_FILE_PATHS:
            valid = path.is_file()
        elif relative_path in REQUIRED_DIRECTORY_PATHS:
            valid = path.is_dir()
        else:
            raise AssertionError(f"Unclassified required bundle path: {relative_path}")
        if not valid:
            missing.append(relative_path)
    for module_name in REQUIRED_QT_MODULES:
        if not _has_qt_module_binary(resource_root, module_name):
            missing.append(f"PySide6/{module_name} (binary)")
    for library_stem in REQUIRED_QT_RUNTIME_LIBRARIES:
        if not _has_qt_runtime_library(resource_root, library_stem):
            missing.append(f"PySide6/{library_stem} (runtime library)")
    for relative_path in NON_EMPTY_DIRECTORIES:
        directory = resource_root / relative_path
        if directory.is_dir() and not any(path.is_file() for path in directory.rglob("*")):
            missing.append(f"{relative_path} (no files)")
    assets_dir = resource_root / "webui" / "dist" / "assets"
    if assets_dir.is_dir() and not any(path.is_file() for path in assets_dir.rglob("*")):
        missing.append("webui/dist/assets (no built assets)")
    spa_index = resource_root / "webui" / "dist" / "index.html"
    if spa_index.is_file():
        for asset_path in ASSET_REFERENCE.findall(spa_index.read_text(encoding="utf-8")):
            if not (spa_index.parent / asset_path).is_file():
                missing.append(f"webui/dist/{asset_path}")
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_dir", type=Path, help="Path to dist/AssetManager")
    args = parser.parse_args()

    missing = check_bundle(args.bundle_dir)
    if missing:
        print("Package is missing required resources:", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        return 1

    print(f"Package contents verified: {args.bundle_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
