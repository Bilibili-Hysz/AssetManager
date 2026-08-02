"""Application services for AssetManager Next.

This package is the migration boundary between presentation code and the
existing core/infrastructure modules. New features should prefer application
services over direct UI-to-database wiring.
"""

from AssetsManager.application.context import LibrarySession
from AssetsManager.application.asset_filters import (
    FILTER_CATEGORY_EXTS,
    FILTER_CATEGORY_LABELS,
    FILTER_CATEGORIES,
    IMAGE_EXTS,
    extension_matches_category,
    find_first_image,
    is_hidden,
    matches_search,
    natural_key,
    normalize_filter_category,
    normalize_sort_key,
    sort_key_for_entry,
)
from AssetsManager.domain.asset import category_for_extension
from AssetsManager.application.asset_index_service import AssetIndexEntry, AssetIndexService
from AssetsManager.application.asset_service import AssetService, DirectoryListOptions
from AssetsManager.application.auth_service import AuthService
from AssetsManager.application.file_operation_service import FileOperationResult, FileOperationService
from AssetsManager.application.library_service import LibraryService
from AssetsManager.application.metadata_service import AssetMetadata, MetadataService
from AssetsManager.application.plugin_service import PluginService
from AssetsManager.application.project_service import ProjectDepthConfig, ProjectDetail, ProjectHome, ProjectListing, ProjectService, ProjectTree
from AssetsManager.application.search_service import SearchResult, SearchService
from AssetsManager.application.share_service import ShareService
from AssetsManager.application.tag_service import TagService
from AssetsManager.application.thumbnail_service import ThumbnailResult, ThumbnailService, clear_thumbnail_cache_keys, thumbnail_cache_key
from AssetsManager.application.undo_service import UndoEntry, UndoService
from AssetsManager.application.bootstrap import ApplicationBootstrap, LanRuntimeServices, LibraryScopedServices
from AssetsManager.application.runtime import LibraryRuntime

__all__ = [
    "FILTER_CATEGORY_EXTS",
    "FILTER_CATEGORY_LABELS",
    "FILTER_CATEGORIES",
    "IMAGE_EXTS",
    "AssetIndexEntry",
    "AssetIndexService",
    "AssetService",
    "AssetMetadata",
    "ApplicationBootstrap",
    "AuthService",
    "DirectoryListOptions",
    "FileOperationResult",
    "FileOperationService",
    "LibraryScopedServices",
    "LibraryService",
    "LibraryRuntime",
    "LibrarySession",
    "LanRuntimeServices",
    "MetadataService",
    "PluginService",
    "ProjectDepthConfig",
    "ProjectDetail",
    "ProjectHome",
    "ProjectListing",
    "ProjectService",
    "ProjectTree",
    "SearchResult",
    "SearchService",
    "ShareService",
    "TagService",
    "ThumbnailResult",
    "ThumbnailService",
    "UndoEntry",
    "UndoService",
    "clear_thumbnail_cache_keys",
    "category_for_extension",
    "extension_matches_category",
    "find_first_image",
    "is_hidden",
    "matches_search",
    "natural_key",
    "normalize_filter_category",
    "normalize_sort_key",
    "sort_key_for_entry",
    "thumbnail_cache_key",
]
