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
    "Assets/Themes",
    "RuntimeData/Shared",
    "Plugins",
)
ASSET_REFERENCE = re.compile(r"(?:src|href)=[\"']/?(assets/[^\"']+)[\"']")


def _resource_root(bundle_dir: Path) -> Path:
    """Return the PyInstaller data directory for a one-directory bundle."""
    internal_dir = bundle_dir / "_internal"
    return internal_dir if internal_dir.is_dir() else bundle_dir


def check_bundle(bundle_dir: Path) -> list[str]:
    """Return all missing resource paths from a built application bundle."""
    resource_root = _resource_root(bundle_dir)
    missing: list[str] = []
    for relative_path in REQUIRED_PATHS:
        path = bundle_dir / relative_path if relative_path == "AssetManager.exe" else resource_root / relative_path
        if not path.exists():
            missing.append(relative_path)
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
