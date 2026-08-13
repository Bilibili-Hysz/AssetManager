# AssetManager

**Python 桌面资产管理器 + 局域网分享服务器**

AssetManager 是一款基于 PySide6 (Qt) 的桌面资产管理应用，内置 aiohttp 局域网分享服务器。用户可以通过桌面端管理文件资产库（元数据、标签、缩略图），也可以通过局域网内的浏览器远程浏览和下载资产。

<!-- stats: app_services=42 core=29 dialogs=17 domain_events=15 e2e_specs=6 hooks=14 i18n_en=812 i18n_ja=812 i18n_zh=812 icons=56 pages=26 python_test_files=232 repos=17 routes=140 routes_modules=24 schema_version=28 stores=4 themes=22 ts=115 webui_test_files=103 widgets=13 -->
> 当前审查证据（2026-08-13，本机 Windows / Python 3.14.3，DSH 沙箱环境）：最近一次 Python 全量运行结果为 **3447 passed, 7 skipped**（沙箱下以 `-n 0` 单进程运行；4 个 multiprocessing 命名管道测试 + 1 个沙箱偶发被阻断，CI 环境不受影响）；`ruff check AssetsManager tests scripts run.py` **全绿**；compileall 通过；**pyright 0 errors / 0 warnings**（CI "Type Check (pyright hard gate)" 固定 1.1.410）。WebUI 单测/typecheck/build/E2E 在上一次会话实测为 683/通过/51 passed 2 skipped（本机沙箱禁止 Node 子进程管道，未复跑；以 CI 为准）。CI Python 3.12/3.13/3.14 矩阵为硬门禁（3.14 已从 continue-on-error 转正，待首次 CI 实跑确认）；clean checkout/Windows package smoke 和真实后端 Commerce 验收仍需分别看待。完整审查文档集见 `docs/full-review/`（含模块地图、数据流、事件系统、审查结果与验证基线）。


> **2026-08-11 更新**：完成 UI/SVG 修复轮（13 项审计 + SVG 化 + 语义色体系 + 菜单栏）、P0 高危轮（15+4）、中危轮（D1/D2/E/F/G1/G2）与 P1 轮（M6a/M9/M6c，42 项清单）——含分享密码强度与爆破防护、投递令牌 rotate 配额守恒与撤销、匿名配额 cookie 身份、备份上限与并发检测、令牌 nonce 等。所有改动处于工作区**未提交**状态（529 条变更），未执行 stage、commit、reset 或 clean。
>
> **2026-08-09 深审增量**：本轮完成 identity marker no-clobber、parent-directory durable flush（含新建祖先目录链）、Seller early-stop/startup-failure 撤销、LAN cleanup attempt 状态协议与普通 stop 失败单次重试、v8/v16/v19 历史 DDL 冻结校正，以及 PyInstaller 稳定资源合同修复。`RuntimeData/Shared` 不再被打进 bundle；icon source 使用已跟踪的 `Assets/icons`，发布目标仍为 `assets/icons`。

