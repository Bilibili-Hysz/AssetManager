# AssetManager 当前代码架构图册

> 日期：2026-09-06。基于 HEAD `6c70153b642f9d7a139937ae5d73da94325eebd8` 及绘制时的未提交工作区代码。
> 这是源码静态走查图册，不是运行验证或未来设计。覆盖生产模块、主要调用与所有权、持久化、异步数据流和开发入口；不将每条函数调用挤进一张图。完整文件与静态 import 索引见配套生成文件。

## 阅读方式

先看 01 总览，再按需求查看分图。实线表示调用、数据流或明确标注的所有权；虚线表示事件、可选分支或间接关系。各图的箭头不是统一的 Python import 图，完整静态 import 另见 `source-inventory.json`。同一分组内列出的服务不一定是同一个实例或共用事务。

| 图 | 解决的问题 |
|---|---|
| 01 系统总览 | 桌面、浏览器、Python 进程、外部依赖在哪里 |
| 02 服务装配 | 应用级与资产库级对象如何创建、谁拥有谁 |
| 03 生命周期 | 打开、切换、关闭资产库时资源如何回收 |
| 04 桌面结构 | 窗口、面板、网格、控制器和后台任务如何协作 |
| 05 服务与数据 | 业务功能分别落在哪些服务和存储组件 |
| 06 存储结构 | 原始文件、库数据库、缓存和全局设置如何划分 |
| 07 实时同步 | 一次写操作如何使桌面和浏览器刷新 |
| 08 WebUI | 页面、认证、API、查询缓存和实时事件如何连接 |
| 09 LAN 请求 | 中间件、路由、身份、权限和传输边界 |
| 10 媒体链路 | 图片快照、缩略图、解码、隐私模糊和缓存 |
| 11 下载链路 | 单文件、批量 ZIP、配额和清理所有权 |
| 12 后台恢复 | 文件操作、导入、监听、持久队列和补偿 |
| 13 扩展与外观 | 插件、命令、MCP、主题和背景渲染 |
| 14 工程验证 | 哪些测试和构建入口覆盖哪些边界 |

## 01 系统总览

```mermaid
flowchart TB
    User["本机用户"] --> Desktop["PySide6 桌面界面"]
    Visitor["远程用户"] --> Browser["浏览器 React SPA"]
    Browser -->|"HTTP / WebSocket"| Lan
    Remote["公网浏览器"] -.->|"可选 cloudflared 隧道"| Lan
    subgraph Proc["AssetManager 单个 Python 进程"]
        Desktop -->|"进程内调用"| Services
        Lan["aiohttp LAN 服务 / 独立 asyncio 线程"] -->|"路由 / DTO / 服务调用"| Services
        Boot["ApplicationBootstrap / LibraryService"] -->|"每库创建并拥有"| Runtime
        Runtime["LibrarySession + LibraryRuntime"] -->|"固定服务快照"| Services
        Services["应用服务层 application"] --> Repo["repositories + core 存储适配"]
        Services --> IO["文件系统 / 解码 / 后台任务"]
        Services -.-> Events["领域事件 EventBus / Qt 桥与 WebSocket 失效通知"]
        Lan -->|"托管构建产物"| Spa["webui/dist"]
    end
    Repo --> DB[("每库 SQLite 数据库")]
    IO --> Files[("用户资产库原始文件")]
    IO --> Cache[("缩略图 / 派生物 / 恢复标记")]
    Services -.-> Ollama["可选 Ollama 图片打标签"]
    IO -.-> Tools["可选 ffmpeg / ffprobe / 外部编辑器"]
```

定位：这是文件资产管理程序。原始资产保留为普通文件；SQLite 保存标签、备注、索引、分享和其他应用数据。桌面和 LAN 在同一进程中运行，浏览器通过 HTTP 访问 LAN。跨进程队列协议的存在不表示支持多个应用同时拥有同一资产库。

源码：[应用入口](../AssetsManager/app.py)、[LAN 实现](../AssetsManager/lan/server.py)、[运行时](../AssetsManager/application/runtime.py)、[SPA 根组件](../webui/src/App.tsx)。

## 02 服务装配与所有权

```mermaid
flowchart LR
    Entry["main.py / run.py"] --> App["app.main / QApplication / 单实例检查"]
    App --> Boot["ApplicationBootstrap"]
    Boot --> Container["ServiceContainer / 应用生命周期"]
    Container --> DBM["DatabaseManager"]
    Container --> LS["LibraryService"]
    Container --> PS["PluginService"]
    App --> Startup["StartupWindow / 选择资产库"]
    Startup --> Window["MainWindow"]
    Window --> LS
    LS --> Session["LibraryContext + LibrarySession / root identity + event token"]
    Session --> Conn["connection_for + operation 租约"]
    Boot -->|"runtime_for / 按 session 缓存"| Runtime["唯一 LibraryRuntime / epoch + revision"]
    Session --> Runtime
    Runtime --> Snapshot["冻结 LibraryScopedServices"]
    Snapshot --> Shared["Metadata / Tag / Thumbnail / FileOperation / Undo / AssetIndex / Collection"]
    Snapshot --> Maintain["Integrity / Maintenance / Export"]
    Snapshot --> Recovery["ReconciliationQueue / Worker / ImportManifestRecovery"]
    Snapshot --> Commands["CommandRegistry / CommandExecutionStore / MediaDerivativesRecorder"]
    Snapshot --> Sharing["RuntimeSharingServices / AuthService + ShareService + token_secret"]
    Snapshot --> Holder["_LanServicesHolder / single-flight 懒装配"]
    Holder --> LAN["Asset / Project / Search / Gallery / Favorite"]
    Snapshot -->|"复用应用级实例"| PS
    Runtime --> Adapters["生命周期适配器 / watcher / maintenance / reconciliation / LAN"]
    Conn --> DBM
```

