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
from AssetsManager.application.asset_index_service import (
    AssetIndexEntry,
    AssetIndexPublishResult,
    AssetIndexPublishStatus,
    AssetIndexService,
)
from AssetsManager.application.asset_index_reconciliation_service import (
    AssetIndexReconciliationService,
    ReconciliationAttemptResult,
    ReconciliationWorkerStopTimeout,
)
from AssetsManager.application.asset_service import AssetService, DirectoryListOptions
from AssetsManager.application.auth_service import AuthService
from AssetsManager.application.database_integrity_service import DatabaseIntegrityService, IntegrityCheckReport
from AssetsManager.application.database_maintenance_service import (
    DatabaseMaintenanceService,
    DatabaseSizeResult,
    VacuumResult,
    WalCheckpointResult,
)
from AssetsManager.application.file_operation_service import (
    FileOperationResult,
    FileOperationService,
    FileOperationWarning,
)
from AssetsManager.application.reconciliation_queue_store import (
    SQLiteReconciliationQueueStore,
)
from AssetsManager.application.reconciliation_queue_migration import (
    ReconciliationMarkerMigrationError,
    ReconciliationMarkerMigrationResult,
    ReconciliationMarkerMigrationStatus,
    migrate_reconciliation_marker,
)
from AssetsManager.application.reconciliation_queue import (
    ReconciliationKind,
    ReconciliationQueue,
    ReconciliationQueueFull,
    ReconciliationQueueClaimResult,
    ReconciliationQueuePersistenceConflict,
    ReconciliationQueuePersistenceError,
    ReconciliationQueueRecoveryResult,
    ReconciliationQueueSnapshot,
    ReconciliationQueueStore,
    ReconciliationState,
    ReconciliationTask,
    reconciliation_backoff,
)
from AssetsManager.application.favorite_service import FavoriteService, MAX_FAVORITES_PER_OWNER
from AssetsManager.application.gallery_service import (
    GalleryCollection,
    GalleryHome,
    GalleryResolve,
    GalleryService,
    GalleryTraversalLimitError,
    GalleryTraversalLimits,
)
from AssetsManager.application.library_export_service import (
    BackupValidationResult,
    LibraryBackupResult,
    LibraryExportResult,
    LibraryExportService,
    LibraryRestoreResult,
    RestoreQuarantineEntry,
)
from AssetsManager.application.library_settings_adapter import (
    LibrarySettingsAdapter,
    LibrarySettingsBlockedError,
    LibrarySettingsViewModel,
)
from AssetsManager.application.library_service import LibraryService
from AssetsManager.application.metadata_service import AssetMetadata, MetadataService
from AssetsManager.application.plugin_service import PluginService
from AssetsManager.application.project_service import ProjectDepthConfig, ProjectDetail, ProjectHome, ProjectListing, ProjectService, ProjectTree
from AssetsManager.application.search_service import SearchResult, SearchService
from AssetsManager.application.share_service import ShareService
from AssetsManager.application.security_preflight import (
    CURRENT_SHARE_SAFETY_ACK_VERSION,
    SecurityPreflight,
    SecuritySnapshot,
    ShareState,
    TunnelState,
    bind_scope_expanded,
    confirmation_failure_reason,
    effective_auth,
    is_lan_bind,
    normalized_ack_version,
    preflight_snapshot,
    settings_security_values,
)
from AssetsManager.application.tag_service import TagService
from AssetsManager.application.thumbnail_service import ThumbnailResult, ThumbnailService, clear_thumbnail_cache_keys, thumbnail_cache_key
from AssetsManager.application.undo_service import UndoEntry, UndoService
from AssetsManager.application.bootstrap import ApplicationBootstrap, LanRuntimeServices, LibraryScopedServices, RuntimeSharingServices
from AssetsManager.application.runtime import LibraryRuntime

__all__ = [
    "FILTER_CATEGORY_EXTS",
    "FILTER_CATEGORY_LABELS",
    "FILTER_CATEGORIES",
    "IMAGE_EXTS",
    "AssetIndexEntry",
    "AssetIndexPublishResult",
    "AssetIndexPublishStatus",
    "AssetIndexService",
    "AssetIndexReconciliationService",
    "ReconciliationAttemptResult",
    "ReconciliationWorkerStopTimeout",
    "SQLiteReconciliationQueueStore",
    "ReconciliationMarkerMigrationError",
    "ReconciliationMarkerMigrationResult",
    "ReconciliationMarkerMigrationStatus",
    "migrate_reconciliation_marker",
    "AssetService",
    "AssetMetadata",
    "ApplicationBootstrap",
    "AuthService",
    "DatabaseIntegrityService",
    "DatabaseMaintenanceService",
    "DatabaseSizeResult",
    "DirectoryListOptions",
    "FileOperationResult",
    "FileOperationService",
    "FileOperationWarning",
    "ReconciliationKind",
    "ReconciliationQueue",
    "ReconciliationQueueFull",
    "ReconciliationQueueClaimResult",
    "ReconciliationQueueRecoveryResult",
    "ReconciliationQueuePersistenceConflict",
    "ReconciliationQueuePersistenceError",
    "ReconciliationQueueSnapshot",
    "ReconciliationQueueStore",
    "ReconciliationState",
    "ReconciliationTask",
    "reconciliation_backoff",
    "FavoriteService",
    "MAX_FAVORITES_PER_OWNER",
    "GalleryCollection",
    "GalleryHome",
    "GalleryResolve",
    "GalleryService",
    "GalleryTraversalLimitError",
    "GalleryTraversalLimits",
    "LibraryScopedServices",
    "LibraryService",
    "LibrarySettingsAdapter",
    "LibrarySettingsBlockedError",
    "LibrarySettingsViewModel",
    "LibraryRuntime",
    "LibrarySession",
    "LanRuntimeServices",
    "RuntimeSharingServices",
    "IntegrityCheckReport",
    "BackupValidationResult",
    "LibraryBackupResult",
    "LibraryExportResult",
    "LibraryExportService",
    "LibraryRestoreResult",
    "RestoreQuarantineEntry",
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
    "CURRENT_SHARE_SAFETY_ACK_VERSION",
    "SecurityPreflight",
    "SecuritySnapshot",
    "ShareState",
    "TunnelState",
    "bind_scope_expanded",
    "confirmation_failure_reason",
    "effective_auth",
    "is_lan_bind",
    "normalized_ack_version",
    "preflight_snapshot",
    "settings_security_values",
    "TagService",
    "ThumbnailResult",
    "ThumbnailService",
    "UndoEntry",
    "UndoService",
    "VacuumResult",
    "WalCheckpointResult",
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
