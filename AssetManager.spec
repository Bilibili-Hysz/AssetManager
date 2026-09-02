# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AssetManager — single-file bundle.

Refactored architecture (2026-06-10).
Application services: library, asset, metadata, tag, file_operation,
  thumbnail, search, auth, plugin, project, undo, asset_index, asset_filters.
LAN routes: split into focused modules under lan/routes/.
Core: database migrations, plugins, settings, path resolution.
"""
from pathlib import Path

_root = Path(SPECPATH).resolve()

# ── Version identity (A1) ─────────────────────────────────────────────────
# AssetsManager/core/constants.py is the single source of truth for the app
# version; the spec mirrors it textually (no package import needed) so the
# Windows version resource embedded in AssetManager.exe always matches the
# About dialog and the installer build script.
import re as _re

APP_VERSION = _re.search(
    r'^APP_VERSION\s*=\s*"([^"]+)"',
    (_root / 'AssetsManager' / 'core' / 'constants.py').read_text(encoding='utf-8'),
    _re.MULTILINE,
).group(1)

# Standard PyInstaller Windows version resource. Built only when the
# platform-specific versioninfo module is importable; elsewhere EXE keeps
# version=None (PyInstaller warns and ignores it on non-Windows hosts).
try:
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    _ver_tuple = tuple(int(part) for part in APP_VERSION.split('.')) + (0,)
    _version_info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=_ver_tuple,
            prodvers=_ver_tuple,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo([
                StringTable('040904B0', [
                    StringStruct('CompanyName', 'AssetManager'),
                    StringStruct('FileDescription', 'AssetManager'),
                    StringStruct('FileVersion', APP_VERSION),
                    StringStruct('InternalName', 'AssetManager'),
                    StringStruct('OriginalFilename', 'AssetManager.exe'),
                    StringStruct('ProductName', 'AssetManager'),
                    StringStruct('ProductVersion', APP_VERSION),
                ]),
            ]),
            VarFileInfo([VarStruct('Translation', [1033, 1200])]),
        ],
    )
except ImportError:  # pragma: no cover - non-Windows build hosts
    _version_info = None

a = Analysis(
    ['run.py'],
    pathex=[str(_root)],
    binaries=[],
    datas=[
        # The tracked canonical icon source is capitalized; keep the bundled destination lowercase for app.py compatibility.
        (str(_root / 'Assets' / 'icons'), 'assets/icons'),
        (str(_root / 'AssetsManager' / 'i18n' / 'en.json'), 'AssetsManager/i18n'),
        (str(_root / 'AssetsManager' / 'i18n' / 'zh.json'), 'AssetsManager/i18n'),
        (str(_root / 'AssetsManager' / 'i18n' / 'ja.json'), 'AssetsManager/i18n'),
        # Theme JSON files
        (str(_root / 'Assets' / 'Themes'), 'Assets/Themes'),
        # Web UI SPA build served by the LAN server
        (str(_root / 'webui' / 'dist'), 'webui/dist'),
        # Plugin addons
        (str(_root / 'Plugins'), 'Plugins'),
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
        'PySide6.QtSvg',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
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
        'asyncio',
        'ssl',
        # LAN module — full enumeration. LAN modules import each other
        # lazily inside handler bodies; the explicit list keeps the bundle
        # correct even when PyInstaller's static graph misses such imports.
        'AssetsManager.lan',
        'AssetsManager.lan.api',
        'AssetsManager.lan.auth',
        'AssetsManager.lan.authorization',
        'AssetsManager.lan.dto',
        'AssetsManager.lan.guarded_tunnel',
        'AssetsManager.lan.manager',
        'AssetsManager.lan.path_guard',
        'AssetsManager.lan.ports',
        'AssetsManager.lan.principal',
        'AssetsManager.lan.route_policy',
        'AssetsManager.lan.runtime_validation',
        'AssetsManager.lan.safe_open',
        'AssetsManager.lan.scanner',
        'AssetsManager.lan.security',
        'AssetsManager.lan.server',
        'AssetsManager.lan.token_revocations',
        'AssetsManager.lan.tunnel',
        'AssetsManager.lan.tunnel_identity',
        'AssetsManager.lan.utils',
        'AssetsManager.lan.ws',
        'AssetsManager.lan.routes',
        'AssetsManager.lan.routes._errors',
        'AssetsManager.lan.routes._helpers',
        'AssetsManager.lan.routes._resource_urls',
        'AssetsManager.lan.routes.auth',
        'AssetsManager.lan.routes.downloads',
        'AssetsManager.lan.routes.favorites',
        'AssetsManager.lan.routes.files',
        'AssetsManager.lan.routes.gallery',
        'AssetsManager.lan.routes.image',
        'AssetsManager.lan.routes.metadata',
        'AssetsManager.lan.routes.pages',
        'AssetsManager.lan.routes.quicksearch',
        'AssetsManager.lan.routes.quota',
        'AssetsManager.lan.routes.shares',
        'AssetsManager.lan.routes.system',
        'AssetsManager.lan.routes.tags',
        'AssetsManager.lan.routes.thumbnails',
        'AssetsManager.lan.routes.users',
        'AssetsManager.lan.routes.websocket',
        # Application services — full enumeration
        'AssetsManager.application',
        'AssetsManager.application.app_settings_provider',
        'AssetsManager.application.asset_filters',
        'AssetsManager.application.asset_index_reconciliation_service',
        'AssetsManager.application.asset_index_service',
        'AssetsManager.application.asset_service',
        'AssetsManager.application.auth_service',
        'AssetsManager.application.bootstrap',
        'AssetsManager.application.context',
        'AssetsManager.application.database_integrity_service',
        'AssetsManager.application.database_maintenance_service',
        'AssetsManager.application.desktop_ports',
        'AssetsManager.application.favorite_service',
        'AssetsManager.application.file_operation_service',
        'AssetsManager.application.filesystem_projection_repair_service',
        'AssetsManager.application.free_download_quota_service',
        'AssetsManager.application.gallery',
        'AssetsManager.application.gallery._incremental',
        'AssetsManager.application.gallery._persistence',
        'AssetsManager.application.gallery._projection_builder',
        'AssetsManager.application.gallery._types',
        'AssetsManager.application.gallery_service',
        'AssetsManager.application.import_manifest_store',
        'AssetsManager.application.import_service',
        'AssetsManager.application.library_export_io',
        'AssetsManager.application.library_export_service',
        'AssetsManager.application.library_export_service_export',
        'AssetsManager.application.library_export_service_restore',
        'AssetsManager.application.library_export_service_types',
        'AssetsManager.application.library_export_service_validate',
        'AssetsManager.application.library_service',
        'AssetsManager.application.library_settings_adapter',
        'AssetsManager.application.library_watcher_service',
        'AssetsManager.application.metadata_service',
        'AssetsManager.application.plugin_service',
        'AssetsManager.application.project_service',
        'AssetsManager.application.reconciliation_queue',
        'AssetsManager.application.reconciliation_queue_migration',
        'AssetsManager.application.reconciliation_queue_store',
        'AssetsManager.application.runtime',
        'AssetsManager.application.runtime_events',
        'AssetsManager.application.search_service',
        'AssetsManager.application.security_preflight',
        'AssetsManager.application.share_service',
        'AssetsManager.application.tag_canonicalizer',
        'AssetsManager.application.tag_service',
        'AssetsManager.application.thumbnail_cache_lifecycle',
        'AssetsManager.application.thumbnail_service',
        'AssetsManager.application.undo_service',
        # Domain layer
        'AssetsManager.domain',
        'AssetsManager.domain.errors',
        'AssetsManager.domain.library',
        'AssetsManager.domain.asset',
        'AssetsManager.domain.auth',
        'AssetsManager.domain.share',
        'AssetsManager.domain.events',
        'AssetsManager.domain.event_bus',
        # Dependency injection
        'AssetsManager.di',
        # Repositories — full enumeration
        'AssetsManager.repositories',
        'AssetsManager.repositories.asset_index_repository',
        'AssetsManager.repositories.auth_repository',
        'AssetsManager.repositories.favorite_repository',
        'AssetsManager.repositories.free_download_quota_repository',
        'AssetsManager.repositories.gallery_home_repository',
        'AssetsManager.repositories.metadata_repository',
        'AssetsManager.repositories.plugin_metadata_repository',
        'AssetsManager.repositories.revoked_token_repository',
        'AssetsManager.repositories.share_repository',
        'AssetsManager.repositories.tag_repository',
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
        'pip', 'pkg_resources',
        'matplotlib', 'pandas',
        # Qt modules not used by this app
        'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtPdf',
        'PySide6.Qt3D', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
        'PySide6.QtMultimedia', 'PySide6.QtSvgWidgets',
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

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
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
    icon=str(_root / 'Assets' / 'icons' / 'icon.ico'),
    version=_version_info,
)