- 容器只注册应用级 `DatabaseManager`、`LibraryService`、`PluginService`；库级服务不能随意从全局容器重新取得。
- `LibraryScopedServices` 是冻结快照，但其中引用的服务具有内部可变状态。冻结不等于全部对象不可变。
- `AuthService`、`ShareService` 和运行时密钥在库级快照中创建，不随每次 LAN 启停重建。LAN 本地 UI 密钥另由运行时密钥和认证配置派生。
- `_build_services` 创建写入侧 `SearchIndexService`；懒装配 `_build_lan_services` 创建自己的搜索索引/资产索引服务对象，共享同一 session 数据库，不能画成所有调用都使用唯一索引服务实例。
- `ImportService`、重关联函数和 AI 打标签等还有按使用场景装配的入口，不全部属于快照字段。`FreeDownloadQuotaService` 通过 LAN 请求辅助层绑定当前库。

源码：[装配根](../AssetsManager/application/bootstrap.py)、[容器](../AssetsManager/di/__init__.py)、[session](../AssetsManager/application/context.py)、[库管理](../AssetsManager/application/library_service.py)。

## 03 资产库生命周期

```mermaid
sequenceDiagram
    participant UI as MainWindow / LifecycleCoordinator
    participant Lib as LibraryService
    participant DB as DatabaseManager
    participant Boot as ApplicationBootstrap
    participant RT as LibraryRuntime
    participant Adapter as 面板 / watcher / worker / LAN
    UI->>Lib: 打开资产库
    Lib->>Lib: 规范化 RootIdentity / 占用库所有权 / LibraryLock
    Lib->>DB: 初始化数据库 / 校验身份 / 迁移与 schema 契约
    DB-->>Lib: 该库连接
    Lib-->>UI: canonical LibrarySession
    UI->>Boot: runtime_for(session)
    Boot->>RT: 构建服务快照 / 事件路由 / 后台适配器
    RT-->>UI: services_snapshot
    UI->>Adapter: 绑定 session / runtime / 固定服务
    Note over UI,Adapter: 切库先停止旧工作并清理旧绑定，再注入新库；失败走回滚或重试
    UI->>Lib: close_session(old_session)
    Lib->>Lib: begin_close / 禁止新操作
    Lib->>Boot: closing listeners
    Boot->>RT: mark_closing / 排空事件回调 / close_adapters
    RT->>Adapter: stop
    Lib->>Lib: 等待已接受的 session.operation 完成
    Lib->>Boot: close listeners
    Boot->>RT: 清理 undo / 懒服务订阅 / runtime 缓存
    Lib->>DB: close_library
    Lib->>Lib: 释放 LibraryLock / 失效 context / 清理所有权
    Note over Lib,RT: 超时或清理失败保留可重试状态，不宣称已释放数据库与库锁
```

桌面切库还包含 LAN 状态恢复、面板预清理、标签工作区和布局保存。`WindowLifecycleCoordinator` 负责这些 UI 编排；`LibraryService._run_owned_teardown` 才是 session/数据库/库锁的最终关闭所有者。`Runtime.close()` 自身不关闭数据库。

源码：[窗口生命周期](../AssetsManager/window_lifecycle_coordinator.py)、[统一面板清单](../AssetsManager/window_scoped_panels.py)、[库生命周期](../AssetsManager/application/library_service.py)、[运行时关闭](../AssetsManager/application/runtime.py)。

## 04 桌面结构

```mermaid
flowchart LR
    Window["MainWindow"] --> Life["WindowLifecycleCoordinator / WindowCoordinator"]
    Window --> Work["WorkspaceBar / TabContainer / 布局与视图状态"]
    Window --> Dock["dock_factory / 统一 Dock 外壳"]
    Dock --> Panels["Sidebar / Info / ImageViewer / 可创建的 TagTree"]
    Work --> FilePanel["FileListPanel"]
    FilePanel --> Mixins["LayoutMixin / LogicMixin / EventsMixin / NavigationMixin / ActionsMixin"]
    Mixins --> Model["FileSystemModel / 文件与排序筛选数据"]
    Model --> Grid["FileListGridWidget / QWidget + QPainter"]
    Model --> Detail["详情模型 / QTreeView"]
    Grid --> GridParts["grid layout / render / interact / texture cache / animator"]
    Mixins --> Loader["ThumbnailLoader / generation + runtime snapshot"]
    Loader --> Pools["QThreadPool / 独立 ffmpeg 池 / 磁盘写入线程"]
    Panels --> Controllers["Info / Sidebar / TagTree 控制器"]
    Mixins --> FileController["FileListController"]
    Controllers --> Ports["desktop_ports / RootBoundTagService / 应用服务"]
    FileController --> Ports
    Mixins -->|"文件操作等直接调用"| Ports
    Loader -->|"缩略图与派生物"| Ports
    Window --> Dialogs["设置 / 分享 / 标签浏览 / 导入 / 活动 / 撤销 / 插件对话框"]
    Dialogs --> Ports
    Dialogs --> SharePort["ShareSettingsPort / LanControlPort"]
    SharePort --> LanAdapter["lan.ports / LanDesktopAdapter / build_lan_server"]
    Window --> Overlays["QuickLook / QuickTagger / CommandPalette / Toast / 托盘"]
    Bus["Qt signal_bus / 导航、主题、语言、缩放"] -.-> Window
    Bus -.-> Panels
    Bridge["DomainEventSubscription / RuntimeEventSubscription / queued Qt"] -.-> Panels
    Bridge -.-> FilePanel
```

