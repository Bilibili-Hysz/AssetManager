#!/usr/bin/env python
"""Cython build script for AssetManager core modules."""
import os
import sys
import subprocess
from pathlib import Path

def build():
    """Build core modules with Cython."""
    root = Path.cwd()
    
    # Core modules to compile
    modules = [
        "AssetsManager/core/cache.py",
        "AssetsManager/core/lru_cache.py",
        "AssetsManager/core/database.py",
        "AssetsManager/core/json_store.py",
        "AssetsManager/core/tag_store.py",
        "AssetsManager/core/tag_library.py",
        "AssetsManager/core/color_utils.py",
        "AssetsManager/core/path_resolver.py",
    ]
    
    print("Building core modules with Cython...")
    
    # Create setup.py for Cython
    setup_content = '''
from setuptools import setup
from Cython.Build import cythonize
import os

# Core modules to compile
modules = [
    "AssetsManager/core/cache.py",
    "AssetsManager/core/lru_cache.py",
    "AssetsManager/core/database.py",
    "AssetsManager/core/json_store.py",
    "AssetsManager/core/tag_store.py",
    "AssetsManager/core/tag_library.py",
    "AssetsManager/core/color_utils.py",
    "AssetsManager/core/path_resolver.py",
]

setup(
    ext_modules=cythonize(modules, compiler_directives={'language_level': 3}),
)
'''
    
    # Write setup.py
    with open("setup_cython.py", "w") as f:
        f.write(setup_content)
    
    # Run Cython compilation
    cmd = [sys.executable, "setup_cython.py", "build_ext", "--inplace"]
    print(f"Running: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, capture_output=False)
    
    if result.returncode == 0:
        print("\n[OK] Cython build successful!")
    else:
        print("\n[FAIL] Cython build failed!")
        sys.exit(1)

if __name__ == "__main__":
    build()