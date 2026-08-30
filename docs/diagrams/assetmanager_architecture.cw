# session_id: e2545483-71c7-4d65-9912-e4e50bbc38e4
classes: {
  zone_1: {
    style: {
      fill: "#F1F5FF"
      stroke: "#4E81FF"
      font-color: "#333333"
      border-radius: 8
    }
  }
  zone_2: {
    style: {
      fill: "#F3F7FF"
      stroke: "#4E81FF"
      font-color: "#333333"
      border-radius: 8
    }
  }
  zone_3: {
    style: {
      fill: "#F6F9FF"
      stroke: "#4E81FF"
      font-color: "#333333"
      border-radius: 8
    }
  }
  zone_4: {
    style: {
      fill: "#F9FBFF"
      stroke: "#4E81FF"
      font-color: "#333333"
      border-radius: 8
    }
  }
  zone_5: {
    style: {
      fill: "#FCFDFF"
      stroke: "#4E81FF"
      font-color: "#333333"
      border-radius: 8
    }
  }
  entity: {
    style: {
      fill: "#FFFFFF"
      stroke: "#1F2937"
      font-color: "#333333"
      border-radius: 6
      shadow: true
    }
  }
  signal: {
    style: {
      fill: transparent
      font-color: "#6B7280"
    }
  }
}

direction: down

# ============ ENTRY LAYER ============
entry: {
  class: zone_1
  label: "入口层 ENTRY"
  direction: right

  main: main.py / run.py {
    class: entity
    label: "main.py / run.py\n进程引导"
  }
  app: app.py {
    class: entity
    label: "app.py\n应用装配"
  }
  window: window.py {
    class: entity
    label: "window.py\n启动窗口选库 → 主窗口"
  }

  main -> app: 启动
  app -> window: 创建
}