当前文件网格不是旧 `QListView` 实现；详情模式才使用 `QTreeView`。控制器不依赖 Qt，但面板并非所有行为都经过控制器，文件操作和媒体加载仍有直接服务调用。`TagTreePanel` 可由工厂创建，当前标签浏览对话框也持有自己的实例，不应假定它始终作为主窗口 Dock 挂载。

源码：[主窗口](../AssetsManager/window.py)、[文件面板组成](../AssetsManager/panels/file_list/_base.py)、[画布](../AssetsManager/panels/file_list/_grid_widget.py)、[缩略图加载器](../AssetsManager/panels/file_list/_loader.py)、[控制器目录](../AssetsManager/controllers/)、[桌面端口](../AssetsManager/application/desktop_ports.py)。

## 05 应用服务与数据依赖

```mermaid
flowchart LR
    Browse["AssetService / ProjectService / GalleryService"] --> BrowseData["DirectoryCache / ProjectData / GalleryHomeRepository / 文件扫描"]
    Meta["MetadataService / TagService"] --> MetaData["MetadataRepository / TagRepository / TagStore / TagLibrary"]
    Fav["FavoriteService / CollectionService"] --> FavData["FavoriteRepository / CollectionRepository"]
    Search["SearchService / search_syntax"] --> Index["AssetIndexService / SearchIndexService"]
    Fav -->|"智能集合评估"| Index
    Meta -->|"提交后维护搜索投影"| Index
    File["FileOperationService / ImportService / UndoService / relink_service"] --> FS["文件系统操作 / 路径元数据迁移 / 补偿"]
    File --> Index
    Index --> IndexData["AssetIndexRepository / assets / asset_search FTS5"]
    Thumb["ThumbnailService / media 模块"] --> ThumbData["ThumbnailRepository / 文件缓存 / asset_derivatives"]
    Auth["AuthService / ShareService / FreeDownloadQuotaService"] --> AuthData["AuthRepository / ShareRepository / RevokedTokenRepository / FreeDownloadQuotaRepository"]
    Plugin["PluginService"] --> PluginData["插件管理器 / PluginMetadataRepository"]
    Maint["Integrity / Maintenance / Export / LibrarySettingsAdapter"] --> SystemData["连接检查 / VACUUM / checkpoint / 备份与恢复"]
    Trace["ActivityRecorder / CommandExecutionStore / ImportManifestStore / ReconciliationQueueStore"] --> Journal["activity_log / command_executions / import 与 queue 表"]
    BrowseData --> DB[("session-bound SQLite")]
    MetaData --> DB
    FavData --> DB
    IndexData --> DB
    ThumbData --> DB
    AuthData --> DB
    PluginData --> DB
    SystemData --> DB
    Journal --> DB
```

服务分组的开发含义：

| 功能 | 主要入口 | 关键约束 |
|---|---|---|
| 浏览与分类 | `asset_service.py`、`project_service.py`、`asset_filters.py` | 文件系统和缓存仍参与读路径，不是全部只读数据库 |
| 标签、备注、链接、评分 | `tag_service.py`、`metadata_service.py` | 写入后发布带库身份的事件；标签和备注也维护搜索索引 |
| 搜索 | `search_service.py`、`search_index_service.py`、`search_syntax.py` | 文件扫描、索引、FTS 多条路径；结果含完整性/降级状态 |
| 集合 | `collection_service.py` | 普通集合是路径引用；智能集合保存查询条件，不移动原文件 |
| 文件操作和撤销 | `file_operation_service.py`、`undo_service.py` | 原文件变化与数据库不能构成单一原子事务，需要修复机制 |
| 导入 | `import_service.py`、`import_manifest_store.py` | 规划预算、指纹、逐项状态、取消和重启恢复 |
| 重关联 | `relink_service.py` | 修复外部移动留下的元数据路径；本身不移动用户文件 |
| 分享与配额 | `share_service.py`、`auth_service.py`、`free_download_quota_service.py` | 绑定 session；HTTP 身份解析和业务规则分层 |
| 维护与备份 | `library_settings_adapter.py`、`library_export_service*.py` | 恢复需要关闭会话并持有恢复 reservation |

并非所有 SQL 都在 `repositories/`：搜索索引、活动日志、命令日志、导入和协调队列等应用模块也持有会话连接并执行 SQL。图中对此单列，不把理想分层写成事实。`domain/` 包含值对象、事件和错误类型；当前也引用 `core` 的部分契约与工具，并非严格零 import 的独立领域包。

源码：[服务装配](../AssetsManager/application/bootstrap.py)、[仓库公共约束](../AssetsManager/repositories/_common.py)、[搜索语法](../AssetsManager/application/search_syntax.py)、[领域资产对象](../AssetsManager/domain/asset.py)。

