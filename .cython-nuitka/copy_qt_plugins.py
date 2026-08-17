#!/usr/bin/env python
"""Copy Qt plugins to the compiled application directory."""
import os
import sys
import shutil
from pathlib import Path


def get_pyside6_path():
    """Get PySide6 installation path."""
    try:
        import PySide6
        return Path(PySide6.__path__[0])
    except ImportError:
        print("ERROR: PySide6 not installed!")
        sys.exit(1)


def copy_plugins():
    """Copy Qt plugins to the dist directory."""
    root = Path.cwd()
    pyside6_path = get_pyside6_path()
    
    # Source paths
    plugins_src = pyside6_path / "plugins"
    
    # Destination paths
    dist_dir = root / "dist"
    main_dist_dir = dist_dir / "main.dist"
    
    # For onefile mode, we need to create a launcher that sets QT_PLUGIN_PATH
    if not main_dist_dir.exists():
        print(f"Creating {main_dist_dir}...")
        main_dist_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy plugins
    plugins_dst = main_dist_dir / "PySide6" / "plugins"
    if plugins_dst.exists():
        print(f"Removing existing plugins: {plugins_dst}")
        shutil.rmtree(plugins_dst)
    
    print(f"Copying plugins from: {plugins_src}")
    print(f"Copying plugins to: {plugins_dst}")
    shutil.copytree(plugins_src, plugins_dst)
    
    # Copy Qt DLLs
    print("Copying Qt DLLs...")
    for dll in pyside6_path.glob("Qt6*.dll"):
        dst = main_dist_dir / dll.name
        if not dst.exists():
            shutil.copy2(dll, dst)
    
    # Copy shiboken6 DLLs
    print("Copying shiboken6 DLLs...")
    for dll in pyside6_path.glob("shiboken6*.dll"):
        dst = main_dist_dir / dll.name
        if not dst.exists():
            shutil.copy2(dll, dst)
    
    print("\n[OK] Qt plugins copied successfully!")
    print(f"\nTo run the application:")
    print(f"  1. cd {main_dist_dir}")
    print(f"  2. set QT_PLUGIN_PATH=PySide6\\plugins")
    print(f"  3. AssetManager.exe")
    print(f"\nOr use the launcher script: {main_dist_dir / 'run.bat'}")


if __name__ == "__main__":
    copy_plugins()