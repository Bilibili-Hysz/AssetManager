# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AssetManager — single-directory bundle.

Refactored architecture (2026-06-10).
Application services: library, asset, metadata, tag, file_operation,
  thumbnail, search, auth, plugin, project, undo, asset_index, asset_filters.
LAN routes: split into focused modules under lan/routes/.
Core: database migrations, plugins, settings, path resolution.
"""
import sys
from pathlib import Path

_root = Path.cwd()

a = Analysis(
    ['run.py'],
    pathex=[str(_root)],
    binaries=[],
    datas=[
        (str(_root / 'assets'), 'assets'),
        (str(_root / 'AssetsManager' / 'i18n' / 'en.json'), 'AssetsManager/i18n'),
        (str(_root / 'AssetsManager' / 'i18n' / 'zh.json'), 'AssetsManager/i18n'),
        (str(_root / 'AssetsManager' / 'i18n' / 'ja.json'), 'AssetsManager/i18n'),
        # Theme JSON files
        (str(_root / 'Assets' / 'Themes'), 'Assets/Themes'),
        # LAN sharing static files
        (str(_root / 'AssetsManager' / 'lan' / 'static'), 'AssetsManager/lan/static'),
        # Plugin addons
        (str(_root / 'Plugins'), 'Plugins'),
        # RuntimeData — settings and shared data for first launch
        (str(_root / 'RuntimeData' / 'Shared'), 'RuntimeData/Shared'),
    ],
    hiddenimports=[
        # Core deps
        'PIL._webp',
        'PIL.Image',
        'send2trash',
        'sqlite3',
        # PySide6
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'shiboken6',
        # LAN sharing — aiohttp + dependencies
        'aiohttp',
        'aiohttp.web',
        'aiohttp.client',
        'aiohttp.hdrs',
        'aiohttp.helpers',
        'aiohttp.http',
        'aiohttp.log',
        'aiohttp.multipart',
        'aiohttp.payload',
        'aiohttp.streams',
        'aiohttp.connector',
        'aiohttp.cookiejar',
        'aiohttp.formdata',
        'aiohttp.protocol',
        'aiohttp.resolver',
        'aiohttp.tracing',
        'aiohttp.typedefs',
        'aiohttp.web_request',
        'aiohttp.web_response',
        'aiohttp.web_runner',
        'aiohttp.web_ws',
        'aiohttp.web_fileresponse',
        'aiohttp.web_urldispatcher',
        'aiohttp.web_protocol',
        # aiohttp C extension deps
        'multidict',
        'multidict._multidict',
        'yarl',
        'yarl._quoting',
        'aiosignal',
        'frozenlist',
        'async_timeout',
        'asyncio',
        'ssl',
        # LAN module
        'AssetsManager.lan',
        'AssetsManager.lan.api',
        'AssetsManager.lan.auth',
        'AssetsManager.lan.server',
        'AssetsManager.lan.security',
        'AssetsManager.lan.ws',
        'AssetsManager.lan.scanner',
        'AssetsManager.lan.tunnel',
        'AssetsManager.lan.manager',
        'AssetsManager.lan.path_guard',
        'AssetsManager.lan.utils',
        'AssetsManager.lan.routes',
        'AssetsManager.lan.routes._helpers',
        'AssetsManager.lan.routes.auth',
        'AssetsManager.lan.routes.downloads',
        'AssetsManager.lan.routes.files',
        'AssetsManager.lan.routes.metadata',
        'AssetsManager.lan.routes.pages',
        'AssetsManager.lan.routes.shares',
        'AssetsManager.lan.routes.system',
        'AssetsManager.lan.routes.tags',
        'AssetsManager.lan.routes.thumbnails',
        'AssetsManager.lan.routes.users',
        'AssetsManager.lan.routes.websocket',
        # Application services
        'AssetsManager.application',
        'AssetsManager.application.asset_filters',
        'AssetsManager.application.asset_index_service',
        'AssetsManager.application.asset_service',
        'AssetsManager.application.auth_service',
        'AssetsManager.application.context',
        'AssetsManager.application.file_operation_service',
        'AssetsManager.application.library_service',
        'AssetsManager.application.metadata_service',
        'AssetsManager.application.plugin_service',
        'AssetsManager.application.project_service',
        'AssetsManager.application.search_service',
        'AssetsManager.application.share_service',
        'AssetsManager.application.tag_service',
        'AssetsManager.application.thumbnail_repository',
        'AssetsManager.application.thumbnail_service',
        'AssetsManager.application.undo_service',
        # Domain layer
        'AssetsManager.domain',
        'AssetsManager.domain.errors',
        'AssetsManager.domain.library',
        'AssetsManager.domain.asset',
        'AssetsManager.domain.share',
        'AssetsManager.domain.events',
        'AssetsManager.domain.event_bus',
        # Dependency injection
        'AssetsManager.di',
        # Repositories
        'AssetsManager.repositories',
        'AssetsManager.repositories.tag_repository',
        'AssetsManager.repositories.metadata_repository',
        'AssetsManager.repositories.share_repository',
        'AssetsManager.repositories.thumbnail_repository',
        # Controllers
        'AssetsManager.controllers',
        'AssetsManager.controllers.file_list_controller',
        # Core
        'AssetsManager.core.format_utils',
        'AssetsManager.core.db_migrations',
        'AssetsManager.core.ui_scale',
        'AssetsManager.core.plugins',
        'AssetsManager.core.plugins.descriptor',
        'AssetsManager.core.plugins.host_context',
        'AssetsManager.core.plugins.loader',
        'AssetsManager.core.plugins.manager',
        # Dialogs
        'AssetsManager.dialogs.plugin_manager_dialog',
        # File list grid
        'AssetsManager.panels.file_list._grid_layout',
        'AssetsManager.panels.file_list._grid_widget',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy optional modules (not packaged by default)
        'scipy', 'numpy', 'pytest', 'pygments', 'setuptools',
        'tkinter', 'unittest', 'test', 'tests',
        'pip', 'pkg_resources', 'distutils',
        'matplotlib', 'pandas',
        # Qt modules not used by this app
        'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtPdf',
        'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
        'PySide6.Qt3D', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
        'PySide6.QtMultimedia', 'PySide6.QtSvg', 'PySide6.QtSvgWidgets',
        'PySide6.QtWebEngine', 'PySide6.QtWebEngineWidgets',
        'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtSql',
        # PIL formats not needed
        'PIL._avif', 'PIL._avifcp314',
        'PIL.FitsStubImagePlugin', 'PIL.GbrStubImagePlugin',
        'PIL.GribStubImagePlugin', 'PIL.Hdf5StubImagePlugin',
        'PIL.MicStubImagePlugin', 'PIL.MpoStubImagePlugin',
        'PIL.MspStubImagePlugin', 'PIL.PalmStubImagePlugin',
        'PIL.PcdStubImagePlugin', 'PIL.PcxStubImagePlugin',
        'PIL.PixarStubImagePlugin', 'PIL.PsdStubImagePlugin',
        'PIL.SgiStubImagePlugin', 'PIL.SunStubImagePlugin',
        'PIL.TgaStubImagePlugin', 'PIL.WebPStubImagePlugin',
        'PIL.XbmStubImagePlugin', 'PIL.XpmStubImagePlugin',
        # AI tagger deps — user installs ollama separately
        # LAN sharing deps — optional, installed via pip install aiohttp
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AssetManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(_root / 'assets' / 'icons' / 'icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AssetManager',
)