## 06 存储结构与一致性

```mermaid
flowchart LR
    Root["用户选择的资产库目录 / 普通文件和目录"] --> Identity["RootIdentity / 规范路径 / 稳定数据槽身份"]
    Identity --> Slot["RuntimeData / 每库数据槽"]
    Identity --> Lock["RuntimeData/Shared / 库锁与 identity 标记"]
    Slot --> DB[("assetmanager.db / WAL / schema v46")]
    Slot --> Cache["thumbnails / 媒体派生文件 / 恢复标记"]
    Shared["RuntimeData/Shared"] --> Settings["应用设置 / tools.json / 日志 / 共享配置"]
    DB --> Asset["assets + asset_index_state"]
    DB --> Metadata["file_meta + file_tags / 标签目录与来源"]
    DB --> Organize["library_favorites / asset_collections / asset_collection_members"]
    DB --> Derived["thumbnail_cache / asset_derivatives / gallery_home / asset_search FTS5"]
    DB --> Access["users / invite_codes / share_links / revoked_tokens / free_download_quota_windows"]
    DB --> Recovery["import_manifests / import_manifest_items / reconciliation_tasks / queue_state / transition_outbox / dead_letters"]
    DB --> Audit["activity_log / command_executions / 插件元数据 / schema_migrations"]
    DB --> Legacy["历史 shop / seller 表与迁移保留；商城运行时已移除"]
    Asset -.->|"路径关联，非统一资产 UUID"| Metadata
    Asset -.->|"路径引用"| Organize
    Asset -.->|"可重建投影"| Derived
```

这是存储分组图，虚线是逻辑路径关联，不承诺数据库中存在外键。文件移动需要同步迁移 `file_meta`、`file_tags`、收藏、集合成员、缩略图和派生物等路径记录。

- 路径由 `path_resolver` 统一计算；运行数据根目录不能简单硬编码为源代码目录。库槽有完整身份标记以防摘要槽冲突。
- 每库使用受管理的 SQLite 连接，`check_same_thread=False`，开启 WAL；读写通过连接级锁等机制协调。WAL 不等于同一个连接可无锁并发写。
- 仓库公共基类处理 session/root 校验、操作租约、SAVEPOINT、事务所有权和可选 SQLITE_BUSY 重试；涉及竞争更新的服务另用 revision/lease/token CAS。
- `schema_defs.py` 定义契约，`db_migrations.py` 当前最高版本为 46。历史商城 schema 的存在不代表商城功能仍可用。
- 原文件是内容来源；索引、缩略图、画廊和全文搜索是派生数据。备份恢复必须区分资产文件和应用数据，不能只复制一个正在使用的数据库文件。

源码：[路径解析](../AssetsManager/core/path_resolver.py)、[数据库](../AssetsManager/core/database.py)、[schema](../AssetsManager/core/schema_defs.py)、[迁移](../AssetsManager/core/db_migrations.py)、[仓库事务](../AssetsManager/repositories/_common.py)。

## 07 写入与实时同步

```mermaid
sequenceDiagram
    participant Caller as 桌面或 LAN handler
    participant Service as 应用服务
    participant DB as 会话数据库 / 文件投影
    participant Bus as Domain EventBus
    participant Qt as queued Qt bridge
    participant Router as RuntimeEventRouter
    participant WS as LAN / WebSocketManager
    participant Web as RealtimeProvider / QueryCache
    Caller->>Service: 修改标签、备注、文件等
    Service->>DB: 校验与写入 / 提交
    Service->>Bus: 发布 library_root + session_token + paths 事件
    Bus-->>Qt: 对应领域事件订阅
    Qt-->>Caller: 在 GUI 线程刷新对应面板
    Bus-->>Router: EVENT_DOMAINS 中已映射的事件
    Router->>Router: 验证所属 session / revision 加一 / 计算 domains 和 paths
    Router-->>WS: InvalidationEvent(epoch, revision, domains, paths)
    WS-->>Web: projection_invalidated
    Web->>Web: 域与路径匹配 / 标记缓存失效
    Web->>Caller: HTTP 重新查询权威数据
    opt 断线重连、游标跳跃或 epoch 变化
        Web->>Caller: GET /api/revision
        Caller-->>Web: 当前 epoch + revision
        Web->>Web: 恢复并重新查询受影响数据
    end
```

领域总线是进程内共享的；运行时路由依据库根和 `session_token` 隔离事件。`RuntimeEventSubscription` 也可直接将投影失效转为 Qt 排队信号。`signal_bus.py` 只承担主题、导航等 UI 协调，不代替业务事件。

当前事实需保留：`AssetRatingChanged` 已由评分服务发布，但不在 `runtime_events.EVENT_DOMAINS` 中，因此不能把评分变化画成已自动广播给其他网页的完整链路；`MaintenanceChanged` 则是有意直接供 UI 订阅的维护通知，不属于投影失效事件。本图只对已映射事件成立。

源码：[领域事件](../AssetsManager/domain/events.py)、[运行时映射](../AssetsManager/application/runtime_events.py)、[Qt 桥](../AssetsManager/panels/_event_bridge.py)、[LAN 事件接线](../AssetsManager/lan/api.py)、[前端实时恢复](../webui/src/stores/RealtimeContext.tsx)。

