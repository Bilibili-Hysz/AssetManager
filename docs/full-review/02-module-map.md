# 模块地图（02-module-map.md）

> 审查日期：2026-08-11 · 工作区实况 · 行数 `wc -l` 实测 · 全部为可引用索引

## 1. 后端模块总览

```
AssetsManager/（约 209 个 .py，约 6.9 万行）
├── 根：app.py(137) window.py(717) window_coordinator.py(146)
│       window_lifecycle_coordinator.py(134) dock_factory.py(234) run.py main.py
├── application/   39 模块 20,142 行（服务层）
├── core/          33 .py + plugins/4（基础设施）
├── controllers/   4（无 Qt 业务控制器）
├── di/            ServiceContainer
├── dialogs/       16（15 对话框）6,100 行
├── domain/        8 文件 995 行（事件/错误/值对象）
├── i18n/          en(710)/zh(749)/ja(749) keys
├── lan/           13 核心 + routes/24，约 10,197 行，139 条路由
├── panels/        file_list/17 + sidebar(1071) info(1472) tag_tree(358) image_viewer(374)...
├── repositories/  15 仓库 + __init__，7,134 行
└── widgets/       20 组件，约 4,600 行
```

## 2. core/ 基础设施（33 模块）

### 数据库与持久化
| 模块 | 行 | 职责 | 关键符号 |
|---|---|---|---|
| database.py | 1165 | SQLite 统一层：open_library 身份标记（os.link 无覆盖+崩溃可恢复+fsync 持久）、`_WriteGate` 读写门、`db_write_lock(conn)`（连接级 RLock+性能录制）、连接归属校验、migrate_path_metadata、clean_orphan_dirs | `DatabaseManager.open_library/connection_for/close/close_library`、`db_write_lock` |
| db_migrations.py | 944 | v1-v23 迁移运行器：SAVEPOINT 原子、历史校验（`MigrationHistoryError`/`UnsupportedSchemaVersion`）、`_versioned_schema_contract` 版本化契约回溯、延迟索引 | `migrate(conn)`、`CURRENT_SCHEMA_VERSION=23` |
| schema_defs.py | 1204 | 全部表 DDL + `SchemaObjectContract` 契约校验器（列/主键/唯一/索引/FK/CHECK，只校验不改库） | `validate_schema_object/validate_schema_objects`、`SCHEMA_OBJECT_CONTRACT` |
| json_store.py | 119 | JSON 原子持久化基类（RLock 覆盖 load/mutate/save；mkstemp+fsync+os.replace） | `JsonStore` |
| settings.py | 331 | AppSettings 单例：settings.json 原子写、损坏隔离（.corrupt）、LAN 安全确认字段、legacy 迁移 | `AppSettings.instance()/get_share_safety_ack_version/...` |
| config_migrator.py | 49 | settings.json 版本化迁移（CURRENT_VERSION=2） | `migrate(data)` |
| tag_store.py | 168 | 旧式标签门面（委托 TagRepository，deprecated→TagService） | `TagStore` |
| tag_library.py | 236 | Pixiv 式规范标签库（约 80 组多语言同义词，持久化 tag_library.json） | `TagLibrary.canonical/get_library` |
| project_data.py | 226 | 遗留 ProjectData（notes/urls/目录大小缓存，工厂 deprecated 但类仍是 LibraryContext 字段） | `ProjectData`、`_SIZE_CACHE_TTL_SECONDS=30` |
| directory_cache.py | 151 | 目录摘要缓存（directory_cache 表，in_transaction 防提前提交） | `DirectoryCache`、`DirCacheEntry` |

### 路径与身份
| 模块 | 行 | 职责 | 关键符号 |
|---|---|---|---|
| path_resolver.py | 202 | RuntimeData/库数据目录/锁路径解析 + `RootIdentity` + LIKE 转义 | `root_identity/library_data_name/sql_like_descendant_pattern/remap_path_subtree` |
| session_contract.py | 31 | 真 LibrarySession 身份令牌（防结构假对象） | `register_library_session/require_library_session` |
| protocols.py | 52 | 服务接口 Protocol（TagStoreProtocol 等） | — |
| library_manager.py | 80 | 库记录 CRUD（AppSettings library_records） | `record_visit/remove/list_all` |
| constants.py | 2 | re-export IMAGE_EXTS | — |

