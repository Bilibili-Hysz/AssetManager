#!/usr/bin/env python
"""Nuitka build script for AssetManager."""
import os
import sys
import subprocess
from pathlib import Path


def check_venv():
    """Check if running in virtual environment."""
    if sys.prefix == sys.base_prefix:
        print("WARNING: Not running in virtual environment!")
        print("Please activate venv first:")
        print("  .venv\\Scripts\\Activate.ps1")
        print()
        
        # Try to use venv python directly
        root = Path.cwd()
        venv_python = root / ".venv" / "Scripts" / "python.exe"
        if venv_python.exists():
            print(f"Found venv Python: {venv_python}")
            print("Re-running with venv Python...")
            result = subprocess.run(
                [str(venv_python)] + sys.argv,
                capture_output=False
            )
            sys.exit(result.returncode)
        else:
            print("ERROR: Virtual environment not found!")
            sys.exit(1)


def check_nuitka():
    """Check if Nuitka is installed."""
    try:
        import nuitka
        return True
    except ImportError:
        print("ERROR: Nuitka not installed!")
        print("Please install Nuitka:")
        print("  pip install nuitka")
        return False


def get_pyside6_path():
    """Get PySide6 installation path."""
    try:
        import PySide6
        return Path(PySide6.__path__[0])
    except ImportError:
        print("ERROR: PySide6 not installed!")
        sys.exit(1)


def build():
    """Build AssetManager with Nuitka."""
    # Check virtual environment
    check_venv()
    
    # Check Nuitka
    if not check_nuitka():
        sys.exit(1)
    
    root = Path.cwd()
    pyside6_path = get_pyside6_path()
    
    print(f"PySide6 path: {pyside6_path}")
    
    # Nuitka command
    cmd = [
        sys.executable, "-m", "nuitka",
        
        # Output settings
        "--standalone",
        "--onefile",
        "--output-dir=dist",
        "--output-filename=AssetManager.exe",
        
        # Enable optimizations
        "--lto=yes",
        "--assume-yes-for-downloads",
        
        # Include data files
        f"--include-data-dir={root / 'assets'}=assets",
        f"--include-data-files={root / 'AssetsManager' / 'i18n' / 'en.json'}=AssetsManager/i18n/en.json",
        f"--include-data-files={root / 'AssetsManager' / 'i18n' / 'zh.json'}=AssetsManager/i18n/zh.json",
        f"--include-data-files={root / 'AssetsManager' / 'i18n' / 'ja.json'}=AssetsManager/i18n/ja.json",
        f"--include-data-dir={root / 'AssetsManager' / 'themes'}=AssetsManager/themes",
        f"--include-data-dir={root / 'webui' / 'dist'}=webui/dist",
        
        # Include binary files
        f"--include-data-files={root / 'cloudflared-windows-amd64.exe'}=cloudflared-windows-amd64.exe",
        
        # Include modules
        "--include-module=PIL",
        "--include-module=send2trash",
        "--include-module=sqlite3",
        "--include-module=aiohttp",
        "--include-module=AssetsManager.lan",
        
        # PySide6 support
        "--include-module=PySide6",
        "--include-module=shiboken6",
        
        # Include Qt plugins - CRITICAL for Qt platform plugin error
        f"--include-data-dir={pyside6_path / 'plugins'}=PySide6/plugins",
        
        # Include Qt DLLs
        f"--include-data-files={pyside6_path / 'Qt6Core.dll'}=Qt6Core.dll",
        f"--include-data-files={pyside6_path / 'Qt6Gui.dll'}=Qt6Gui.dll",
        f"--include-data-files={pyside6_path / 'Qt6Widgets.dll'}=Qt6Widgets.dll",
        f"--include-data-files={pyside6_path / 'Qt6OpenGL.dll'}=Qt6OpenGL.dll",
        f"--include-data-files={pyside6_path / 'Qt6Network.dll'}=Qt6Network.dll",
        f"--include-data-files={pyside6_path / 'Qt6Svg.dll'}=Qt6Svg.dll",
        
        # Windows specific
        "--windows-icon-from-ico=assets/icons/icon.ico",
        "--windows-console-mode=disable",
        
        # Plugin options
        "--enable-plugin=anti-bloat",
        "--enable-plugin=pylint-warnings",
        
        # Main script
        "main.py"
    ]
    
    print("Building AssetManager with Nuitka...")
    print(f"Python: {sys.executable}")
    print(f"Command: {' '.join(cmd)}")
    print()
    
    # Run Nuitka
    result = subprocess.run(cmd, capture_output=False)
    
    if result.returncode == 0:
        print("\n[OK] Build successful!")
        print(f"Output: {root / 'dist' / 'AssetManager.exe'}")
    else:
        print("\n[FAIL] Build failed!")
        sys.exit(1)


if __name__ == "__main__":
    build()