## 08 WebUI 结构

```mermaid
flowchart TB
    Main["main.tsx / App.tsx / BrowserRouter"] --> Auth["AuthProvider / principal / capabilities / identityGeneration"]
    Auth --> Realtime["RealtimeProvider / useWebSocket / revision recovery"]
    Realtime --> CacheProvider["QueryCacheProvider"]
    CacheProvider --> UIProviders["ToastProvider / DownloadProgressProvider"]
    UIProviders --> Pages["Landing / Login / Browse / Detail / GalleryHome / GalleryCollection / GalleryFavorites / ShareReceive / Admin / NotFound"]
    Guard["ProtectedRoute / browse 或 manage_users"] --> Pages
    Pages --> Hooks["usePageApis / useProjects / useSearch / useFavorites / useQuota"]
    Hooks --> Cached["useCachedQuery / QueryCache / 域与路径失效"]
    Hooks --> API["api 模块工厂 / files / metadata / tags / shares / users / collections 等"]
    Cached --> API
    API --> Client["ApiClient / 身份头 / AbortSignal / 错误类型 / GET 重试退避"]
    Client --> HTTP["aiohttp /api 接口"]
    Realtime -.-> Cached
    Auth -.->|"身份切换隔离"| Cached
    Pages --> Thumbs["useThumbnailCache / 媒体资源 URL"]
    Thumbs --> HTTP
    Pages --> PublicShare["usePublicShareApi / 独立匿名客户端"]
    PublicShare --> HTTP
    Types["types/contracts / DTO 生成契约"] -.-> API
    Theme["useServerTheme / tokens / i18n / 响应式 CSS"] -.-> Pages
```

- 页面通过 hooks 获取 API，缓存读路径使用 `useCachedQuery`。单独的 `usePublicShareApi` 避免分享密码错误的 401 被全局认证当成用户登录失效。
- 浏览器路由访问限制用于界面行为；实际数据权限仍由服务端验证，不能只依赖 `ProtectedRoute`。
- React 当前包含 `/admin` 路由；配套路由清单另列 aiohttp 注册路径。客户端路由与服务端 SPA 回退规则是两份配置，不应默认完全相同。
- `api/*`、`types/*`、错误和失效契约是接口变化时需要联动的位置。

源码：[根组件](../webui/src/App.tsx)、[页面 API 入口](../webui/src/hooks/usePageApis.ts)、[API 客户端](../webui/src/api/client.ts)、[查询缓存](../webui/src/cache/queryCache.ts)、[缓存失效规则](../webui/src/cache/invalidation.ts)、[认证上下文](../webui/src/stores/AuthContext.tsx)。

## 09 LAN 请求、安全与传输边界

```mermaid
flowchart TB
    Request["HTTP 请求 / LAN 或 cloudflared"] --> Security["security middleware / IP 黑白名单 / 分级限流 / 隧道身份"]
    Security --> Metrics["metrics middleware / 请求与流量指标"]
    Metrics --> Auth["auth middleware / 身份验证 / token 撤销 / capability 检查"]
    Auth --> Error["error_contract_middleware / handler 异常契约"]
    Error --> Routes["api.setup_routes / routes 各功能 handler"]
    Policy["RoutePolicy / 每路径每方法声明"] -.-> Security
    Policy -.-> Auth
    Routes --> Guards["require_permission / require_user_write / PathGuard / 分享路径约束"]
    Guards --> Services["LanScopedServices / 当前 Runtime 应用服务"]
    Services --> DTO["dto.py / _resource_urls.py / 库相对路径与资源 URL"]
    DTO --> Response["JSON / 媒体响应 / ZIP / WebSocket"]
    Routes --> Pages["pages.py / webui/dist 静态资源与 SPA"]
    Routes --> MCP["mcp_server.py / 独立 Bearer token / 默认关闭 / 只读工具"]
    Principal["guest / password / access_key / local_ui / user / share"] -.-> Auth
    AuthService["AuthService / ShareService / 持久撤销表"] --> Auth
    Preflight["SecurityPreflight / 启动设置检查"] -.-> Server["LanServer facade / _LanServerImpl / 生命周期 mixin"]
    Server --> Routes
    Server --> Tunnel["GuardedTunnel / TunnelManager / cloudflared 子进程"]
```

| 路由模块组 | 职责 |
|---|---|
| `files`、`metadata`、`quicksearch` | 文件与目录摘要、项目树、搜索、备注和评分 |
| `tags`、`collections`、`favorites`、`gallery` | 资产组织与画廊投影 |
| `image`、`thumbnails`、`sequence` | 图片、缩略图和序列邻居 |
| `downloads`、`quota`、`shares` | 下载、配额、分享验证与获取内容 |
| `auth`、`users` | 登录、访问密钥、用户、邀请码和写权限 |
| `system`、`websocket`、`pages` | 服务信息、游标、活动与统计、实时连接和网页 |
| `lan/mcp_server.py` | 只读 MCP 协议入口，不在 `routes/` 子包中 |

服务层返回业务数据；URL 和 HTTP 状态在 LAN 层组装。路由存在能力校验和输入解析，不能把所有 validation 一概画成已下沉。中间件顺序按当前 `_build_app` 记录，错误契约中间件在最内层，不代表外层所有异常都经过它。

