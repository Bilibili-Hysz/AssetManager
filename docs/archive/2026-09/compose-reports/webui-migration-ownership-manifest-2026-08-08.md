# WebUI 迁移变更归属清单（Dry-run）

- 生成日期：2026-08-08
- 工作区：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
- 参考源：`D:\~Vibe-Coding\Projects\AssetsManager_New_WebUI`（只读）
- 初始清单：479 个状态条目；187 个 tracked modified；292 个 untracked；0 个 staged。2026-08-09 当前复核基线：486 个状态条目；194 个 tracked modified；292 个 untracked；0 个 staged。
- 本清单只用于审查和后续手工 staging，不执行 `git add`、commit、reset 或 clean。

## 归属原则

- 每个状态路径先归入一个主批次；跨域 tracked 文件另列，必须使用 `git add -p` 按 hunk 处理。
- `EXCLUDE_TEMP` 和所有 `OUT_*` 路径不得被 WebUI 批次的宽泛命令带入。
- `webui/playwright.config.ts` 只能提交一次，建议与 Batch 8 的 CI 门禁一起处理。
- `AssetsManager/core/db_migrations.py` 同时含 Batch 1、Batch 3 内容，必须拆 hunk。

## 汇总

| 分类 | 数量 |
|---|---:|
| Batch 1 — Schema / migrations | 6 |
| Batch 2 — Restore / integrity / maintenance | 9 |
| Batch 3 — G17 reconciliation | 22 |
| Batch 4 — Commerce backend | 31 |
| Batch 5 — LAN Commerce / auth | 23 |
| Batch 6 — WebUI shared / Gallery / legacy | 74 |
| Batch 7 — WebUI Storefront / Seller | 62 |
| Batch 8 — CI / docs / tooling | 13 |
| Cross-domain — Playwright config (stage once) | 1 |
| Cross-domain — tracked hunk staging required | 5 |
| Exclude — temporary/local artifacts | 3 |
| Out of WebUI scope — existing docs/evidence | 86 |
| Out of WebUI scope — existing mainline/other engineering | 151 |

## Batch 1 — Schema / migrations

```text
M	AssetsManager/core/db_migrations.py
M	AssetsManager/core/schema_defs.py
??	tests/core/test_commerce_migration_matrix.py
M	tests/core/test_db_migrations.py
??	tests/core/test_delivery_attempt_migration.py
??	tests/core/test_reconciliation_queue_migration.py
```

## Batch 2 — Restore / integrity / maintenance

```text
??	AssetsManager/application/database_integrity_service.py
??	AssetsManager/application/database_maintenance_service.py
??	AssetsManager/application/library_export_service.py
??	AssetsManager/application/library_settings_adapter.py
??	tests/integration/test_core_store_session_binding.py
??	tests/unit/test_database_integrity_service.py
??	tests/unit/test_database_maintenance_service.py
??	tests/unit/test_library_export_service.py
??	tests/unit/test_library_settings_adapter.py
```

## Batch 3 — G17 reconciliation

```text
??	AssetsManager/application/asset_index_reconciliation_service.py
??	AssetsManager/application/reconciliation_queue.py
??	AssetsManager/application/reconciliation_queue_migration.py
??	AssetsManager/application/reconciliation_queue_store.py
??	tests/integration/test_reconciliation_bootstrap_order.py
??	tests/integration/test_reconciliation_cutover_lock_order.py
??	tests/integration/test_reconciliation_library_owner_handoff.py
??	tests/integration/test_reconciliation_queue_cross_process_wakeup.py
??	tests/integration/test_reconciliation_queue_external_lock.py
??	tests/integration/test_reconciliation_queue_fault_injection.py
??	tests/integration/test_reconciliation_queue_heartbeat_inflight.py
??	tests/integration/test_reconciliation_queue_process_matrix.py
??	tests/integration/test_reconciliation_queue_process_termination.py
??	tests/integration/test_reconciliation_queue_process_termination_subprocess.py
??	tests/integration/test_reconciliation_queue_sqlite_runtime.py
??	tests/integration/test_reconciliation_runtime_cutover.py
??	tests/integration/test_reconciliation_runtime_lifecycle.py
??	tests/unit/test_asset_index_reconciliation_service.py
??	tests/unit/test_reconciliation_queue.py
??	tests/unit/test_reconciliation_queue_migration.py
??	tests/unit/test_reconciliation_queue_sqlite_store.py
??	tests/unit/test_reconciliation_supervisor_conflicts.py
```

## Batch 4 — Commerce backend

```text
??	AssetsManager/application/favorite_service.py
??	AssetsManager/application/free_download_quota_service.py
??	AssetsManager/application/order_service.py
??	AssetsManager/application/quota_service.py
??	AssetsManager/application/seller_auth_service.py
??	AssetsManager/application/seller_profile_service.py
??	AssetsManager/application/shop_authorization.py
??	AssetsManager/application/shop_buyer_service.py
??	AssetsManager/application/shop_service.py
??	AssetsManager/application/storefront_analytics_service.py
??	AssetsManager/repositories/favorite_repository.py
??	AssetsManager/repositories/free_download_quota_repository.py
??	AssetsManager/repositories/order_repository.py
??	AssetsManager/repositories/quota_repository.py
??	AssetsManager/repositories/seller_profile_repository.py
??	AssetsManager/repositories/shop_buyer_repository.py
??	AssetsManager/repositories/shop_repository.py
??	AssetsManager/repositories/storefront_analytics_repository.py
??	tests/integration/test_commerce_repository_session_binding.py
??	tests/integration/test_delivery_attempt_idempotency.py
??	tests/integration/test_order_receipts.py
??	tests/unit/test_commerce_repositories.py
??	tests/unit/test_commerce_services.py
??	tests/unit/test_favorite_repository.py
??	tests/unit/test_free_download_quota.py
??	tests/unit/test_seller_profile_repository.py
??	tests/unit/test_seller_profile_service.py
??	tests/unit/test_shop_authorized_roots.py
??	tests/unit/test_shop_buyer_service.py
??	tests/unit/test_storefront_analytics_repository.py
??	tests/unit/test_storefront_analytics_service.py
```

## Batch 5 — LAN Commerce / auth

```text
M	AssetsManager/lan/api.py
M	AssetsManager/lan/principal.py
M	AssetsManager/lan/routes/__init__.py
M	AssetsManager/lan/routes/_helpers.py
??	AssetsManager/lan/routes/commerce_policy.py
??	AssetsManager/lan/routes/favorites.py
??	AssetsManager/lan/routes/gallery.py
??	AssetsManager/lan/routes/quota.py
??	AssetsManager/lan/routes/seller_auth.py
??	AssetsManager/lan/routes/seller_profile.py
??	AssetsManager/lan/routes/shop.py
??	AssetsManager/lan/routes/storefront_analytics.py
M	AssetsManager/lan/server.py
??	tests/lan/test_commerce_error_contract.py
??	tests/lan/test_commerce_policy.py
??	tests/lan/test_commerce_routes.py
??	tests/lan/test_free_download_quota.py
??	tests/lan/test_order_receipt_routes.py
??	tests/lan/test_public_commerce_auth.py
??	tests/lan/test_seller_profile_routes.py
??	tests/lan/test_storefront_analytics_routes.py
??	tests/lan/test_storefront_commerce_integration.py
??	tests/lan/test_system_feature_flags.py
```

## Batch 6 — WebUI shared / Gallery / legacy

```text
M	webui/src/App.test.tsx
M	webui/src/App.tsx
M	webui/src/api/client.test.ts
M	webui/src/api/client.ts
M	webui/src/api/files.contract.test.ts
M	webui/src/api/files.ts
??	webui/src/api/notes.contract.test.ts
??	webui/src/api/notes.ts
??	webui/src/api/quicksearch.contract.test.ts
??	webui/src/api/quicksearch.ts
M	webui/src/api/shares.contract.test.ts
M	webui/src/api/shares.ts
M	webui/src/api/system.contract.test.ts
M	webui/src/api/system.ts
M	webui/src/api/tags.contract.test.ts
M	webui/src/api/tags.ts
M	webui/src/components/admin/UserManagement.tsx
M	webui/src/components/files/Breadcrumb.tsx
M	webui/src/components/files/FileToolbar.tsx
??	webui/src/components/files/MasonryView.tsx
M	webui/src/components/files/ProjectCard.tsx
M	webui/src/components/files/ProjectGrid.tsx
M	webui/src/components/files/ProjectList.tsx
??	webui/src/components/gallery/Gallery.css
??	webui/src/components/gallery/GalleryCard.tsx
??	webui/src/components/gallery/GalleryEmptyState.tsx
??	webui/src/components/gallery/GalleryLayout.tsx
??	webui/src/components/gallery/GallerySection.tsx
??	webui/src/components/gallery/GalleryTiledGrid.tsx
??	webui/src/components/gallery/GalleryViewControls.tsx
??	webui/src/components/layout/AppHeader.test.tsx
??	webui/src/components/layout/AppHeader.tsx
M	webui/src/components/layout/AppLayout.tsx
??	webui/src/components/layout/Header.css
M	webui/src/components/layout/Header.tsx
M	webui/src/components/layout/InfoPanel.test.tsx
M	webui/src/components/layout/InfoPanel.tsx
M	webui/src/components/layout/Sidebar.test.tsx
M	webui/src/components/layout/Sidebar.tsx
M	webui/src/components/layout/StatusBar.test.tsx
M	webui/src/components/layout/StatusBar.tsx
??	webui/src/components/layout/Workspace.css
M	webui/src/components/tags/TagChip.tsx
??	webui/src/components/ui/CommandPalette.css
??	webui/src/components/ui/CommandPalette.test.tsx
??	webui/src/components/ui/CommandPalette.tsx
M	webui/src/components/ui/ContextMenu.tsx
M	webui/src/components/ui/DownloadProgress.tsx
M	webui/src/components/ui/Modal.tsx
M	webui/src/components/ui/Toast.tsx
M	webui/src/hooks/useSearch.test.tsx
M	webui/src/hooks/useSearch.ts
M	webui/src/hooks/useWebSocket.test.tsx
M	webui/src/hooks/useWebSocket.ts
M	webui/src/i18n/en.ts
M	webui/src/i18n/ja.ts
M	webui/src/i18n/zh.ts
M	webui/src/index.css
M	webui/src/pages/BrowsePage.test.tsx
M	webui/src/pages/BrowsePage.tsx
??	webui/src/pages/DetailPage.css
M	webui/src/pages/DetailPage.test.tsx
M	webui/src/pages/DetailPage.tsx
??	webui/src/pages/GalleryCollectionPage.tsx
??	webui/src/pages/GalleryFavoritesPage.tsx
??	webui/src/pages/GalleryHomePage.test.tsx
??	webui/src/pages/GalleryHomePage.tsx
M	webui/src/pages/LandingPage.test.tsx
M	webui/src/pages/LandingPage.tsx
M	webui/src/pages/ShareReceivePage.test.tsx
M	webui/src/stores/AuthContext.tsx
M	webui/src/stores/RealtimeContext.test.tsx
M	webui/src/stores/RealtimeContext.tsx
M	webui/src/types/api.ts
```

## Batch 7 — WebUI Storefront / Seller

```text
??	webui/e2e/commerce-buyer.spec.ts
??	webui/e2e/commerce-real-backend.spec.ts
??	webui/e2e/seller.spec.ts
??	webui/e2e/webui-shell.spec.ts
??	webui/src/api/favorites.contract.test.ts
??	webui/src/api/favorites.ts
??	webui/src/api/gallery.contract.test.ts
??	webui/src/api/gallery.ts
??	webui/src/api/shop.contract.test.ts
??	webui/src/api/shop.ts
??	webui/src/components/storefront/BuyerDeliveryDownloadButton.test.tsx
??	webui/src/components/storefront/BuyerDeliveryDownloadButton.tsx
??	webui/src/components/storefront/LegacyAssetCard.tsx
??	webui/src/components/storefront/ProductCard.tsx
??	webui/src/components/storefront/SellerAccessGate.tsx
??	webui/src/components/storefront/SellerGalleryEditor.test.tsx
??	webui/src/components/storefront/SellerGalleryEditor.tsx
??	webui/src/components/storefront/ShopBuyerContext.test.tsx
??	webui/src/components/storefront/ShopBuyerContext.tsx
??	webui/src/components/storefront/Storefront.css
??	webui/src/components/storefront/StorefrontShell.test.tsx
??	webui/src/components/storefront/StorefrontShell.tsx
??	webui/src/components/storefront/types.ts
??	webui/src/hooks/useCommerce.test.ts
??	webui/src/hooks/useCommerce.ts
??	webui/src/hooks/useFavorites.test.tsx
??	webui/src/hooks/useFavorites.ts
??	webui/src/hooks/useQuota.test.tsx
??	webui/src/hooks/useQuota.ts
??	webui/src/pages/LegacyStorefrontGalleryPage.test.tsx
??	webui/src/pages/LegacyStorefrontGalleryPage.tsx
??	webui/src/pages/LegacyStorefrontItemPage.test.tsx
??	webui/src/pages/LegacyStorefrontItemPage.tsx
??	webui/src/pages/SellerDashboardPage.test.tsx
??	webui/src/pages/SellerDashboardPage.tsx
??	webui/src/pages/SellerLoginPage.test.tsx
??	webui/src/pages/SellerLoginPage.tsx
??	webui/src/pages/SellerOrdersPage.test.tsx
??	webui/src/pages/SellerOrdersPage.tsx
??	webui/src/pages/SellerProductsPage.test.tsx
??	webui/src/pages/SellerProductsPage.tsx
??	webui/src/pages/SellerSettingsPage.test.tsx
??	webui/src/pages/SellerSettingsPage.tsx
??	webui/src/pages/StorefrontBuyerOrdersPage.test.tsx
??	webui/src/pages/StorefrontBuyerOrdersPage.tsx
??	webui/src/pages/StorefrontCartPage.tsx
??	webui/src/pages/StorefrontCheckoutGroupPage.test.tsx
??	webui/src/pages/StorefrontCheckoutGroupPage.tsx
??	webui/src/pages/StorefrontCheckoutPage.test.tsx
??	webui/src/pages/StorefrontCheckoutPage.tsx
??	webui/src/pages/StorefrontDeliveryPage.test.tsx
??	webui/src/pages/StorefrontDeliveryPage.tsx
??	webui/src/pages/StorefrontMediaFallback.test.tsx
??	webui/src/pages/StorefrontPage.tsx
??	webui/src/pages/StorefrontProductPage.test.tsx
??	webui/src/pages/StorefrontProductPage.tsx
??	webui/src/pages/StorefrontProductsPage.test.tsx
??	webui/src/pages/StorefrontProductsPage.tsx
??	webui/src/pages/StorefrontWishlistPage.test.tsx
??	webui/src/pages/StorefrontWishlistPage.tsx
??	webui/src/stores/SellerAuthContext.test.tsx
??	webui/src/stores/SellerAuthContext.tsx
```

