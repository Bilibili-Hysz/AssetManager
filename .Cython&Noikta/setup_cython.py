
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