源码：[LAN 装配](../AssetsManager/lan/server.py)、[路由注册](../AssetsManager/lan/api.py)、[策略](../AssetsManager/lan/route_policy.py)、[身份](../AssetsManager/lan/principal.py)、[能力](../AssetsManager/lan/authorization.py)、[路径守卫](../AssetsManager/lan/path_guard.py)。

## 10 媒体、缩略图与缓存

```mermaid
flowchart TB
    Desktop["桌面 ThumbnailLoader / ImageViewer / Info / QuickLook"] --> Snapshot["core.file_snapshot / source identity / 稳定字节快照"]
    HTTP["LAN image / thumbnails / share preview"] --> Guard["权限 / 路径 / 隐私模糊策略"]
    Guard --> Open["safe_open / 最终打开与文件身份"]
    Open --> Snapshot
    Snapshot --> Admit["ThumbnailService / 来源大小与像素等准入"]
    Admit --> Decode["Pillow / Qt 解码 / media.decoders 注册表"]
    Decode --> RAW["可选 rawpy / psd-tools"]
    Decode --> Analysis["media.analysis / 调色板 / 音频波形"]
    Desktop --> FF["专用 ffmpeg 池 / 视频首帧 / 音频分析"]
    FF --> Derivatives["MediaDerivativesRecorder / asset_derivatives"]
    Decode --> Policy["尺寸 / 质量 / 模糊 / 输出格式"]
    Policy --> Key["thumbnail_key / 源身份 + 渲染 profile + 隐私变体"]
    Key --> Cache["内存缓存 / 文件缓存 / ThumbnailRepository"]
    Cache --> Desktop
    Cache --> Response["LAN 字节响应 / 内容类型 / 缓存校验"]
    Derivatives --> Cache
    Owner["ThumbnailCacheLifecycle / 进程锁 + 库缓存 owner lease"] -.-> Cache
```

这是各媒体消费者共有机制的分组图，不意味着桌面和 LAN 使用完全相同的解码函数。当前工作区的快照改动要保证来源身份、用于解码的字节和响应缓存校验相互一致；缩略图缓存还需要区分渲染 profile 和模糊策略。普通资源缓存命中不应绕过当前访问权限。

视频首帧与音频波形属于派生能力，依赖外部工具可用性；专业图片解码是可选依赖。文件扩展名可分类不代表内置三维模型实时渲染或完整文档预览。

源码：[缩略图服务](../AssetsManager/application/thumbnail_service.py)、[文件快照](../AssetsManager/core/file_snapshot.py)、[媒体解码](../AssetsManager/application/media/decoders.py)、[派生物](../AssetsManager/application/media/derivatives.py)、[缓存生命周期](../AssetsManager/application/thumbnail_cache_lifecycle.py)、[图片路由](../AssetsManager/lan/routes/image.py)。

## 11 下载、ZIP 资源与清理

```mermaid
flowchart TB
    Request["普通下载 / 批量下载 / 分享下载"] --> Auth["权限与路径校验 / 分享有效性 / 配额预检"]
    Auth --> Kind{"内容类型"}
    Kind -->|"单文件"| Open["open_download_file / SafeOpenedFile / 保留最终文件句柄"]
    Open --> Single["SafeFileResponse / 固定 Content-Length / 分块读取与身份复核"]
    Kind -->|"目录或批量"| Scan["zip_sources / 有界扫描 / 来源数量、大小、深度检查"]
    Scan --> Reserve["进程级 ZipResourceBudget / job + 预留字节"]
    Reserve --> Builder["每 LAN 的 ZIP executor / build_zip_async / 输出大小限制"]
    Builder --> Temp["TemporaryFileResponse / 临时文件 owner / reservation 引用"]
    Single --> Count["最终来源就绪后 / 普通配额或分享下载次数准入"]
    Temp --> Count
    Count --> Transfer["发送响应 / HEAD 特殊处理 / 断开与取消"]
    Transfer --> Close["关闭持有的文件句柄"]
    Close --> Cleanup["临时 ZIP 删除 / cleanup_zip_path"]
    Cleanup --> Released["成功后释放对应 reservation 引用"]
    Cleanup -->|"删除失败"| Retry["进程级 ZipCleanupService / 有界注册 / 退避重试 / 文件身份检查"]
    Retry --> Cleanup
```

- 单文件 `SafeFileResponse` 从已打开的句柄传输，不在发送时重新打开可变化的路径。读取校验来源身份；响应头发出后错误只能中止连接。
- ZIP job 和存储预留是进程级预算；ZIP 构建 executor 是每 LAN 实例所有。取消构建或取消请求时，builder、response 和清理回调各自持有的 reservation 引用必须最终释放。
- 普通配额与分享次数是两种计数入口，本图将其分支汇总，不表示所有请求都会扣两次。准入后的传输中断仍可能计数，不能将“准备好响应”表述成“客户端完整接收后才扣次”。
- `ZipCleanupService` 只重试显式注册的临时归档；当前实现没有目录扫描或进程重启后的孤儿 ZIP 自动恢复。
- 本节包含绘制时尚未提交的 `file_response.py`、`temporary_file_response.py`、`zip_resources.py`、`zip_sources.py` 和 `zip_cleanup.py`。