## Batch 8 — CI / docs / tooling

```text
M	.github/workflows/ci.yml
M	AssetManager.spec
M	webui/package-lock.json
M	README.md
M	requirements-dev.txt
M	run.py
??	docs/archive/2026-09/compose-reports/webui-migration-batch-commit-plan-2026-08-08.md
??	docs/archive/2026-09/compose-reports/webui-migration-ownership-manifest-2026-08-08.md
??	docs/session-handoff-2026-08-08-second-to-first.md
M	ruff.toml
M	scripts/check_package_contents.py
M	tests/core/test_package_contents.py
M	tests/core/test_packaging_entrypoints.py
```

## Cross-domain — Playwright config (stage once)

```text
M	webui/playwright.config.ts
```

## Cross-domain — tracked hunk staging required

```text
M	AssetsManager/application/bootstrap.py
M	AssetsManager/application/file_operation_service.py
M	AssetsManager/application/library_service.py
M	AssetsManager/application/runtime.py
M	AssetsManager/core/database.py
```

## Exclude — temporary/local artifacts

```text
??	tmp/node-repl-test.txt
??	tmp/server.diff
??	webui/test-results/.last-run.json
```

## Out of WebUI scope — existing docs/evidence

```text
M	DeepSeek Docs/01-项目总览与架构.md
M	DeepSeek Docs/02-入口与启动链路.md
M	DeepSeek Docs/03-应用服务层.md
M	DeepSeek Docs/05-领域层与数据访问层.md
M	DeepSeek Docs/09-端到端数据流.md
M	DeepSeek Docs/10-风险与改进建议.md
M	DeepSeek Docs/README.md
M	DeepSeek Docs/前后端分离改造计划/02-推荐实施计划.md
M	DeepSeek Docs/前后端分离改造计划/03-验收标准与风险预案.md
M	DeepSeek Docs/功能缺口分析/03-应用服务与数据层.md
M	DeepSeek Docs/功能缺口分析/06-安全与可靠性.md
M	DeepSeek Docs/功能缺口分析/07-优先级路线图.md
M	DeepSeek Docs/功能缺口分析/README.md
M	DeepSeek Docs/施行路线图.md
M	DeepSeek Docs/架构与设计评价/02-后端架构评价.md
M	DeepSeek Docs/架构与设计评价/05-可扩展性与演进方向.md
M	DeepSeek Docs/架构与设计评价/06-前后端分离深度分析.md
M	docs/adr/0003-library-runtime.md
M	docs/architecture-diagram.md
M	docs/architecture.md
??	docs/compose/handoffs/assetsmanager-mainline-session-04-2026-08-04/05-start-prompt.md
??	docs/compose/handoffs/assetsmanager-mainline-session-04-2026-08-04/README.md
??	docs/compose/handoffs/desktop-ui-session-03-2026-08-04/01-current-state.md
??	docs/compose/handoffs/desktop-ui-session-03-2026-08-04/02-scope-and-file-ownership.md
??	docs/compose/handoffs/desktop-ui-session-03-2026-08-04/03-task-backlog.md
??	docs/compose/handoffs/desktop-ui-session-03-2026-08-04/04-verification-and-acceptance.md
??	docs/compose/handoffs/desktop-ui-session-03-2026-08-04/05-start-prompt.md
??	docs/compose/handoffs/desktop-ui-session-03-2026-08-04/README.md
M	docs/archive/2026-09/compose-reports/a3-service-assembly-2026-08-02.md
??	docs/archive/2026-09/compose-reports/b1-runtime-sharing-2026-08-03.md
??	docs/archive/2026-09/compose-reports/g10-project-session-binding-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g11-core-store-session-binding-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g12-auth-share-session-contract-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g13-auth-share-repository-session-binding-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g14-auth-share-strict-repository-hardening-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g15-metadata-repository-session-binding-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g16-tag-repository-session-binding-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g17-1-asset-index-generation-cas-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g17-10-runtime-cutover-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-11-queue-generation-cas-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-12-per-task-claim-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-13-per-task-completion-cas-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-14-enqueue-upsert-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-15-recovery-busy-retry-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-16-cross-process-wakeup-conflict-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-17-a-b-schema-token-roundtrip-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-17-c-claim-token-generation-2026-08-08.md
??	docs/archive/2026-09/compose-reports/g17-17-claim-identity-plan-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-17-d-worker-token-cas-2026-08-08.md
??	docs/archive/2026-09/compose-reports/g17-17-e-worker-lease-renewal-2026-08-08.md
??	docs/archive/2026-09/compose-reports/g17-17-f-cutover-cross-process-plan-2026-08-08.md
??	docs/archive/2026-09/compose-reports/g17-2-schema-contract-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g17-3-asset-index-publish-result-retry-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g17-4-transaction-finality-degraded-observability-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g17-5-refresh-warning-reconciliation-contract-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-6-desktop-warning-consumption-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-7-2-runtime-worker-lifecycle-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-7-3-worker-failure-restart-marker-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-7-4-caller-inventory-marker-ownership-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-7-final-closure-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-7-reconciliation-queue-phase-1-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-8-worker-supervisor-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-9-sqlite-reconciliation-queue-foundation-2026-08-07.md
??	docs/archive/2026-09/compose-reports/g17-asset-index-session-binding-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g17-stop-the-world-cutover-release-ownership-checklist-2026-08-08.md
??	docs/archive/2026-09/compose-reports/g3e-raw-connection-compat-2026-08-05.md
??	docs/archive/2026-09/compose-reports/g4-schema-lifecycle-2026-08-05.md
??	docs/archive/2026-09/compose-reports/g5-search-error-contract-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g6-1-backup-validation-2026-08-04.md
??	docs/archive/2026-09/compose-reports/g6-1-metadata-export-2026-08-04.md
??	docs/archive/2026-09/compose-reports/g6-1-orphan-quarantine-2026-08-04.md
??	docs/archive/2026-09/compose-reports/g6-1-product-entry-contract-2026-08-04.md
??	docs/archive/2026-09/compose-reports/g6-1-restore-2026-08-04.md
??	docs/archive/2026-09/compose-reports/g6-5-database-integrity-2026-08-03.md
??	docs/archive/2026-09/compose-reports/g6-6-security-preflight-contract-2026-08-04.md
??	docs/archive/2026-09/compose-reports/g6-6-security-preflight-implementation-2026-08-04.md
??	docs/archive/2026-09/compose-reports/g6-lan-fallback-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g7-p1-safety-and-info-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g8-repository-error-contract-2026-08-06.md
??	docs/archive/2026-09/compose-reports/g9-search-result-set-2026-08-06.md
??	docs/archive/2026-09/compose-reports/mainline-audit-followup-2026-08-05.md
??	docs/archive/2026-09/compose-reports/mainline-parallel-batch-2026-08-04.md
??	docs/archive/2026-09/compose-reports/real-image-io-directory-benchmark-protocol-2026-08-04.md
M	docs/archive/2026-09/compose-reports/repository-followup-review-2026-08-01.md
M	docs/lan-security.md
M	docs/migrations.md
```

## Out of WebUI scope — existing mainline/other engineering

```text
M	AssetsManager/application/__init__.py
M	AssetsManager/application/asset_index_service.py
M	AssetsManager/application/asset_service.py
M	AssetsManager/application/auth_service.py
M	AssetsManager/application/context.py
??	AssetsManager/application/gallery_service.py
M	AssetsManager/application/metadata_service.py
M	AssetsManager/application/project_service.py
M	AssetsManager/application/runtime_events.py
M	AssetsManager/application/search_service.py
??	AssetsManager/application/security_preflight.py
M	AssetsManager/application/share_service.py
M	AssetsManager/application/tag_service.py
M	AssetsManager/application/thumbnail_service.py
M	AssetsManager/controllers/info_controller.py
M	AssetsManager/core/directory_cache.py
M	AssetsManager/core/library_lock.py
M	AssetsManager/core/path_resolver.py
M	AssetsManager/core/project_data.py
??	AssetsManager/core/session_contract.py
M	AssetsManager/core/settings.py
M	AssetsManager/core/tag_store.py
M	AssetsManager/dialogs/generic_settings_dialog.py
M	AssetsManager/dialogs/plugin_manager_dialog.py
M	AssetsManager/dialogs/settings_dialog.py
M	AssetsManager/dialogs/sharing_settings_dialog.py
M	AssetsManager/dialogs/sidebar_settings_dialog.py
M	AssetsManager/dialogs/startup.py
M	AssetsManager/dialogs/tabbed_dialog.py
M	AssetsManager/dock_factory.py
M	AssetsManager/domain/errors.py
M	AssetsManager/domain/events.py
M	AssetsManager/i18n/en.json
M	AssetsManager/i18n/ja.json
M	AssetsManager/i18n/zh.json
M	AssetsManager/lan/__init__.py
M	AssetsManager/lan/dto.py
M	AssetsManager/lan/manager.py
M	AssetsManager/lan/routes/downloads.py
??	AssetsManager/lan/routes/image.py
M	AssetsManager/lan/routes/metadata.py
M	AssetsManager/lan/routes/pages.py
??	AssetsManager/lan/routes/quicksearch.py
M	AssetsManager/lan/routes/system.py
M	AssetsManager/lan/routes/tags.py
M	AssetsManager/lan/tunnel.py
M	AssetsManager/lan/ws.py
M	AssetsManager/panels/empty.py
M	AssetsManager/panels/file_list/_actions.py
M	AssetsManager/panels/file_list/_base.py
M	AssetsManager/panels/file_list/_model.py
M	AssetsManager/panels/file_list/_navigation.py
M	AssetsManager/panels/info.py
M	AssetsManager/repositories/asset_index_repository.py
M	AssetsManager/repositories/auth_repository.py
M	AssetsManager/repositories/metadata_repository.py
M	AssetsManager/repositories/plugin_metadata_repository.py
M	AssetsManager/repositories/share_repository.py
M	AssetsManager/repositories/tag_repository.py
M	AssetsManager/repositories/thumbnail_repository.py
??	AssetsManager/widgets/command_palette.py
??	AssetsManager/widgets/file_picker.py
M	AssetsManager/widgets/lan_sharing.py
??	AssetsManager/widgets/pager_overlay.py
??	AssetsManager/widgets/shortcut_manager.py
??	AssetsManager/widgets/status_bar.py
??	AssetsManager/widgets/status_indicator.py
??	AssetsManager/widgets/stylekit.py
M	AssetsManager/widgets/tag_chip.py
??	AssetsManager/widgets/theme_gallery.py
M	AssetsManager/widgets/title_bar.py
M	AssetsManager/widgets/toast.py
M	AssetsManager/window.py
M	tests/core/test_database_metadata.py
M	tests/core/test_directory_cache.py
M	tests/core/test_path_resolver.py
M	tests/core/test_settings.py
M	tests/core/test_tag_store.py
??	tests/desktop/test_command_palette.py
M	tests/desktop/test_file_list_model.py
M	tests/desktop/test_file_list_shim.py
??	tests/desktop/test_file_picker.py
M	tests/desktop/test_info_async_identity.py
??	tests/desktop/test_library_stats.py
??	tests/desktop/test_pager_overlay.py
M	tests/desktop/test_scoped_service_access.py
M	tests/desktop/test_sharing_settings_dialog.py
??	tests/desktop/test_shortcut_manager.py
??	tests/desktop/test_status_bar.py
??	tests/desktop/test_status_indicator.py
??	tests/desktop/test_stylekit.py
M	tests/desktop/test_tabbed_dialog_visuals.py
??	tests/desktop/test_tag_chip.py
??	tests/desktop/test_theme_gallery.py
??	tests/desktop/test_toast_and_empty_visuals.py
M	tests/e2e/test_webui_realtime_acceptance.py
??	tests/fixtures/db/v1_schema.sql
??	tests/integration/test_asset_index_repository_session_binding.py
M	tests/integration/test_asset_index_service.py
M	tests/integration/test_asset_service.py
M	tests/integration/test_auth_service.py
??	tests/integration/test_auth_share_session_binding.py
??	tests/integration/test_favorite_file_operations.py
??	tests/integration/test_favorite_service.py
M	tests/integration/test_file_operation_service.py
??	tests/integration/test_gallery_service.py
M	tests/integration/test_library_service.py
??	tests/integration/test_metadata_repository_session_binding.py
M	tests/integration/test_metadata_service.py
M	tests/integration/test_project_service.py
??	tests/integration/test_project_service_session_binding.py
M	tests/integration/test_repositories.py
??	tests/integration/test_repository_session_binding.py
M	tests/integration/test_runtime_events.py
??	tests/integration/test_search_result_set_contract.py
M	tests/integration/test_search_service.py
M	tests/integration/test_share_service.py
??	tests/integration/test_tag_repository_session_binding.py
M	tests/integration/test_tag_service.py
M	tests/integration/test_thumbnail_service.py
M	tests/integration/test_window_lifecycle_lan_failure.py
??	tests/lan/support/__init__.py
??	tests/lan/support/legacy_runtime_adapter.py
??	tests/lan/test_favorite_routes.py
??	tests/lan/test_gallery_routes.py
??	tests/lan/test_image_routes.py
M	tests/lan/test_lan_api.py
??	tests/lan/test_metadata_tag_mutation_routes.py
??	tests/lan/test_quicksearch_routes.py
M	tests/lan/test_runtime_realtime.py
??	tests/lan/test_search_status_route.py
??	tests/lan/test_security_preflight_integration.py
??	tests/lan/test_security_preflight_internal.py
M	tests/lan/test_server_lifecycle.py
??	tests/lan/test_share_manager_tunnel_failures.py
??	tests/lan/test_tunnel_security.py
??	tests/perf/real_io_directory_benchmark.py
M	tests/performance/test_baselines.py
M	tests/unit/test_architecture_boundaries.py
??	tests/unit/test_auth_repository_error_contract.py
M	tests/unit/test_bootstrap.py
M	tests/unit/test_info_controller.py
M	tests/unit/test_lan_sharing.py
M	tests/unit/test_library_runtime.py
??	tests/unit/test_library_service.py
??	tests/unit/test_plugin_metadata_repository_lifecycle.py
M	tests/unit/test_project_data.py
??	tests/unit/test_quicksearch_service.py
??	tests/unit/test_security_preflight.py
??	tests/unit/test_share_repository_error_contract.py
??	tests/unit/test_tag_repository_error_contract.py
```

