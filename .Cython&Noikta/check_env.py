#!/usr/bin/env python
"""Verify virtual environment setup."""
import sys
import subprocess

def check_environment():
    """Check if the virtual environment is properly set up."""
    print("=== Environment Check ===")
    print(f"Python Version: {sys.version}")
    print(f"Python Path: {sys.executable}")
    print()
    
    # Check PySide6
    try:
        import PySide6
        print(f"[OK] PySide6 {PySide6.__version__}")
    except ImportError:
        print("[FAIL] PySide6 not installed")
    
    # Check Pillow
    try:
        import PIL
        print(f"[OK] Pillow {PIL.__version__}")
    except ImportError:
        print("[FAIL] Pillow not installed")
    
    # Check requests
    try:
        import requests
        print(f"[OK] requests {requests.__version__}")
    except ImportError:
        print("[FAIL] requests not installed")
    
    # Check aiohttp
    try:
        import aiohttp
        print(f"[OK] aiohttp {aiohttp.__version__}")
    except ImportError:
        print("[SKIP] aiohttp not installed (optional)")
    
    # Check pytest
    try:
        import pytest
        print(f"[OK] pytest {pytest.__version__}")
    except ImportError:
        print("[FAIL] pytest not installed")
    
    print()
    print("=== Running Tests ===")
    result = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"], 
                          capture_output=True, text=True)
    if result.returncode == 0:
        print("[OK] All tests passed")
    else:
        print("[FAIL] Tests failed")
        print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
    
    print()
    print("=== Environment Ready ===")
    print("Run: python main.py")

if __name__ == "__main__":
    check_environment()