### 并发/生命周期/锁
| 模块 | 行 | 职责 | 关键符号 |
|---|---|---|---|
| library_lock.py | 94 | 跨进程库锁：QLockFile 引用计数 + `setStaleLockTime(0)`（永不自行判 PID 陈旧） | `LibraryLock`、`LibraryAlreadyOpenError` |
| singleton.py | 64 | 线程安全单例工厂 | `ThreadSafeSingleton.get/reset` |
| signal_bus.py | 32 | Qt 表现层信号总线（7 信号：directory_changed/file_focused/refresh_requested/theme_changed/language_changed/sidebar_depth_changed/ui_scale_changed） | `bus()` |
| performance.py | 139 | 性能事件记录器（200 有界环，默认关闭） | `PerformanceRecorder.record/measure/recent` |
| cache.py | 168 | DictCache/LRUCache/TTLCache | — |

### 主题/图标/效果
| 模块 | 行 | 职责 | 关键符号 |
|---|---|---|---|
| themes.py | 593 | 22 主题（13 暗+9 亮）、14 必填 token + 24 扩展（含 6 个 icon_* 语义 token）、QSS 生成缓存、热重载、背景 API | `get/set_theme/color/prop/stylesheet/apply_to/reload_themes` |
| theme_loader.py | 265 | 主题扫描/校验/QFileSystemWatcher 热重载/自定义主题 CRUD | `ThemeLoader` |
| icons.py | 169 | SVG 注册表（48 语义图标+10 别名）、三态 color（None→icon_primary/token→themes.color/hex 原样）、DPR 渲染、缓存键(name,tint,size,dpr) | `icon/normalize/clear_cache` |
| bg_effects.py | 74 | 背景模糊（3×3 平铺抗边缘）/马赛克 | `apply_blur/apply_mosaic` |
| color_utils.py | 108 | alpha/lighten/darken/contrast_ratio（WCAG） | — |
| format_utils.py | 31 | format_size + CATEGORY_MAP | — |

### 工具/杂项
| 模块 | 行 | 职责 |
|---|---|---|
| crash_handler.py | 96 | 全局异常钩子 + 5 组脱敏正则 + 512KB 轮转 |
| tool_scheduler.py | 90 | 外部工具启动（tools.json，{file}/{folder} 占位，NUL 校验，win32 无 shell） |
| ui_scale.py | 29 | 全局 UI 缩放（0.5-3.0 钳制） |
| plugins/ | 1113 | descriptor(197)/loader(115)/host_context(513)/manager(347)：9 类贡献、9 权限、7 状态机、路径逃逸校验、运行时唯一模块名 |

## 3. domain/ 领域层（995 行）

| 模块 | 行 | 内容 |
|---|---|---|
| events.py | 190 | 19 个 frozen dataclass 事件（清单见 04 §2） |
| event_bus.py | 127 | 线程安全总线：subscribe/subscribe_weak/publish（快照锁、单 handler 异常隔离）、单例 |
| errors.py | 105 | DomainError 层级：PathEscapeError/MissingPathError/DuplicateError/NotFoundError/ValidationError/OperationNotPermitted（含 5 个带 code 子类） |
| asset.py | 115 | IMAGE_EXTS/AssetPath/AssetType/AssetInfo/assert_under_root |
| library.py | 61 | LibraryPath（目录名=basename_sha256[:10]） |
| share.py | 92 | ShareLink 值对象（is_expired/can_download/is_path_allowed 前缀匹配+根分享） |
| auth.py | 290 | 纯密码学：PBKDF2（50k/100k）、HMAC 令牌（ts.nonce.sig + 旧格式兼容）、validate_password_strength |

## 4. repositories/ 数据访问层（15 仓库 + __init__，7,134 行）

**统一模式**：双构造路径（`Repository(conn, library_root, session)` 兼容 + `for_session(session)` 规范）；`_bind_session`（root map_key 校验 + `_publish_while_live` 原子发布）；`@_repository_operation` 会话租约；写路径 `db_write_lock` + SAVEPOINT（`_write_scope`/`_transaction`，尊重外层事务）；路径键 resolve+is_relative_to。

