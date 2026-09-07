# 当前代码架构图源与索引

[架构图册正文](../../architecture-code-atlas-2026-09-06.md) · [浏览图册](index.html) · [机器可读索引](source-inventory.json)

源码基准：`6c70153b642f9d7a139937ae5d73da94325eebd8` 加捕获时工作区。统计：460 个生产源码/配置文件，72 个显式 HTTP 注册项，14 张图。

本清单排除生产目录内的 `.test.` / `.spec.` 文件，不包含用户资产或运行数据库。顶层符号和 import 由 Python AST 提取；前端列出源文件，不推断 TypeScript 调用图。

## 图源

| 图 | Mermaid | SVG |
|---|---|---|
| 01 系统总览 | [01.mmd](01.mmd) | [01.svg](01.svg) |
| 02 服务装配与所有权 | [02.mmd](02.mmd) | [02.svg](02.svg) |
| 03 资产库生命周期 | [03.mmd](03.mmd) | [03.svg](03.svg) |
| 04 桌面结构 | [04.mmd](04.mmd) | [04.svg](04.svg) |
| 05 应用服务与数据依赖 | [05.mmd](05.mmd) | [05.svg](05.svg) |
| 06 存储结构与一致性 | [06.mmd](06.mmd) | [06.svg](06.svg) |
| 07 写入与实时同步 | [07.mmd](07.mmd) | [07.svg](07.svg) |
| 08 WebUI 结构 | [08.mmd](08.mmd) | [08.svg](08.svg) |
| 09 LAN 请求、安全与传输边界 | [09.mmd](09.mmd) | [09.svg](09.svg) |
| 10 媒体、缩略图与缓存 | [10.mmd](10.mmd) | [10.svg](10.svg) |
| 11 下载、ZIP 资源与清理 | [11.mmd](11.mmd) | [11.svg](11.svg) |
| 12 文件操作、导入与后台恢复 | [12.mmd](12.mmd) | [12.svg](12.svg) |
| 13 插件、命令、AI 与外观 | [13.mmd](13.mmd) | [13.svg](13.svg) |
| 14 工程验证与构建 | [14.mmd](14.mmd) | [14.svg](14.svg) |

## HTTP 显式注册项

策略列是 `_add` 调用参数，不包含后续覆盖，例如 `/api/files` 的 GET 策略另被 `declare` 设为 browse。aiohttp 自动 HEAD 和静态资源另由框架注册。