## 手工处理重点

以下 tracked 文件不能使用整文件 staging：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\db_migrations.py  # Batch 1 + Batch 3
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\bootstrap.py  # G17 + existing runtime wiring
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\runtime.py  # G17 + existing runtime wiring
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\database.py  # migration/G17 + existing database changes
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\library_service.py  # restore/G17 + existing service changes
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\file_operation_service.py  # restore/G17 + existing service changes
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\playwright.config.ts  # Batch 7 + Batch 8, stage once
```

## 额外 hunk 审查候选

以下文件在主批次中有明确归属，但同时包含旧主线、兼容层或多个功能域的修改；实际提交时应先查看 hunk，再决定是否纳入：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\__init__.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\__init__.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\dto.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\principal.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\system.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\index.css
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\README.md
```

当前清单没有执行任何 staging 或提交。

## 2026-08-08 hunk-audit addendum (no staging)

当前 manifest 中“`AssetsManager/core/db_migrations.py` = Batch 1 + Batch 3”描述的是历史/逻辑归属，不应直接当作可执行的普通 `git add -p` 配方。只按 Commerce 版本和 G17 版本拆开会使 `schema_migrations` 注册项不连续；后续 `_validate_history()` 会拒绝该中间状态。

安全执行规则：

1. `AssetsManager/core/schema_defs.py` 与 `AssetsManager/core/db_migrations.py` 作为完整 Schema migration spine 一起审查；若按提交顺序要求每个 commit 可运行，完整 v1–v22 registry、contract 和 runner 校验应在同一前置 Schema 批次中保持连续。
2. `db_migrations.py` 的 309 行新增 migration 大 hunk、registry hunk 和 `required_objects` hunk 不得粗暴整块归入 Commerce 或 G17；若必须保留历史会话归属，先创建独立 Schema spine prerequisite，再 stage G17 application/runtime 文件。
3. 本轮没有 stage/commit；上述规则只更新归属解释，不改变现有工作区文件的代码内容。

### 2026-08-08 test-hardening addendum

已完成最小测试修复但未 stage：v14 正向边界、v15 正向边界、v22 compatible/incompatible existing-table 与 rollback。四文件定向组合为 `71 passed`，目标测试 Ruff 通过。该修复只增加/调整测试，不覆盖或回滚已有生产迁移代码。

### 2026-08-08 legacy-boundary hardening addendum

深度审查发现并最小修复了旧 v8/v17 `shop_orders` 在 v18 owner migration 前被当前 contract 错误拒绝的问题，并覆盖 cart/reconciliation boundary 的 current-or-legacy contract 校验。新增 legacy upgrade 回归后，migration/schema 定向组合为 `72 passed`，目标 Ruff/pyright 均通过。生产代码修改仍只在旧项目工作区，未 stage/commit。

### 2026-08-08 full Python verification addendum

legacy-boundary 修复后重新运行完整 Python 测试集：`2716 passed, 7 skipped, 1 warning`。未 stage/commit，工作区混合 dirty 状态保持不变。

### 2026-08-08 deferred-index addendum

旧 Commerce 表升级时，v8/v16 的 future index 不能在列尚未由 v18/v19 migration 补齐时直接执行；已增加最小 deferred-index 保护并用 legacy regression 覆盖。完整 Python 回归仍为 `2716 passed, 7 skipped, 1 warning`。

### 2026-08-08 migration behavior hardening addendum

新增 v13/v20/v22 constraint/FK/index 行为测试，并使 v18 legacy owner upgrade 真正包含旧订单、验证不回填。定向组合 `74 passed`，完整 Python `2718 passed, 7 skipped, 1 warning`；仍未 stage/commit。

### 2026-08-08 bootstrap/runtime hunk-audit addendum

`bootstrap.py` / `runtime.py` 已完成只读 hunk 归属审查：G17 runtime/ownership、Batch 2 restore/integrity、LAN/Favorite/Gallery/session wiring 相互交错；不得整文件 staging。重点人工边界为 `bootstrap.py:407–520`、`352–387`、`564–585`、`529–562` 与 `runtime.py:51–117`。

### 2026-08-08 database/library/file-operation hunk-audit addendum

完成 `database.py`、`library_service.py`、`file_operation_service.py` 逻辑归属预演：三者均混合 G17 ownership、Batch 2 restore/integrity、文件操作/主线 wiring，禁止整文件 staging。建议先 Schema spine，再 Batch 2，再 G17，最后做跨域调用方回归。

### 2026-08-08 precise cross-domain staging map

已追加 `database.py`、`library_service.py`、`file_operation_service.py` 的逻辑区间 staging map。三者均存在 mixed hunk；任何整文件 `git add` 都会跨越 G17、Batch 2、Schema 或主线 API 边界，因此继续保持 `0 staged`。

### 2026-08-08 dependency-graph addendum

确认 Batch 2/3 共同依赖 `DatabaseManager` managed connection、`db_write_lock` 与 `RootIdentity`。长期提交计划增加 Core ownership foundation 作为 Schema spine 后、Batch 2/3 前的审查边界；当前不执行 staging。

### 2026-08-08 Core ownership foundation addendum

修复 `LibraryContext.root_identity` 对空 `root_key` 的 legacy/manual context 缺口；canonical owner contract 未改变。新增回归后 Core ownership/session 定向组合 `119 passed`，Ruff/Pyright 均通过。

### 2026-08-08 full regression addendum

`LibraryContext.root_identity` fallback 修复后完整 Python 回归为 `2719 passed, 7 skipped, 1 warning`；Core ownership/session 定向为 `119 passed`。工作区仍保持 0 staged。


## 2026-08-08 deep lifecycle audit addendum (continued, no staging)

本轮在既有 migration/WebUI 归属审查基础上继续完成 G17 runtime/ownership、DatabaseManager 和 file-operation clean-boundary 的深度检查。工作区仍保持：

```text
471 status entries
187 tracked modifications
284 untracked entries
0 staged
```

未执行 `git reset`、`git clean`、`git add` 或 `git commit`；`AssetsManager_New_WebUI` 仍仅作为只读参考。

### 本轮最小修复（均未 stage）

1. `AssetsManager/application/bootstrap.py`
   - `_build_services()` 改用 `session.context.root_identity`，不再直接从可能为空的 `root_key` 构造 `RootIdentity`；
   - runtime 构建在 session live 检查后、`_runtime_lock` 保护下启动 reconciliation worker，再发布 runtime，避免 close/start race；
   - runtime 构建或 reconciliation `start()` 失败时，主动关闭临时 Runtime，保留 session 可重试；
   - 新增 manual/legacy context identity 与 reconciliation startup failure 回归。

2. `AssetsManager/core/database.py`
   - thumbnail directory 在 managed SQLite connection 发布前创建；目录创建失败不会残留 manager/global connection registry；
   - `validate_connection_owner()` / `require_managed_connection_owner()` 对已标记 `closed` 的 managed connection fail-closed，返回 cleanup-pending；
   - 新增对应失败路径和 owner lifecycle 回归。

3. `AssetsManager/application/file_operation_service.py`
   - `delete_permanent()` 和 `delete_to_trash()` 在文件系统变更前复用 clean transaction boundary；调用方已有 outer SQLite transaction 时拒绝执行，避免“文件已删除、projection 仍可 rollback”的跨系统不一致；
   - 新增 permanent/trash 两种路径的回归。

### 定向验证

```text
bootstrap/runtime/reconciliation：81 passed
Database metadata/migration/concurrency：83 passed
File operation/favorites/event：61 passed
Ruff（本轮目标文件）：通过
Pyright（AssetsManager/application/bootstrap.py）：0 errors, 0 warnings, 0 informations
```

全量 Python 回归本轮首次运行得到：

```text
2724 passed, 7 skipped, 1 failed, 1 warning
```

失败为 `tests/lan/test_server_lifecycle.py::test_startup_cleanup_base_exception_retains_owner_thread_until_stop_retry[cleanup_error1]`；该测试随后单独两参数运行 `2 passed`，完整 `tests/lan/test_server_lifecycle.py` 运行 `39 passed`，判定为现有 LAN 生命周期测试的时序性 flaky failure，而非本轮修改的直接失败。后续若要宣称全量绿，仍应再执行一次完整回归确认。

### 仍保留为后续长期任务的真实风险

这些问题已确认但本轮没有扩大修复范围，必须在长期计划中保持可见：

- `DatabaseManager.migrate_path_metadata()` 同时移动 thumbnail 文件和提交 SQLite 事务，文件系统 rename 与 SQLite commit 不具备原子性；需要后续设计补偿/可重建 cache 策略，并覆盖 thumbnail rows + outer rollback/commit failure；
- `migrate_path_metadata(conn, thumb_dir, ...)` 目前没有验证 managed connection 与 thumbnail directory 是否属于同一 library；
- explicit connection write lock 与 legacy global write lock 的 reader→writer upgrade、多个 connection 的反向嵌套顺序；
- 多个 `DatabaseManager` 可打开同一 root，各自拥有独立 per-connection lock；“每 root 一个 connection/lock”目前是 canonical `LibraryService` invariant，不是 DatabaseManager 自身强制；
- orphan cleanup 与 open/restore 的 TOCTOU admission；
- `_build_services()` 已创建的 canonical `AssetIndexService` 与 LAN projection 可能重复实例化；该项属于低风险一致性优化，尚未为避免扩大测试 monkeypatch 面而改动；
- delete/trash clean-boundary 已修复，但 move/copy/restore 与 projection/file-system 其他跨系统边界仍需专项审计。

### 安全 staging 顺序更新

后续手工 staging 时：

1. Schema spine (`schema_defs.py` + 完整 `db_migrations.py`)；
2. Core ownership foundation（`context.py`、`database.py` managed owner/close 子集、`library_service.py` canonical lifecycle 子集）；
3. G17 runtime/bootstrap/race cleanup 子集；
4. Batch 2 file-operation/projection clean-boundary 子集；
5. Commerce/WebUI 新增文件及其契约测试；
6. 最后再处理 docs/evidence 与临时产物排除。

上述顺序只是人工 `git add -p` 规划，当前继续保持 `0 staged`，不得整文件 stage 混合域文件。


### Full regression follow-up after the audit fixes

在上述首次全量运行出现一次 LAN lifecycle 时序失败后，立即再次运行完整 Python 回归，结果为：

```text
2725 passed, 7 skipped, 1 warning
```

同时，`tests/lan/test_server_lifecycle.py` 单独运行结果为 `39 passed`；当前以第二次完整回归作为本轮最终基线。warning 仍为测试构造重复 ZIP entry 的既有 `UserWarning`，7 个 skip 均为 Windows symlink/spawn 能力边界。


## 2026-08-08 Commerce/WebUI hunk ledger consistency audit (no staging)

### 1. Manifest completeness check

针对当前工作区的 `AssetsManager/`、`webui/`、`tests/`、`.github/`、`README.md`、`ruff.toml` 和交接文档相关状态项进行了机械比对：

```text
relevant status paths：383
ownership manifest 未列出的 relevant path：0
Batch 4–7 跨 batch 重复归属：0
当前 staged：0
```

因此当前 manifest 没有发现遗漏文件或同一文件被错误分配到多个功能批次的问题。以下内容仍必须排除：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tmp\node-repl-test.txt
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tmp\server.diff
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\test-results\.last-run.json
```

### 2. Commerce backend dependency ledger

Commerce 后端不应按目录直接 staging，安全依赖顺序为：

```text
Schema spine
  → Core ownership foundation
  → shop_repository.py
  → domain repositories
  → application services
  → commerce policy/helpers
  → route handlers
  → routes/__init__.py exports
  → lan/api.py registration
  → lan/server.py middleware/runtime binding
```

核心文件归属：

- Storefront：
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_authorization.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\storefront_analytics_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\shop_repository.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\storefront_analytics_repository.py`
- Cart/Wishlist：
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_buyer_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\shop_buyer_repository.py`
- Checkout/Orders：
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\order_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\order_repository.py`
  - 与 `shop_buyer_service.py` 共享 checkout/cart 转换逻辑。