| 仓库 | 行 | 表 | 要点 |
|---|---|---|---|
| tag_repository.py | 604 | file_tags + tag_metadata | 绑定最严格；rename_tag 迁移元数据 + DuplicateError 防冲突 |
| metadata_repository.py | 596 | file_meta | notes/urls/目录大小缓存 |
| thumbnail_repository.py | 106 | thumbnail_cache | 薄封装（无 session 绑定） |
| favorite_repository.py | 107 | library_favorites | 单语句原子插入防超限 |
| share_repository.py | 418 | share_links | JSON paths 容错解码 |
| auth_repository.py | 461 | users + invite_codes | 异常分层（IntegrityError vs re-raise） |
| asset_index_repository.py | 586 | assets + asset_index_state | **revision CAS**（`_advance_revision(expected)`）、transaction_scope、raw 模式删除拒绝 |
| plugin_metadata_repository.py | 155 | plugin_metadata | 子树查询 LIKE 转义（sql_like_descendant_pattern） |
| shop_repository.py | 635 | shop_items | `_CommerceRepository` 基类（for_session/init_tables/JSON1 探测缓存） |
| order_repository.py | 1087 | shop_orders/events/delivery_tokens/receipts/recoveries/attempts | 最大仓库；状态机常量 ORDER_STATUSES/ALLOWED_TRANSITIONS；rotate 作废+rowid 排序 |
| quota_repository.py | 161 | shop_delivery_tokens | 原子扣减/get_quota（revoked 过滤） |
| free_download_quota_repository.py | 194 | free_download_quota_windows | 窗口制配额（identity_key+window_start PK） |
| seller_profile_repository.py | 119 | seller_profile | 单行 id=1 |
| storefront_analytics_repository.py | 123 | view_days + visitors | 隐私聚合（sha256 访客哈希） |
| shop_buyer_repository.py | 618 | carts/items/checkouts/wishlist | CartRepository + WishlistRepository（merge_guest_into_user） |

## 5. 数据库迁移 v1-v23 清单

| v | 内容 | v | 内容 |
|---|---|---|---|
| 1 | 基线记录 | 13 | storefront_analytics |
| 2 | assets 索引 | 14 | reconciliation_tasks |
| 3 | tag_metadata | 15 | reconciliation_queue_state |
| 4 | plugin_metadata | 16 | shop_cart_wishlist |
| 5 | directory_cache | 17 | reconciliation lease_token 列 |
| 6 | auth_share_schema（users/invites/share_links，契约校验） | 18 | shop_orders buyer_owner 列 |
| 7 | library_favorites | 19 | shop checkout_generation（checkouts 重建） |
| 8 | commerce_schema（v8 历史快照） | 20 | receipt_recoveries |
| 9 | asset_index_state | 21 | request_fingerprint 列 |
| 10 | free_download_quota | 22 | shop_delivery_attempts |
| 11 | shop_order_receipts | 23 | catalog_ordering_index |
| 12 | seller_profile | — | — |

## 6. application/ 服务层（39 模块，20,142 行）— 服务分类

| 类别 | 服务 |
|---|---|
| 容器级单例（跨库） | LibraryService、AssetService、MetadataService、TagService、FileOperationService、ThumbnailService、SearchService、AssetIndexService、UndoService、PluginService + DatabaseManager(instance) |
| 每会话 eager | DatabaseIntegrityService、DatabaseMaintenanceService、LibraryExportService、AssetIndexReconciliationService、ReconciliationQueue(+SQLite store) |
| 每会话 Runtime-owned | AuthService、ShareService（+token_secret） |
| LAN-only 懒投影 | AssetService、ProjectService、SearchService、GalleryService、FavoriteService（_LanServicesHolder） |
| LAN-only 路由级 | ShopService、OrderService、QuotaService、SellerAuthService、ShopBuyerService（shop.py 缓存构造）；FreeDownloadQuotaService、SellerProfileService、StorefrontAnalyticsService（每请求） |
| 非服务类 | shop_authorization、security_preflight、asset_filters、runtime_events、reconciliation_queue_store/migration |

**关键服务签名索引**（详见应用层审查素材）：
- `LibraryService.open_session/close_session/restore_reservation/restore_state_provider/restore_acknowledger/retry_open_cleanup`
- `FileOperationService`：create_folder/rename/move/copy_to_directory/move_to_directory(moved_pairs)/duplicate/delete_permanent/delete_to_trash/restore_backup
- `UndoService`：record_rename/record_delete/prepare_delete(备份+projection 快照)/perform_undo/redo/skip_poisoned_*/cleanup_stale_undo_dirs
- `AssetIndexService`：index_directory_result（PUBLISHED/EMPTY/SKIPPED/SCAN_FAILED/STALE/BUSY）/index_directory_tree_result/query_by_parent/search_by_name
- `SearchService`：search_by_tags(_detailed)/search_by_name(_detailed)/search_by_name_indexed(_detailed)/quick_search（75ms 预算）；SearchResultSet 状态合并
- `LibraryExportService`：build_metadata_export/create_backup（上限 100k 成员/512GB/64MB manifest）/validate_backup/restore_backup（保留令牌+ACK+隔离恢复）
- `OrderService`：create_order_with_receipt/confirm_by_receipt/fulfill/rotate_delivery（继承+作废）/revoke_delivery/resolve_delivery（CAS+幂等）
- `ShareService`：create_share/verify_password（失败计数 5/60s 锁定）/validate_access/increment_download

