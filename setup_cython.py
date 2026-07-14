"""Cython build script — compiles hotspot modules to .pyd for 2-5x speedup."""
from setuptools import setup
from Cython.Build import cythonize

TARGET_MODULES = [
    'AssetsManager/core/cache.py',
    'AssetsManager/core/color_utils.py',
    'AssetsManager/core/format_utils.py',
    'AssetsManager/application/asset_filters.py',
]

setup(
    ext_modules=cythonize(
        TARGET_MODULES,
        compiler_directives={'language_level': '3'},
    ),
)