| 方法 | 路径 | Handler | 声明策略 | 源码行 |
|---|---|---|---|---|
| GET | `/` | `handle_index` | `_PUBLIC` | [L209](../../../AssetsManager/lan/api.py#L209) |
| GET | `/browse` | `handle_browse_page` | `_PUBLIC` | [L210](../../../AssetsManager/lan/api.py#L210) |
| GET | `/detail` | `handle_detail_page` | `_PUBLIC` | [L211](../../../AssetsManager/lan/api.py#L211) |
| GET | `/login` | `handle_login_page` | `_PUBLIC` | [L212](../../../AssetsManager/lan/api.py#L212) |
| GET | `/gallery` | `handle_gallery_page` | `_PUBLIC` | [L216](../../../AssetsManager/lan/api.py#L216) |
| GET | `/gallery/collection` | `handle_gallery_collection_page` | `_PUBLIC` | [L217](../../../AssetsManager/lan/api.py#L217) |
| GET | `/gallery/favorites` | `handle_gallery_favorites_page` | `_PUBLIC` | [L218](../../../AssetsManager/lan/api.py#L218) |
| GET | `/api/gallery/home` | `handle_gallery_home` | `_BROWSE_RATE` | [L222](../../../AssetsManager/lan/api.py#L222) |
| GET | `/api/gallery/collection` | `handle_gallery_collection` | `_BROWSE_RATE` | [L223](../../../AssetsManager/lan/api.py#L223) |
| GET | `/api/gallery/resolve` | `handle_gallery_resolve` | `_BROWSE_RATE` | [L224](../../../AssetsManager/lan/api.py#L224) |
| GET | `/api/image` | `handle_image` | `_SKIP` | [L225](../../../AssetsManager/lan/api.py#L225) |
| GET | `/api/favorites` | `handle_favorites` | `_BROWSE_RATE` | [L226](../../../AssetsManager/lan/api.py#L226) |
| POST | `/api/favorites` | `handle_add_favorite` | `_BROWSE_WRITE` | [L227](../../../AssetsManager/lan/api.py#L227) |
| POST | `/api/favorites/remove` | `handle_remove_favorite` | `_BROWSE_WRITE` | [L228](../../../AssetsManager/lan/api.py#L228) |
| DELETE | `/api/favorites` | `handle_remove_favorite` | `_BROWSE_WRITE` | [L229](../../../AssetsManager/lan/api.py#L229) |
| GET | `/api/files` | `handle_files` | `_DEFAULT` | [L232](../../../AssetsManager/lan/api.py#L232) |
| POST | `/api/files/summaries` | `handle_directory_summaries` | `_BROWSE_WRITE` | [L234](../../../AssetsManager/lan/api.py#L234) |
| GET | `/api/thumbnails/{path:.*}` | `handle_thumbnail` | `_SKIP` | [L235](../../../AssetsManager/lan/api.py#L235) |
| POST | `/api/thumbnails/batch` | `handle_thumbnail_batch` | `_PREVIEW_WRITE_SKIP` | [L236](../../../AssetsManager/lan/api.py#L236) |
| GET | `/api/download/{path:.*}` | `handle_download` | `_DEFAULT` | [L237](../../../AssetsManager/lan/api.py#L237) |
| POST | `/api/download/batch` | `handle_batch_download` | `_DOWNLOAD_WRITE` | [L238](../../../AssetsManager/lan/api.py#L238) |
| GET | `/api/projects` | `handle_projects` | `_BROWSE_RATE` | [L239](../../../AssetsManager/lan/api.py#L239) |
| GET | `/api/projects/{path:.*}` | `handle_project_detail` | `_DEFAULT` | [L240](../../../AssetsManager/lan/api.py#L240) |
| GET | `/api/tree` | `handle_tree` | `_BROWSE_RATE` | [L241](../../../AssetsManager/lan/api.py#L241) |
| GET | `/api/home` | `handle_home` | `_BROWSE_RATE` | [L242](../../../AssetsManager/lan/api.py#L242) |
| GET | `/api/tags` | `handle_tags` | `_BROWSE_RATE` | [L243](../../../AssetsManager/lan/api.py#L243) |
| POST | `/api/tags` | `handle_create_tag` | `_WRITE_TAG_BROWSE` | [L244](../../../AssetsManager/lan/api.py#L244) |
| PUT | `/api/tags/{name}` | `handle_rename_tag` | `_ADMIN_TAG` | [L245](../../../AssetsManager/lan/api.py#L245) |
| DELETE | `/api/tags/{name}` | `handle_delete_tag` | `_ADMIN_TAG` | [L246](../../../AssetsManager/lan/api.py#L246) |
| POST | `/api/tags/remove` | `handle_remove_tag` | `_ADMIN_TAG` | [L247](../../../AssetsManager/lan/api.py#L247) |
| POST | `/mcp` | `handle_mcp_post` | `RoutePolicy(auth='public', capabilities=_BROWSE)` | [L255](../../../AssetsManager/lan/api.py#L255) |
| GET | `/api/collections` | `handle_collections` | `RoutePolicy(capabilities=_BROWSE)` | [L257](../../../AssetsManager/lan/api.py#L257) |
| POST | `/api/collections` | `handle_create_collection` | `RoutePolicy(capabilities=_WRITE_TAGS)` | [L258](../../../AssetsManager/lan/api.py#L258) |
| PATCH | `/api/collections/{id}` | `handle_update_collection` | `RoutePolicy(capabilities=_WRITE_TAGS)` | [L259](../../../AssetsManager/lan/api.py#L259) |
| DELETE | `/api/collections/{id}` | `handle_delete_collection` | `RoutePolicy(capabilities=_WRITE_TAGS)` | [L260](../../../AssetsManager/lan/api.py#L260) |
| GET | `/api/collections/{id}/members` | `handle_collection_members` | `RoutePolicy(capabilities=_BROWSE)` | [L261](../../../AssetsManager/lan/api.py#L261) |
| POST | `/api/collections/{id}/members` | `handle_add_collection_members` | `RoutePolicy(capabilities=_WRITE_TAGS)` | [L262](../../../AssetsManager/lan/api.py#L262) |
| DELETE | `/api/collections/{id}/members` | `handle_remove_collection_members` | `RoutePolicy(capabilities=_WRITE_TAGS)` | [L263](../../../AssetsManager/lan/api.py#L263) |
| GET | `/api/collections/{id}/evaluate` | `handle_collection_evaluate` | `RoutePolicy(capabilities=_BROWSE)` | [L264](../../../AssetsManager/lan/api.py#L264) |
| GET | `/api/search` | `handle_search` | `_BROWSE_RATE` | [L265](../../../AssetsManager/lan/api.py#L265) |
| GET | `/api/quicksearch` | `handle_quicksearch` | `_BROWSE_RATE` | [L266](../../../AssetsManager/lan/api.py#L266) |
| GET | `/api/meta/{path:.*}` | `handle_meta` | `_DEFAULT` | [L267](../../../AssetsManager/lan/api.py#L267) |
| GET | `/api/sequence/neighbors` | `handle_sequence_neighbors` | `RoutePolicy(capabilities=_BROWSE)` | [L271](../../../AssetsManager/lan/api.py#L271) |
| PUT | `/api/notes/{path:.*}` | `handle_save_notes` | `_WRITE_NOTES_BROWSE` | [L273](../../../AssetsManager/lan/api.py#L273) |
| PUT | `/api/rating/{path:.*}` | `handle_save_rating` | `_WRITE_NOTES_BROWSE` | [L274](../../../AssetsManager/lan/api.py#L274) |
| GET | `/api/info` | `handle_info` | `_OPTIONAL_BROWSE` | [L275](../../../AssetsManager/lan/api.py#L275) |
| GET | `/api/revision` | `handle_revision` | `_SKIP` | [L276](../../../AssetsManager/lan/api.py#L276) |
| POST | `/api/auth/login` | `handle_login` | `_PUBLIC_AUTH_STRICT_CAP` | [L277](../../../AssetsManager/lan/api.py#L277) |
| POST | `/api/auth/register` | `handle_register` | `_PUBLIC_AUTH_STRICT_CAP` | [L278](../../../AssetsManager/lan/api.py#L278) |
| POST | `/api/auth/verify_key` | `handle_verify_key` | `_PUBLIC_AUTH_STRICT_CAP` | [L279](../../../AssetsManager/lan/api.py#L279) |
| POST | `/api/auth/logout` | `handle_logout` | `_AUTH_BOOTSTRAP` | [L280](../../../AssetsManager/lan/api.py#L280) |
| GET | `/api/auth/me` | `handle_me` | `_DEFAULT` | [L281](../../../AssetsManager/lan/api.py#L281) |
| GET | `/api/users` | `handle_users` | `_ADMIN_USER` | [L282](../../../AssetsManager/lan/api.py#L282) |
| POST | `/api/users/{id}/toggle` | `handle_toggle_user` | `_ADMIN_USER` | [L283](../../../AssetsManager/lan/api.py#L283) |
| PATCH | `/api/users/{username}` | `handle_update_user` | `_ADMIN_USER` | [L284](../../../AssetsManager/lan/api.py#L284) |
| GET | `/api/invites` | `handle_invites` | `_ADMIN_USER` | [L285](../../../AssetsManager/lan/api.py#L285) |
| POST | `/api/invites` | `handle_create_invite` | `_ADMIN_USER` | [L286](../../../AssetsManager/lan/api.py#L286) |
| POST | `/api/invites/{code}/revoke` | `handle_revoke_invite` | `_ADMIN_USER` | [L287](../../../AssetsManager/lan/api.py#L287) |
| GET | `/api/activity` | `handle_activity` | `_ADMIN_USER_BROWSE` | [L288](../../../AssetsManager/lan/api.py#L288) |
| GET | `/api/online-users` | `handle_online_users` | `_ADMIN_USER` | [L289](../../../AssetsManager/lan/api.py#L289) |
| GET | `/api/tunnel/status` | `handle_tunnel_status` | `_SETTINGS_BROWSE` | [L290](../../../AssetsManager/lan/api.py#L290) |
| GET | `/api/stats` | `handle_stats` | `RoutePolicy(rate_limit='skip', capabilities=_SETTINGS)` | [L291](../../../AssetsManager/lan/api.py#L291) |
| POST | `/api/shares` | `handle_create_share` | `_LINK_WRITE` | [L292](../../../AssetsManager/lan/api.py#L292) |
| GET | `/api/shares` | `handle_list_shares` | `_DEFAULT` | [L293](../../../AssetsManager/lan/api.py#L293) |
| DELETE | `/api/shares/{id}` | `handle_delete_share` | `_LINK_WRITE` | [L294](../../../AssetsManager/lan/api.py#L294) |
| GET | `/s/{id}` | `handle_share_page` | `_PUBLIC` | [L295](../../../AssetsManager/lan/api.py#L295) |
| POST | `/api/shares/{id}/verify` | `handle_verify_share_password` | `_AUTH_STRICT` | [L298](../../../AssetsManager/lan/api.py#L298) |
| GET | `/api/shares/{id}/download/{path:.*}` | `handle_share_download` | `_DEFAULT` | [L300](../../../AssetsManager/lan/api.py#L300) |
| GET | `/api/shares/{id}/preview/{path:.*}` | `handle_share_preview` | `_DEFAULT` | [L302](../../../AssetsManager/lan/api.py#L302) |
| GET | `/api/shares/{id}/info` | `handle_share_info` | `_DEFAULT` | [L304](../../../AssetsManager/lan/api.py#L304) |
| GET | `/api/quota` | `handle_free_quota` | `_PUBLIC_BROWSE` | [L306](../../../AssetsManager/lan/api.py#L306) |
| GET | `/ws` | `handle_websocket` | `_SKIP` | [L307](../../../AssetsManager/lan/api.py#L307) |

## 生产模块清单

| 文件 | 顶层类与函数 |
|---|---|
| [.github/workflows/ci.yml](../../../.github/workflows/ci.yml) | 配置 / 前端 / 模块声明 |
| [.github/workflows/nightly-perf.yml](../../../.github/workflows/nightly-perf.yml) | 配置 / 前端 / 模块声明 |
| [.github/workflows/release.yml](../../../.github/workflows/release.yml) | 配置 / 前端 / 模块声明 |
| [AssetManager.spec](../../../AssetManager.spec) | 配置 / 前端 / 模块声明 |
| [AssetsManager/__init__.py](../../../AssetsManager/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/app.py](../../../AssetsManager/app.py) | `_bind_single_instance`, `build_crash_report_dialog`, `launch_github_crash_report`, `show_crash_report_dialog`, `main` |
| [AssetsManager/application/__init__.py](../../../AssetsManager/application/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/application/activity_recorder.py](../../../AssetsManager/application/activity_recorder.py) | `summarize_targets`, `ActivityRecorder` |
| [AssetsManager/application/ai_tagging/__init__.py](../../../AssetsManager/application/ai_tagging/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/application/ai_tagging/ollama_client.py](../../../AssetsManager/application/ai_tagging/ollama_client.py) | `AiTaggingErrorKind`, `AiTaggingError`, `AiTaggingResult`, `_native_base`, `_native_models_url`, `_chat_completions_url`, `probe`, `build_tagging_prompt`, `_flatten_to_rgb`, `_load_image`, `_image_to_data_url`, `_raise_for_status`, `_post_chat`, `analyze_image`, `_extract_content`, `_strip_code_fences`, `_extract_json_object`, `_parse_tagging_payload` |
| [AssetsManager/application/ai_tagging/service.py](../../../AssetsManager/application/ai_tagging/service.py) | `AiTaggingOutcome`, `tag_paths` |
| [AssetsManager/application/ai_tagging/write_policy.py](../../../AssetsManager/application/ai_tagging/write_policy.py) | `_matches_existing`, `_is_valid_new_tag`, `converge_tags` |
| [AssetsManager/application/app_settings_provider.py](../../../AssetsManager/application/app_settings_provider.py) | `install_app_settings_provider`, `get_app_settings` |
| [AssetsManager/application/asset_filters.py](../../../AssetsManager/application/asset_filters.py) | `CategoryRegistrySubscription`, `subscribe_category_registry_changed`, `_publish_category_registry_changed`, `CategoryLabelRegistry`, `CategoryExtensionRegistry`, `natural_key`, `category_registry_snapshot`, `category_labels`, `normalize_sort_key`, `normalize_filter_category`, `extension_matches_category`, `find_first_image`, `is_hidden`, `matches_search`, `matches_exclude`, `filters_accept`, `matches_structured`, `sort_key_for_entry` |
| [AssetsManager/application/asset_index_reconciliation_service.py](../../../AssetsManager/application/asset_index_reconciliation_service.py) | `ReconciliationWorkerStopTimeout`, `_SweeperStopEvent`, `ReconciliationAttemptResult`, `AssetIndexReconciliationService` |
| [AssetsManager/application/asset_index_service.py](../../../AssetsManager/application/asset_index_service.py) | `_refresh_lock_for`, `AssetIndexPublishStatus`, `AssetIndexPublishResult`, `_is_busy_error`, `_busy_retry_delay`, `_is_link_or_reparse`, `AssetIndexService` |
| [AssetsManager/application/asset_service.py](../../../AssetsManager/application/asset_service.py) | `DirectoryListOptions`, `AssetListItem`, `DirectoryListing`, `AssetService`, `_scan_dir_summary`, `_record_summary_performance` |
| [AssetsManager/application/auth_service.py](../../../AssetsManager/application/auth_service.py) | `AuthService` |
| [AssetsManager/application/bootstrap.py](../../../AssetsManager/application/bootstrap.py) | `RuntimeSharingServices`, `LanRuntimeServices`, `_LanServicesHolder`, `LibraryScopedServices`, `ApplicationBootstrap` |
| [AssetsManager/application/collection_service.py](../../../AssetsManager/application/collection_service.py) | `_validated_collection_name`, `_validated_query`, `_resolve_connection`, `_get_repo`, `CollectionService` |
| [AssetsManager/application/command_executions.py](../../../AssetsManager/application/command_executions.py) | `plan_hash`, `target_identity`, `CommandExecutionStore` |
| [AssetsManager/application/command_registry.py](../../../AssetsManager/application/command_registry.py) | `CommandResult`, `CommandDescriptor`, `_result_from_operation`, `build_command_registry`, `CommandRegistry` |
| [AssetsManager/application/context.py](../../../AssetsManager/application/context.py) | `_SessionLiveness`, `session_operation`, `LibraryContext`, `LibrarySession` |
| [AssetsManager/application/database_integrity_service.py](../../../AssetsManager/application/database_integrity_service.py) | `_IntegrityCheckCancelled`, `_QuickCheckBusy`, `_is_busy_error`, `PathExistence`, `IntegrityCheckReport`, `DatabaseIntegrityService` |
| [AssetsManager/application/database_maintenance_service.py](../../../AssetsManager/application/database_maintenance_service.py) | `DatabaseSizeResult`, `WalCheckpointResult`, `VacuumResult`, `MaintenanceFailureResult`, `DatabaseMaintenanceService` |
| [AssetsManager/application/desktop_ports.py](../../../AssetsManager/application/desktop_ports.py) | `TagsViewPort`, `ShareSettingsPort`, `LanControlPort`, `LanServerFactory`, `FallbackShareSettingsPort`, `MetadataViewPort`, `FileOpsViewPort`, `ScopedServicesConsumer`, `RootBoundTagService` |
| [AssetsManager/application/favorite_service.py](../../../AssetsManager/application/favorite_service.py) | `FavoriteService` |
| [AssetsManager/application/file_operation_service.py](../../../AssetsManager/application/file_operation_service.py) | `FileOperationWarning`, `FileOperationResult`, `RestoreResult`, `_assert_under_root`, `_windows_name_error`, `error_category`, `acquire_path_locks`, `_measure_command`, `FileOperationService`, `unique_destination`, `_try_reserve` |
| [AssetsManager/application/filesystem_projection_repair_service.py](../../../AssetsManager/application/filesystem_projection_repair_service.py) | `FilesystemProjectionRepairTerminalError`, `FilesystemProjectionRepairService` |
| [AssetsManager/application/free_download_quota_service.py](../../../AssetsManager/application/free_download_quota_service.py) | `FreeDownloadQuotaConfig`, `FreeDownloadQuotaService` |
| [AssetsManager/application/gallery/__init__.py](../../../AssetsManager/application/gallery/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/application/gallery/_incremental.py](../../../AssetsManager/application/gallery/_incremental.py) | `_GalleryIncrementalMixin` |
| [AssetsManager/application/gallery/_persistence.py](../../../AssetsManager/application/gallery/_persistence.py) | `_GalleryPersistenceMixin` |
| [AssetsManager/application/gallery/_projection_builder.py](../../../AssetsManager/application/gallery/_projection_builder.py) | `_GalleryProjectionMixin` |
| [AssetsManager/application/gallery/_types.py](../../../AssetsManager/application/gallery/_types.py) | `GalleryTraversalLimits`, `GalleryTraversalLimitError`, `_IncrementalFallback`, `_TraversalBudget`, `GalleryImage`, `GalleryHome`, `GalleryCollection`, `GalleryResolve`, `_ImageRef`, `_QueuedChange`, `_StateNode`, `_HomeState`, `_strip_legacy_url_fields` |
| [AssetsManager/application/gallery_service.py](../../../AssetsManager/application/gallery_service.py) | `GalleryService` |
| [AssetsManager/application/import_manifest_store.py](../../../AssetsManager/application/import_manifest_store.py) | `_canonical`, `_validate_payload_header`, `_validate_item`, `_encode_payload`, `_record_generation`, `_recovery_retired_task_ids`, `_validate_payload`, `_canonical_item_bytes`, `_stream_item_storage_bytes`, `_decode_stream_item_row`, `_stream_header`, `_payload_requires_stream`, `ImportManifestStore`, `ImportManifestRecoveryService` |
| [AssetsManager/application/import_service.py](../../../AssetsManager/application/import_service.py) | `ImportBudget`, `ImportBudgetExceeded`, `_BudgetReader`, `_reject_link_or_reparse_ancestors`, `ImportCancelled`, `ImportResult`, `RecoveryEnqueueOutcome`, `ImportService` |
| [AssetsManager/application/library_export_io.py](../../../AssetsManager/application/library_export_io.py) | `_BackupCancelledError`, `preflight_archive_path`, `archive_structure_preflight`, `archive_structure_errors`, `inspect_archive_member`, `read_archive_member`, `is_link_or_junction`, `assert_real_contained`, `assert_real_staging_tree`, `configure_quick_check_connection`, `quick_check_database_file`, `safe_restore_quarantine_root`, `restore_quarantine_path`, `restore_intent_path`, `write_restore_intent`, `read_restore_intent`, `clear_restore_intent`, `quarantine_restore_intent_marker`, `quarantined_restore_intent_marker`, `compression_type_for_bytes`, `validate_backup_destination`, `is_safe_backup_path`, `windows_component_key`, `windows_path_key`, `valid_file_digest`, `utc_timestamp`, `portable_path` |
| [AssetsManager/application/library_export_service.py](../../../AssetsManager/application/library_export_service.py) | `LibraryExportService` |
| [AssetsManager/application/library_export_service_export.py](../../../AssetsManager/application/library_export_service_export.py) | `ExportMixin` |
| [AssetsManager/application/library_export_service_restore.py](../../../AssetsManager/application/library_export_service_restore.py) | `RestoreMixin` |
| [AssetsManager/application/library_export_service_types.py](../../../AssetsManager/application/library_export_service_types.py) | `LibraryExportResult`, `LibraryBackupResult`, `BackupValidationResult`, `LibraryRestoreResult`, `RestoreQuarantineEntry`, `RestoreFailureState`, `RestoreAdmissionBlockedError` |
| [AssetsManager/application/library_export_service_validate.py](../../../AssetsManager/application/library_export_service_validate.py) | `ValidateMixin` |
| [AssetsManager/application/library_governance.py](../../../AssetsManager/application/library_governance.py) | `LibraryHealthSnapshot`, `_dir_size`, `_file_size`, `collect_library_health`, `_count_rows`, `run_startup_governance`, `schedule_startup_governance` |
| [AssetsManager/application/library_service.py](../../../AssetsManager/application/library_service.py) | `_tag_repository_factory`, `_path_is_link_or_reparse`, `_RootOwnership`, `_TeardownProgress`, `_OpeningProgress`, `_RestoreRecoveryState`, `_lexical_map_key`, `_CanonicalRootMap`, `LibraryService` |
| [AssetsManager/application/library_settings_adapter.py](../../../AssetsManager/application/library_settings_adapter.py) | `LibrarySettingsBlockedError`, `LibrarySettingsViewModel`, `_LibraryScopedServices`, `LibrarySettingsAdapter` |
| [AssetsManager/application/library_watcher_service.py](../../../AssetsManager/application/library_watcher_service.py) | `LibraryWatcherStopTimeout`, `LibraryWatcherService` |
| [AssetsManager/application/media/__init__.py](../../../AssetsManager/application/media/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/application/media/analysis.py](../../../AssetsManager/application/media/analysis.py) | `_hex_color`, `extract_palette`, `_pcm_samples`, `_bucket_peaks`, `_render_peaks_png`, `_generate_waveform_pcm_wav`, `_generate_waveform_ffmpeg`, `generate_waveform`, `generate_waveform_from_bytes`, `_safe_source_mtime`, `_derivative_matches_source`, `ensure_audio_waveform`, `ensure_extracted_palette` |
| [AssetsManager/application/media/decoders.py](../../../AssetsManager/application/media/decoders.py) | `normalize_ext`, `MediaDecoder`, `_flatten_rgb`, `_fit_max_dim`, `_finish`, `_import_optional`, `RawDecoder`, `PsdDecoder`, `register`, `_rebuild_registry`, `decoder_for`, `supported_extensions` |
| [AssetsManager/application/media/derivatives.py](../../../AssetsManager/application/media/derivatives.py) | `derivatives_root`, `_normalize_ext`, `_resolve_target`, `MediaDerivative`, `MediaDerivativesRecorder` |
| [AssetsManager/application/metadata_service.py](../../../AssetsManager/application/metadata_service.py) | `AssetMetadata`, `MetadataService` |
| [AssetsManager/application/plugin_service.py](../../../AssetsManager/application/plugin_service.py) | `_category_registry_provider`, `PluginService` |
| [AssetsManager/application/project_service.py](../../../AssetsManager/application/project_service.py) | `_is_link_or_reparse`, `_SafeDirEntry`, `_clamp_depth`, `ProjectDepthConfig`, `ProjectListItem`, `ProjectListing`, `ProjectDetail`, `ProjectTree`, `ProjectHome`, `ProjectService` |
| [AssetsManager/application/reconciliation_queue.py](../../../AssetsManager/application/reconciliation_queue.py) | `_same_listener`, `ReconciliationKind`, `_validate_restore_snapshot`, `normalize_reconciliation_payload`, `ReconciliationState`, `ReconciliationTransitionDisposition`, `_ReconciliationTransitionRetryRequested`, `ReconciliationQueueFull`, `ReconciliationQueuePersistenceError`, `ReconciliationQueuePersistenceConflict`, `ReconciliationTask`, `ReconciliationQueueSnapshot`, `ReconciliationQueueClaimResult`, `ReconciliationQueueRecoveryResult`, `ReconciliationQueueMutationResult`, `ReconciliationTaskTransition`, `ReconciliationTransitionOutboxEntry`, `ReconciliationTransitionOutboxDeadLetter`, `ReconciliationTransitionOutboxMetrics`, `ReconciliationTransitionOutboxPruneResult`, `_TransitionBacklogEntry`, `_notify_task_transitions`, `_serialize_transition_mutation`, `ReconciliationQueueStore`, `ReconciliationQueue`, `reconciliation_backoff`, `_canonical_path`, `_resolve_expected_attempts`, `_resolve_nonretryable_attempts`, `_ensure_worker_lease`, `_merge_operation_ids`, `_task_to_json`, `_task_from_json` |
| [AssetsManager/application/reconciliation_queue_migration.py](../../../AssetsManager/application/reconciliation_queue_migration.py) | `ReconciliationMarkerMigrationError`, `ReconciliationMarkerMigrationStatus`, `ReconciliationMarkerMigrationResult`, `migrate_reconciliation_marker`, `_read_legacy_marker`, `_same_snapshot`, `_retire_marker` |
| [AssetsManager/application/reconciliation_queue_store.py](../../../AssetsManager/application/reconciliation_queue_store.py) | `_is_sqlite_busy_error`, `_retry_sqlite_busy`, `_TransitionOutboxDeliveryAttemptsExhausted`, `_outbox_delivery_backoff`, `_canonical_path`, `SQLiteReconciliationQueueStore` |
| [AssetsManager/application/relink_service.py](../../../AssetsManager/application/relink_service.py) | `RelinkTargetMissingError`, `LostEntry`, `NewcomerEntry`, `RelinkSuggestion`, `RelinkReport`, `suggest_pairs`, `scan`, `relink` |
| [AssetsManager/application/runtime.py](../../../AssetsManager/application/runtime.py) | `_LifecycleAdapter`, `LibraryRuntime` |
| [AssetsManager/application/runtime_events.py](../../../AssetsManager/application/runtime_events.py) | `ProjectionDomain`, `InvalidationEvent`, `_RouterSubscription`, `RuntimeEventRouter` |
| [AssetsManager/application/search_index_service.py](../../../AssetsManager/application/search_index_service.py) | `SearchIndexService` |
| [AssetsManager/application/search_service.py](../../../AssetsManager/application/search_service.py) | `_Scanner`, `_category_for_extension`, `SearchResult`, `QuickSearchResult`, `SearchStatus`, `SearchError`, `SearchSourceStatus`, `SearchResultSet`, `_contained_relative_path`, `_append_error`, `SearchService` |
| [AssetsManager/application/search_syntax.py](../../../AssetsManager/application/search_syntax.py) | `QueryUnit`, `ParsedQuery`, `_fts_string`, `_field_fragment`, `_State`, `_unit_fragment`, `_feed_word`, `parse_query`, `_unit_matches`, `make_row_predicate` |
| [AssetsManager/application/security_preflight.py](../../../AssetsManager/application/security_preflight.py) | `ShareState`, `TunnelState`, `_as_bool`, `normalized_ack_version`, `settings_security_values`, `_normalized_previous_bind`, `_normalized_previous_auth_status`, `settings_security_history`, `is_lan_bind`, `bind_scope_expanded`, `effective_auth`, `SecuritySnapshot`, `confirmation_failure_reason`, `probe_environment`, `preflight_snapshot`, `SecurityPreflight`, `security_preflight_from_settings`, `persist_successful_share_security_history` |
| [AssetsManager/application/sequence_service.py](../../../AssetsManager/application/sequence_service.py) | `SequenceGroup`, `SequenceNeighbors`, `_beats`, `group_sequences`, `_DirScan`, `_scan_directory`, `_cached_scan`, `clear_sequence_cache`, `find_neighbors` |
| [AssetsManager/application/share_service.py](../../../AssetsManager/application/share_service.py) | `ShareService` |
| [AssetsManager/application/tag_canonicalizer.py](../../../AssetsManager/application/tag_canonicalizer.py) | `install_tag_canonicalizer`, `canonical_tag` |
| [AssetsManager/application/tag_service.py](../../../AssetsManager/application/tag_service.py) | `_validated_tag_name`, `_resolve_connection`, `_get_repo`, `TagService` |
| [AssetsManager/application/thumbnail_cache_lifecycle.py](../../../AssetsManager/application/thumbnail_cache_lifecycle.py) | `_lock_for`, `artifact_lock`, `cache_owner_lock`, `artifact_path`, `remove_artifacts`, `eviction_artifact` |
| [AssetsManager/application/thumbnail_service.py](../../../AssetsManager/application/thumbnail_service.py) | `ThumbnailAdmissionError`, `ThumbnailSourceChangedError`, `thumbnail_source_identity`, `validate_thumbnail_source`, `admit_thumbnail_source`, `admit_thumbnail_cache_artifact`, `thumbnail_cache_key`, `clear_thumbnail_cache_keys`, `ThumbnailResult`, `ThumbnailService`, `finalize_pil_image`, `process_image_snapshot` |
| [AssetsManager/application/undo_service.py](../../../AssetsManager/application/undo_service.py) | `UndoEntry`, `UndoHistoryItem`, `UndoService` |
| [AssetsManager/background/__init__.py](../../../AssetsManager/background/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/background/cpu.py](../../../AssetsManager/background/cpu.py) | `render_chain` |
| [AssetsManager/background/gl/__init__.py](../../../AssetsManager/background/gl/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/background/gl/presets.py](../../../AssetsManager/background/gl/presets.py) | `ShaderPreset`, `preset_keys`, `get_preset`, `display_name`, `get_display_names`, `resolve` |
| [AssetsManager/background/gl/renderer.py](../../../AssetsManager/background/gl/renderer.py) | `GlPipeline` |
| [AssetsManager/background/gl/shaders.py](../../../AssetsManager/background/gl/shaders.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/background/model.py](../../../AssetsManager/background/model.py) | `EffectSpec`, `EffectChain` |
| [AssetsManager/background/pipeline.py](../../../AssetsManager/background/pipeline.py) | `ImageEffectRenderer` |
| [AssetsManager/controllers/__init__.py](../../../AssetsManager/controllers/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/controllers/file_list_controller.py](../../../AssetsManager/controllers/file_list_controller.py) | `FileListController` |
| [AssetsManager/controllers/info_controller.py](../../../AssetsManager/controllers/info_controller.py) | `_DirectoryClassifyCache`, `_read_url_file_text`, `PluginField`, `FileInfo`, `InfoController` |
| [AssetsManager/controllers/sidebar_controller.py](../../../AssetsManager/controllers/sidebar_controller.py) | `SidebarController` |
| [AssetsManager/controllers/tag_tree_controller.py](../../../AssetsManager/controllers/tag_tree_controller.py) | `TagTreeController` |
| [AssetsManager/core/__init__.py](../../../AssetsManager/core/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/core/bg_effects.py](../../../AssetsManager/core/bg_effects.py) | `_cap_source_edge`, `_flipped`, `_mirror_pad`, `apply_blur`, `apply_mosaic`, `apply_kuwahara`, `_kuwahara_numpy`, `_kuwahara_pure` |
| [AssetsManager/core/cache.py](../../../AssetsManager/core/cache.py) | `DictCache`, `LRUCache`, `ByteLRUCache`, `TTLCache` |
| [AssetsManager/core/color_utils.py](../../../AssetsManager/core/color_utils.py) | `_hex_to_rgb`, `_rgb_to_hex`, `alpha`, `contrast_on`, `lighten`, `darken`, `lighter`, `darker`, `contrast_ratio` |
| [AssetsManager/core/config_migrator.py](../../../AssetsManager/core/config_migrator.py) | `FutureConfigVersionError`, `_migrate_v0_to_v1`, `_migrate_v1_to_v2`, `migrate` |
| [AssetsManager/core/constants.py](../../../AssetsManager/core/constants.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/core/crash_handler.py](../../../AssetsManager/core/crash_handler.py) | `_redact`, `_rotate_log`, `_note_crash`, `_write_report`, `consume_pending_crash`, `read_last_crash`, `parse_last_crash_summary`, `build_github_issue_url`, `_excepthook`, `_thread_excepthook`, `install` |
| [AssetsManager/core/database.py](../../../AssetsManager/core/database.py) | `is_sqlite_busy_error`, `sqlite_busy_retry_delay`, `slow_query_threshold_ms`, `_slow_query_caller`, `_format_query_parameters`, `_report_slow_query`, `_timed_call`, `execute`, `executemany`, `SlowQueryConnection`, `slow_query_wrapper`, `_flush_directory_durable`, `_ensure_directory_chain`, `_flush_directory_chain_durable`, `_ConnectionWriteState`, `_WriteGate`, `_write_lock_for`, `_identity_claim_lock`, `_legacy_migration_looks_complete`, `_persisted_library_roots`, `DatabaseManager`, `db_write_lock`, `locked_read`, `_record_write_lock`, `_migrate_path_metadata_impl`, `migrate_path_metadata`, `_thumbnail_cache_key`, `clean_orphan_dirs` |
| [AssetsManager/core/db_migrations.py](../../../AssetsManager/core/db_migrations.py) | `UnsupportedSchemaVersion`, `MigrationHistoryError`, `IncompleteSchemaError`, `Migration`, `_ensure_migrations_table`, `_table_exists`, `_reconciliation_tasks_contract`, `_versioned_schema_contract`, `_should_defer_index_statement`, `_validate_schema_object_at_version`, `_validate_history`, `_read_history`, `preflight_recorded_version`, `_current_version`, `_index_columns`, `_validate_baseline_schema`, `_supported_version`, `_record`, `_baseline_v1`, `_add_assets_index_v2`, `_add_tag_metadata_v3`, `_add_plugin_metadata_v4`, `_add_directory_cache_v5`, `_add_auth_share_schema_v6`, `_add_library_favorites_v7`, `_add_commerce_schema_v8`, `_add_asset_index_state_v9`, `_add_reconciliation_tasks_schema_v14`, `_add_reconciliation_queue_state_schema_v15`, `_add_free_download_quota_schema_v10`, `_add_shop_order_receipts_v11`, `_add_seller_profile_v12`, `_add_storefront_analytics_v13`, `_add_shop_cart_wishlist_schema_v16`, `_add_shop_checkout_generation_schema_v19`, `_add_shop_checkout_fingerprint_schema_v21`, `_add_shop_delivery_attempts_schema_v22`, `_add_shop_catalog_index_schema_v23`, `_add_asset_dir_mtime_schema_v24`, `_add_shop_order_receipt_recovery_schema_v20`, `_add_shop_order_buyer_owner_schema_v18`, `_add_shop_share_claims_schema_v25`, `_add_gallery_home_schema_v26`, `_add_revoked_tokens_schema_v27`, `_add_user_can_write_schema_v28`, `_add_activity_log_schema_v29`, `_add_filesystem_projection_repair_schema_v30`, `_add_import_manifests_schema_v31`, `_add_import_manifest_recovery_lease_schema_v34`, `_add_import_manifest_items_schema_v43`, `_add_reconciliation_transition_outbox_schema_v44`, `_add_reconciliation_transition_outbox_dead_letters_schema_v45`, `_add_reconciliation_transition_outbox_delivery_backoff_schema_v46`, `_add_file_count_mtime_schema_v35`, `_add_tag_source_partition_v36`, `_add_media_derivatives_schema_v37`, `_add_asset_collections_schema_v38`, `_apply_asset_search_fts`, `_add_asset_search_fts_v39`, `_rebuild_asset_search_fts_trigram_v40`, `_add_asset_derivative_lifecycle_schema_v41`, `_add_command_executions_schema_v42`, `_add_thumbnail_cache_lifecycle_schema_v32`, `_add_thumbnail_render_profile_schema_v33`, `_add_reconciliation_lease_token_schema_v17`, `frozen_history_signature`, `_is_concurrent_migration_failure`, `_migrate_once`, `migrate`, `current_version` |
| [AssetsManager/core/directory_cache.py](../../../AssetsManager/core/directory_cache.py) | `_normalize_dir_key`, `DirCacheEntry`, `DirectoryCache` |
| [AssetsManager/core/event_contracts.py](../../../AssetsManager/core/event_contracts.py) | `DomainEventBase`, `EventSubscriptionPort`, `EventBusPort` |
| [AssetsManager/core/file_snapshot.py](../../../AssetsManager/core/file_snapshot.py) | `SnapshotPathEscapeError`, `_reject_path_text`, `_assert_under_root`, `FileIdentity`, `FileSnapshotError`, `OpenedFile`, `_reject_reparse_ancestors`, `_open_posix_no_follow`, `open_under_root`, `read_snapshot`, `_SnapshotIterator`, `iter_snapshot` |
| [AssetsManager/core/format_utils.py](../../../AssetsManager/core/format_utils.py) | `format_size`, `LiveCategoryMap` |
| [AssetsManager/core/icons.py](../../../AssetsManager/core/icons.py) | `_resolve_tint`, `normalize`, `names`, `has`, `_detect_dpr`, `icon`, `clear_cache` |
| [AssetsManager/core/json_store.py](../../../AssetsManager/core/json_store.py) | `JsonStore` |
| [AssetsManager/core/library_lock.py](../../../AssetsManager/core/library_lock.py) | `LibraryAlreadyOpenError`, `_PosixRecoveryUnavailable`, `_pid_is_alive`, `_new_lock`, `_posix_stale_recovery_guard`, `_recover_posix_stale_lock`, `LibraryLock` |
| [AssetsManager/core/library_manager.py](../../../AssetsManager/core/library_manager.py) | `_all`, `_save`, `record_visit`, `remove`, `list_all`, `get_by_uid` |
| [AssetsManager/core/path_resolver.py](../../../AssetsManager/core/path_resolver.py) | `RootIdentity`, `_identity_marker_owner`, `path_key_separator`, `escape_sql_like`, `sql_like_descendant_pattern`, `remap_path_subtree`, `root_identity`, `user_data_root`, `runtime_root`, `shared_dir`, `library_data_dir`, `library_data_name`, `library_data_identity_path`, `library_lock_path`, `legacy_library_data_dir`, `thumb_dir`, `favorites_path`, `recent_path`, `db_path`, `plugins_root`, `addons_dir`, `plugins_docs_dir`, `builtin_plugins_addons_dir`, `themes_dir`, `builtin_themes_dir` |
| [AssetsManager/core/performance.py](../../../AssetsManager/core/performance.py) | `PerformanceEvent`, `PerformanceRecorder` |
| [AssetsManager/core/plugins/__init__.py](../../../AssetsManager/core/plugins/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/core/plugins/descriptor.py](../../../AssetsManager/core/plugins/descriptor.py) | `DisplayField`, `PluginDiagnostic`, `PluginDescriptor`, `PluginRecord`, `PluginLoadResult`, `load_manifest`, `parse_plugin_descriptor`, `build_plugin_record` |
| [AssetsManager/core/plugins/host_context.py](../../../AssetsManager/core/plugins/host_context.py) | `install_event_bus_provider`, `_event_bus`, `_HookDispatchDrain`, `CommandContribution`, `MenuContribution`, `ToolWindowContribution`, `FileHandlerContribution`, `ContextMenuContribution`, `CategoryContribution`, `ColumnContribution`, `SearchProviderContribution`, `ThemeTokenContribution`, `_PluginServicesView`, `PluginHostContext`, `_open_with_default_handler`, `_opt_str`, `_to_int` |
| [AssetsManager/core/plugins/loader.py](../../../AssetsManager/core/plugins/loader.py) | `LoadedPlugin`, `_FunctionAdapter`, `_CallableAdapter`, `PluginLoader` |
| [AssetsManager/core/plugins/manager.py](../../../AssetsManager/core/plugins/manager.py) | `_host_callback_lock`, `_CategoryExtensionRegistry`, `set_category_registry_provider`, `_category_registries`, `PluginManagerService` |
| [AssetsManager/core/plugins/preferences.py](../../../AssetsManager/core/plugins/preferences.py) | `_AdvisoryLock`, `set_prefs_root`, `_prefs_root`, `_lock_for`, `_safe_plugin_id`, `PluginPreferenceBag` |
| [AssetsManager/core/project_data.py](../../../AssetsManager/core/project_data.py) | `ProjectData`, `get_project_data` |
| [AssetsManager/core/protocols.py](../../../AssetsManager/core/protocols.py) | `TagStoreProtocol` |
| [AssetsManager/core/schema_defs.py](../../../AssetsManager/core/schema_defs.py) | `ForeignKeyContract`, `ColumnContract`, `SchemaObjectContract`, `InvalidSchemaError`, `_table_exists`, `_index_columns`, `_sql_contains_tokens`, `validate_schema_object`, `validate_schema_objects` |
| [AssetsManager/core/session_contract.py](../../../AssetsManager/core/session_contract.py) | `register_library_session`, `require_library_session` |
| [AssetsManager/core/settings.py](../../../AssetsManager/core/settings.py) | `_positive_finite_number`, `_nonnegative_finite_number`, `_valid_http_url`, `_validate_setting`, `generate_mcp_token`, `AppSettings` |
| [AssetsManager/core/signal_bus.py](../../../AssetsManager/core/signal_bus.py) | `_SignalBus`, `get` |
| [AssetsManager/core/singleton.py](../../../AssetsManager/core/singleton.py) | `ThreadSafeSingleton` |
| [AssetsManager/core/tag_library.py](../../../AssetsManager/core/tag_library.py) | `TagLibrary`, `get_library` |
| [AssetsManager/core/tag_store.py](../../../AssetsManager/core/tag_store.py) | `install_repository_factory`, `_build_repository`, `_tag_store_operation`, `TagStore`, `get_store` |
| [AssetsManager/core/theme_loader.py](../../../AssetsManager/core/theme_loader.py) | `_default_themes_dir`, `_default_builtin_themes_dir`, `ThemeLoader` |
| [AssetsManager/core/themes.py](../../../AssetsManager/core/themes.py) | `_get_loader`, `set_plugin_token_fallbacks`, `_themes_dir`, `_load_all_themes`, `_merge_theme`, `_is_hex_color`, `_load_saved`, `_invalidate_icon_cache`, `get`, `set_theme`, `invalidate_cache`, `names`, `reload_themes`, `font_size`, `dark_themes`, `light_themes`, `categories`, `name`, `is_dark`, `color`, `prop`, `metrics`, `motion`, `set_button_variant`, `_bg_defaults`, `_bg_setting`, `_bg_number`, `bg_enabled`, `bg_image`, `bg_scale`, `bg_panel_opacity`, `bg_header_opacity`, `bg_overall_opacity`, `bg_effect`, `bg_shader_preset`, `bg_effect_intensity`, `panel_color`, `header_for_dock`, `stylesheet`, `apply_to`, `theme_mode_for_base` |
| [AssetsManager/core/thumbnail_key.py](../../../AssetsManager/core/thumbnail_key.py) | `ThumbnailSourceFingerprint`, `_identity_tuple`, `thumbnail_source_fingerprint`, `thumbnail_cache_key`, `normalize_webp_render_profile`, `profiled_thumbnail_cache_key_v3`, `legacy_thumbnail_cache_key` |
| [AssetsManager/core/timers.py](../../../AssetsManager/core/timers.py) | `TimerHandle` |
| [AssetsManager/core/tool_scheduler.py](../../../AssetsManager/core/tool_scheduler.py) | `_load`, `_save`, `list_tools`, `set_tools`, `run_tool`, `_wait_for_tool`, `_windows_launch_command` |
| [AssetsManager/core/ui_scale.py](../../../AssetsManager/core/ui_scale.py) | `get_ui_scale`, `scaled_px`, `scaled_pt` |
| [AssetsManager/core/workers.py](../../../AssetsManager/core/workers.py) | `_reap_pool`, `retained_pool_count`, `CancellationToken`, `TaskCancelled`, `CancellableRunnable`, `BoundedPool`, `should_continue` |
| [AssetsManager/di/__init__.py](../../../AssetsManager/di/__init__.py) | `CircularDependencyError`, `ServiceContainer` |
| [AssetsManager/dialogs/__init__.py](../../../AssetsManager/dialogs/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/dialogs/_maintenance_tasks.py](../../../AssetsManager/dialogs/_maintenance_tasks.py) | `_alive`, `BusyProgressDialog`, `MaintenanceTaskRunner` |
| [AssetsManager/dialogs/_plugin_manager_widget.py](../../../AssetsManager/dialogs/_plugin_manager_widget.py) | `PluginManagerWidget` |
| [AssetsManager/dialogs/_share_api.py](../../../AssetsManager/dialogs/_share_api.py) | `ShareApiResult`, `ShareApiTask`, `ShareCreationTask`, `_service_session`, `_service_runtime`, `_runtime_epoch` |
| [AssetsManager/dialogs/_sharing_helpers.py](../../../AssetsManager/dialogs/_sharing_helpers.py) | `_t`, `_endpoint_state`, `_endpoint_primary_action` |
| [AssetsManager/dialogs/activity_panel.py](../../../AssetsManager/dialogs/activity_panel.py) | `_cutoff_timestamp`, `ActivityPanelDialog`, `_format_time` |
| [AssetsManager/dialogs/color_picker_dialog.py](../../../AssetsManager/dialogs/color_picker_dialog.py) | `ColorPickerDialog` |
| [AssetsManager/dialogs/generic_settings_dialog.py](../../../AssetsManager/dialogs/generic_settings_dialog.py) | `_NoSettingsDialog`, `generic_settings_dialog` |
| [AssetsManager/dialogs/modal_dialog.py](../../../AssetsManager/dialogs/modal_dialog.py) | `StandardModalDialog` |
| [AssetsManager/dialogs/plugin_manager_dialog.py](../../../AssetsManager/dialogs/plugin_manager_dialog.py) | `PluginManagerDialog` |
| [AssetsManager/dialogs/plugin_operator_dialog.py](../../../AssetsManager/dialogs/plugin_operator_dialog.py) | `_OperatorParamsDialog`, `prompt_operator_params` |
| [AssetsManager/dialogs/settings_dialog.py](../../../AssetsManager/dialogs/settings_dialog.py) | `_RelinkRowWidget`, `_ThumbnailLoader`, `_FileListHost`, `_BackgroundStyleHost`, `_ThumbnailHost`, `_SettingsNavShell`, `_ProgressSignals`, `SettingsDialog` |
| [AssetsManager/dialogs/share_link_dialog.py](../../../AssetsManager/dialogs/share_link_dialog.py) | `ShareLinkDialog` |
| [AssetsManager/dialogs/share_qr_dialog.py](../../../AssetsManager/dialogs/share_qr_dialog.py) | `qr_pixmap`, `ShareQrDialog` |
| [AssetsManager/dialogs/sharing_settings/__init__.py](../../../AssetsManager/dialogs/sharing_settings/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/dialogs/sharing_settings/_access_page.py](../../../AssetsManager/dialogs/sharing_settings/_access_page.py) | `AccessPageMixin` |
| [AssetsManager/dialogs/sharing_settings/_configuration_page.py](../../../AssetsManager/dialogs/sharing_settings/_configuration_page.py) | `ConfigurationPageMixin` |
| [AssetsManager/dialogs/sharing_settings/_endpoint_page.py](../../../AssetsManager/dialogs/sharing_settings/_endpoint_page.py) | `EndpointPageMixin` |
| [AssetsManager/dialogs/sharing_settings/_links_page.py](../../../AssetsManager/dialogs/sharing_settings/_links_page.py) | `LinksPageMixin` |
| [AssetsManager/dialogs/sharing_settings/_ui.py](../../../AssetsManager/dialogs/sharing_settings/_ui.py) | `SharedUiMixin` |
| [AssetsManager/dialogs/sharing_settings_dialog.py](../../../AssetsManager/dialogs/sharing_settings_dialog.py) | `SharingSettingsDialog` |
| [AssetsManager/dialogs/sidebar_favorites.py](../../../AssetsManager/dialogs/sidebar_favorites.py) | `SidebarFavorites` |
| [AssetsManager/dialogs/sidebar_recent.py](../../../AssetsManager/dialogs/sidebar_recent.py) | `SidebarRecentFolders`, `_time_label` |
| [AssetsManager/dialogs/sidebar_settings_dialog.py](../../../AssetsManager/dialogs/sidebar_settings_dialog.py) | `SidebarSettingsDialog` |
| [AssetsManager/dialogs/startup.py](../../../AssetsManager/dialogs/startup.py) | `_font`, `_DetailPanel`, `_LibraryCard`, `_FirstRunCard`, `StartupWindow` |
| [AssetsManager/dialogs/tabbed_dialog.py](../../../AssetsManager/dialogs/tabbed_dialog.py) | `_DialogButtonBar`, `TabbedDialog` |
| [AssetsManager/dialogs/tag_browser_dialog.py](../../../AssetsManager/dialogs/tag_browser_dialog.py) | `TagBrowserDialog` |
| [AssetsManager/dialogs/tag_editor_dialog.py](../../../AssetsManager/dialogs/tag_editor_dialog.py) | `TagEditorDialog`, `_DeleteUnusedWorker` |
| [AssetsManager/dialogs/tag_style_dialog.py](../../../AssetsManager/dialogs/tag_style_dialog.py) | `TagStyleDialog` |
| [AssetsManager/dialogs/theme_preview_dialog.py](../../../AssetsManager/dialogs/theme_preview_dialog.py) | `ThemePreviewDialog` |
| [AssetsManager/dialogs/undo_panel.py](../../../AssetsManager/dialogs/undo_panel.py) | `UndoPanelDialog`, `_type_label_key`, `_format_time` |
| [AssetsManager/dock_factory.py](../../../AssetsManager/dock_factory.py) | `_DockPanel`, `create`, `_attach_footer`, `_build_title_bar`, `_menu`, `_close_dock`, `_split`, `_close`, `_run_dock_refresh`, `_schedule_dock_refresh`, `install_dock_refresh_handlers`, `request_refresh` |
| [AssetsManager/domain/__init__.py](../../../AssetsManager/domain/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/domain/asset.py](../../../AssetsManager/domain/asset.py) | `category_for_extension`, `assert_under_root`, `AssetPath`, `AssetType`, `AssetInfo` |
| [AssetsManager/domain/auth.py](../../../AssetsManager/domain/auth.py) | `generate_access_key`, `hash_key`, `verify_key`, `hash_password`, `_parse_password_hash`, `is_password_hash`, `verify_password`, `needs_password_rehash`, `generate_token`, `verify_token`, `verify_auth_token`, `generate_user_token`, `verify_user_token`, `generate_share_token`, `verify_share_token`, `validate_password_strength` |
| [AssetsManager/domain/errors.py](../../../AssetsManager/domain/errors.py) | `DomainError`, `PathEscapeError`, `MissingPathError`, `DuplicateError`, `NotFoundError`, `ValidationError`, `OperationNotPermitted` |
| [AssetsManager/domain/event_bus.py](../../../AssetsManager/domain/event_bus.py) | `EventSubscription`, `WeakEventSubscription`, `get_event_bus`, `EventBus` |
| [AssetsManager/domain/events.py](../../../AssetsManager/domain/events.py) | `DomainEvent`, `ShareChanged`, `FavoritesChanged`, `UserChanged`, `InviteChanged`, `ActivityChanged`, `MaintenanceChanged`, `PresenceChanged`, `FileSystemChanged`, `AssetTagsChanged`, `TagCatalogChanged`, `AssetNotesChanged`, `AssetUrlsChanged`, `AssetRatingChanged`, `QuotaChanged`, `CollectionChanged` |
| [AssetsManager/domain/library.py](../../../AssetsManager/domain/library.py) | `LibraryPath`, `_library_data_name` |
| [AssetsManager/domain/share.py](../../../AssetsManager/domain/share.py) | `ShareLink` |
| [AssetsManager/i18n/__init__.py](../../../AssetsManager/i18n/__init__.py) | `init`, `tr`, `set_language`, `languages`, `current_language`, `_available_codes`, `_load_lang`, `_lookup` |
| [AssetsManager/i18n/en.json](../../../AssetsManager/i18n/en.json) | 配置 / 前端 / 模块声明 |
| [AssetsManager/i18n/ja.json](../../../AssetsManager/i18n/ja.json) | 配置 / 前端 / 模块声明 |
| [AssetsManager/i18n/zh.json](../../../AssetsManager/i18n/zh.json) | 配置 / 前端 / 模块声明 |
| [AssetsManager/lan/__init__.py](../../../AssetsManager/lan/__init__.py) | `_AuthStatusProvider`, `is_available`, `LanServer`, `ShareManager` |
| [AssetsManager/lan/api.py](../../../AssetsManager/lan/api.py) | `stop_runtime_realtime`, `setup_routes` |
| [AssetsManager/lan/auth.py](../../../AssetsManager/lan/auth.py) | `verify_token_async` |
| [AssetsManager/lan/authorization.py](../../../AssetsManager/lan/authorization.py) | `_has_principal_capability`, `enforce_capabilities` |
| [AssetsManager/lan/dto.py](../../../AssetsManager/lan/dto.py) | `UserRecord`, `InviteRecord`, `_as_int`, `_as_float`, `_as_children`, `_as_optional_str`, `CapabilitiesResponse`, `SessionPrincipalResponse`, `UserResponse`, `InviteResponse`, `TagResponse`, `CollectionResponse`, `CollectionsResponse`, `CollectionMemberResponse`, `CollectionMembersResponse`, `CollectionEvaluateResultResponse`, `CollectionEvaluateResponse`, `TreeItemResponse`, `ZipCleanupDiagnosticsResponse`, `ZipResourcesResponse`, `StatsResponse`, `RuntimeCursorResponse`, `ProjectionInvalidationResponse` |
| [AssetsManager/lan/file_response.py](../../../AssetsManager/lan/file_response.py) | `open_download_file`, `SafeFileResponse` |
| [AssetsManager/lan/guarded_tunnel.py](../../../AssetsManager/lan/guarded_tunnel.py) | `_GuardedTunnel` |
| [AssetsManager/lan/manager.py](../../../AssetsManager/lan/manager.py) | `_TunnelHandle`, `ShareManager` |
| [AssetsManager/lan/mcp_server.py](../../../AssetsManager/lan/mcp_server.py) | `_InvalidToolArguments`, `_is_integer`, `_is_number`, `_validate_tool_arguments`, `_error_response`, `_tool_definitions`, `_run_tool`, `handle_mcp_post` |
| [AssetsManager/lan/path_guard.py](../../../AssetsManager/lan/path_guard.py) | `PathGuardError`, `PathEscapeError`, `MissingPathError`, `InvalidPathError`, `reject_path_text`, `assert_under_root`, `PathGuard` |
| [AssetsManager/lan/ports.py](../../../AssetsManager/lan/ports.py) | `LanDesktopAdapter`, `build_lan_server` |
| [AssetsManager/lan/principal.py](../../../AssetsManager/lan/principal.py) | `_as_int`, `_as_float`, `_can_write`, `Capabilities`, `SessionPrincipal`, `_settings_get`, `_guest_capabilities`, `principal_for_request` |
| [AssetsManager/lan/route_policy.py](../../../AssetsManager/lan/route_policy.py) | `RoutePolicy`, `declare`, `lookup`, `request_policy` |
| [AssetsManager/lan/routes/__init__.py](../../../AssetsManager/lan/routes/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/lan/routes/_errors.py](../../../AssetsManager/lan/routes/_errors.py) | `error_response`, `_plain`, `_mapped`, `error_contract_middleware` |
| [AssetsManager/lan/routes/_helpers.py](../../../AssetsManager/lan/routes/_helpers.py) | `build_media_etag`, `build_snapshot_media_etag`, `inspect_raster_bytes`, `etag_matches`, `media_not_modified`, `ActivityLog`, `OnlineUsers`, `sanitize_filename`, `LanScopedServices`, `get_lan`, `set_request_principal`, `get_request_principal`, `request_owner_key`, `require_role`, `require_admin`, `require_user_write`, `require_permission`, `oversized_query`, `get_services`, `get_auth_service`, `get_gallery_service`, `get_favorite_service`, `get_metadata_service`, `get_project_service`, `get_tag_service`, `get_collection_service`, `get_share_service`, `get_search_service`, `get_thumbnail_service`, `get_asset_service`, `validate_path`, `validated_existing_key`, `set_auth_cookie`, `set_share_cookie`, `get_share_token`, `get_auth_token`, `find_first_image`, `should_blur_target`, `serve_blur_gated_raster`, `_ZipBuildCancelled`, `_BoundedZipOutput`, `build_zip_sync`, `_zip_executor_for`, `build_zip_async` |
| [AssetsManager/lan/routes/_resource_urls.py](../../../AssetsManager/lan/routes/_resource_urls.py) | `thumbnail_url`, `download_url`, `image_url`, `search_result_response`, `project_listing_response`, `project_home_response`, `project_detail_response`, `_project_summary_response`, `gallery_entry_response`, `gallery_home_response`, `gallery_collection_response` |
| [AssetsManager/lan/routes/_telemetry.py](../../../AssetsManager/lan/routes/_telemetry.py) | `record_route_event` |
| [AssetsManager/lan/routes/auth.py](../../../AssetsManager/lan/routes/auth.py) | `_record_activity`, `handle_login`, `handle_register`, `handle_verify_key`, `handle_logout`, `handle_me` |
| [AssetsManager/lan/routes/collections.py](../../../AssetsManager/lan/routes/collections.py) | `_collection_id`, `_relative_or_none`, `handle_collections`, `handle_create_collection`, `handle_update_collection`, `handle_delete_collection`, `handle_collection_members`, `_member_paths`, `handle_add_collection_members`, `handle_remove_collection_members`, `handle_collection_evaluate` |
| [AssetsManager/lan/routes/downloads.py](../../../AssetsManager/lan/routes/downloads.py) | `_preflight_exhausted_response`, `_quota_unavailable_response`, `_quota_denied_response`, `_content_disposition_filename`, `_file_response_with_cleanup`, `_estimate_download_size`, `_estimate_batch_download_size`, `_estimate_reserved_zip_size`, `_prepare_zip_download`, `handle_download`, `handle_batch_download` |
| [AssetsManager/lan/routes/favorites.py](../../../AssetsManager/lan/routes/favorites.py) | `_service_or_unavailable`, `_request_path`, `_error_response`, `handle_favorites`, `handle_add_favorite`, `handle_remove_favorite` |
| [AssetsManager/lan/routes/files.py](../../../AssetsManager/lan/routes/files.py) | `_parse_paging`, `handle_files`, `handle_directory_summaries` |
| [AssetsManager/lan/routes/gallery.py](../../../AssetsManager/lan/routes/gallery.py) | `_path_query`, `_service_or_unavailable`, `handle_gallery_home`, `handle_gallery_collection`, `handle_gallery_resolve` |
| [AssetsManager/lan/routes/image.py](../../../AssetsManager/lan/routes/image.py) | `_blurred_snapshot_response`, `_not_found`, `_serve_decoded_raster`, `serve_verified_image`, `handle_image` |
| [AssetsManager/lan/routes/metadata.py](../../../AssetsManager/lan/routes/metadata.py) | `_parse_structured_search_params`, `handle_meta`, `handle_save_rating`, `handle_save_notes`, `handle_search`, `handle_home`, `handle_tree`, `handle_projects`, `handle_project_detail` |
| [AssetsManager/lan/routes/pages.py](../../../AssetsManager/lan/routes/pages.py) | `_spa_index`, `_spa_response`, `handle_index`, `handle_detail_page`, `handle_login_page`, `handle_browse_page`, `handle_gallery_page`, `handle_gallery_collection_page`, `handle_gallery_favorites_page` |
| [AssetsManager/lan/routes/quicksearch.py](../../../AssetsManager/lan/routes/quicksearch.py) | `_parse_limit`, `_quick_search_response`, `handle_quicksearch` |
| [AssetsManager/lan/routes/quota.py](../../../AssetsManager/lan/routes/quota.py) | `QuotaUnavailableError`, `_as_bool`, `get_free_download_quota_config`, `_disabled_info`, `_quota_cookie_signing_secret`, `_new_quota_cookie_token`, `_quota_cookie_id`, `_valid_quota_cookie_token`, `resolve_free_download_quota_identity`, `free_download_quota_identity`, `apply_free_quota_identity_cookie`, `get_free_download_quota_service`, `maintain_free_download_quota_service`, `get_free_download_quota_info`, `consume_free_download_quota`, `apply_free_quota_headers`, `handle_free_quota`, `quota_retry_after_seconds` |
| [AssetsManager/lan/routes/sequence.py](../../../AssetsManager/lan/routes/sequence.py) | `_empty_payload`, `handle_sequence_neighbors` |
| [AssetsManager/lan/routes/shares.py](../../../AssetsManager/lan/routes/shares.py) | `_content_disposition_filename`, `_resolve_share_target`, `handle_create_share`, `handle_list_shares`, `handle_delete_share`, `handle_share_page`, `handle_verify_share_password`, `handle_share_download`, `handle_share_preview`, `handle_share_info` |
| [AssetsManager/lan/routes/system.py](../../../AssetsManager/lan/routes/system.py) | `_owner_theme_name`, `_cached_project_count`, `handle_info`, `handle_tunnel_status`, `handle_stats`, `handle_revision` |
| [AssetsManager/lan/routes/tags.py](../../../AssetsManager/lan/routes/tags.py) | `handle_tags`, `handle_create_tag`, `handle_remove_tag`, `handle_rename_tag`, `handle_delete_tag` |
| [AssetsManager/lan/routes/thumbnails.py](../../../AssetsManager/lan/routes/thumbnails.py) | `_thumbnail_target_key`, `_thumbnail_source_root`, `_derivatives_recorder`, `_decoded_thumbnail_factory`, `handle_thumbnail`, `handle_thumbnail_batch` |
| [AssetsManager/lan/routes/users.py](../../../AssetsManager/lan/routes/users.py) | `handle_users`, `handle_toggle_user`, `handle_update_user`, `handle_invites`, `handle_create_invite`, `handle_revoke_invite`, `handle_activity`, `handle_online_users` |
| [AssetsManager/lan/routes/websocket.py](../../../AssetsManager/lan/routes/websocket.py) | `_close_quietly`, `_authorization_validator`, `_authorization_authority`, `handle_websocket` |
| [AssetsManager/lan/runtime_validation.py](../../../AssetsManager/lan/runtime_validation.py) | `_observe_broadcast`, `_runtime_services_snapshot`, `_runtime_operation`, `_derive_local_ui_auth_secret`, `_provider_matches_session`, `_service_session_matches`, `_validate_runtime_service_bindings` |
| [AssetsManager/lan/safe_open.py](../../../AssetsManager/lan/safe_open.py) | `_translate_path_error`, `safe_open_under_root`, `read_safe_file`, `iter_safe_file`, `open_safe_file`, `read_file_snapshot` |
| [AssetsManager/lan/scanner.py](../../../AssetsManager/lan/scanner.py) | `DirectoryScanner` |
| [AssetsManager/lan/security.py](../../../AssetsManager/lan/security.py) | `_request_policy`, `_normalize_ip`, `RateLimiter`, `AuthRateLimiter`, `IPBlacklist`, `create_security_middleware` |
| [AssetsManager/lan/server.py](../../../AssetsManager/lan/server.py) | `_LanServerImpl` |
| [AssetsManager/lan/server_lifecycle.py](../../../AssetsManager/lan/server_lifecycle.py) | `LanServerLifecycleMixin` |
| [AssetsManager/lan/temporary_file_response.py](../../../AssetsManager/lan/temporary_file_response.py) | `_TemporaryFileOwner`, `TemporaryFileResponse` |
| [AssetsManager/lan/token_revocations.py](../../../AssetsManager/lan/token_revocations.py) | `TokenRevocationPersistenceError`, `TokenRevocationRegistry` |
| [AssetsManager/lan/tunnel.py](../../../AssetsManager/lan/tunnel.py) | `_download_cloudflared`, `_fetch_expected_sha256`, `_sha256_of`, `_validate_cloudflared_binary`, `_find_cloudflared`, `_dev_mode_cloudflared_path`, `is_available`, `ensure_available`, `_extract_public_url`, `TunnelManager` |
| [AssetsManager/lan/tunnel_identity.py](../../../AssetsManager/lan/tunnel_identity.py) | `signing_secret`, `new_token`, `token_client_id`, `valid_token`, `apply_visitor_cookie` |
| [AssetsManager/lan/utils.py](../../../AssetsManager/lan/utils.py) | `_is_fake_ip_or_benchmark`, `_is_private_ipv4`, `_is_virtual_interface`, `_default_route_ip`, `_enumerate_private_ips`, `get_local_ip`, `generate_auth_token`, `get_auth_headers` |
| [AssetsManager/lan/ws.py](../../../AssetsManager/lan/ws.py) | `_AuthorityLease`, `_AuthorityTransition`, `_CallbackReservation`, `WebSocketManager` |
| [AssetsManager/lan/zip_cleanup.py](../../../AssetsManager/lan/zip_cleanup.py) | `_PendingCleanup`, `ZipCleanupService`, `_PathFingerprint`, `_fingerprint`, `_PathCleanupAttempt`, `IdentityChangedError`, `IdentityUnavailableError`, `get_process_zip_cleanup`, `cleanup_zip_path` |
| [AssetsManager/lan/zip_resources.py](../../../AssetsManager/lan/zip_resources.py) | `_validate_nonnegative_int`, `_ReservationState`, `ZipReservation`, `ZipResourceBudget`, `get_process_zip_budget` |
| [AssetsManager/lan/zip_sources.py](../../../AssetsManager/lan/zip_sources.py) | `ZipLimitExceeded`, `_ScanState`, `_stat_is_reparse`, `_entry_info`, `_entry_is_hidden`, `_entry_is_link`, `_archive_join`, `_assert_in_root`, `_close_scandir`, `_scan_directory`, `_target_stat`, `_target_is_link`, `scan_zip_sources`, `estimate_zip_source_bytes` |
| [AssetsManager/panels/__init__.py](../../../AssetsManager/panels/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/panels/_ai_tag_common.py](../../../AssetsManager/panels/_ai_tag_common.py) | `ai_tagging_enabled`, `ai_tag_error_text` |
| [AssetsManager/panels/_event_bridge.py](../../../AssetsManager/panels/_event_bridge.py) | `DomainEventSubscription`, `CategoryRegistrySubscription`, `RuntimeEventSubscription` |
| [AssetsManager/panels/_info_parts.py](../../../AssetsManager/panels/_info_parts.py) | `_DragLabel`, `_PreviewLabel`, `_FlowLayout`, `format_info_size`, `_AsyncRequest`, `_FileInfoSignals`, `_FileInfoTask`, `_LinkScanSignals`, `_LinkScanTask` |
| [AssetsManager/panels/_sidebar_parts.py](../../../AssetsManager/panels/_sidebar_parts.py) | `_fs_level`, `_PreloadSignals`, `_PreloadTask` |
| [AssetsManager/panels/base.py](../../../AssetsManager/panels/base.py) | `PanelContent`, `StandardPanel` |
| [AssetsManager/panels/empty.py](../../../AssetsManager/panels/empty.py) | `EmptyPanel` |
| [AssetsManager/panels/file_list/__init__.py](../../../AssetsManager/panels/file_list/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/panels/file_list/_actions.py](../../../AssetsManager/panels/file_list/_actions.py) | `ActionsMixin` |
| [AssetsManager/panels/file_list/_animator.py](../../../AssetsManager/panels/file_list/_animator.py) | `_Tween`, `Animator` |
| [AssetsManager/panels/file_list/_background.py](../../../AssetsManager/panels/file_list/_background.py) | `run_in_background`, `run_task` |
| [AssetsManager/panels/file_list/_base.py](../../../AssetsManager/panels/file_list/_base.py) | `FileListPanel` |
| [AssetsManager/panels/file_list/_base_events.py](../../../AssetsManager/panels/file_list/_base_events.py) | `EventsMixin` |
| [AssetsManager/panels/file_list/_base_layout.py](../../../AssetsManager/panels/file_list/_base_layout.py) | `LayoutMixin` |
| [AssetsManager/panels/file_list/_base_logic.py](../../../AssetsManager/panels/file_list/_base_logic.py) | `_CoverScanSignals`, `_CoverScanTask`, `_cover_view_window`, `LogicMixin` |
| [AssetsManager/panels/file_list/_batch_rename.py](../../../AssetsManager/panels/file_list/_batch_rename.py) | `BatchRenameEntry`, `BatchRenamePlan`, `plan_batch_rename`, `_name_errors` |
| [AssetsManager/panels/file_list/_batch_rename_dialog.py](../../../AssetsManager/panels/file_list/_batch_rename_dialog.py) | `BatchRenameDialog` |
| [AssetsManager/panels/file_list/_commands.py](../../../AssetsManager/panels/file_list/_commands.py) | `FileListCommandContext`, `FileListCommand`, `shortcut_command_id` |
| [AssetsManager/panels/file_list/_common.py](../../../AssetsManager/panels/file_list/_common.py) | `pil_image_to_qimage`, `qimage_to_pil`, `ExtensionCategoryLookup`, `refresh_extension_categories`, `_badge_category`, `badge_color_for_extension`, `badge_label_for_extension` |
| [AssetsManager/panels/file_list/_detail_model.py](../../../AssetsManager/panels/file_list/_detail_model.py) | `DetailModel` |
| [AssetsManager/panels/file_list/_grid_layout.py](../../../AssetsManager/panels/file_list/_grid_layout.py) | `GridLayout` |
| [AssetsManager/panels/file_list/_grid_texture_cache.py](../../../AssetsManager/panels/file_list/_grid_texture_cache.py) | `GridTextureCache` |
| [AssetsManager/panels/file_list/_grid_widget.py](../../../AssetsManager/panels/file_list/_grid_widget.py) | `FileListGridWidget` |
| [AssetsManager/panels/file_list/_grid_widget_data.py](../../../AssetsManager/panels/file_list/_grid_widget_data.py) | `_GridMetrics`, `_build_grid_metrics`, `rebuild_grid_runtime_metrics`, `DataMixin` |
| [AssetsManager/panels/file_list/_grid_widget_interact.py](../../../AssetsManager/panels/file_list/_grid_widget_interact.py) | `InteractMixin` |
| [AssetsManager/panels/file_list/_grid_widget_render.py](../../../AssetsManager/panels/file_list/_grid_widget_render.py) | `_GridRenderMetrics`, `_build_render_metrics`, `RenderMixin` |
| [AssetsManager/panels/file_list/_host.py](../../../AssetsManager/panels/file_list/_host.py) | `FileListHost`, `FileListActionsHost` |
| [AssetsManager/panels/file_list/_loader.py](../../../AssetsManager/panels/file_list/_loader.py) | `_VideoFramePending`, `_Runtime`, `_MemoryCacheEntry`, `get_bake_size`, `_bake_max_depth`, `_read_qimage_bytes`, `_suppress_libpng_warnings`, `_LoadTask`, `_ExtractVideoFrameTask`, `_ExtractAudioWaveformTask`, `_BakeTask`, `_TrackedTask`, `ThumbnailLoader` |
| [AssetsManager/panels/file_list/_model.py](../../../AssetsManager/panels/file_list/_model.py) | `_pixmap_bytes`, `_ScanSignals`, `_ScanTask`, `_StructuredFilter`, `FileSystemModel` |
| [AssetsManager/panels/file_list/_navigation.py](../../../AssetsManager/panels/file_list/_navigation.py) | `NavigationMixin` |
| [AssetsManager/panels/file_list/_shortcuts.py](../../../AssetsManager/panels/file_list/_shortcuts.py) | `handle_key` |
| [AssetsManager/panels/file_list/_status_helpers.py](../../../AssetsManager/panels/file_list/_status_helpers.py) | `compute_total_size`, `status_text`, `operation_feedback_text` |
| [AssetsManager/panels/file_list/_thumbnail_delivery.py](../../../AssetsManager/panels/file_list/_thumbnail_delivery.py) | `ThumbnailDeliveryCoordinator` |
| [AssetsManager/panels/file_list/_ui_helpers.py](../../../AssetsManager/panels/file_list/_ui_helpers.py) | `_DetailsItemDelegate`, `_make_folder_highlight`, `_first_image_in`, `_make_nav_button`, `_is_external_drop`, `_always`, `_add_command_group`, `_save_search_term` |
| [AssetsManager/panels/image_viewer.py](../../../AssetsManager/panels/image_viewer.py) | `_ViewerBridge`, `_is_viewable_ext`, `_decode_image_bytes`, `_decode_image`, `_decode_captured_image`, `_decode_media_image`, `_snapshot_path`, `_FullImageTask`, `_ExifTask`, `_StripThumbTask`, `_GraphicsView`, `ImageViewerOverlay`, `open_image_viewer` |
| [AssetsManager/panels/info.py](../../../AssetsManager/panels/info.py) | `InfoPanel` |
| [AssetsManager/panels/panel_state.py](../../../AssetsManager/panels/panel_state.py) | `PanelState` |
| [AssetsManager/panels/sidebar.py](../../../AssetsManager/panels/sidebar.py) | `_cancel_task`, `SidebarPanel` |
| [AssetsManager/panels/tag_tree.py](../../../AssetsManager/panels/tag_tree.py) | `TagTreePanel` |
| [AssetsManager/plugin_api/__init__.py](../../../AssetsManager/plugin_api/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/plugin_api/types.py](../../../AssetsManager/plugin_api/types.py) | `_as_path`, `PluginContext`, `PluginHost`, `CommandOperator`, `FileParser`, `ContextMenuItem`, `MenuContributor`, `PanelContributor`, `EventHook`, `CategoryContributor`, `ThemeTokenContributor`, `Preferences` |
| [AssetsManager/repositories/__init__.py](../../../AssetsManager/repositories/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/repositories/_common.py](../../../AssetsManager/repositories/_common.py) | `_repository_operation`, `_session_root`, `_require_session_contract`, `_transaction`, `_json_dump`, `_json_load`, `_ensure_commerce_schema`, `_SessionBoundRepository`, `_guarded_commit`, `_retry_sqlite_busy`, `_with_sqlite_busy_retry` |
| [AssetsManager/repositories/asset_index_repository.py](../../../AssetsManager/repositories/asset_index_repository.py) | `AssetIndexRevisionConflict`, `AssetIndexEntry`, `AssetIndexRepository` |
| [AssetsManager/repositories/auth_repository.py](../../../AssetsManager/repositories/auth_repository.py) | `InviteCodeLookupError`, `_rollback_safely`, `AuthRepository` |
| [AssetsManager/repositories/collection_repository.py](../../../AssetsManager/repositories/collection_repository.py) | `_collection_kind`, `CollectionRepository` |
| [AssetsManager/repositories/favorite_repository.py](../../../AssetsManager/repositories/favorite_repository.py) | `FavoriteRepository` |
| [AssetsManager/repositories/free_download_quota_repository.py](../../../AssetsManager/repositories/free_download_quota_repository.py) | `_validate_identity`, `FreeDownloadQuotaRepository` |
| [AssetsManager/repositories/gallery_home_repository.py](../../../AssetsManager/repositories/gallery_home_repository.py) | `GalleryHomeRepository` |
| [AssetsManager/repositories/metadata_repository.py](../../../AssetsManager/repositories/metadata_repository.py) | `MetadataRepository` |
| [AssetsManager/repositories/plugin_metadata_repository.py](../../../AssetsManager/repositories/plugin_metadata_repository.py) | `PluginMetadataRepository` |
| [AssetsManager/repositories/revoked_token_repository.py](../../../AssetsManager/repositories/revoked_token_repository.py) | `RevokedTokenRepository` |
| [AssetsManager/repositories/share_repository.py](../../../AssetsManager/repositories/share_repository.py) | `_cleanup_insert_savepoint`, `ShareRepository` |
| [AssetsManager/repositories/tag_repository.py](../../../AssetsManager/repositories/tag_repository.py) | `_tag_table`, `TagRepository` |
| [AssetsManager/repositories/thumbnail_repository.py](../../../AssetsManager/repositories/thumbnail_repository.py) | `ThumbnailMetadata`, `ThumbnailRepository` |
| [AssetsManager/widgets/__init__.py](../../../AssetsManager/widgets/__init__.py) | 配置 / 前端 / 模块声明 |
| [AssetsManager/widgets/command_palette.py](../../../AssetsManager/widgets/command_palette.py) | `PaletteCommand`, `CommandPaletteDelegate`, `CommandPalette` |
| [AssetsManager/widgets/dominant_palette_strip.py](../../../AssetsManager/widgets/dominant_palette_strip.py) | `_is_light`, `DominantPaletteStrip` |
| [AssetsManager/widgets/elevation.py](../../../AssetsManager/widgets/elevation.py) | `shadow_params`, `apply_elevation`, `refresh_elevation` |
| [AssetsManager/widgets/empty_state.py](../../../AssetsManager/widgets/empty_state.py) | `EmptyStateWidget` |
| [AssetsManager/widgets/hsv_wheel.py](../../../AssetsManager/widgets/hsv_wheel.py) | `_pos_to_hue`, `_hue_to_angle`, `HSVWheel`, `BrightnessSlider` |
| [AssetsManager/widgets/lan_sharing.py](../../../AssetsManager/widgets/lan_sharing.py) | `LanSharingMixin` |
| [AssetsManager/widgets/micro_tab_bar.py](../../../AssetsManager/widgets/micro_tab_bar.py) | `_IntCallable`, `_ListCallable`, `MicroTabBar` |
| [AssetsManager/widgets/overlay_shell.py](../../../AssetsManager/widgets/overlay_shell.py) | `OverlayShell` |
| [AssetsManager/widgets/plugin_ui.py](../../../AssetsManager/widgets/plugin_ui.py) | `PluginCard`, `PluginDetailPanel` |
| [AssetsManager/widgets/quick_look_overlay.py](../../../AssetsManager/widgets/quick_look_overlay.py) | `ImageCanvasWidget`, `GenericFileWidget`, `CanvasContainer`, `QuickLookOverlay` |
| [AssetsManager/widgets/quick_tagger_overlay.py](../../../AssetsManager/widgets/quick_tagger_overlay.py) | `QuickTaggerOverlay` |
| [AssetsManager/widgets/sharing_contracts.py](../../../AssetsManager/widgets/sharing_contracts.py) | `_security_blocked_message`, `confirm_security_preflight` |
| [AssetsManager/widgets/shortcut_manager.py](../../../AssetsManager/widgets/shortcut_manager.py) | `ShortcutManager` |
| [AssetsManager/widgets/stylekit.py](../../../AssetsManager/widgets/stylekit.py) | `_identity_px`, `_identity_pt`, `StyleKit` |
| [AssetsManager/widgets/tab_container.py](../../../AssetsManager/widgets/tab_container.py) | `TabContainer` |
| [AssetsManager/widgets/tag_chip.py](../../../AssetsManager/widgets/tag_chip.py) | `_synonyms_text_for`, `_contrast_text`, `tag_color_from`, `create_tag_chip` |
| [AssetsManager/widgets/theme_preview.py](../../../AssetsManager/widgets/theme_preview.py) | `_ButtonSection`, `_InputSection`, `_LabelSection`, `_ListSection`, `_TableSection`, `_DialogSection`, `_CheckRadioSection`, `_SliderProgressSection`, `_GroupBoxSection`, `_ColorSwatchSection`, `ThemePreviewWidget`, `ThemePreviewRenderer` |
| [AssetsManager/widgets/toast.py](../../../AssetsManager/widgets/toast.py) | `Toast` |
| [AssetsManager/widgets/tray.py](../../../AssetsManager/widgets/tray.py) | `SystemTrayManager` |
| [AssetsManager/widgets/workspace_bar.py](../../../AssetsManager/widgets/workspace_bar.py) | `WorkspaceBar`, `WorkspaceSection` |
| [AssetsManager/window.py](../../../AssetsManager/window.py) | `_alive`, `_save_window_geometry`, `_ImportProgressDialog`, `_restore_window_geometry`, `maybe_show_tray_hide_hint`, `build_shortcuts_help_text`, `MainWindow` |
| [AssetsManager/window_coordinator.py](../../../AssetsManager/window_coordinator.py) | `CoordinatedWindow`, `WindowCoordinator` |
| [AssetsManager/window_lifecycle_coordinator.py](../../../AssetsManager/window_lifecycle_coordinator.py) | `_restore_lan_state`, `_select_workspace_tab`, `_remove_workspace_tab`, `_notify_switch_failed`, `_rollback_open_failure`, `WindowLifecycleCoordinator` |
| [AssetsManager/window_scoped_panels.py](../../../AssetsManager/window_scoped_panels.py) | 配置 / 前端 / 模块声明 |
| [Plugins/Addons/booth_link/parser.py](../../../Plugins/Addons/booth_link/parser.py) | `match`, `parse` |
| [Plugins/Addons/booth_link/plugin.json](../../../Plugins/Addons/booth_link/plugin.json) | 配置 / 前端 / 模块声明 |
| [Plugins/Addons/download_tracker/plugin.json](../../../Plugins/Addons/download_tracker/plugin.json) | 配置 / 前端 / 模块声明 |
| [Plugins/Addons/download_tracker/tracker.py](../../../Plugins/Addons/download_tracker/tracker.py) | `_realign_to_main_thread`, `_ensure_refresh_notifier`, `_emit_refresh`, `_load_history`, `_save_history`, `_prune`, `TrackerPrefs`, `DownloadParser`, `ImportHook`, `ClearHistory`, `HistoryPanel`, `Plugin` |
| [assets/Themes/D_Amber.json](../../../assets/Themes/D_Amber.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/D_Charcoal.json](../../../assets/Themes/D_Charcoal.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/D_Default.json](../../../assets/Themes/D_Default.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/D_Dracula.json](../../../assets/Themes/D_Dracula.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/D_Espresso.json](../../../assets/Themes/D_Espresso.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/D_Forest.json](../../../assets/Themes/D_Forest.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/D_Gruvbox.json](../../../assets/Themes/D_Gruvbox.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/D_Midnight.json](../../../assets/Themes/D_Midnight.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/D_Navy.json](../../../assets/Themes/D_Navy.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/D_Nord.json](../../../assets/Themes/D_Nord.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/D_Onyx.json](../../../assets/Themes/D_Onyx.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/D_Rosepine.json](../../../assets/Themes/D_Rosepine.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/D_Slate.json](../../../assets/Themes/D_Slate.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/L_Coral.json](../../../assets/Themes/L_Coral.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/L_Dawn.json](../../../assets/Themes/L_Dawn.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/L_Frost.json](../../../assets/Themes/L_Frost.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/L_Lavender.json](../../../assets/Themes/L_Lavender.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/L_Lilac.json](../../../assets/Themes/L_Lilac.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/L_Mint.json](../../../assets/Themes/L_Mint.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/L_Peach.json](../../../assets/Themes/L_Peach.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/L_Rose.json](../../../assets/Themes/L_Rose.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/L_Sage.json](../../../assets/Themes/L_Sage.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/L_Silver.json](../../../assets/Themes/L_Silver.json) | 配置 / 前端 / 模块声明 |
| [assets/Themes/L_Sky.json](../../../assets/Themes/L_Sky.json) | 配置 / 前端 / 模块声明 |
| [build.py](../../../build.py) | `clean`, `webui_build`, `_run_pyinstaller`, `build`, `report` |
| [main.py](../../../main.py) | 配置 / 前端 / 模块声明 |
| [pyrightconfig.json](../../../pyrightconfig.json) | 配置 / 前端 / 模块声明 |
| [pytest.ini](../../../pytest.ini) | 配置 / 前端 / 模块声明 |
| [requirements-ci.txt](../../../requirements-ci.txt) | 配置 / 前端 / 模块声明 |
| [requirements-dev.txt](../../../requirements-dev.txt) | 配置 / 前端 / 模块声明 |
| [requirements-lan.txt](../../../requirements-lan.txt) | 配置 / 前端 / 模块声明 |
| [requirements-media.txt](../../../requirements-media.txt) | 配置 / 前端 / 模块声明 |
| [requirements-perf.txt](../../../requirements-perf.txt) | 配置 / 前端 / 模块声明 |
| [requirements.txt](../../../requirements.txt) | 配置 / 前端 / 模块声明 |
| [ruff.toml](../../../ruff.toml) | 配置 / 前端 / 模块声明 |
| [run.py](../../../run.py) | `_show_startup_error`, `_run_package_smoke` |
| [webui/package.json](../../../webui/package.json) | 配置 / 前端 / 模块声明 |
| [webui/playwright.config.ts](../../../webui/playwright.config.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/App.tsx](../../../webui/src/App.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/api/auth.ts](../../../webui/src/api/auth.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/api/client.ts](../../../webui/src/api/client.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/api/collections.ts](../../../webui/src/api/collections.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/api/degradationBus.ts](../../../webui/src/api/degradationBus.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/api/errors.ts](../../../webui/src/api/errors.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/api/favorites.ts](../../../webui/src/api/favorites.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/api/files.ts](../../../webui/src/api/files.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/api/gallery.ts](../../../webui/src/api/gallery.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/api/metadata.ts](../../../webui/src/api/metadata.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/api/notes.ts](../../../webui/src/api/notes.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/api/quicksearch.ts](../../../webui/src/api/quicksearch.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/api/shares.ts](../../../webui/src/api/shares.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/api/system.ts](../../../webui/src/api/system.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/api/tags.ts](../../../webui/src/api/tags.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/api/thumbnails.ts](../../../webui/src/api/thumbnails.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/api/users.ts](../../../webui/src/api/users.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/cache/QueryCacheContext.tsx](../../../webui/src/cache/QueryCacheContext.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/cache/invalidation.ts](../../../webui/src/cache/invalidation.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/cache/queryCache.ts](../../../webui/src/cache/queryCache.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/components/admin/ActivityLog.tsx](../../../webui/src/components/admin/ActivityLog.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/admin/InviteManagement.tsx](../../../webui/src/components/admin/InviteManagement.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/admin/OnlineUsers.tsx](../../../webui/src/components/admin/OnlineUsers.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/admin/ShareManagement.tsx](../../../webui/src/components/admin/ShareManagement.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/admin/UserManagement.tsx](../../../webui/src/components/admin/UserManagement.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/auth/ProtectedRoute.tsx](../../../webui/src/components/auth/ProtectedRoute.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/files/Breadcrumb.tsx](../../../webui/src/components/files/Breadcrumb.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/files/FileToolbar.tsx](../../../webui/src/components/files/FileToolbar.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/files/LayeredPreview.tsx](../../../webui/src/components/files/LayeredPreview.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/files/MasonryView.tsx](../../../webui/src/components/files/MasonryView.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/files/ProjectCard.tsx](../../../webui/src/components/files/ProjectCard.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/files/ProjectGrid.tsx](../../../webui/src/components/files/ProjectGrid.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/files/ProjectList.tsx](../../../webui/src/components/files/ProjectList.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/gallery/Gallery.css](../../../webui/src/components/gallery/Gallery.css) | 配置 / 前端 / 模块声明 |
| [webui/src/components/gallery/GalleryCard.tsx](../../../webui/src/components/gallery/GalleryCard.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/gallery/GalleryEmptyState.tsx](../../../webui/src/components/gallery/GalleryEmptyState.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/gallery/GalleryLayout.tsx](../../../webui/src/components/gallery/GalleryLayout.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/gallery/GallerySection.tsx](../../../webui/src/components/gallery/GallerySection.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/gallery/GalleryTiledGrid.tsx](../../../webui/src/components/gallery/GalleryTiledGrid.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/gallery/GalleryViewControls.tsx](../../../webui/src/components/gallery/GalleryViewControls.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/layout/AmbientBackdrop.tsx](../../../webui/src/components/layout/AmbientBackdrop.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/layout/AppHeader.tsx](../../../webui/src/components/layout/AppHeader.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/layout/AppLayout.tsx](../../../webui/src/components/layout/AppLayout.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/layout/Header.css](../../../webui/src/components/layout/Header.css) | 配置 / 前端 / 模块声明 |
| [webui/src/components/layout/Header.tsx](../../../webui/src/components/layout/Header.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/layout/InfoPanel.tsx](../../../webui/src/components/layout/InfoPanel.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/layout/ResizablePanel.tsx](../../../webui/src/components/layout/ResizablePanel.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/layout/Sidebar.tsx](../../../webui/src/components/layout/Sidebar.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/layout/StatusBar.tsx](../../../webui/src/components/layout/StatusBar.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/layout/Workspace.css](../../../webui/src/components/layout/Workspace.css) | 配置 / 前端 / 模块声明 |
| [webui/src/components/media/DominantPaletteStrip.tsx](../../../webui/src/components/media/DominantPaletteStrip.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/shares/ShareDialog.tsx](../../../webui/src/components/shares/ShareDialog.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/tags/TagChip.tsx](../../../webui/src/components/tags/TagChip.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/ui/BottomSheet.tsx](../../../webui/src/components/ui/BottomSheet.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/ui/CommandPalette.css](../../../webui/src/components/ui/CommandPalette.css) | 配置 / 前端 / 模块声明 |
| [webui/src/components/ui/CommandPalette.tsx](../../../webui/src/components/ui/CommandPalette.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/ui/ContextMenu.tsx](../../../webui/src/components/ui/ContextMenu.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/ui/DownloadProgress.tsx](../../../webui/src/components/ui/DownloadProgress.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/ui/EmptyState.css](../../../webui/src/components/ui/EmptyState.css) | 配置 / 前端 / 模块声明 |
| [webui/src/components/ui/EmptyState.tsx](../../../webui/src/components/ui/EmptyState.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/ui/ErrorBoundary.tsx](../../../webui/src/components/ui/ErrorBoundary.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/ui/Modal.tsx](../../../webui/src/components/ui/Modal.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/ui/ShortcutsDialog.css](../../../webui/src/components/ui/ShortcutsDialog.css) | 配置 / 前端 / 模块声明 |
| [webui/src/components/ui/ShortcutsDialog.tsx](../../../webui/src/components/ui/ShortcutsDialog.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/ui/Skeleton.tsx](../../../webui/src/components/ui/Skeleton.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/ui/Toast.tsx](../../../webui/src/components/ui/Toast.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/viewer/ImageViewer.tsx](../../../webui/src/components/viewer/ImageViewer.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/components/viewer/QuickLookOverlay.tsx](../../../webui/src/components/viewer/QuickLookOverlay.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useApiDegradationToast.ts](../../../webui/src/hooks/useApiDegradationToast.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useAuth.ts](../../../webui/src/hooks/useAuth.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useCachedQuery.ts](../../../webui/src/hooks/useCachedQuery.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useDialogFocus.ts](../../../webui/src/hooks/useDialogFocus.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useFavorites.ts](../../../webui/src/hooks/useFavorites.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useI18n.ts](../../../webui/src/hooks/useI18n.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useInvalidation.ts](../../../webui/src/hooks/useInvalidation.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useMediaQuery.ts](../../../webui/src/hooks/useMediaQuery.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/usePageApis.ts](../../../webui/src/hooks/usePageApis.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useProjects.ts](../../../webui/src/hooks/useProjects.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useQuickLook.ts](../../../webui/src/hooks/useQuickLook.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useQuota.ts](../../../webui/src/hooks/useQuota.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useSearch.ts](../../../webui/src/hooks/useSearch.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useServerTheme.ts](../../../webui/src/hooks/useServerTheme.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useTheme.ts](../../../webui/src/hooks/useTheme.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useThumbnailCache.ts](../../../webui/src/hooks/useThumbnailCache.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/hooks/useWebSocket.ts](../../../webui/src/hooks/useWebSocket.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/i18n/en.ts](../../../webui/src/i18n/en.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/i18n/index.ts](../../../webui/src/i18n/index.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/i18n/ja.ts](../../../webui/src/i18n/ja.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/i18n/zh.ts](../../../webui/src/i18n/zh.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/index.css](../../../webui/src/index.css) | 配置 / 前端 / 模块声明 |
| [webui/src/main.tsx](../../../webui/src/main.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/pages/AdminPage.tsx](../../../webui/src/pages/AdminPage.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/pages/BrowsePage.tsx](../../../webui/src/pages/BrowsePage.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/pages/DetailPage.css](../../../webui/src/pages/DetailPage.css) | 配置 / 前端 / 模块声明 |
| [webui/src/pages/DetailPage.tsx](../../../webui/src/pages/DetailPage.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/pages/GalleryCollectionPage.tsx](../../../webui/src/pages/GalleryCollectionPage.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/pages/GalleryFavoritesPage.tsx](../../../webui/src/pages/GalleryFavoritesPage.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/pages/GalleryHomePage.tsx](../../../webui/src/pages/GalleryHomePage.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/pages/LandingPage.css](../../../webui/src/pages/LandingPage.css) | 配置 / 前端 / 模块声明 |
| [webui/src/pages/LandingPage.tsx](../../../webui/src/pages/LandingPage.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/pages/LoginPage.tsx](../../../webui/src/pages/LoginPage.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/pages/NotFoundPage.tsx](../../../webui/src/pages/NotFoundPage.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/pages/ShareReceivePage.tsx](../../../webui/src/pages/ShareReceivePage.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/shortcuts/registry.ts](../../../webui/src/shortcuts/registry.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/stores/AuthContext.tsx](../../../webui/src/stores/AuthContext.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/stores/RealtimeContext.tsx](../../../webui/src/stores/RealtimeContext.tsx) | 配置 / 前端 / 模块声明 |
| [webui/src/tokens/themes.generated.css](../../../webui/src/tokens/themes.generated.css) | 配置 / 前端 / 模块声明 |
| [webui/src/tokens/themes.manifest.generated.ts](../../../webui/src/tokens/themes.manifest.generated.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/types/api.ts](../../../webui/src/types/api.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/types/contracts.ts](../../../webui/src/types/contracts.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/utils/backoff.ts](../../../webui/src/utils/backoff.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/utils/collectionSnapshot.ts](../../../webui/src/utils/collectionSnapshot.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/utils/concurrency.ts](../../../webui/src/utils/concurrency.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/utils/download.ts](../../../webui/src/utils/download.ts) | 配置 / 前端 / 模块声明 |
| [webui/src/vite-env.d.ts](../../../webui/src/vite-env.d.ts) | 配置 / 前端 / 模块声明 |
| [webui/vite.config.ts](../../../webui/vite.config.ts) | 配置 / 前端 / 模块声明 |

## 重新生成

从仓库根目录执行：

```powershell
python docs/diagrams/code-atlas-2026-09-06/build_atlas.py
node docs/diagrams/code-atlas-2026-09-06/render_atlas.mjs
```

先更新正文中的分图再生成。`build_atlas.py` 仅解析与哈希源码；`render_atlas.mjs` 使用现有 Playwright 和 Mermaid 生成静态 SVG 与离线 HTML，首次渲染需要获取固定版本 Mermaid。重新捕获源码会更新清单，不自动证明人工分图仍准确。