## 7. LAN 层（13 核心 + routes/24，139 条路由）

核心模块职责：server.py（_LanServerImpl 生命周期/认证中间件/撤销表/负缓存）、manager.py（ShareManager 状态机）、api.py（139 条注册 + realtime 桥）、ws.py（WebSocketManager：50 连接/心跳 30s/authority 锁/1MB 截断）、security.py（RateLimiter 1000/60s + AuthRateLimiter 10/300s + 黑名单）、tunnel.py（cloudflared 下载校验/崩溃监控/start 串行）、path_guard.py（resolve+is_relative_to 唯一防线）、principal.py（6 principal + 8 capabilities）、dto.py（稳定响应 DTO）。

**路由表**（139 条，完整见 LAN 审查素材 §4）：页面 30（SPA 回退）、核心库 API 51（browse/preview/download/admin 权限矩阵）、Commerce/Seller 55（commerce/seller/receipt/buyer 门）、认证/WS 3。权限矩阵：browse=浏览类端点；preview=image/thumbnails；download=download/batch（+免费配额）；manage_links=shares 管理；admin(role)=users/invites/activity/online-users/tags 写/notes 写/tunnel-status；realtime=/ws+revision；公开=SPA 页/info/quota/认证端点/分享 verify|info|download|preview/shop 全链。

## 8. 桌面 UI 层

| 区域 | 文件 | 要点 |
|---|---|---|
| 根 | window.py(717)/window_coordinator.py(146)/window_lifecycle_coordinator.py(134)/dock_factory.py(234)/app.py(137) | 菜单行+WorkspaceSection；主题动画 coordinator；库切换编排（停 LAN→关旧→开新）；PANELS 注册表 |
| panels/file_list | 17 文件 7,842 行 | `_grid_widget.py`(1755 GPU-free 自绘网格：纹理烘焙/动画引擎/缩放锚点/遥测)、`_base.py`(1307 FileListPanel)、`_actions.py`(738 7 操作+撤销)、`_loader.py`(977 QThreadPool 缩略图)、`_model.py`(689 后台扫描) |
| panels 其他 | sidebar(1071)/info(1472)/tag_tree(358)/image_viewer(374)/empty/base/_event_bridge | 虚拟树+懒加载；异步信息任务+字段注册表；TagTree 订阅 TAGS 投影；QOpenGL 查看器 |
| widgets | 20 组件 | toast/status_indicator/tag_chip/tabbed_dialog(基类)/lan_sharing/workspace_bar/tray/hsv_wheel/stylekit/elevation/...；**6 个零生产消费方**：command_palette/file_picker/pager_overlay/theme_gallery/status_bar/title_bar（待接线） |
| dialogs | 15 | startup/settings/tabbed_dialog/sharing_settings(2035)/share_link/share_qr/theme_preview/sidebar_favorites/sidebar_recent/sidebar_settings/tag_editor/plugin_manager/color_picker/generic_settings/_share_api |
| controllers | 4 | file_list_controller/info_controller/tag_tree_controller/sidebar_controller（注入服务见 01 §素材） |

## 9. 前端 src 地图（196 ts/tsx：90 测试 + 106 源）

```
api/       client.ts(308) + errors.ts + 13 工厂（auth/files/gallery/tags/metadata/notes/
           thumbnails/shares/favorites/quicksearch/system/users/shop）+ 18 测试（14 contract）
stores/    AuthContext / RealtimeContext / SellerAuthContext
hooks/     13 源（useAuth/useProjects/useSearch/useFavorites/useQuota/useThumbnailCache/
           useI18n/useTheme/useWebSocket/useInvalidation/useCommerce×3/useMediaQuery/useDialogFocus）
pages/     24 页面组件 + 20 测试
components/ admin/ auth/ files/ gallery/ layout/ shares/ storefront/ tags/ ui/ viewer/
types/     api.ts（666 行，约 90 DTO）
i18n/      en/zh/ja.ts（useSyncExternalStore）
```

（前端完整细节见 05-frontend.md）