- Delivery：
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\quota_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\free_download_quota_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\quota_repository.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\free_download_quota_repository.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\downloads.py` 的相关 quota hunk。
- Seller：
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\seller_auth_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\seller_profile_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\seller_profile_repository.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_service.py` 的 seller-only 函数族。
- LAN Commerce：
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\commerce_policy.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\shop.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\seller_auth.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\seller_profile.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\api.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\__init__.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\server.py` 的 public-path/auth/runtime hunk。

明确的 mixed 文件：

```text
AssetsManager/application/order_service.py
AssetsManager/lan/routes/shop.py
AssetsManager/lan/api.py
AssetsManager/lan/routes/__init__.py
AssetsManager/lan/server.py
AssetsManager/application/bootstrap.py
AssetsManager/core/database.py
```

这些文件不得整文件归入单一 Commerce 批次或整文件 staging。特别是 `shop.py` 同时承载 Storefront、Cart/Wishlist、Checkout、Orders、Delivery、Seller 六个域；`order_service.py` 同时承载 Orders、Checkout、Delivery 和 Seller fulfill/revoke。

### 3. WebUI route/API closure check

当前 `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\App.tsx` 已覆盖交接文档中的主要路由：

```text
/storefront
/storefront/products
/storefront/product/:id
/storefront/cart
/storefront/wishlist
/storefront/orders
/storefront/checkout/:orderId
/storefront/checkout/group
/storefront/delivery/:token
/store
/store/gallery/:tag
/store/checkout
/store/delivery/:token
/store/*
/seller
/seller/products
/seller/products/new
/seller/products/:id
/seller/orders
/seller/settings
/app
/app/items
/app/orders
```

前端 Commerce API 静态路径与 `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\api.py` 的注册结果一致；动态路径包括：

```text
shop/items/{item_id} (GET public active-only；PUT/DELETE seller-only)
shop/cart/items/{line_id}
shop/wishlist/items/{item_id}
shop/order/{order_id}/...
shop/cart/checkout/{checkout_group_id}
shop/delivery/{token}/...
```

对应的前端 API/契约测试集中在：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\shop.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\shop.contract.test.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\hooks\useCommerce.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\hooks\useCommerce.test.ts
```

Seller/Buyer 页面与测试成对存在，真实浏览器验收文件仍保留：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\commerce-buyer.spec.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\commerce-real-backend.spec.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\webui-shell.spec.ts
```

### 4. 当前需要继续关注的共享边界

1. `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\shop.py` 通过 `get_commerce_services()` lazy 组装 Commerce service；下一轮需确认其 lifetime 与 `LibraryRuntime` close 的清理顺序。
2. `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\server.py::connection_for()` 仍使用 `Path.resolve()` 做 active-root 比较，而 Core ownership 使用 `RootIdentity.map_key`；当前 canonical 路径工作正常，但应在正式提交前统一 ownership boundary 或补充明确的兼容说明。
3. `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\downloads.py` 是 Delivery 与既有下载功能的 mixed tracked file，只能按函数/hunk staging。
4. Gallery favorites (`favorite_*`) 与 Commerce wishlist (`shop_buyer_*`) 是不同 schema、owner 和 API，不得按名称合并。

本次只完成 ledger 与一致性核验，没有扩大到上述 shared-lifecycle 重构，也没有执行 staging/commit。

## 2026-08-08 WebUI concurrency and deep-link audit addendum (no staging)

本轮继续对 Commerce/WebUI 迁移代码做运行时竞态与深链生命周期审查。仅在 `D:/~Vibe-Coding/Projects/AssetsManager_old-bak` 内修改；参考源 `D:/~Vibe-Coding/Projects/AssetsManager_New_WebUI` 未修改。当前工作区仍保持：

```text
471 status entries
187 tracked modifications
284 untracked entries
0 staged
```

### 本轮最小修复（均未 stage）

1. `webui/src/components/storefront/ShopBuyerContext.tsx`
   - 将 cart、wishlist、refresh、merge、checkout 等 buyer-state 操作纳入同一代次感知的串行队列，避免 refresh/merge 响应覆盖较新的 cart version；
   - 身份代次切换时断开旧队列并清空 `cartRef`，新身份不会继承上一身份的 version；
   - refresh/merge loading 使用 request id + identity guard，旧请求的 `finally` 不会提前清除新请求的 loading；
   - clear/checkout/wishlist mutation 在响应返回后再次校验身份，stale response 不再向调用方返回旧身份结果。

2. `webui/src/components/storefront/ShopBuyerContext.test.tsx`
   - 新增 stale identity refresh regression；
   - 新增连续 cart mutation version serialization regression；
   - 当前文件共 4 个测试通过。

3. `webui/src/pages/StorefrontProductPage.tsx` 与 `webui/src/pages/StorefrontProductPage.test.tsx`
   - catalog 首次加载期间显示 loading，不再立即误报 product not found；
   - catalog 请求失败显示 retryable error，不再把网络错误伪装为商品不存在；
   - 只有 catalog settled 且没有匹配商品时才显示 not found；
   - 新增 loading/error/settled match/settled miss 四个页面级回归。

4. `webui/src/i18n/en.ts`、`webui/src/i18n/ja.ts`、`webui/src/i18n/zh.ts`
   - 为产品 loading/error 状态补齐三种语言的文案，保持 i18n contract 完整。

### 验证结果

```text
WebUI targeted ShopBuyerContext：4 passed
WebUI targeted StorefrontProductPage：4 passed
WebUI full Vitest：82 test files passed，538 tests passed
TypeScript typecheck：通过
WebUI build：通过
Playwright Mock/Shell：4 passed
LAN Commerce targeted：237 passed
Python full regression：2725 passed，7 skipped，1 warning
```

### 新确认但暂不扩大修复范围的长期风险

- 公开 Commerce catalog 当前默认最多返回 500 个 active 商品；该上限仍影响列表/搜索覆盖，但 numeric `/storefront/product/:id` 已通过 active-only detail endpoint 绕过列表上限。
- active-only 单商品 detail API 已补齐并复用 public DTO；draft/archived/未授权路径统一按 not-found 处理。后续仍需决定是否支持非 numeric slug/path 深链。
- Wishlist、Delivery、Seller 页面仍需继续补齐默认 E2E 与页面级覆盖；真实后端 Commerce E2E 仍可由环境变量整体 skip。

本轮未执行 `git add`、stage、commit、reset 或 clean；后续仍按 Batch 1→8 和 mixed-file hunk ledger 手工 staging。
## 2026-08-08 public Commerce item detail follow-up (no staging)

上一轮确认的 catalog limit=500 深链缺口已完成最小安全闭环：

- `D:/~Vibe-Coding/Projects/AssetsManager_old-bak/AssetsManager/application/shop_service.py` 新增 active-only public item lookup；非 active、disabled、未授权路径和不存在的 item 不泄漏存在性，统一返回 not-found。
- `D:/~Vibe-Coding/Projects/AssetsManager_old-bak/AssetsManager/lan/routes/shop.py`、`D:/~Vibe-Coding/Projects/AssetsManager_old-bak/AssetsManager/lan/api.py`、`D:/~Vibe-Coding/Projects/AssetsManager_old-bak/AssetsManager/lan/routes/__init__.py` 新增 `GET /api/shop/items/{item_id}` 公共详情路由。
- `D:/~Vibe-Coding/Projects/AssetsManager_old-bak/webui/src/api/shop.ts` 新增 `getItem()`；`D:/~Vibe-Coding/Projects/AssetsManager_old-bak/webui/src/pages/StorefrontProductPage.tsx` 在 catalog settled 且 numeric ID 未命中时回退详情 API。

验证：
```text
Commerce/backend targeted：53 passed
WebUI detail/API targeted：16 passed
WebUI full Vitest：82 test files passed，539 tests passed
TypeScript typecheck：通过
WebUI build：通过
Python full regression：2728 passed，7 skipped，1 warning
Ruff target files：通过
```

剩余风险：catalog limit 仍影响目录列表本身；当前详情 fallback 只对 numeric ID 生效，`slug/path` 深链仍需明确产品契约；Wishlist/Delivery/Seller 默认 E2E 与页面级覆盖仍未完全补齐。

本轮仍未执行 `git add`、stage、commit、reset 或 clean。
## 2026-08-08 product detail response-race follow-up (no staging)

`D:/~Vibe-Coding/Projects/AssetsManager_old-bak/webui/src/pages/StorefrontProductPage.test.tsx` 新增 route-change stale response 回归：

- 商品 ID 7 的详情请求尚未返回时切换到商品 ID 8；
- 旧商品响应返回后不得渲染到当前路由；
- 新商品响应返回后才允许渲染当前详情。

最新验证：
```text
StorefrontProductPage targeted：6 passed
WebUI full Vitest：82 test files passed，540 tests passed
TypeScript typecheck：通过
```

工作区仍为 471 / 187 / 284 / 0，manifest path closure 471/471，未执行 staging 或 commit。
## 2026-08-08 Wishlist/Delivery page coverage follow-up (no staging)

新增两个 Batch 7 页面级回归文件：

- `D:/~Vibe-Coding/Projects/AssetsManager_old-bak/webui/src/pages/StorefrontWishlistPage.test.tsx`：覆盖空愿望清单 loading/refresh、可用与不可用条目、remove/clear mutation。
- `D:/~Vibe-Coding/Projects/AssetsManager_old-bak/webui/src/pages/StorefrontDeliveryPage.test.tsx`：覆盖 delivery loading、成功下载链接和 token 解析失败 alert。

最新 WebUI 验证：
```text
WebUI full Vitest：84 test files passed，544 tests passed
TypeScript typecheck：通过
```

当前工作区：473 status entries / 187 tracked modified / 286 untracked / 0 staged；manifest path closure 473/473。
## 2026-08-08 path-detail contract follow-up (no staging)

本轮将此前记录的“非 numeric slug/path 深链待决策”落地为显式、兼容的 Commerce path-detail contract。相关路径均已存在于本清单的 Batch 4/5/7 归属中；本节补充实现边界、测试归属和提交时的拆分要求，不新增状态路径。

### 实现与归属

- Backend service：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_service.py::ShopService.get_public_item_by_path()`。
- LAN route/registration：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\shop.py::handle_public_shop_item_by_path()`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\__init__.py`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\api.py`。
- Backend tests：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_commerce_services.py`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\lan\test_commerce_routes.py`。
- WebUI API/page：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\shop.ts`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\StorefrontProductPage.tsx`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\App.tsx`。
- WebUI regressions：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\shop.contract.test.ts`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\StorefrontProductPage.test.tsx`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\commerce-buyer.spec.ts`。

### Contract

- `GET /api/shop/items/by-path?path=<URL-encoded-relative-path>`；缺失或非法 path 为 validation `400`。
- 不存在、draft、archived、disabled 或不在授权销售根目录内的商品统一为 public `404`；Commerce disabled 继续使用 `503`。
- `GET /api/shop/items/{item_id}`、`/storefront/product/:id` 与 legacy `/store/*` 保持兼容；新增 canonical WebUI route 为 `/storefront/product/path/*`。
- 由 API client 的 query 参数编码处理路径，后端复用 `normalize_relative_shop_path`；不把绝对路径或 parent path 传入 repository。

### Verification / closure

- Backend path contract：12 passed；WebUI API/detail targeted：20 passed；path deep-link 已纳入 Buyer Playwright suite。
- WebUI 当前 baseline：88 个测试文件、566 个测试通过；typecheck/build 通过。
- 当前工作区：478 status entries、187 tracked modified、291 untracked、0 staged；本清单逐路径闭合 478/478，无重复归属。
- 本轮没有执行 `git add`、stage、commit、reset 或 clean；参考源仍只读。
## 2026-08-08 Commerce public media hardening (no staging)

深度审查确认公共 Commerce 商品 JSON 与普通 LAN preview 图片路由之间存在权限断层：商品页面公开，但 `/api/thumbnails/*` 仍受普通 `preview`/LAN 鉴权保护。本轮完成最小安全闭环，没有改变普通 LAN 预览权限，也没有把 `lan_guest_preview` 改成 Commerce 开关。

### 修复边界

- `ShopService` 的 cover/gallery 创建与更新继续执行 authorized-root 校验；配置销售根后，商品媒体不能指向授权根外文件。
- 新增 `GET /api/shop/items/{item_id}/media/{slot}?size=...`，只允许 `cover` 或 `gallery-N` 槽位；先经过 Commerce gate 和 active/enabled/authorized public item 校验，再选择商品自身媒体。
- public media 只允许商品 cover（无 cover 时回退主商品 path）或 gallery 数组中的对应项；不接受任意路径、绝对路径或 parent path；不存在、非法、未授权、非文件、非安全 raster 统一 `404`。
- 复用安全图片校验、SVG 排除、Pillow 内容校验、thumbnail/blur 处理、`nosniff` 和缓存控制；普通 `/api/thumbnails/*`、`/api/image`、`lan_guest_preview` 语义保持不变。
- WebUI 数字商品的 cover/gallery 改用专用 public media URL；无数字 id、外部 URL 和普通图库仍保留原有安全 fallback。

### 归属文件

- Backend/service：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_service.py`。
- LAN Commerce：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\shop.py`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\__init__.py`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\api.py`。
- 安全图片共享 hunk：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\image.py`；该文件属于既有 LAN/image 归属，正式提交必须按 hunk 审查。
- Tests：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_commerce_services.py`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\lan\test_commerce_routes.py`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\lan\test_image_routes.py`。
- WebUI：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\hooks\useCommerce.ts`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\hooks\useCommerce.test.ts`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\commerce-buyer.spec.ts`。

### Verification

```text
Python full regression：2736 passed，7 skipped，1 warning
Commerce/media targeted：30 passed；Ruff：All checks passed
WebUI full Vitest：88 个测试文件、573 个测试通过
WebUI typecheck：通过
WebUI build：通过
Playwright Buyer：6 passed；Buyer + Seller + WebUI Shell：此前 11 passed
```

本轮仍未执行 `git add`、stage、commit、reset 或 clean。当前工作区保持 `478` status entries（`187` tracked modified、`291` untracked、`0` staged），ownership manifest 逐路径闭合 `478/478`。

## 2026-08-08 reference-source provenance audit (read-only)

`D:\~Vibe-Coding\Projects\AssetsManager_New_WebUI` 没有 `.git`，因此无法用 Git status 证明其“未修改”。目录附带的 `original-webui-requested-files.zip` 与参考源当前内容在抽样 11 个早期文件中有 10 个不一致；这只能证明参考源相对该归档发生过演进，不能单独证明是非法覆盖。对旧项目 WebUI 与参考源的快照比较也显示大量分叉和旧项目独有文件，没有发现整个旧 WebUI 被参考源整体覆盖的可靠证据。后续仍将参考源视为只读输入，不反向写入。
## 2026-08-08 real backend E2E and catalog contract follow-up (no staging)

### Optional real-backend E2E hardening

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\commerce-real-backend.spec.ts` 新增独立只读测试，不插入既有 checkout/fulfillment 状态机：

- 从真实 `/api/shop/items` 选择 active/enabled 商品；
- 显式验证 `/api/shop/items/by-path` 返回同一商品；
- 直接访问 `/storefront/product/path/{item_path}` 并验证 SPA/商品标题；
- 仅在 `cover_path` 或 gallery entry 存在时验证 `/api/shop/items/{id}/media/{slot}` 返回 `image/*`；
- 复用现有 `REAL_COMMERCE_BASE_URL`；只读 path/media 与 seller checkout 分别按各自凭据进行 per-test skip。

当前环境没有设置真实凭据，因此该 spec 当前结果为 `2 skipped`；Playwright 编译和 skip 行为已验证。真实后端环境可用时，该测试将作为只读前置验收，不会创建订单或改变 seller 状态。

### Catalog contract audit

只读审查确认当前 Commerce catalog 仍不是分页/搜索 API：

- `ShopRepository.list_items()` 默认 SQL `LIMIT 500`，没有 offset/cursor/total；
- 状态过滤和 service authorized-root 过滤发生在初始 LIMIT 之后，可能造成结果不足和漏项；
- `/api/shop/items` 只接受既有 `status/include_disabled` 语义，public 强制 active；
- WebUI 的 q/category/sort 仍全部对已加载商品做本地过滤；
- 没有正式 catalog pagination DTO，legacy `/api/search` 是文件/资产搜索，不能替代 Commerce catalog。

本轮不直接修改现有 `/api/shop/items`，避免破坏旧 response shape、numeric detail、by-path、public media、legacy `/api/search` 和 `/store/*` 兼容。下一阶段建议先冻结独立 `GET /api/shop/catalog` 合同：第一批只承诺 q/title+description、page/page_size、稳定 newest sort 和 public active-only；category/tags/featured 等字段需先明确 metadata/schema 来源。

当前长期任务仍为：合同冻结 → repository/service SQL-side filtering 与稳定分页 → WebUI hook/page 迁移 → 大目录性能和安全回归。`staged = 0`。
## 2026-08-08 continuation audit: handoff consistency and real-backend E2E gate

本轮在不回滚、不清理、不 stage/commit 的前提下继续审查当前工作区。审查前已执行 `git status --short --untracked-files=all`；当前基线仍为：

- `478` status entries；
- `187` tracked dirty；
- `291` untracked；
- `0` staged；
- `git diff --check` 无 whitespace error（仅保留既有 LF/CRLF 提示）。

交接摘要中的历史递归搜索会话 `exec session 2737` 已终止；未删除任何 `tmp/pytest-*` 或既有 dirty/untracked 文件。参考源 `D:\~Vibe-Coding\Projects\AssetsManager_New_WebUI` 仍只读，且没有 `.git`，不能将其 Git 状态当作 provenance 证据。

### 并行深度审查结论

- path-detail、public media、authorized-root、numeric fallback、`ShopBuyerContext` 身份隔离和 stale response 保护之间未发现明确的运行时回滚/覆盖冲突；
- 当前最严重的交付风险仍是关键 Commerce 运行时文件属于 `??` untracked，不能仅凭 `git diff` 形成可交付 patch；后续必须按 ownership manifest 和 mixed-file hunk ledger 手工分批 stage；
- `/api/shop/catalog` 尚未形成正式 contract，WebUI 仍通过 `/api/shop/items` 读取商品列表；已确认旧 repository 存在 `LIMIT` 后 status/authorized-root 过滤可能造成漏项，但本轮不直接改旧 endpoint，避免在合同冻结前改变 `/api/shop/items`、Seller 旧语义和 `/api/search` 兼容边界；
- 下一产品批次仍为独立 `/api/shop/catalog` 合同冻结 → SQL-side filtering/稳定分页 → route/policy tests → WebUI API/hook/page → 大目录性能/安全回归；
- 真实后端 E2E 的 public path/media 只读测试不应依赖 seller password，已完成最小修复。

### 本轮最小修复

文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\commerce-real-backend.spec.ts
```

调整为：

- 只读 path/media contract 测试仅由 `REAL_COMMERCE_BASE_URL` 控制；
- buyer checkout/seller fulfillment/delivery 测试仍同时要求 `REAL_COMMERCE_BASE_URL` 与 `REAL_COMMERCE_SELLER_PASSWORD`；
- 两个 skip 均位于各自测试体内，避免 suite-level modifier 作用域歧义。

### 现场验证

- Commerce/media Python 定向组合：`77 passed`；
- WebUI Commerce 定向：`38 passed`；
- Playwright `e2e/commerce-real-backend.spec.ts` 在无真实凭据环境：`2 skipped`，没有空 URL 请求或编译错误；
- 本轮仍未执行 `git add`、stage、commit、reset 或 clean。

### 当前待办优先级

1. 交付前先按 manifest 闭合 untracked/tracked 归属，避免只提交 tracked diff 遗漏 Commerce 核心文件；
2. 冻结独立 Catalog contract（第一批建议 `q`、`page`、`page_size`、`sort=newest`、`total`、public active-only）；
3. 在不改变 `/api/shop/items` 的前提下实现 Catalog repository/service；
4. 补 path-detail route 级异常矩阵、authorized-root media route 级验证、stale wishlist/identity-change 回归；
5. 真实后端凭据可用时分别执行只读 path/media 和完整 checkout/fulfillment/delivery 验收。

当前工作区继续保持 `staged = 0`，暂不自动提交。

## 2026-08-08 independent public Catalog Batch 0/1 completion

在保留旧 `/api/shop/items`、`ShopRepository.list_items()`、Seller 管理查询、`/api/search` 与现有 WebUI 页面语义的前提下，完成独立 public Catalog 的第一批实现。

### Frozen contract

```http
GET /api/shop/catalog?q=<optional>&page=<optional>&page_size=<optional>&sort=newest
```

响应为：

```json
{
  "items": [],
  "page": 1,
  "page_size": 24,
  "total": 0
}
```

约束：

- public active-only；
- 授权销售根过滤和状态过滤在分页切片前生效；
- `q` 搜索 title + description，大小写不敏感；
- `page` 从 1 开始；
- `page_size` 默认 24，允许 1–100；
- `sort` 当前仅接受 `newest`，稳定排序为 `created_at DESC, id DESC`；
- 不接受或返回绝对文件系统路径；
- category/tags/featured/复杂排序暂不属于本批合同。

### Implemented files

Backend：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\shop_repository.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\shop.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\__init__.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\api.py
```

新增：

```text
GET /api/shop/catalog
ShopRepository.list_catalog()
ShopService.list_catalog()
```

WebUI 非破坏性 API/type 层：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\types\api.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\shop.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\shop.contract.test.ts
```

新增 `ShopCatalogQuery`、`ShopCatalogResponse`、`ShopCatalogSort` 和 `shop.catalog()`；当前没有自动迁移 `useCommerceCatalog()`、Storefront 页面或 Seller 页面，避免一次性改变旧页面的完整列表假设。

### Verification

本批现场验证：

- Python 全量：`2742 passed / 7 skipped / 1 warning`；
- Backend Catalog + Commerce route 定向：`27 passed`；
- Commerce route/policy/error/public-auth 组合：`40 passed`；
- Ruff：Catalog/backend/route/test 文件 `All checks passed`；
- WebUI 全量：`88 个测试文件、574 个测试通过`；
- WebUI typecheck：通过；
- WebUI build：通过；
- Playwright Buyer + Seller + WebUI Shell + real-backend spec：`11 passed / 2 skipped`；
- real-backend spec 的 `2 skipped` 仅因当前环境未设置真实凭据；只读 path/media 与 seller checkout 已按各自测试分别门控。

### Known boundary / next hardening

当前 Catalog repository 为保证 legacy metadata/status 兼容，会先读取 enabled 候选并在内存中完成 metadata status 与授权相对路径过滤，再做 page slice；这保证了“过滤后分页”的正确性，但尚未完成大目录场景的 SQL-side status/root filtering、COUNT 查询优化和性能基准。该项必须在将 Storefront 页面迁移到 `shop/catalog` 前完成，并补充大目录安全/性能回归。

当前 `shop.catalog()` 只作为新 API/type contract 暴露，页面仍使用旧 `shop/items`；下一批再决定 URL query 状态、分页/无限滚动和首页 `HomeData + ShopItem` join 的迁移方式。

当前工作区仍保持 `staged = 0`，未执行自动 commit、reset 或 clean。

## 2026-08-08 Catalog SQL-side hardening and schema v23

本轮继续处理上一节记录的 Catalog 性能边界，在不改变旧 `/api/shop/items` 语义的前提下完成以下硬化：

### SQL-side filtering

文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\shop_repository.py
```

`ShopRepository.list_catalog()` 在当前 SQLite/JSON1 可用时：

- SQL 过滤 `enabled=1`；
- 使用受保护的 `json_valid()` / `json_extract()` 排除显式 draft/archived；
- malformed、缺失或未知 `metadata.status` 继续按 legacy 规则回退；
- 使用 SQL 表达式完成相对路径、父路径、绝对路径和 authorized-root 过滤；
- 先执行精确 `COUNT(*)`，再执行稳定排序和 `LIMIT/OFFSET`；
- 保留无 JSON1 环境的 Python fallback，不让旧 SQLite 直接失败。

新增回归覆盖 malformed metadata、SQL COUNT/LIMIT、过滤后 total 和 Catalog ordering index。

### Existing database index migration

由于只修改 `SHOP_ITEMS_SCHEMA` 不能覆盖已经完成 v22 migration 的现有数据库，本轮同时新增：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\db_migrations.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\schema_defs.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\core\test_db_migrations.py
```

新增：

```text
schema migration v23: shop_catalog_ordering_index
idx_shop_items_enabled_created(enabled, created_at DESC, id DESC)
```

该 migration 对已有 Commerce 数据库非破坏性，仅创建缺失索引；旧 schema/history 不被重写。

### Route/security matrix

并行测试审查补齐：

- `/api/shop/catalog` 唯一 GET 路由与 response shape；
- Commerce disabled -> `404 feature_disabled`；
- page/page_size/sort 非法参数 -> `400 validation_error` 与正确 field；
- active-only、draft/archived/disabled、authorized-root 外商品隔离；
- LAN password 开启时 public Catalog 仍可访问，Seller mutation 仍受保护。

当前仍明确未冻结的 q 产品约束包括最大长度、控制字符、重复 query 参数等；本轮不凭空定义这些语义。

### Verification

本轮新增/复验结果：

- Catalog/backend/route/migration 定向组合：`122 passed`；
- Ruff：相关生产与测试文件 `All checks passed`；
- Python 全量：`2753 passed / 7 skipped / 1 warning`；
- WebUI 上一轮全量基线仍为 `88 files / 574 tests`，typecheck/build 通过；
- Playwright 上一轮 Buyer + Seller + WebUI Shell + real-backend spec 为 `11 passed / 2 skipped`。

当前工作区继续保持：

```text
478 status entries
187 tracked dirty
291 untracked
0 staged
```

未执行 `git reset`、`git clean`、`git add` 或自动 commit。

## 2026-08-08 StorefrontProductsPage server Catalog migration

本轮将新的 Storefront 商品列表页从 legacy full-list/local-filter 模式迁移到独立 Catalog contract，同时保留首页 legacy full-list 边界。

### Page contract

文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\StorefrontProductsPage.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\hooks\useCommerce.ts
```

`StorefrontProductsPage` 现在：

- 使用 `useCommerceCatalogPage()`；
- 从 URL 读取 `q`、`page`、`page_size`；
- 固定发送 `sort=newest`；
- 直接渲染服务端返回顺序的 `catalog.products`；
- 使用服务端 `catalog.total`，不再使用当前数组长度；
- 上一页/下一页只修改 URL，不执行本地 `slice()`；
- page size 改变时重置 page=1；
- 搜索提交时重置 page=1；
- 完整处理 loading、error、retry、empty 和 no-result；
- 不再执行当前页本地 `filter()`、`sort()` 或 category/tags/featured/price 排序。

新增分页 hook 保留 legacy `useCommerceCatalog()` 不变，因此：

- `/storefront/products` 使用 `/api/shop/catalog`；
- `StorefrontPage` 首页继续使用 `/api/shop/items?status=active` 的 legacy full list；
- 首页不会把 Catalog 第一页误认为 featured/latest 全量集合。

### Search/UI consistency

文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\components\storefront\StorefrontShell.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\components\storefront\StorefrontShell.test.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\components\storefront\Storefront.css
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\i18n\en.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\i18n\zh.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\i18n\ja.ts
```

Header 搜索现在支持页面传入 URL search value，直接访问或浏览器历史切换时不会与页面 query 脱节。新增分页、page size、上一页/下一页的中英日文案和响应式样式。

首页分类卡片不再生成未冻结的 `?category=` URL，改为只读展示；category/tags contract 仍未伪造或扩展。

### Regression coverage

文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\StorefrontProductsPage.test.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\commerce-buyer.spec.ts
```

新增验证：

- URL q/page/page_size → Catalog 参数透传；
- 服务端返回顺序不被前端重排；
- `total` 不被当前页数量替代；
- page navigation 产生真实 `page=2` 请求；
- page size/query 变更重置 page；
- loading/error/retry；
- `/storefront/products` 不调用 legacy `/api/shop/items`；
- Mock Playwright 真实断言 Catalog 分页 response 顺序和 total。

### Verification

本轮现场结果：

- Catalog page/hook/Shell 定向：`21 passed`；
- 页面/Shell/App 组合：`33 passed`；
- WebUI 全量：`89 个测试文件、582 个测试通过`；
- WebUI typecheck：通过；
- WebUI build：通过；
- Buyer + Seller + WebUI Shell + real-backend Playwright：`12 passed / 2 skipped`；
- Python backend 上一轮全量基线：`2753 passed / 7 skipped / 1 warning`。

真实后端的 `2 skipped` 仍只因当前环境未设置真实 Commerce 凭据。

当前工作区状态已因新增页面回归文件变为：

```text
479 status entries
187 tracked dirty
292 untracked
0 staged
```

仍未执行 `git add`、commit、reset 或 clean。


## 2026-08-08 Catalog q contract and performance review

本轮最终工作区基线：`479` status entries（`187` tracked dirty、`292` untracked、`0` staged）；所有操作仍只发生在旧项目，未对参考源写入。

归属清单修正：`webui/src/pages/StorefrontProductsPage.test.tsx` 已补入 Batch 7 主 ledger；本轮重新核对后，清单总数与当前状态条目均为 `479/479`。

本轮在既有 Catalog 分页迁移之上冻结了 `q` 的输入合同，并保留旧 `/api/shop/items` 语义不变。

### q contract

涉及文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\shop.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\shop.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_commerce_services.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\lan\test_commerce_routes.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\shop.contract.test.ts
```

冻结语义：

- 最大长度为 `200` 个 Python/JavaScript 字符；超限返回 `400 + code=validation_error + field=q`；
- `q` 为缺省、空字符串或仅包含外部空白时表示“不筛选”；
- 只去除首尾空白，内部空白保留，用于标题/描述子串匹配；
- Unicode `Cc` 控制字符被拒绝；
- `q`、`page`、`page_size`、`sort` 都是单值 query 参数，重复出现不会静默取第一个值，而是返回 `must be provided once`；
- WebUI client 与页面层在请求前执行相同的首尾空白/空值规范化；
- 旧 `shop/items`、Seller 查询及其他旧路由没有复用或改变该新合同。

### 性能 benchmark

使用 SQLite 3.50.4 内存数据库，预热后各运行 5 次；数据同时包含多个 authorized roots、root 外路径、malformed metadata、draft/archived 与 disabled 行。Catalog 仍使用精确 `COUNT(*)` 和 `LIMIT/OFFSET`，因此结果同时反映了分页查询和总数计算成本。

| rows | q=needle median | page=100/page_size=100 median | q total | page total |
|---:|---:|---:|---:|---:|
| 10,000 | 12.125 ms | 86.476 ms | 10 | 8,839 |
| 100,000 | 80.891 ms | 479.028 ms | 89 | 88,405 |

`EXPLAIN QUERY PLAN` 对排序基线使用：

```text
SEARCH shop_items USING COVERING INDEX idx_shop_items_enabled_created (enabled=?)
```

结论：

1. v23 ordering index 已生效，稳定排序没有退化为完全无索引排序；
2. 10k 规模下请求成本较低，100k 规模下深页和精确 total 已达到需要产品/架构决策的量级；
3. 当前没有在未冻结合同的情况下引入 generated column、物化 total 或 keyset pagination；这些应作为后续性能批次单独设计并基准验证；
4. SQL-side hardening 的 malformed metadata fallback 与 authorized-root 过滤仍保持正确性优先，未改变旧接口。

### 本轮验证

```text
Backend q/Catalog service + route：31 passed（合并 repository/auth/error contract 回归：61 passed）
WebUI q/API + hook + Storefront page：33 passed
WebUI full：89 个测试文件，583 个测试通过
TypeScript typecheck：通过
WebUI build：通过
Playwright Mock/Shell：12 passed
Real backend Playwright：2 skipped（缺少 REAL_COMMERCE_BASE_URL / REAL_COMMERCE_SELLER_PASSWORD）
```

Python 全量回归：

```text
2756 passed，7 skipped，1 warning
```

首次长套件运行曾出现 1 个与 Catalog/q 无关的 LAN 生命周期 cleanup timeout；随后生命周期文件单独运行 `39 passed`、失败用例单独重跑 `1 passed`，并在第二次全量回归中确认完全通过。警告仍为既有 zipfile duplicate-name warning，7 个 skip 主要来自 Windows symlink/权限边界。

## 2026-08-08 current ownership closure audit (no staging)

当前归属清单已将 `webui/src/pages/StorefrontProductsPage.test.tsx` 纳入 Batch 7，Batch 7 当前计数为 62；状态基线为 `479/187/292/0`，cached diff 为空。

Schema migration spine 定向验证：

```text
75 passed
```

本轮仅修正 dry-run 文档归属与基线，没有修改迁移生产代码，没有执行 staging 或 commit。

## 2026-08-08 Batch 2/3 shared prerequisite audit (no staging)

逐文件审查发现，Batch 2 与 Batch 3 不能只按各自新增文件独立提交；两批都依赖当前工作区的 shared session/identity/connection-owner contract。

### 必须先闭合的 shared hunk

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\session_contract.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\path_resolver.py       # RootIdentity / root_identity / path remap hunk
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\context.py      # session liveness / root identity / registration hunk
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\database.py       # validate_connection_owner / managed owner / identity-aware connection hunk
```

证据：

- Batch 2 的 integrity、maintenance、export service 直接调用 `DatabaseManager.validate_connection_owner(..., allow_unmanaged=True)`、`db_write_lock` 和当前 `LibrarySession` liveness API；
- `AssetsManager/application/context.py` 当前 hunk 引入 `AssetsManager.core.session_contract.register_library_session`，如果不同时纳入 `AssetsManager/core/session_contract.py`，中间提交会在 import 阶段失败；
- Batch 2 的 export service 使用 `RootIdentity`、`root_identity`、identity-aware data/lock paths；
- Batch 3 的 `reconciliation_queue_store.py` 同样调用 connection-owner validation 和 connection-bound `db_write_lock`；
- Batch 3 的 runtime/bootstrap 集成还依赖当前 `LibrarySession`、`LibraryRuntime` 和 `DatabaseManager` 的生命周期 hunk。

### 安全提交顺序修正

建议将顺序解释为：

```text
Batch 1 Schema spine
→ Shared session/identity/connection-owner prerequisite（按 hunk + session_contract.py）
→ Batch 2 Restore/integrity/maintenance
→ Batch 3 G17 reconciliation/runtime
```

或将 shared prerequisite 与 Batch 2/3 的首个功能提交绑定，但不能把 Batch 2/3 新增文件单独提交到仍缺少上述 API 的 HEAD。`database.py`、`context.py`、`path_resolver.py`、`bootstrap.py`、`runtime.py` 仍禁止整文件 stage。

本轮没有执行 staging、commit、reset 或 clean。


### Batch 2/3 targeted verification

```text
198 passed，2 skipped，1 warning
```

Skip 为 Windows symlink/进程边界；warning 为既有 zipfile duplicate-name warning。


## 2026-08-08 Batch 4/5 Commerce/LAN closure audit (no staging)

### 文件闭合

当前清单中 Batch 4 的 31 个文件和 Batch 5 的 23 个文件全部存在，并全部出现在当前 `git status --short --untracked-files=all` 结果中。

### Commerce backend 依赖

Batch 4 的新增 service/repository 文件主要依赖：

```text
AssetsManager/application/context.py
AssetsManager/core/database.py
AssetsManager/core/path_resolver.py
AssetsManager/core/schema_defs.py
AssetsManager/application/auth_service.py
AssetsManager/repositories/auth_repository.py
```

其中：

- `shop_service.py`、`order_service.py`、`shop_buyer_service.py` 和多个 repository 使用当前 connection-owner validation；
- `seller_auth_service.py` 依赖当前 `AuthService`；
- 当前 `AuthService`/`AuthRepository` 的 session-binding hunk 又依赖 shared `LibrarySession`、`session_contract.py` 和 `RootIdentity`；
- 因此 Batch 4 不能作为完全脱离 shared auth/session prerequisite 的孤立提交。

### LAN Commerce 依赖

Batch 5 的新增路由文件通过以下 mixed tracked 文件接入旧 LAN：

```text
AssetsManager/lan/api.py
AssetsManager/lan/routes/__init__.py
AssetsManager/lan/routes/_helpers.py
AssetsManager/lan/server.py
AssetsManager/lan/principal.py
```

安全边界审查结果：

- route registration 中 `/api/shop/catalog` 的 GET 路由唯一；
- selected Commerce/Seller/public route 共 80 条，未发现同一 method/path 重复注册；
- `/api/shop` 由 server public-prefix 放行，但 Seller mutation/auth 仍由 handler-level `commerce_policy`/seller gate 保护；
- 旧 LAN 页面、旧下载、旧 `/store/*` 路由仍与 Commerce 新 handler 分离。

### 定向验证

```text
Batch 4/5 Commerce + LAN：149 passed
```

本轮没有修改 Commerce/LAN 生产代码，没有执行 staging、commit、reset 或 clean。


## 2026-08-08 Batch 6/7 WebUI closure audit (no staging)

### 依赖与批次边界

Batch 6 的 tracked integration 文件不能简单作为独立、先于 Batch 7 的提交：

- `webui/src/App.tsx` 直接导入 Batch 7 的 `SellerAuthContext`、`SellerAccessGate`、`ShopBuyerContext`，以及所有 Storefront/Seller lazy pages；
- `webui/src/types/api.ts` 同时包含 shared API types 与 Commerce types，必须按 hunk 或作为 shared type prerequisite 处理；
- `webui/src/api/client.ts`、`webui/src/stores/AuthContext.tsx`、`webui/src/stores/RealtimeContext.tsx` 是 Batch 6/7 共用边界，应先审查其 shared hunk；
- `webui/playwright.config.ts` 同时连接 Batch 7 E2E 与 Batch 8 CI，必须只 stage 一次；
- `App.tsx` 的 33 个相对导入、AuthContext 的 5 个相对导入、RealtimeContext 的 2 个相对导入，以及 Storefront/Seller 关键页面导入均已解析，无缺失目标。

安全顺序应调整为：

```text
Batch 6 shared API/types/auth/realtime prerequisite
→ Batch 7 Storefront/Seller implementation and tests
→ App.tsx route integration hunk
→ Playwright/CI cross-domain hunk（只提交一次）
```

如果要保持 Batch 6→Batch 7 的提交顺序，则 `App.tsx` 的 Commerce route integration 必须延后到 Batch 7 完成后，不能整文件提前提交。

### 当前验证

```text
WebUI full：89 个测试文件，585 个测试通过
TypeScript typecheck：通过
WebUI build：通过
Playwright Mock/Shell：12 passed
```

本轮没有修改 WebUI 业务代码，没有执行 staging、commit、reset 或 clean。


## 2026-08-08 Batch 8 CI/tooling closure audit (minimal repair, no staging)

### 本轮最小修复

修改文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\.github\workflows\ci.yml
```

修复内容：

- `hygiene` job 不再对干净 checkout 执行无效的空 diff；现在按 pull request base、push before 或当前 commit parent 选择真实变更范围执行 `git diff --check`；
- WebUI CI E2E 现在同时运行 Commerce Buyer、Seller 和 WebUI Shell 三组 Mock/Shell spec，不再漏掉 Seller E2E。

### Cross-domain 审查

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\playwright.config.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\.github\workflows\ci.yml
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\ruff.toml
```

- Playwright config 的本地 Chromium 路径有 `existsSync` fallback，Linux CI 不会被 Windows 路径硬失败；
- `webServer` 使用 WebUI preview，CI E2E 可自包含启动；
- `webui/package-lock.json` 存在，`npm ci` 依赖锁定有效；
- `ruff.toml` 的临时目录排除与当前 `tmp/**` 工作区边界一致。

### 本地门禁验证

```text
CI YAML parse：通过
Ruff check AssetsManager tests scripts run.py：通过
Python compileall：通过
git diff --check：通过（仅既有 LF/CRLF 提示）
WebUI full：89 个测试文件，585 个测试通过
WebUI typecheck/build：通过
Playwright full：28 passed，2 skipped（30 tests discovered；Mock/Shell subset 12 passed）
```

本地没有运行 GitHub-hosted Windows package smoke 或 Ubuntu/Windows CI runner 本身；这些仍需在远程 CI 环境执行。没有执行 staging、commit、reset 或 clean。

## 2026-08-08 final consistency addendum (no staging)

### Batch 7/8 ownership corrections

- `webui/e2e/seller.spec.ts` is explicitly Batch 7, is untracked, and is included in default CI with Buyer and Shell specs.
- `webui/playwright.config.ts` remains Cross-domain and must be staged once. Hunk ledger: lines 1-17 = Batch 7 local Chromium portability; lines 19-23 = Batch 8 CI `webServer` integration.
- Batch 8 primary files remain `.github/workflows/ci.yml`, `README.md`, `ruff.toml`, the handoff document, and the two reports; Playwright is not a second Batch 8 primary file.
- `README.md` is mixed-domain; only CI/tooling/verification hunks belong to Batch 8. Commerce/Seller/LAN explanation hunks require manual review and must not be staged as a whole file.

### Current verification evidence

- `.github/workflows/ci.yml` hygiene now uses `fetch-depth: 0` before diffing PR base/push-before ranges.
- Default Mock/Shell Playwright scope is 12 tests: Buyer 7, Seller 3, Shell 2. The default CI job additionally discovers `app.spec.ts` and the optional real-backend spec.
- Local full Python verification on 2026-08-08 (Windows, Python 3.14): `2760 passed, 7 skipped, 1 warning`. Remote CI Python matrix remains a separate gate.
- Current full status baseline remains 479 entries: 187 tracked modified, 292 untracked, 0 staged. Historical pytest temp-directory permission warnings remain known and are not cleanup targets.
- Clean prerequisites (`webui/package.json`, `webui/package-lock.json`, `requirements*.txt`, `scripts/check_package_contents.py`, `.github/workflows/nightly-perf.yml`) are intentionally not staging targets because they are clean.

本轮仍未执行 `git add`、stage、commit、reset 或 clean。


## 2026-08-08 CI coverage follow-up (no staging)

- Push hygiene compares `PUSH_BEFORE` to `CURRENT_SHA` as two tree objects. Missing-before/root events use root-safe `git show --check --format=` fallback; the PR path retains the base-to-current three-dot comparison after `fetch-depth: 0`.
- Default `webui-e2e` runs all 5 spec files and discovers 30 tests. Local 2026-08-08 result: `28 passed, 2 skipped`; the two skips are optional real-backend cases without environment variables. Mock/Shell subset: 12 passed.
- Ruff scope is now `ruff check AssetsManager tests scripts run.py`; local expanded check passed.

本轮仍未执行 `git add`、stage、commit、reset 或 clean。


## 2026-08-08 final manual staging closure (no staging)

最终 staging 规则以 Batch plan 的人工顺序为准：

```text
Schema spine
→ shared session/identity/connection-owner prerequisite
→ Batch 2/3 core services/runtime
→ Batch 4 Commerce backend
→ Batch 5 LAN routes/auth
→ Batch 6 WebUI shared prerequisite
→ Batch 7 Storefront/Seller + all E2E specs
→ App.tsx route hunk
→ Playwright/CI cross-domain hunk
→ Batch 8 docs/tooling hunks
```

必须人工 hunk 审查的文件包括：`db_migrations.py`、`bootstrap.py`、`runtime.py`、`database.py`、`path_resolver.py`、`context.py`、`auth_service.py`、`auth_repository.py`、LAN registration entrypoints、`webui/src/App.tsx`、`webui/src/types/api.ts`、`webui/src/api/client.ts`、`webui/src/stores/AuthContext.tsx`、`webui/src/stores/RealtimeContext.tsx`、`webui/playwright.config.ts` 和 `README.md`。`playwright.config.ts` 只 stage 一次；临时文件永不自动纳入。

本清单只用于后续人工操作；本轮仍未执行 `git add`、stage 或 commit。


## 2026-08-08 deep audit hardening follow-up (minimal fixes, no staging)

- `/api/shop/**` 的 public-prefix 现在支持可选 LAN principal resolution：有效 LAN user token 可进入 user-owned Buyer cart/wishlist/merge；无凭据仍保持 guest/public 行为。
- `LibraryService` canonical teardown 现在会失效 retained `LibraryContext`、`TagStore`、`ProjectData` liveness；`close_session()` 与 `close()` 共享该契约。
- `ShopBuyerProvider` 已移入 `FeatureFlagRoute(feature="commerce")` 下的 route subtree，非 Commerce 页面不会触发 Commerce buyer bootstrap 请求。
- `SellerAuthService.authenticate()` 已加入当前 active-admin revalidation；管理员停用/降权后旧 seller bearer fail closed 并移除。
- identity marker 发布后不再因 legacy/thumb 准备失败而回滚删除；identity/database targeted `29 passed`。
- Python full：`2760 passed, 7 skipped, 1 warning`；Seller/Commerce regression subset + architecture boundary `39 passed`；Commerce/LAN + core session `53 passed`；App route `14 passed`；WebUI full Vitest `89 个测试文件 / 585 个测试通过`；Playwright `28 passed, 2 skipped`；WebUI typecheck/build 通过；受影响 Python 文件 Ruff 通过。

下一轮仍需处理：Seller feature-toggle/event-driven mass revocation、`.pending` identity recovery、historical migration DDL freeze、deprecated `get_library_dir()` boundary，以及干净 checkout/远程 CI 验证。

本轮仍未执行 `git add`、stage、commit、reset 或 clean。

## 2026-08-09 continuation audit (no staging)

- Identity claim ownership now uses a per-slot OS lock; matching fixed-pending recovery is allowed only while holding that lock，mismatched/malformed pending remains fail-closed。
- Seller sessions now have explicit bulk revocation；LAN `_shutdown()` clears cached and scoped/injected sessions before realtime/WebSocket/site/runner cleanup；disabled status/logout only touches already-created SellerAuthService。
- Effective Commerce/Seller settings transitions now increment a persisted generation；dormant Seller sessions are invalidated across a disabled→enabled window。
- Current evidence: Python `2767 passed, 7 skipped, 1 warning`；identity/database `31 passed`；Seller/Commerce `39 passed`；LAN shutdown-focused `5 passed`；LAN lifecycle full file `40 passed + 1 known pre-existing timing flaky`（失败用例 isolated rerun `1 passed`）；Ruff affected files passed。
- Remaining P1/P2: Seller stop/start/startup-failure termination coverage，unique-temp/no-clobber marker publication，durable marker directory sync，migration DDL freeze，deprecated helper boundary，clean checkout/remote CI。

本轮仍未执行 `git add`、stage、commit、reset 或 clean。

---

## 2026-08-09 增量归属校正（仍不 staging）

本轮在不删除、不清理、不提交的前提下新增了 4 个 tracked dirty 路径；因此当前状态基线从历史的 `479 = 187 modified + 292 untracked` 更新为：

```text
483 status entries
191 tracked modified
292 untracked
0 staged
```

新增的四个路径全部归入 **Batch 8 — CI / docs / tooling / packaging**：

```text
M  AssetManager.spec
M  scripts/check_package_contents.py
M  tests/core/test_package_contents.py
M  tests/core/test_packaging_entrypoints.py
```

归属理由：

- `AssetManager.spec`：PyInstaller 稳定资源输入；使用已跟踪的 `Assets/icons` 作为 source，发布到兼容路径 `assets/icons`；移除本地运行时 `RuntimeData/Shared`；
- `scripts/check_package_contents.py`：同步 bundle 资源合同，不再要求首次启动时生成的 RuntimeData；
- 两个 package tests：验证稳定资源缺失失败、SPA 引用完整性以及不再要求 RuntimeData。

当前 manifest 的迁移/Commerce/WebUI 路径仍保持原有归属；本增量只修正这 4 个新增 tracked dirty 路径，不执行宽泛 `git add`。

本轮 identity、Seller、migration v8/v16/v19 的代码/测试路径均已在既有 Batch 1/4/5、cross-domain 或 core prerequisite 归属中，不新增重复归属。

本轮仍未执行 `git add`、stage、commit、reset 或 clean。

---

## 2026-08-09 identity/lifecycle 增量说明（仍不 staging）

`AssetsManager/core/database.py` 与 `tests/core/test_path_resolver.py` 仍归入已有 core identity prerequisite；本次只把 matching pending 恢复从“直接 hard-link pending”细化为“验证 pending 后用本调用唯一临时文件 no-clobber 发布”，没有新增路径归属。

该段是 parent-directory flush 实现前的历史快照；后续增量已完成 POSIX/Windows parent-directory flush，当前剩余边界是同一调用中新建多级祖先目录的递归 flush 语义。

该段是 cleanup-attempt 状态协议实现前的历史快照；后续已在 Batch 5 / LAN lifecycle core hunk 完成显式状态/事件与普通 stop 单次 retry，并与现有 server lifecycle 测试共同验证。

---

## 2026-08-09 lifecycle retry closure（仍不 staging）

本轮没有新增 status entry；已有 dirty 路径的归属保持不变：

- `AssetsManager/lan/server.py`：**Batch 5 — LAN auth/routes/lifecycle**；cleanup attempt 协议、generation-scoped single retry 与 Seller session shutdown 属于同一 LAN 生命周期 hunk，必须与现有 server lifecycle tests 一起人工审查；
- `tests/lan/test_server_lifecycle.py`：**Batch 5 测试**；新增普通 stop failure → one retry → no third retry 回归；
- `tests/integration/test_window_lifecycle_lan_failure.py`：**Batch 5 / desktop-LAN cross-domain 测试**；验证 window switch/exit 的第二次生命周期清理确实关闭旧 WebSocket、释放 session/runtime adapter；
- `AssetsManager/core/database.py`、`tests/core/test_path_resolver.py`：继续归入 **core identity prerequisite**；parent-directory flush 是同一 identity durability hunk，不新增独立归属。

当前归属与状态基线：

```text
483 status entries
191 tracked modified
292 untracked
0 staged
```

本轮验证：Python 全量 `2789 passed, 7 skipped, 1 warning`；LAN lifecycle `46 passed`；窗口显式 LAN stop-failure 集成 `2 passed`；Ruff 与 compileall 通过；WebUI typecheck/build 通过。当前不再把 LAN cleanup retry 标为未完成 timing-flaky 项；历史失败证据保留在前文，仅作为审查记录。

仍需人工处理：Batch 5 与 shared session/runtime prerequisite 的 hunk 顺序、Batch 8 文档/packaging hunk、远程/clean-checkout 门禁；本轮仍未执行 `git add`、stage、commit、reset 或 clean。


---

## 2026-08-09 identity durable flush closure（仍不 staging）

`AssetsManager/core/database.py` 与 `tests/core/test_path_resolver.py` 继续归入 **core identity prerequisite**，没有新增独立 Batch。目录链补强的归属边界如下：

- `_ensure_directory_chain()` 只记录本次实际创建的目录；
- `_flush_directory_chain_durable()` 在 marker 发布后覆盖 leaf、所有新建祖先及其已有父目录；
- 失败时 formal marker 保留并 fail-closed；
- 既有 Shared 目录路径仍只执行必要的 marker 所在目录 flush。

定向 identity/database 组合现在为 `39 passed`，Python 全量最终为 `2790 passed, 7 skipped, 1 warning`。该改动应与已有 identity no-clobber、pending recovery、path resolver 和 database metadata 测试一并人工 hunk 审查；本轮没有 stage 或 commit。


---

## 2026-08-09 package smoke closure（仍不 staging）

`AssetManager.spec` 与 `tests/core/test_packaging_entrypoints.py` 继续归入 **Batch 8 — CI / docs / tooling / packaging**：

- 移除 PyInstaller 已不存在的 `aiohttp.protocol`、`AssetsManager.application.thumbnail_repository` hidden imports；
- 保留 canonical `AssetsManager.repositories.thumbnail_repository`；
- 新增 static contract，防止 stale hidden import 回归；
- 本机真实 PyInstaller `6.19.0` bundle 构建成功，资源 checker 通过，临时 bundle offscreen runtime 启动成功；
- package contract 定向组合为 `15 passed`。

该验证没有执行 stage/commit，也没有改变 `483 / 191 / 292 / 0` 工作区状态基线。


---

## 2026-08-09 manifest coverage audit（仍不 staging）

以当前 `git status --porcelain=v1 --untracked-files=all` 和本清单逐路径比对：

```text
Current status paths：483
Manifest listed paths：483
Current paths absent from manifest：0
Manifest paths absent from current status：0
Duplicate Batch assignment：0
```

初始 Batch 1–8 之外的路径均已落入 Cross-domain、Exclude 或 Out-of-WebUI-scope 分类；没有发现 package smoke 新增路径遗漏。该核对只读当前状态，不执行 stage、commit、reset 或 clean。


---

## 2026-08-09 deprecated `get_library_dir()` boundary closure（仍不 staging）

本轮没有新增 status path，也没有改变既有归属：

- `AssetsManager/core/database.py`：继续归入 **core identity prerequisite**；
- `tests/core/test_database_metadata.py`、`tests/core/test_path_resolver.py`：继续归入 **core identity/database prerequisite tests**；
- `tests/unit/test_architecture_boundaries.py`：继续归入既有 **architecture boundary / cross-domain test** 归属。

`get_library_dir()` 的修复只把 deprecated path-only 入口接回 canonical identity marker 与 legacy migration protocol，并新增入口级 parity tests；不应作为独立 WebUI migration batch，也不应整文件覆盖或单独提交。当前仍为 `483 status entries / 191 tracked modified / 292 untracked / 0 staged` 基线，未执行 stage、commit、reset 或 clean。


---

## 2026-08-09 helper parity tests and Python full-suite closure（仍不 staging）

本轮只增加既有 core identity/database 与 architecture boundary 测试覆盖，没有新增路径或归属。入口级 parity tests 后 Python full 为 `2796 passed, 7 skipped, 1 warning`；当前 status 仍为 `483 / 191 / 292 / 0`，未执行 stage、commit、reset 或 clean。


---

## 2026-08-09 package startup dependency closure（仍不 staging）

本轮没有新增 status path；既有归属保持不变：

- `AssetManager.spec`、`run.py`：**Batch 8 — CI / docs / tooling / packaging**；
- `tests/core/test_packaging_entrypoints.py`、`tests/core/test_package_contents.py`：**Batch 8 package contract tests**。

本轮修复 PySide6.QtSvg 被错误 exclude、以及 tkinter fallback 与 frozen package 不一致的问题。该 hunk 必须和现有 package resource contract 一起人工审查，不应被宽泛 staging 带入其他 Batch。


---

## 2026-08-09 package startup fix full-regression closure（仍不 staging）

Batch 8 package hunk 在 QtSvg/tkinter fallback 修复后保持既有归属；Python full `2798 passed, 7 skipped, 1 warning`，无新增未归属路径。当前 status 基线为 `484 entries / 192 tracked modified / 292 untracked / 0 staged`，未执行 stage、commit、reset 或 clean。


---

## 2026-08-09 ownership correction after launcher fix（仍不 staging）

前一段 package startup closure 中“没有新增 status path”的表述已更正：本轮确实新增了一个 tracked dirty path `run.py`，它归入 Batch 8 packaging/launcher hunk。当前状态与归属为：

```text
Current status paths：485
Manifest listed paths：485
Current paths absent from manifest：0
Manifest paths absent from current status：0
Duplicate Batch assignment：0

M  run.py
M  requirements-dev.txt
```

`AssetManager.spec` 与 package contract tests 仍使用既有 Batch 8 归属；没有执行宽泛 staging。

---

## 2026-08-09 non-root PyInstaller root and AnyIO matrix closure（仍不 staging）

本轮在修改前重新读取了完整 `git status --short --untracked-files=all`。当前工作区基线为：

```text
Current status paths：485
Tracked modified：193
Untracked：292
Staged：0
```

新增/确认的归属：

- `requirements-dev.txt`：**Batch 8 — CI / docs / tooling / packaging**；补入 `anyio>=4.0`，对应 CI Python 3.12/3.13 对 `pytest.mark.anyio` 的真实依赖；
- `AssetManager.spec`：继续归入 **Batch 8 packaging**；构建根改为 `Path(SPECPATH).resolve()`，不再依赖调用方 cwd，也不使用 spec namespace 中不存在的 `__file__`；
- `tests/core/test_packaging_entrypoints.py`：继续归入 **Batch 8 package contract tests**，静态合同同步断言 `SPECPATH`。

本轮证据：

- package contract 定向组合：`21 passed`；
- 从非仓库 cwd 使用 PyInstaller `6.19.0` 构建：成功；
- bundle resource checker：通过；
- 实际 bundle 存在 `webui/dist`、三种 i18n、`Assets/Themes`、`Plugins`、`PySide6.QtSvg`、`PySide6.QtOpenGL` 和 `PySide6.QtOpenGLWidgets`；
- `QT_QPA_PLATFORM=offscreen` 下临时 bundle 启动并保持运行 15 秒，随后仅终止本 smoke 进程；
- Python 3.12/3.13 矩阵均为 `2792 passed，8 skipped，1 warning`；Python 3.14 本机基线为 `2798 passed，7 skipped，1 warning`；
- `async_timeout` 仍可能出现在 PyInstaller conditional optional-import warning 中，但不属于本项目 Python 3.11+ 的必需运行依赖，不应重新加入 stale hidden import。

当前 manifest 全文逐路径审查结果：

```text
Manifest unique paths：485
Current status paths absent from manifest：0
Duplicate ownership entries：0
```

该段只记录归属与验证，不执行 `git add`、stage、commit、reset 或 clean。
---

## 2026-08-09 final local regression closure（仍不 staging）

在完成 `SPECPATH` 修复、ownership 文档更新后重新执行 Python 全量：

```text
2802 passed，7 skipped，1 warning
```

相比上一条 `2798` 基线，本次新增的 4 个 package contract 用例已纳入全量结果；没有出现回归。Windows symlink 权限相关 skip 与 zip duplicate-name warning 均为既有平台/测试夹具现象。

manifest 当前逐路径审计仍为：

```text
Current status paths：485
Manifest unique paths：485
Current paths absent from manifest：0
Duplicate ownership entries：0
```

本轮仍未执行 stage、commit、reset 或 clean。
---

## 2026-08-09 canonical icon source closure（仍不 staging）

并行审查发现 `datas` 已使用 `Assets/icons`，但 `EXE(icon=...)` 仍使用大小写不同的 `assets/icons` source。Windows 当前不敏感，但这会在大小写敏感环境产生跨平台不一致；已在同一 Batch 8 packaging hunk 中统一为：

```python
icon=str(_root / 'Assets' / 'icons' / 'icon.ico')
```

并新增静态合同测试 `test_pyinstaller_uses_canonical_icon_file_source`。

最新 package contract 定向组合为 `22 passed`；重新从非仓库 cwd 构建 PyInstaller `6.19.0` bundle 后，resource checker、`icon.ico`、QtSvg、QtOpenGL、QtOpenGLWidgets、WebUI/i18n/Themes/Plugins 资源和 offscreen 15 秒启动 smoke 均通过。

本轮没有新增 status path，`AssetManager.spec` 与 `tests/core/test_packaging_entrypoints.py` 继续归入 Batch 8；没有执行 stage、commit、reset 或 clean。
---

## 2026-08-09 final full-suite count after icon closure（仍不 staging）

加入 canonical icon source contract 后，重新执行 Python 全量：

```text
2803 passed，7 skipped，1 warning
```

package contract 定向组合为 `22 passed`；没有生产回归。该结果是当前 dirty 工作区最新本地 Python 门禁记录。
---

## 2026-08-09 cross-version package gate closure（仍不 staging）

在当前 485-path dirty 工作区上，使用独立临时 Python 环境重新执行 package contract：

```text
Python 3.12.13：22 passed
Python 3.13.13：22 passed
```

两个环境均未写入项目字节码或 pytest cache；没有修改、stage、commit、reset 或 clean。该结果补强了 QtSvg/QtOpenGL/launcher/SPECPATH/icon contract 在 CI 目标 Python 版本上的当前证据。
---

## 2026-08-09 bundle runtime binary contract closure（仍不 staging）

为避免原始 `PySide6.QtSvg` 打包缺失再次回归，`scripts/check_package_contents.py` 现在不仅检查稳定数据资源，还检查：

- `assets/icons/icon.ico`；
- `PySide6/QtSvg` extension binary；
- `PySide6/QtOpenGL` extension binary；
- `PySide6/QtOpenGLWidgets` extension binary。

检查器兼容 Windows `.pyd` 以及其他平台带版本后缀的 extension binary。package contract 更新为 `26 passed`；Python 3.12/3.13 当前环境也均为 `26 passed`。真实临时 bundle checker 仍通过。

本轮只修改既有 Batch 8 packaging/checker hunk，没有新增 status path，也没有执行 stage、commit、reset 或 clean。
---

## 2026-08-09 CI foreign-cwd package-smoke closure（仍不 staging）

`.github/workflows/ci.yml` 的 Windows `package-smoke` 已改为：

- 从 `RUNNER_TEMP` 外部 cwd 调用项目内 `AssetManager.spec`；
- 将 `distpath/workpath` 指向 runner 临时目录；
- 使用绝对 bundle 路径调用 `scripts/check_package_contents.py`；
- 由 checker 实际验证 QtSvg/QtOpenGL/icon 等运行时资源。

同时在 `tests/core/test_packaging_entrypoints.py` 增加 CI workflow static contract，当前 package 定向组合为 `27 passed`。该修改仍属于 Batch 8，不新增 status path。
---

## 2026-08-09 CI-equivalent foreign-cwd bundle smoke closure（仍不 staging）

本机按 CI 新步骤重新执行：从系统 Temp cwd 调用项目绝对 spec，使用独立 dist/work 目录构建 PyInstaller bundle。

结果：

```text
PyInstaller 6.19.0 build：通过
Enhanced bundle checker：通过
QtSvg / QtOpenGL / QtOpenGLWidgets / icon.ico：存在
Offscreen runtime：保持运行 15 秒
```

该证据与 `.github/workflows/ci.yml` 的 foreign-cwd package-smoke 逻辑一致；没有在项目工作区生成 build/dist，也没有 stage/commit/reset/clean。
---

## 2026-08-09 package contract completeness and hunk audit（仍不 staging）

本轮补强了发布合同：

- checker 现在要求 `en.json`、`zh.json`、`ja.json` 三种语言资源；
- `Assets/Themes` 与 `Plugins` 目录必须存在有效文件；
- Windows regression lane 改为安装 `requirements-dev.txt`，确保 AnyIO/测试依赖与 Python matrix 一致；
- package contract 当前为 `31 passed`。

并完成跨 Batch tracked 文件只读 hunk 审查。人工 staging 不得整文件宽泛加入，优先顺序为：

```text
Core identity/database prerequisite
→ shared LibraryService/LibraryRuntime lifecycle
→ Batch 2 restore/integrity
→ Batch 3 reconciliation/index
→ Batch 4 favorite projection
→ mainline Gallery wiring
→ Batch 5 LAN lifecycle
→ Batch 8 package/CI
```

重点风险文件：`AssetsManager/core/database.py`、`AssetsManager/application/bootstrap.py`、`AssetsManager/application/file_operation_service.py`、`AssetsManager/application/library_service.py`、`AssetsManager/application/runtime.py`、`.github/workflows/ci.yml`。这些文件必须使用 `git add -p` 并按 hunk 依赖顺序审查。本轮未执行 staging。
---

## 2026-08-09 latest Python full-suite closure（仍不 staging）

在加入三种 i18n、Themes/Plugins 非空合同后，重新执行当前工作区 Python 全量：

```text
2812 passed，7 skipped，1 warning
```

当前 package 定向门禁为 `31 passed`；Python 3.12/3.13 各为 `31 passed`。warning/skip 原因仍是既有 Windows symlink/进程限制及 zip duplicate-name 测试夹具。
---

## 2026-08-09 WebUI latest local gate closure（仍不 staging）

在当前工作区重新执行 WebUI 门禁：

```text
Vitest：89 个测试文件，585 passed
TypeScript typecheck：通过
WebUI build：通过
Playwright migrated shell：2 passed
```

本轮只生成/更新被忽略的构建与测试临时产物，没有新增 status path，也没有 stage/commit。
---

## 2026-08-09 final bundle after latest WebUI build（仍不 staging）

在最新 WebUI `npm run build` 之后，重新执行 CI 等价 foreign-cwd PyInstaller 构建：

```text
PyInstaller 6.19.0：build passed
Enhanced bundle checker：passed
Offscreen runtime：alive-after-15s
```

本次 bundle 使用最新生成的 `webui/dist`，输出仍位于系统 Temp，不改变项目工作区的 dirty/untracked 文件。
---

## 2026-08-09 full Playwright local gate closure（仍不 staging）

当前 WebUI 全部 Playwright suite 重新执行：

```text
30 tests discovered
28 passed
2 skipped
```

两个 skip 是 optional real-backend Commerce tests，因为本地未设置 `REAL_COMMERCE_BASE_URL`；其余 app、buyer mock、seller mock、shell、responsive、network resilience 测试全部通过。
---

## 2026-08-09 clean-like snapshot build closure（仍不 staging）

创建了不触碰原工作区的 selective clean-like Temp snapshot，排除 `.git`、缓存、`node_modules`、旧 `dist` 和测试产物；补入 tracked 的 `tests/contracts/lan_public_contracts.json` 后完成：

```text
npm ci：成功
WebUI build：成功
PyInstaller foreign-cwd build：成功
Enhanced bundle checker：成功
Offscreen runtime：alive-after-15s
```

这证明最新工作区不依赖原项目的 `node_modules` 或既有 WebUI build cache。`npm ci` 报告的 2 个漏洞均属于 dev/build 依赖（nanoid、postcss）；`npm audit --omit=dev` 为 0 vulnerabilities，作为后续依赖维护 P2 记录，不在本轮自动改锁文件。

## 2026-08-09 ownership ledger reconciliation（仍不 staging）

将当前 dirty workspace 与本清单重新对齐：

```text
485 status paths = 193 tracked modified + 292 untracked + 0 staged
0 tracked deletions / 0 renames or copies
Batch 8 = 12 paths（包含 package entrypoint、resource checker、dev requirements 与 launcher）

AssetManager.spec
requirements-dev.txt
run.py
scripts/check_package_contents.py
tests/core/test_package_contents.py
tests/core/test_packaging_entrypoints.py
```

本节修订的是当前 ledger；文档前部的 479 条为历史生成快照。上述路径仍属于 Batch 8，提交时与 `.github/workflows/ci.yml` 一起按功能域审查，不执行宽泛 staging。

---

## 2026-08-09 post-smoke Python full-suite closure（仍不 staging）

在加入 CI frozen runtime static contract 后重新执行当前工作区 Python 全量：

```text
2813 passed，7 skipped，1 warning
```

package/static contract 当前为 `32 passed`；ownership ledger 仍为 `485 unique paths / 0 missing / 0 extra`。本轮没有新增状态路径。

---

## 2026-08-09 package checker 与 Chromium acceptance 稳定性闭环（仍不 staging）

当前已补强两个既有归属路径：

```text
M	scripts/check_package_contents.py       # Batch 8 package contract
M	tests/core/test_package_contents.py     # Batch 8 package regression
M	tests/e2e/test_webui_realtime_acceptance.py  # Batch 7/8 acceptance hunk
```

变更内容：

- package checker 使用 file/directory kind contract，拒绝同名文件/目录替代；
- Chromium realtime acceptance 过滤 blocked ports，避免 `ERR_UNSAFE_PORT`。

当前验证：`41` 个 package contract 测试、`6` 个 real Chromium acceptance 测试和 Python 全量 `2822 passed` 均通过。状态路径数量未增加，仍为 `485`，本轮没有 staging。

---

## 2026-08-09 frozen runtime early-exit contract closure（仍不 staging）

Batch 8 CI hunk 已补强 frozen EXE smoke：任何 15 秒内提前退出（包括 exit code 0）都失败，避免静默启动失败被误判为通过。状态路径数量仍为 `485`，无新增归属路径。

---

## 2026-08-09 Python LAN browser CI lane（仍不 staging）

`.github/workflows/ci.yml` 的新增 `python-browser-e2e` 属于 Batch 8 CI/tooling；它依赖 Batch 7 的 `tests/e2e/test_webui_realtime_acceptance.py`，但不新增工作区状态路径。提交时需与现有 `webui/playwright.config.ts` cross-domain 依赖一起进行 hunk 审查，仍不宽泛 staging。

---

## 2026-08-09 final current-worktree Python closure（仍不 staging）

当前验证最终记录：`2823 passed，7 skipped，1 warning`；package/CI contract `42 passed`；real Chromium LAN acceptance `6 passed`。ownership 状态路径仍为 `485`，本轮没有新增路径、staging 或提交。

---

## 2026-08-09 Qt binary suffix contract closure（仍不 staging）

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\scripts\check_package_contents.py` 与 `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\core\test_package_contents.py` 的本轮增量仍归 Batch 8 package cluster；没有新增状态路径或 staging。

---

## 2026-08-09 latest clean-like snapshot closure（仍不 staging）

当前 ownership ledger 对应的最新 snapshot 已完成 npm ci、WebUI build、foreign-cwd PyInstaller、bundle checker 与 15 秒 frozen runtime smoke；没有新增状态路径，ledger 仍为 `485 / 0 missing / 0 extra`。

---

## 2026-08-09 final hunk ownership audit（仍不 staging）

当前 ledger 的跨域处理约束已最终确认：五个 core/application 文件必须按 hunk 依赖顺序处理；`webui/playwright.config.ts` 只能 stage once；realtime acceptance 文件不得把既有 LAN lifecycle 与本轮 blocked-port 修复混为单一归属；Batch 8 package cluster必须保持 spec、checker、tests、CI 的合同连续性。

---

## 2026-08-09 WebUI lockfile security closure（仍不 staging）

新增 dirty 路径：

```text
M\twebui/package-lock.json
```

归属：Batch 8 dependency/package cluster。该 lockfile 变更仅修复 `nanoid` 与 `postcss` 已审计版本，当前 ledger 已更新为 `486` paths / `194 tracked modified` / `292 untracked`，无 duplicate/missing。

---

## 2026-08-09 lockfile security closure final verification（仍不 staging）

当前 ledger 已包含 `webui/package-lock.json`，状态为 `486 unique paths / 0 missing / 0 extra`。更新后的 lockfile 已通过 npm ci、npm audit、Vitest、typecheck、build、foreign-cwd package 与 runtime smoke。

---

## 2026-08-09 continuous npm audit gate closure（仍不 staging）

`.github/workflows/ci.yml` 的 `npm audit --audit-level=moderate` 属于 Batch 8 CI/tooling；它与 `webui/package-lock.json` 同属 dependency/package cluster。当前 ledger 仍为 `486 unique paths / 0 missing / 0 extra`。

---

## 2026-08-09 QtSvg / tkinter frozen startup closure（仍不 staging）

Batch 8 package/CI cluster 完成 frozen startup 最小闭环：

```text
AssetManager.spec
run.py
scripts/check_package_contents.py
tests/core/test_package_contents.py
tests/core/test_packaging_entrypoints.py
.github/workflows/ci.yml
```

除 `PySide6.QtSvg` extension binary 外，bundle checker 现在还验证：

```text
PySide6/Qt6Svg.dll
PySide6/Qt6OpenGL.dll
PySide6/Qt6OpenGLWidgets.dll
```

当前源码重新构建的 bundle 已通过资源检查；`--package-smoke` 返回 `0`，普通 frozen runtime 保持 15 秒存活。没有新增状态路径，仍未 staging 或 commit。

---

## 2026-08-09 continuation deep audit closure（仍不 staging）

本轮对 migration/compatibility 与 Seller/LAN lifecycle 做只读深审并运行定向回归：

```text
migration/database/compatibility：98 passed
LAN lifecycle/window failure/seller routes：50 passed
```

`get_library_dir()` 直接入口的异常与 path-only 约束已经存在，不新增重复测试。ownership path ledger 仍为 486/486，0 missing，0 extra；package/CI static contract 为 51 passed。

---

## 2026-08-09 continuation hunk ownership audit（仍不 staging）

当前 manifest 与 status 对齐后，tracked hunk staging 约束为：

```text
194 tracked modified
25 必须 hunk stage
169 归属上可整文件 stage 候选
```

其中 `database.py`、`bootstrap.py`、`file_operation_service.py`、`library_service.py`、`runtime.py` 为最高风险混合文件；`webui/playwright.config.ts` 只能 stage 一次；CI/E2E/README 等跨域文件必须按 hunk 处理。未执行 staging/commit。

---

## 2026-08-09 current-worktree full regression closure（仍不 staging）

ownership ledger 对应的当前工作区全量 Python 回归：

```text
2832 passed
7 skipped
1 warning
```

Ruff 全路径检查通过；无新增状态路径，无 staging 或 commit。