源码：[普通下载](../AssetsManager/lan/routes/downloads.py)、[分享下载](../AssetsManager/lan/routes/shares.py)、[ZIP 构建辅助](../AssetsManager/lan/routes/_helpers.py)、[文件响应](../AssetsManager/lan/file_response.py)、[临时响应](../AssetsManager/lan/temporary_file_response.py)、[ZIP 预算](../AssetsManager/lan/zip_resources.py)、[清理服务](../AssetsManager/lan/zip_cleanup.py)。

## 12 文件操作、导入与后台恢复

```mermaid
flowchart TB
    UI["文件操作 / 批量重命名 / 导入 / 撤销"] --> Operation["FileOperationService / ImportService / UndoService"]
    Operation --> FS["文件系统实际变更"]
    Operation --> Projection["路径元数据迁移 / AssetIndexService / SearchIndexService"]
    Operation --> Manifest["ImportManifestStore / 批次与逐项状态 / 指纹 / claim lease"]
    Operation -->|"失败补偿意图"| Markers["pending_projection_repairs 标记"]
    FS -.-> Watcher["LibraryWatcherService / 轮询目录快照"]
    Watcher --> Queue["ReconciliationQueue / 同进程 Condition + 跨进程轮询"]
    Manifest --> Recovery["ImportManifestRecoveryService"]
    Recovery --> Queue
    Markers -->|"启动 drain"| Queue
    Queue --> Store[("SQLiteReconciliationQueueStore / tasks + queue state")]
    Store --> Worker["AssetIndexReconciliationService / 领取租约 / heartbeat / 有界重试"]
    Worker --> Rescan["资产重扫 / CAS 发布"]
    Worker --> Repair["FilesystemProjectionRepairService / 意图与实际文件对齐"]
    Repair --> Projection
    Rescan --> Projection
    Worker --> Outbox[("transition outbox / 顺序投递 / ACK / dead letters")]
    Outbox -->|"持久 consumer"| Recovery
    Recovery -->|"收到所需 ACK 后结算"| Manifest
    Projection -.-> Events["FileSystemChanged / 失效通知"]
    Worker --> Health["故障状态 / retention / dead-letter 诊断"]
```

- 入队成功与索引修复完成是不同状态。导入恢复需要匹配的持久 transition ACK，不能在 enqueue 返回时直接宣称恢复完成。
- 运行时启动会重投未入队的修复标记并恢复导入 manifest；重试有预算、租约身份和失败状态，不是无限循环。
- 持久队列不是领域事件总线。领域总线提供进程内通知；队列和 outbox 承担跨重启恢复与确认。
- 常驻 `LibraryWatcherService` 由配置控制；桌面导航仍有自己的 `QFileSystemWatcher`，两者用途不同。
- 自动监听不是内容级实时文件版本系统。备份恢复和外部移动重关联还有独立入口。

源码：[文件操作](../AssetsManager/application/file_operation_service.py)、[导入](../AssetsManager/application/import_service.py)、[manifest](../AssetsManager/application/import_manifest_store.py)、[队列](../AssetsManager/application/reconciliation_queue.py)、[队列存储](../AssetsManager/application/reconciliation_queue_store.py)、[协调 worker](../AssetsManager/application/asset_index_reconciliation_service.py)、[监听](../AssetsManager/application/library_watcher_service.py)。

## 13 插件、命令、AI 与外观

```mermaid
flowchart LR
    Plugins["Plugins/Addons / plugin.json"] --> PluginService["PluginService / discover / enable / load / unload"]
    PluginService --> Manager["core.plugins / descriptor / loader / manager / preferences"]
    Manager --> Host["PluginHostContext / 当前窗口绑定的库服务"]
    Host --> API["plugin_api v2 / 注册、贡献归属、权限检查"]
    API --> Contributions["菜单 / 分类 / 解析器 / 信息字段 / 工具面板 / 快捷键 / 主题 / 事件"]
    Command["CommandRegistry / 现有文件和标签操作描述"] --> Services["库级应用服务"]
    Journal["CommandExecutionStore / 执行记录基础设施"] -.-> Command
    MCP["独立只读 MCP endpoint / 5 个工具"] --> Services
    AI["Info 单图 / FileList 批量 AI 标签"] --> Ollama["ollama_client / requests / 图像分析"]
    Ollama --> Write["write_policy / converge_tags / TagService"]
    Write --> Services
    ThemeJSON["主题 JSON / core.themes / theme_loader"] --> Qt["StyleKit / icons / ui_scale / Qt 外观"]
    ThemeJSON --> Tokens["gen_web_tokens / Web tokens / useServerTheme"]
    Language["i18n / 中英日"] --> Qt
    Language --> Web["React 外观与文案"]
    Tokens --> Web
    Wallpaper["静态背景图片 / EffectChain"] --> Effects["ImageEffectRenderer"]
    Effects --> GL["离屏 OpenGL 滤镜"]
    Effects --> CPU["CPU fallback / 不支持的 shader 返回原图"]
    GL --> Paint["MainWindow.paintEvent / 整窗 CPU 合成"]
    CPU --> Paint
```

插件与主程序在同一 Python 解释器中执行，权限声明不是隔离沙箱。当前内置插件包括 `booth_link` 和 `download_tracker`，后者 manifest 默认禁用。