---

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [项目架构](#项目架构)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [开发指南](#开发指南)
- [构建与部署](#构建与部署)
- [LAN 分享系统](#lan-分享系统)
- [插件系统](#插件系统)
- [国际化](#国际化)
- [测试](#测试)

---

## 功能特性

### 桌面端 (PySide6)

- **文件浏览**：网格/列表视图，支持缩略图预览、元数据显示、标签管理
- **多库支持**：在多个资产库之间切换，每个库独立的数据库和设置
- **图片查看器**：内置图片预览，支持缩放、平移
- **标签系统**：为文件添加标签，支持标签树、标签搜索、批量操作
- **元数据管理**：为文件添加备注、URL 链接、自定义属性
- **撤销/重做**：文件操作支持撤销和重做（按库隔离）
- **主题系统**：深色/浅色/自定义主题，支持实时预览和切换
- **背景效果**：支持模糊/马赛克背景效果
- **插件系统**：可扩展的插件架构，支持自定义分类、菜单、文件处理器
- **系统托盘**：最小化到系统托盘，支持快捷操作
- **工作区标签**：多标签页浏览不同目录
- **快捷键**：丰富的键盘快捷键支持

### 局域网分享 (aiohttp)

- **文件浏览**：通过浏览器浏览资产库，支持网格/列表/瀑布流视图（React SPA）
- **文件下载**：单文件下载和批量 ZIP 打包下载（免费下载配额限制）
- **分享链接**：创建密码保护（≥8 字符 + 暴力破解锁定）、限时、限次的分享链接
- **用户系统**：管理员/注册用户/访客三级权限，支持邀请码注册、卖家独立会话
- **QR 码**：生成分享链接的 QR 码，支持一键复制
- **Cloudflare 隧道**：一键暴露到公网，支持自动下载/校验 cloudflared
- **WebSocket**：实时失效推送（projection_invalidated，HTTP 快照为权威）
- **商城系统**：商品目录/购物车/结账（幂等键）/订单状态机/投递令牌（rotate/revoke）/卖家面板/匿名分析
- **安全机制**：速率限制（通用 + 认证双限流）、IP 黑名单/白名单、路径遍历防护、认证中间件（fail-closed）、令牌撤销表
- **移动端适配**：响应式布局，底部操作栏，触摸优化

### 国际化

- 支持英语、中文、日语三种语言
- 桌面端和 Web 端均有完整翻译
- Web 端自动检测浏览器语言，支持手动切换

---

## 技术栈

### 核心框架

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.12/3.13/3.14 | 主语言（CI 矩阵；本机 3.14） |
| PySide6 | >=6.6,<7 | 桌面 UI 框架 (Qt 6) |
| aiohttp | >=3.9 | 异步 HTTP 服务器（可选依赖） |
| SQLite3 | 内置 | 数据库 (WAL 模式，迁移 v1-v28) |
| Pillow | >=10.0 | 图片处理（缩略图/EXIF/模糊） |
| segno | >=1.6 | QR 码生成 |
| send2trash / requests | — | 回收站删除 / HTTP 工具 |

### 桌面 UI

| 组件 | 说明 |
|------|------|
| QDockWidget | 可拖拽停靠面板（dock_factory 统一构建） |
| QAbstractListModel | 文件列表数据模型（FileSystemModel/DetailModel） |
| QPropertyAnimation | UI 动画（主题过渡/网格缓动） |
| QThreadPool | 异步任务执行（缩略图加载/后台扫描） |
| signal_bus | Qt 信号总线（7 信号，低频协调） |
| event_bus | 领域事件总线（业务逻辑，线程安全） |
| icons.py | SVG 图标注册表（56 图标，DPR 感知渲染，语义色 token） |

### LAN 服务器

| 组件 | 说明 |
|------|------|
| aiohttp.web | REST API（140 条路由）+ WebSocket |
| aiohttp middleware | 认证、安全、速率限制（顺序：security → metrics → auth） |
| PathGuard | 路径遍历防护（resolve + is_relative_to） |
| HMAC tokens | 认证令牌（ts.nonce.sig，24h；不支持 query 认证） |
| WebSocketManager | 50 连接/心跳 30s/1MB 帧截断 |
| Cloudflare Tunnel | 公网穿透（可选，自动下载校验） |
| React SPA | 前端由 `webui/dist` 托管（pages.py SPA 回退） |

### 数据层

| 组件 | 说明 |
|------|------|
| DatabaseManager | 每库独立连接 + 身份标记 + 读写门（_WriteGate）+ 归属校验 |
| db_migrations | 版本化迁移 v1-v28（SAVEPOINT 原子 + 契约回溯校验） |
| schema_defs | 表 DDL 契约（SchemaObjectContract 校验器，fail-closed） |
| repositories/ | **17 个 SQL 仓库**（tag/metadata/thumbnail/favorite/share/auth/asset_index/plugin_metadata/shop/order/quota/free_download_quota/seller_profile/storefront_analytics/shop_buyer/gallery_home/revoked_token）——统一 for_session 绑定 + SAVEPOINT 事务 + CAS |
| LibraryLock | 跨进程库锁（QLockFile 引用计数，staleLockTime(0)） |
| json_store / settings | JSON 原子持久化（mkstemp+fsync+os.replace） |

### 开发工具

| 工具 | 用途 |
|------|------|
| ruff | 代码风格检查 |
| pyright | 类型检查 |
| pytest | 测试框架 |
| Cython | 热点模块编译加速 |
| PyInstaller | 打包为独立 exe |

---

## 项目架构

```
┌─────────────────────────────────────────────────────────┐
│                    Presentation Layer                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │  Panels   │  │ Dialogs  │  │ Widgets  │  │ React   │ │
│  │(file_list,│  │(settings,│  │(toast,   │  │  SPA    │ │
│  │ sidebar,  │  │ share,   │  │ tray,    │  │(webui/) │ │
│  │ info,tag) │  │ startup) │  │ tab)     │  │         │ │
│  └─────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬────┘ │
│        └──────────────┼──────────────┼──────────────┘     │
├───────────────────────┼──────────────┼────────────────────┤
│                 Controllers Layer                         │
│  ┌─────────────────┐ ┌────────────┐ ┌──────────────────┐ │
│  │FileListController│ │InfoController│ │TagTreeController│ │
│  └────────┬────────┘ └─────┬──────┘ └────────┬─────────┘ │
├───────────┼────────────────┼──────────────────┼───────────┤
│                  Application Layer（42 模块）              │
│  LibraryService  Runtime/LibrarySession  RuntimeEventRouter│
│  AssetIndex/Reconciliation/Undo/FileOperation/Export       │
│  Metadata/Tag/Thumbnail/Search/Project/Gallery/Favorite    │
│  Auth/Share/Order/Shop/ShopBuyer/Quota/Seller*/Analytics   │
├────────────────────────────────────────────────────────────┤
│                   Domain Layer                             │
│  events/event_bus  errors  asset  library  share  auth     │
├────────────────────────────────────────────────────────────┤
│                Infrastructure Layer                        │
│  database/schema_defs/db_migrations  settings  themes/icons│
│  plugins  path_resolver/library_lock  cache  json_store    │
│  session_contract  performance  crash_handler  bg_effects  │
└────────────────────────────────────────────────────────────┘
        LAN 层（aiohttp：server/manager/ws/security/tunnel/
        path_guard/principal/dto + routes/ 24 模块 140 条路由）
```

### 架构原则

- **分层架构**：Domain → Repositories → Application → Presentation/LAN，依赖向下流动
- **依赖注入**：`ApplicationBootstrap` 通过 `ServiceContainer` 管理服务生命周期；每库 `LibraryRuntime`/`LibraryScopedServices` 作用域；LAN 服务经 `_LanServicesHolder` 懒投影
- **领域事件**：业务事件通过 `event_bus` 发布 → `RuntimeEventRouter` 映射为投影失效（WebSocket 推送 + 桌面 Qt 桥）
- **Qt 信号**：UI 层内部通信使用 Qt 信号/槽机制
- **Repository 模式**：所有 SQL 操作封装在 Repository（for_session 绑定 + SAVEPOINT + CAS）
- **LibrarySession**：每库独立的服务作用域（operation 租约），切换库时注入新服务
- **fail-closed**：认证/锁/schema 校验在无法确认安全状态时拒绝而非放行

---

## 项目结构

```
AssetsManager_old-bak/
├── AssetsManager/              # 主包
│   ├── app.py                  # 应用入口（启动窗口 → 主窗口）
│   ├── window.py               # 主窗口（QMainWindow + LanSharingMixin）
│   ├── window_coordinator.py   # 窗口协调器（主题动画/语言/菜单）
│   ├── window_lifecycle_coordinator.py  # 库切换与退出编排
│   ├── dock_factory.py         # QDockWidget 工厂
│   │
│   ├── application/            # 应用服务层（42 模块，20k 行）
│   │   ├── bootstrap.py        # DI 装配（LibraryScopedServices/LanRuntimeServices）
│   │   ├── runtime.py          # LibraryRuntime（服务快照/事件路由/生命周期）
│   │   ├── context.py          # LibrarySession/LibraryContext（operation 租约）
│   │   ├── library_service.py  # 库生命周期（open/close 状态机 + restore 保留）
│   │   ├── runtime_events.py   # RuntimeEventRouter（投影失效路由）
│   │   ├── asset_index_service.py / asset_index_reconciliation_service.py
│   │   ├── reconciliation_queue.py / _store.py / _migration.py
│   │   ├── file_operation_service.py / undo_service.py
│   │   ├── library_export_service.py  # 备份/恢复/导出（1748 行）
│   │   ├── database_integrity_service.py / database_maintenance_service.py
│   │   ├── metadata/tag/thumbnail/search/project/asset/favorite/gallery_service.py
│   │   ├── auth_service.py / share_service.py / security_preflight.py
│   │   ├── shop_service.py / shop_buyer_service.py / order_service.py
│   │   ├── quota_service.py / free_download_quota_service.py
│   │   ├── seller_auth_service.py / seller_profile_service.py
│   │   ├── storefront_analytics_service.py / shop_authorization.py
│   │   ├── plugin_service.py / library_settings_adapter.py / asset_filters.py
│   │   └── ...
│   │
│   ├── controllers/            # UI 控制器（非 Qt 业务逻辑）
│   │   ├── file_list_controller.py
│   │   ├── info_controller.py
│   │   ├── sidebar_controller.py
│   │   └── tag_tree_controller.py
│   │
│   ├── core/                   # 基础设施层（29 模块 + plugins/4）
│   │   ├── database.py         # DatabaseManager（连接/身份标记/读写门）
│   │   ├── db_migrations.py    # 数据库迁移 v1-v28
│   │   ├── schema_defs.py      # 表 DDL 契约 + 校验器
│   │   ├── settings.py / config_migrator.py / json_store.py
│   │   ├── themes.py / theme_loader.py / icons.py / bg_effects.py
│   │   ├── color_utils.py / format_utils.py / ui_scale.py
│   │   ├── path_resolver.py / library_lock.py / library_manager.py
│   │   ├── session_contract.py / protocols.py / constants.py
│   │   ├── signal_bus.py / singleton.py / performance.py
│   │   ├── cache.py / directory_cache.py / tag_library.py
│   │   ├── tag_store.py / project_data.py / tool_scheduler.py
│   │   ├── crash_handler.py
│   │   └── plugins/            # 插件系统
│   │       ├── descriptor.py / host_context.py / loader.py / manager.py
│   │
│   ├── domain/                 # 领域层（无基础设施依赖）
│   │   ├── events.py           # 15 个领域事件（frozen dataclass）
│   │   ├── event_bus.py        # 领域事件总线（线程安全）
│   │   ├── errors.py           # DomainError 层级
│   │   ├── asset.py / auth.py / library.py / share.py
│   │
│   ├── repositories/           # 数据访问层（17 个 SQL 仓库）
│   │   ├── tag/metadata/thumbnail/favorite/share/auth_repository.py
│   │   ├── asset_index_repository.py
│   │   ├── plugin_metadata_repository.py
│   │   ├── shop/order/quota/free_download_quota_repository.py
│   │   ├── seller_profile/storefront_analytics/shop_buyer_repository.py
│   │
│   ├── lan/                    # LAN 服务器（aiohttp）
│   │   ├── server.py           # _LanServerImpl（认证中间件/撤销表/负缓存）
│   │   ├── manager.py          # ShareManager 状态机
│   │   ├── api.py              # 路由注册（139 条）+ realtime 桥
│   │   ├── auth.py / principal.py / dto.py / utils.py
│   │   ├── path_guard.py / security.py / scanner.py
│   │   ├── tunnel.py           # Cloudflare 隧道
│   │   ├── ws.py               # WebSocketManager
│   │   └── routes/             # 24 个路由模块（约 89 handler）
│   │       ├── auth/files/downloads/shares/tags/thumbnails/metadata
│   │       ├── users/system/websocket/pages/quicksearch/image
│   │       ├── gallery/favorites/quota/shop/commerce_policy
│   │       ├── seller_auth/seller_profile/storefront_analytics
│   │       ├── _helpers.py / _resource_urls.py
│   │
│   ├── panels/                 # Qt 停靠面板
│   │   ├── file_list/          # 17 文件（grid 自绘网格/列表/详情/加载器/动作）
│   │   ├── sidebar.py / info.py / tag_tree.py / image_viewer.py
│   │   ├── empty.py / base.py / _event_bridge.py
│   │
│   ├── dialogs/                # Qt 对话框（17 个）
│   │   ├── startup/settings/tabbed_dialog/sharing_settings(2212 行)
│   │   ├── share_link/share_qr/_share_api/theme_preview
│   │   ├── sidebar_favorites/sidebar_recent/sidebar_settings
│   │   ├── tag_editor/plugin_manager/color_picker/generic_settings
│   │
│   ├── widgets/                # 可复用 Qt 组件（13 个）
│   │   ├── toast/status_indicator/tag_chip/tab_container
│   │   ├── workspace_bar/tray/hsv_wheel/stylekit/elevation
│   │   ├── lan_sharing/collapsible_panel/shortcut_manager
│   │   ├── theme_preview（2026-08-13 删除 6 个零消费方组件：
│   │   │   command_palette/file_picker/pager_overlay/theme_gallery/status_bar/title_bar）
│   │
│   ├── di/                     # 依赖注入容器
│   └── i18n/                   # 国际化（en 812 / zh 812 / ja 812 keys）
│
├── webui/                      # React 18 + Vite + TS SPA（217 ts/tsx）
│   ├── src/                    # api(15 工厂)/stores(4 Context)/hooks(14)
│   │                           # pages(26)/components(10 域)/types/i18n
│   ├── e2e/                    # Playwright 6 spec（53 用例，默认 51 passed、2 skipped）
│   └── dist/                   # 构建产物（打进 PyInstaller bundle）
│
├── tests/                      # 本机复核基线（Windows：3450 passed, 7 skipped）
│   ├── core/ unit/ integration/ desktop/ lan/
│   ├── performance/ perf/ e2e/ contracts/ fixtures/
│
├── docs/                       # 文档
│   ├── full-review/            # 完整审查文档集（构造详情/模块地图/数据流/事件/审查结果/验证）
│   ├── compose/                # specs/plans/reports/handoffs
│   └── adr/                    # 架构决策记录
│
├── Plugins/                    # 插件（Addons/booth_link、download_tracker）
├── Assets/Themes/              # 22 个主题 JSON（13 暗 + 9 亮）
├── RuntimeData/                # 运行时数据（设置、缓存、库身份标记）
├── main.py / run.py            # 入口脚本
├── build.py                    # 构建脚本
├── setup_cython.py             # Cython 编译脚本
├── AssetManager.spec           # PyInstaller 打包规格
├── pyrightconfig.json / pytest.ini
├── requirements*.txt           # 核心/LAN/开发/性能依赖
```

---

## 快速开始

### 环境要求

- Python 3.12+ (推荐 3.14)
- Windows 10/11 (主要平台)
- Visual Studio Build Tools (Cython 编译需要)

### 安装

```bash
# 克隆项目
git clone <repo-url>
cd AssetsManager_old-bak

# 安装核心依赖
pip install -r requirements.txt

# 安装 LAN 分享依赖（可选）
pip install -r requirements-lan.txt

# 安装开发依赖（可选）
pip install -r requirements-dev.txt
```

### 运行

```bash
# 启动应用
python main.py

# 或使用预构建的 exe
dist/AssetManager/AssetManager.exe
```

### 首次启动

1. 启动后显示「启动窗口」
2. 选择或创建一个资产库目录
3. 进入主窗口，开始浏览文件

---

## 开发指南

### 质量门

每次提交前必须通过：

```bash
python -m ruff check AssetsManager tests scripts run.py
python -m pyright
python -m compileall -q AssetsManager tests
python -m pytest -q -p no:cacheprovider
```

本机复核状态（2026-08-13，Windows / Python 3.14.3）：**Python 全量回归 3450 passed, 7 skipped, 0 failed**；**`ruff check AssetsManager tests scripts run.py` 全绿**；**compileall 通过**。默认浏览器 E2E 共 53 个测试（6 个 spec，含 23 个 axe-core 双主题无障碍扫描），当前本机 **51 passed、2 skipped**；其中 Mock/Shell 子集为 12 passed，真实后端用例在未配置环境变量时跳过。7 个 Python skip 包括 Windows symlink 权限限制与历史 multiprocessing Queue 终止 draft。Pyright 在本机 Python 3.14 + pyright 1.1.410 下 **0 errors / 0 warnings**（CI "Type Check (pyright hard gate)" 已固定同版本）。远程 CI 的 Python 3.12/3.13/3.14 矩阵仍是独立门禁；本轮 WebUI 单测 `683 passed`、`typecheck` 与 `build` 通过。
> **G17 边界：** Reconciliation queue 当前支持单 library、单 application owner 下的 stop-the-world cutover、lease recovery 与 stale-worker protection；不支持旧版/新版应用同时持有同一 library 的 rolling upgrade。详细证据见 `docs/compose/reports/g17-stop-the-world-cutover-release-ownership-checklist-2026-08-08.md`。

### Cython 编译加速

```bash
# 安装 Cython
pip install cython

# 编译热点模块（LRUCache, color_utils, format_size, asset_filters）
python setup_cython.py build_ext --inplace

# 验证加速效果
python -m pytest tests/performance/test_cython_benchmarks.py -v -s
```

加速效果：
| 模块 | 编译前 | 编译后 | 提升 |
|------|--------|--------|------|
| format_size | 1.2M ops/s | 2.8M ops/s | 2.3x |
| is_hidden | 10M ops/s | 14.9M ops/s | 1.5x |
| hex_to_rgb | 2.1M ops/s | 3.2M ops/s | 1.5x |
| matches_search | 7.3M ops/s | 9.8M ops/s | 1.3x |

### 性能基准测试

```bash
python -m pytest tests/performance/test_baselines.py -v
```

测试内容：
- 1K/10K 文件目录列表
- 元数据读取延迟
- 标签列表性能
- PathGuard 路径解析
- 索引搜索性能
- 分享链接创建/读取
- 目录缓存冷/热对比

---

## 构建与部署

### PyInstaller 打包

```bash
# 完整构建（清理 + 编译 + 优化 + 报告）
python build.py --clean --build --optimize --report

# 输出
# dist/AssetManager/AssetManager.exe (127 MB)
```

### 构建优化

| 优化项 | 节省 |
|--------|------|
| Cloudflare 延迟下载 | -51.6 MB |
| 删除 opengl32sw.dll | -19.7 MB |
| 排除未使用 Qt/PIL 模块 | -31.6 MB |
| 精简翻译文件 | -3 MB |
| **总计** | **262 MB → 127 MB** |

### CI/CD

GitHub Actions 工作流（`.github/workflows/ci.yml`）：

```yaml
- Lint: `ruff check AssetsManager tests scripts run.py`
- Git Hygiene: whitespace check
- Type Check: pyright
- WebUI: `npm test` + typecheck + build
- Windows Package Smoke
- Windows Regression
- Python Test Matrix: compileall + pytest (Python 3.12, 3.13, 3.14)
- Browser E2E：6 个 spec，共 53 tests（当前本机 51 passed、2 skipped；Mock/Shell 子集 12 passed）
```

### 可选真实后端 Commerce 浏览器验收

真实后端验收不属于默认 CI 门禁，但可以使用 `webui/e2e/commerce-real-backend.spec.ts` 对隔离后端执行完整的买家 Checkout、Seller Fulfill、Buyer Delivery 链路。测试默认跳过；运行前必须准备一个启用 Commerce/Seller、至少包含一个 active 商品和 Seller 管理员账号的隔离后端：

```powershell
$env:REAL_COMMERCE_BASE_URL = "http://127.0.0.1:8765"
$env:REAL_COMMERCE_SELLER_USERNAME = "admin"
$env:REAL_COMMERCE_SELLER_PASSWORD = "<isolated-admin-password>"
npm run test:e2e -- e2e/commerce-real-backend.spec.ts
```

默认 `webui-e2e` job 现在运行全部 6 个 spec（含 axe-core 无障碍门禁）；真实后端 spec 在未设置环境变量时自带 skip，因此默认本机结果为 51 passed、2 skipped。Mock/Shell 子集仍为 12 个测试；设置隔离后端环境变量后才会执行真实 Commerce 链路。

---

## LAN 分享系统

### 启动分享

```python
# 桌面端：点击工具栏的分享按钮
# 或通过代码（需绑定 LibraryRuntime 的服务快照）：
from AssetsManager.lan import LanServer
from AssetsManager.application import ApplicationBootstrap

bootstrap = ApplicationBootstrap()
session = bootstrap.library_service.open_session("/path/to/library")
runtime = bootstrap.runtime_for(session)
server = LanServer(runtime=runtime)     # 构造器强制 runtime=（无 library_root 参数）
server.start(port=8080)
```

### API 端点

LAN 服务器注册 **140 条路由**（实测 `api.py` `_add` 注册：页面 32 / Commerce-Seller 53 / 认证 8 / 核心库 API 46）。完整路由表（方法+路径+权限+handler+服务）见 `docs/full-review/02-module-map.md` 与 `docs/compose/reports` 系列；主要端点：

| 端点 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/api/files`、`/api/files/summaries` | GET/POST | browse | 文件列表/目录摘要 |
| `/api/projects`、`/api/tree`、`/api/home` | GET | browse | 项目列表/树/首页聚合 |
| `/api/search`、`/api/quicksearch` | GET | browse | 双轨搜索（标签/名称/索引） |
| `/api/gallery/home|collection|resolve` | GET | browse | 画廊投影（预算受限；单文件事件增量更新，失败回退全量重建） |
| `/api/favorites` | GET/POST/DELETE | browse | 收藏（主体作用域） |
| `/api/tags`、`/api/tags/{name}` | GET/POST/PUT/DELETE | admin 写 | 标签管理 |
| `/api/shares`、`/api/shares/{id}/...` | GET/POST/DELETE | manage_links | 分享管理；verify/info/download/preview 公开 |
| `/api/download/{path}`、`/api/download/batch` | GET/POST | download+配额 | 下载/批量 ZIP |
| `/api/thumbnails/{path}`、`/api/thumbnails/batch` | GET/POST | preview | 缩略图 |
| `/api/image` | GET | preview | 原图（Pillow verify 内容门） |
| `/api/meta/{path}`、`/api/notes/{path}` | GET/PUT | browse/admin | 元数据/备注 |
| `/api/auth/*` | POST | 公开+限流 | login/register/verify_key/logout/me |
| `/api/users`、`/api/invites`、`/api/activity`、`/api/online-users` | GET/POST | admin | 用户/邀请码/活动/在线 |
| `/api/info` | GET | 公开 | 服务器信息（feature_flags 驱动前端路由） |
| `/api/revision` | GET | realtime | 实时游标（epoch+revision） |
| `/api/tunnel/status` | GET | admin | 隧道状态 |
| `/api/quota` | GET | 公开 | 免费下载配额 |
| `/api/shop/*` | 55 条 | commerce/seller/receipt/buyer | 商城全套（目录/购物车/结账/订单/投递/卖家/分析） |
| `/ws` | WS | realtime | WebSocket（失效推送） |
| `/s/{id}`、`/browse`、`/storefront/*`、`/seller/*` | GET | 公开 | SPA 页面 |

### Commerce / Seller 售卖目录限制

启用 Commerce 和 Seller 后，可在桌面端的分享设置中配置“允许售卖的目录”。
`lan_shop_authorized_roots` 保存为相对于资源库根目录的路径列表（每行一个）；
配置后，只有这些目录内的项目可以上架、出现在商城并创建订单。留空保持兼容行为，
允许整个资源库。未保存桌面设置时，也可以通过环境变量
`SHOP_AUTHORIZED_ROOTS=shop/sales;original` 提供分号分隔的目录列表。

服务端会拒绝绝对路径、盘符路径和包含 `..` 的路径，并在创建商品、更新商品、公开目录、
订单创建及交付解析等边界重复执行校验。

同一页面还可以配置普通资源库下载额度：启用后按用户或 IP 计算每日/每周下载次数，
并可设置总次数与两次下载之间的最小间隔。该额度只作用于普通库下载，不影响分享链接交付。

### 权限模型

六种 principal：`guest / password / access_key / local_ui / user / share`；能力位掩码 8 位：**browse / preview / download / upload / manage_links / manage_users / settings / realtime**。

| 角色 | 浏览 | 预览 | 下载 | 上传 | 管理链接 | 管理用户 | 设置 | 实时 |
|------|------|------|------|------|----------|----------|------|------|
| 管理员（password/access_key/local_ui） | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 注册用户 | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| 访客 | ✅* | ✅ | ❌* | ❌ | ❌ | ❌ | ❌ | ❌ |
| 分享访问者 | ✅* | ✅* | ✅* | ❌ | ❌ | ❌ | ❌ | ❌ |

*访客浏览/预览默认开启（`lan_guest_list`/`lan_guest_preview`），下载默认关闭（`lan_guest_download`）；分享访问者的能力由分享配置决定（密码/限时/限次/allow_preview）。

**卖家门（独立体系）**：`require_seller` = seller feature 启用 + LAN 管理员 principal 或 `seller_session` cookie（SellerAuthService，12h 内存会话，管理员降权即失效）。

### 分享链接权限

- **只读**：只能预览（图片/视频/文本）
- **可下载**：预览 + 下载（先准备响应成功再计数，超限 429）
- **密码保护**：≥8 字符；连续失败 5 次锁定 60 秒（429 + Retry-After）
- **限时**：过期后自动失效（410 折叠为 404）
- **限次**：达到下载次数后自动失效
- **撤销**：删除分享即时阻断下载与令牌（is_active=0）

---

## 插件系统

### 插件结构

```
Plugins/Addons/my_plugin/
├── plugin.json     # 插件描述符
├── parser.py       # 入口模块
└── ...
```

### plugin.json

```json
{
  "id": "my_plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "entry": "parser.py",
  "permissions": ["filesystem.read"]
}
```

### 插件能力

- 注册自定义文件分类
- 添加菜单项和工具栏按钮
- 注册文件解析器
- 注册搜索提供者
- 注册主题令牌
- 注册事件钩子

### 权限系统

插件权限是建议性的（advisory），不强制执行。插件运行在完整的 Python 解释器中，拥有完全的系统访问权限。

---

## 国际化

### 支持语言

| 语言 | 文件 | 状态 |
|------|------|------|
| English | `i18n/en.json` | ✅ 完整 |
| 中文 | `i18n/zh.json` | ✅ 完整 |
| 日本語 | `i18n/ja.json` | ✅ 完整 |

### 添加新语言

1. 复制 `i18n/en.json` 为 `i18n/xx.json`
2. 翻译所有键值
3. 在 `i18n/__init__.py` 中注册语言代码

### Web 端 i18n

Web 端使用独立的 i18n 系统（`webui/src/i18n/`）：
- `index.ts` — 外部 store（t/setLang/getLang/subscribeToLang，useSyncExternalStore 订阅）
- `en.ts / zh.ts / ja.ts` — 三语字典（localStorage `am_lang` 持久化）

---

## 测试

### 测试结构

```
tests/
├── core/           # 核心基础设施测试（数据库、迁移、设置、主题、缓存、打包）
├── unit/           # 单元测试（领域、控制器、过滤器、事件、边界扫描）
├── integration/    # 集成测试（服务层、Repository、库生命周期、对账队列）
├── desktop/        # 桌面 UI 测试（PySide6 offscreen 模式）
├── lan/            # LAN API 测试（安全、路由、路径防护、契约）
├── contracts/      # LAN 公开契约 JSON（lan_public_contracts.json）
├── fixtures/db/    # 历史 schema 快照（v1_schema.sql）
├── e2e/            # 真实 LAN + Playwright Chromium 验收
├── performance/    # 性能基准测试（目录列表、元数据、搜索、Cython）
└── perf/           # 基准脚本（grid/thumbnail/directory telemetry）
```

### 运行测试

```bash
# 全部测试（基线 3450 passed, 7 skipped）
python -m pytest -q -p no:cacheprovider

# 特定目录
python -m pytest tests/unit/ -q
python -m pytest tests/lan/ -q

# 性能测试
python -m pytest tests/performance/ -v

# 前端（webui/ 下）
npm test && npm run typecheck && npm run build
npm run test:e2e   # Playwright 30 用例（28 passed/2 skipped）
```

### 测试 fixture

- `temp_dir` — 临时目录
- `memory_db` — 内存 SQLite 数据库
- `schema_db` — 带完整迁移 schema 的内存数据库
- `_cleanup_stores` (autouse) — 测试后清理全局状态（QThreadPool/DB/EventBus/RuntimeData）

---

## 许可证

私有项目。


---

## 2026-08-09 package smoke 复核

本机 Windows / Python 3.14 工作区已完成一次不污染当前仓库的真实 PyInstaller 验证：

- PyInstaller `6.19.0` 成功构建 onedir bundle；
- `scripts/check_package_contents.py` 资源检查通过；
- bundle 在 `QT_QPA_PLATFORM=offscreen` 下成功启动并保持运行，随后仅停止本次临时 smoke 进程；
- package contract tests 当前为 `15 passed`；
- 清除了 `AssetManager.spec` 中已不存在的 `aiohttp.protocol` 与 `AssetsManager.application.thumbnail_repository` hidden imports，并增加防回归测试。

该证据针对当前 dirty 工作区的临时输出目录，不等价于 clean checkout 或 GitHub-hosted Windows runner；后两项仍是提交前外部门禁。