# ============ PRESENTATION LAYER ============
presentation: {
  class: zone_2
  label: "展示层 PRESENTATION（双展示面，零业务规则）"
  direction: down

  desktop_ui: {
    class: zone_3
    label: "桌面 UI（纯渲染）"
    direction: right

    panels: panels/ {
      class: entity
      label: "panels/\nsidebar · file_list · info\ntag_tree · image_viewer"
    }
    widgets: widgets/ {
      class: entity
      label: "widgets/\n14 个可复用 Qt 组件"
    }
    dialogs: dialogs/ {
      class: entity
      label: "dialogs/\n21 个对话框"
    }
    dock_factory: dock_factory {
      class: entity
      label: "dock_factory\n统一 dock 构建"
    }
    window_lc: window_lifecycle_coordinator.py {
      class: entity
      label: "window_lifecycle_coordinator.py"
    }
    tray: 系统托盘 {
      class: entity
    }
    stylekit: stylekit/ {
      class: entity
      label: "stylekit/\n主题预览"
    }
    grid-columns: 3
  }

  controllers: {
    class: zone_3
    label: "Controllers（4 个，零 Qt import）"
    direction: right

    info_ctrl: InfoController {
      class: entity
      label: "InfoController\n元数据/标签/备注"
    }
    filelist_ctrl: FileListController {
      class: entity
      label: "FileListController\n搜索历史/状态"
    }
    tagtree_ctrl: TagTreeController {
      class: entity
      label: "TagTreeController\n标签 CRUD"
    }
    sidebar_ctrl: SidebarController {
      class: entity
      label: "SidebarController\n搜索计数"
    }
    grid-columns: 2
  }

  lan_ui: {
    class: zone_3
    label: "LAN 展示（可选侧翼）"
    direction: right

    lan_routes: lan/routes/* {
      class: entity
      label: "lan/routes/*\n24 模块 · 140 路由"
    }
    react_spa: React SPA {
      class: entity
      label: "React SPA\nwebui/dist 托管\nRealtimeContext"
    }
  }

  desktop_ui -> controllers: 委托
  controllers -> lan_ui: 共享同一套服务
}

# ============ APPLICATION + RUNTIME LAYER ============
application: {
  class: zone_4
  label: "应用与运行时层 APPLICATION + RUNTIME（51 个服务模块，DI 装配）"
  direction: down

  bootstrap: {
    class: zone_3
    label: "DI 装配"
    direction: right

    app_bootstrap: ApplicationBootstrap {
      class: entity
    }
    service_container: ServiceContainer {
      class: entity
    }
    library_runtime: LibraryRuntime {
      class: entity
    }
    library_session: LibrarySession {
      class: entity
    }
    library_context: LibraryContext {
      class: entity
      label: "LibraryContext\n冻结快照：root/data_dir\nthumb_dir/db_conn\ntag_store/project_data"
    }
  }

  eager_services: {
    class: zone_3
    label: "桌面/共享 eager 服务"
    direction: right

    library_svc: LibraryService {
      class: entity
      label: "LibraryService\n开库 + QLockFile 跨进程准入"
    }
    metadata_svc: MetadataService {
      class: entity
    }
    tag_svc: TagService {
      class: entity
    }
    thumb_svc: ThumbnailService {
      class: entity
    }
    fileop_svc: FileOperationService {
      class: entity
    }
    undo_svc: UndoService {
      class: entity
    }
    plugin_svc: PluginService {
      class: entity
    }
    asset_index_svc: AssetIndexService {
      class: entity
    }
    asset_recon_svc: AssetIndexReconciliationService {
      class: entity
    }
    db_integrity: DatabaseIntegrity / Maintenance / Export {
      class: entity
    }
    settings_adapter: LibrarySettingsAdapter {
      class: entity
      label: "LibrarySettingsAdapter\nQt-free 维护边界"
    }
  }

  lan_projection: {
    class: zone_3
    label: "LAN 惰性投影（single-flight 惰性构建）"
    direction: right

    asset_svc: AssetService {
      class: entity
    }
    project_svc: ProjectService {
      class: entity
    }
    search_svc: SearchService {
      class: entity
    }
    gallery_svc: GalleryService {
      class: entity
    }
    favorite_svc: FavoriteService {
      class: entity
    }
    grid-columns: 3
  }

  runtime_sharing: {
    class: zone_3
    label: "冻结 RuntimeSharingServices 包"
    direction: right

    auth_svc: AuthService {
      class: entity
    }
    share_svc: ShareService {
      class: entity
    }
    token_secret: token_secret {
      class: entity
      label: "每 runtime 一次性 token_secret\n（不落库）"
    }
    event_router: RuntimeEventRouter {
      class: entity
      label: "RuntimeEventRouter\n投影失效路由"
    }
    recon_queue: ReconciliationQueue {
      class: entity
      label: "ReconciliationQueue\n跨进程后台重建队列"
    }
  }

  bootstrap -> eager_services: 组装
  bootstrap -> lan_projection: 惰性构建
  bootstrap -> runtime_sharing: 冻结
}

# ============ DOMAIN LAYER ============
domain: {
  class: zone_1
  label: "领域层 DOMAIN（零基础设施依赖）"
  direction: right

  value_objects: 值对象 {
    class: entity
  }
  domain_events: 16 个领域事件 {
    class: entity
    label: "16 个领域事件\ndomain.event_bus 不可变事实"
  }
  error_hierarchy: 错误层级 {
    class: entity
  }
  domain_auth: domain.auth {
    class: entity
    label: "domain.auth\n纯密码哈希/令牌生成"
  }
  grid-columns: 2
}

# ============ REPOSITORIES LAYER ============
repositories: {
  class: zone_2
  label: "仓库层 REPOSITORIES（17 个 SQL 仓库，统一 for_session + SAVEPOINT + CAS）"
  direction: right

  repo_core: {
    class: zone_3
    label: "核心仓库"
    direction: right

    repo_tag: tag {
      class: entity
    }
    repo_metadata: metadata {
      class: entity
    }
    repo_thumb: thumbnail {
      class: entity
    }
    repo_favorite: favorite {
      class: entity
    }
    repo_share: share {
      class: entity
    }
    repo_auth: auth {
      class: entity
    }
    repo_asset_index: asset_index {
      class: entity
    }
    repo_plugin_meta: plugin_metadata {
      class: entity
    }
    grid-columns: 3
  }

  repo_commerce: {
    class: zone_3
    label: "商业仓库"
    direction: right

    repo_shop: shop {
      class: entity
    }
    repo_order: order {
      class: entity
    }
    repo_quota: quota {
      class: entity
    }
    repo_free_quota: free_download_quota {
      class: entity
    }
    repo_seller: seller_profile {
      class: entity
    }
    repo_analytics: storefront_analytics {
      class: entity
    }
    repo_buyer: shop_buyer {
      class: entity
    }
    repo_gallery: gallery_home {
      class: entity
    }
    repo_revoked: revoked_token {
      class: entity
    }
    grid-columns: 3
  }
}

# ============ CORE INFRASTRUCTURE ============
core_infra: {
  class: zone_5
  label: "核心基础设施 CORE INFRASTRUCTURE（被上层共享）"
  direction: right

  database: database.py {
    class: entity
    label: "database.py\nDatabaseManager\n连接级读写门 + 身份标记"
  }
  migrations: db_migrations {
    class: entity
    label: "db_migrations\nv1–v35 契约回溯"
  }
  settings: settings {
    class: entity
  }
  tag_store: tag_store {
    class: entity
  }
  project_data: project_data {
    class: entity
  }
  signal_bus: signal_bus {
    class: entity
    label: "signal_bus\n7 个 Qt 信号，仅 UI 协调"
  }
  path_resolver: path_resolver {
    class: entity
    label: "path_resolver\nPathGuard 防路径穿越"
  }
  themes: themes {
    class: entity
    label: "themes\n24 主题"
  }
  icons: icons {
    class: entity
    label: "icons\n56 图标 DPR 感知"
  }
  cache: cache {
    class: entity
  }
  json_store: json_store {
    class: entity
    label: "json_store\n原子持久化"
  }
  plugins: plugins/ {
    class: entity
    label: "plugins/\ndescriptor/loader/manager/host_context"
  }
}

# ============ LAN LAYER (optional side wing) ============
lan_layer: {
  class: zone_3
  label: "LAN 层（可选，与 core 共享，经 application 访问数据）"
  direction: down

  lan_server: LanServer(runtime) {
    class: entity
  }
  lan_api: lan/api.py {
    class: entity
    label: "lan/api.py\nsetup_routes 注册 140 路由 + 实时桥"
  }
  lan_routes_detail: lan/routes/* {
    class: entity
  }
  lan_auth: lan/auth {
    class: entity
  }
  lan_security: lan/security {
    class: entity
    label: "lan/security\n中间件顺序 security→metrics→auth"
  }
  lan_path_guard: lan/path_guard {
    class: entity
  }
  lan_ws: lan/ws {
    class: entity
    label: "lan/ws\nWebSocketManager\n实时失效推送 >1MB 帧截断"
  }
  lan_tunnel: lan/tunnel {
    class: entity
    label: "lan/tunnel\nCloudflare 一键公网\n强制强认证"
  }
  lan_manager: lan/manager {
    class: entity
    label: "lan/manager\n生命周期"
  }

  lan_server -> lan_api
  lan_api -> lan_routes_detail
  lan_api -> lan_auth
  lan_api -> lan_security
  lan_api -> lan_ws
  lan_api -> lan_tunnel
}

# ============ EXTERNAL DEPENDENCIES ============
external: {
  class: zone_5
  label: "外部依赖 EXTERNAL"
  direction: right

  pyside6: PySide6 {
    class: entity
    label: "PySide6\nQt GUI"
  }
  sqlite3: sqlite3 {
    class: entity
    label: "sqlite3\nWAL + 文件锁 + CAS"
  }
  pillow: Pillow {
    class: entity
    label: "Pillow\n缩略图/内容门"
  }
  aiohttp: aiohttp {
    class: entity
    label: "aiohttp\nLAN 服务"
  }
  segno: segno {
    class: entity
    label: "segno\nQR"
  }
  send2trash: send2trash {
    class: entity
  }
  requests: requests {
    class: entity
  }
  cloudflared: cloudflared {
    class: entity
    label: "cloudflared\n隧道"
  }
  react_vite: React/Vite {
    class: entity
    label: "React/Vite\nwebui 构建产物"
  }
  grid-columns: 3
}

# ============ CROSS-ZONE DEPENDENCY ARROWS (依赖向下) ============
entry -> presentation: 启动装配
presentation -> application: 调用服务
application -> domain: 业务规则
application -> repositories: 持久化
repositories -> core_infra: SQLite 适配
lan_layer -> application: 经 application 访问数据
lan_layer -> core_infra: 与 core 共享
core_infra -> external: 外部依赖

# ============ REAL-TIME INVALIDATION CHAIN ============
application.(bootstrap.library_runtime -> runtime_sharing.event_router): 投影失效
application.runtime_sharing.event_router -> lan_layer.lan_ws: 经 local_ui_auth_secret 鉴权
lan_layer.lan_ws -> presentation.lan_ui.react_spa: WebSocket 失效提示

# ============ OPEN LIBRARY CHAIN ============
entry.main -> application.eager_services.library_svc: open_session
application.eager_services.library_svc -> core_infra.database: QLockFile 准入 → 连接
core_infra.tag_store -> application.bootstrap.library_context: 冻结快照
application.bootstrap.(library_context -> app_bootstrap): runtime_for
application.bootstrap.app_bootstrap -> entry.window: 主窗口 + 各面板