`CommandRegistry` 是已有命令描述和处理入口，桌面保留自己的调用路径；`CommandExecutionStore` 是单独装配的执行记录能力，不能据此推断所有操作都自动写命令日志。当前 MCP 仅有 `search_assets`、`get_asset_metadata`、`list_collections`、`evaluate_smart_collection`、`recent_activity` 五个只读工具，未暴露命令注册表的写操作。

背景是静态图像滤镜系统，GPU 用于离屏处理，最后仍由窗口 `paintEvent` 合成；不是视频壁纸或整窗 `QOpenGLWidget` 渲染。

源码：[插件 API](../AssetsManager/plugin_api/__init__.py)、[插件主机](../AssetsManager/core/plugins/host_context.py)、[命令注册表](../AssetsManager/application/command_registry.py)、[MCP](../AssetsManager/lan/mcp_server.py)、[AI 标签](../AssetsManager/application/ai_tagging/service.py)、[背景管线](../AssetsManager/background/pipeline.py)。

## 14 工程验证与构建

```mermaid
flowchart TB
    Python["AssetsManager Python 代码"] --> Static["ruff / pyright / compileall / 边界脚本"]
    Python --> Unit["tests/unit / core / plugins"]
    Python --> Integration["tests/integration / SQLite + 文件系统 + 生命周期"]
    Python --> Desktop["tests/desktop / Qt offscreen / 视觉"]
    Python --> LAN["tests/lan / HTTP、身份、下载、WS"]
    Web["webui/src"] --> TS["TypeScript / Vitest / Vite build"]
    Web --> Browser["Playwright / app、a11y、shell / 真实 LAN E2E"]
    Python --> Browser
    Contracts["gen_ts_types / route capabilities / frontend data fetch / web tokens"] --> Python
    Contracts --> Web
    TS --> Dist["webui/dist"]
    Dist --> Build["build.py / AssetManager.spec / PyInstaller / installer"]
    Python --> Build
    Static --> CI[".github/workflows / CI 与 release"]
    Unit --> CI
    Integration --> CI
    Desktop --> CI
    LAN --> CI
    Browser --> CI
    Build --> Smoke["run.py --package-smoke / 冻结包启动验证"]
```

此图描述工程入口，不表示本轮执行过这些检查，也不表示每次 CI 都运行全部测试。`pytest.ini` 默认排除 `e2e` 和 `perf`，性能与真实浏览器验收需要显式运行。发布能力不能用本地图册生成结果替代验证。

源码：[pytest 配置](../pytest.ini)、[Web 工程配置](../webui/package.json)、[构建脚本](../build.py)、[冻结包定义](../AssetManager.spec)、[CI 目录](../.github/workflows/)。

## 开发任务定位表

| 接下来要改什么 | 优先查看 | 需要联动关注 |
|---|---|---|
| 网格、缩放、选择、拖拽、动画 | `panels/file_list/_grid_*`、`_animator.py`、`_base_*` | 布局尺寸、模型一致性、缩略图代际、桌面测试 |
| 文件操作、导入、撤销 | `file_operation_service.py`、`import_service.py`、`undo_service.py` | 所有路径关联记录、修复队列、取消和恢复 |
| 标签、备注、评分 | 对应 service、repository、Info 与 LAN 路由 | 搜索索引、领域事件、EVENT_DOMAINS、前端缓存 |
| 搜索、智能集合 | `search_syntax.py`、`search_service.py`、`collection_service.py` | CJK 短词、FTS、筛选语义、结果降级状态 |
| 切库、窗口关闭、服务重启 | `window_lifecycle_coordinator.py`、`library_service.py`、`runtime.py` | 后台排空、订阅、数据库和库锁的释放顺序 |
| Web 页面或 HTTP 接口 | `webui/src/pages`、`hooks`、`api`、`lan/routes`、`dto.py` | 错误与类型契约、权限、路径 URL 转换 |
| 分享、下载、限流 | `lan/api.py`、`server.py`、`security.py`、`authorization.py`、下载路由 | 单文件句柄、HEAD、ZIP 预算、配额和取消清理 |
| 媒体预览与缓存 | `thumbnail_service.py`、`file_snapshot.py`、`media`、`_loader.py` | 快照身份、缓存键、模糊策略、可选依赖 |
| 持久化字段 | `schema_defs.py`、`db_migrations.py`、对应 repository/service | 新旧迁移、备份恢复、路径迁移、契约生成 |
| 插件或自动化 | `core/plugins`、`plugin_api`、`command_registry.py`、`mcp_server.py` | 当前库绑定、权限实际边界、贡献卸载、只读与写入口差异 |
| 主题和视觉 | `themes.py`、主题 JSON、`StyleKit`、`background`、Web tokens | 桌面/Web 同源、语言、缩放、视觉回归 |

## 配套文件与证据范围

- [独立图源与源码索引](diagrams/code-atlas-2026-09-06/README.md)：每张图的 `.mmd`、生产文件清单和自动提取的 HTTP 注册项。
- `source-inventory.json` 记录生产源文件 SHA-256、Python AST import、顶层符号和路由注册源码位置。它不读取用户资产、运行数据库或应用设置内容。
- Python 静态 import 列表包含函数内和 `TYPE_CHECKING` 导入；不是运行时调用图。React 的动态行为按本图册已读取的入口说明，清单不声称解析了完整 TypeScript 调用图。
- 此文档记录当前代码，也记录尚未接通或刻意分离的能力；后续实现改变时，应更新相应分图并重新生成索引。
