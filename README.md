# AssetManager

> 状态:**LIVING（门面）** · updated: 2026-08-27 · 结构统计由 `scripts/check_doc_stats.py` 守护;详情层见 `docs/overview-2026-08-27.md`。

**Python 桌面资产管理器 + 局域网分享服务器**

AssetManager 是一款基于 PySide6 (Qt) 的桌面资产管理应用,内置 aiohttp 局域网分享服务器。用户可以通过桌面端管理文件资产库(元数据、标签、缩略图),也可以通过局域网内的浏览器远程浏览和下载资产。仓库名 `AssetsManager_old-bak` 仅为目录命名,项目包名为 `AssetsManager`。

<!-- stats: app_services=51 controllers=4 core=34 dialogs=21 domain_events=16 e2e_specs=6 hooks=16 i18n_en=849 i18n_ja=849 i18n_zh=849 icons=56 pages=26 python_test_files=290 repos=17 routes=140 routes_modules=24 schema_version=35 stores=4 themes=24 ts=119 webui_test_files=103 widgets=14 -->
> **验证边界（2026-08-21）**：README 的结构统计由 `scripts/check_doc_stats.py` 从当前工作树测量；测试、构建、浏览器、真实 LAN、依赖和发布结果只在带 commit、精确命令、平台、工具版本与 artifact digest 的日期化证据中成立。历史全量数字（包括 2026-08-17 的 3778/7 和此前 WebUI/E2E 数字）保留在 dated 文档中，不作为当前 release 或 `verified-fixed` 声明。当前 C6-C10 收敛与剩余限制见 [`docs/full-review/c6-c10-convergence-2026-08-21.md`](docs/full-review/c6-c10-convergence-2026-08-21.md)。
> **工作区实况索引**：结构/机制/数据流/弱点/文档导航的全量地图见 [`docs/overview-2026-08-27.md`](docs/overview-2026-08-27.md)（LIVING）；已移入归档的文档溯源见 [`docs/archive/INDEX.md`](docs/archive/INDEX.md)。

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
- [文档导航](#文档导航)
- [关键设计取舍](#关键设计取舍)

---

## 功能特性

**桌面端 (PySide6)**：文件浏览（网格/列表/详情，缩略图预览、元数据、标签）；多资产库（每库独立数据库与设置）；内置图片查看器（缩放/平移）；标签系统（标签树/搜索/批量操作）；元数据（备注/URL/自定义属性）；撤销/重做（按库隔离）；24 个主题（深/浅/自定义 + 实时预览）；背景模糊/马赛克；插件系统；系统托盘；多标签工作区；快捷键。

**局域网分享 (aiohttp)**：浏览器浏览（网格/列表/瀑布流，React SPA）；单文件/批量 ZIP 下载（免费配额限制）；分享链接（密码 ≥8 字符 + 暴力破解锁定、限时、限次）；管理员/注册用户/访客三级权限 + 邀请码注册 + 卖家独立会话；QR 码；Cloudflare 隧道一键公网；WebSocket 实时失效推送（HTTP 快照为权威）；商城系统（商品/购物车/结账幂等/订单状态机/投递令牌/卖家面板/匿名分析）；速率限制 + IP 黑名单/白名单 + 路径遍历防护 + 认证 fail-closed + 令牌撤销表；移动端适配。

**国际化**：英语/中文/日语三语，桌面与 Web 全套翻译；Web 自动检测浏览器语言并支持手动切换。

---

## 技术栈

| 层 | 技术 |
|---|---|
| 核心 | Python 3.12/3.13/3.14（CI 矩阵；本机 3.14）；PySide6 >=6.6,<7；aiohttp >=3.9（可选）；SQLite3（WAL，迁移 v1-v35）；Pillow；segno；send2trash/requests |
| 桌面 | QDockWidget（dock_factory 统一构建）、QAbstractListModel、QThreadPool、signal_bus（7 信号）/event_bus（16 个领域事件）、icons.py（56 图标，DPR 感知） |
| LAN | aiohttp（24 个路由模块，140 条路由 + WebSocket）；middleware 顺序 security→metrics→auth；PathGuard 路径守卫；HMAC 令牌（ts.nonce.sig）；WebSocketManager（50 连接/心跳 30s/1MB 帧截断）；Cloudflare Tunnel；React SPA（webui/dist 托管） |
| 数据层 | DatabaseManager（连接级读写门 + 身份标记）；**17 个 SQL 仓库**（统一 for_session 绑定 + SAVEPOINT + CAS）；db_migrations（迁移 v1-v35，契约回溯校验）；schema_defs 契约；LibraryLock；json_store 原子持久化 |
| 开发工具 | ruff / pyright / pytest / Cython（4 个热点模块）/ PyInstaller |

> 细节（版本号、常量、令牌 TTL、限流档位）见 `docs/overview-2026-08-27.md` §1-§15 与 `docs/lan-security.md`。

---

## 项目架构

```
┌─ Presentation ──────────────── 桌面 UI（panels/dialogs/widgets）+ LAN routes + React SPA
│  Controllers（4 个，零 Qt import）
├─ Application Layer（51 模块）— bootstrap 装配 → 每库 LibraryRuntime/LibrarySession
│  （应用服务层（51 模块）顶层，另有 gallery/ 子包 5 文件）
├─ Repositories — 17 个 SQL 仓库（for_session + savepoint 事务 + CAS）
├─ Domain — 值对象 + 16 个领域事件 + 错误层级（零基础设施依赖）
└─ Infrastructure core/ — database/迁移/契约/锁/路径/主题/图标/缓存/插件
        LAN 层（aiohttp：认证/限流/隧道/WS）与 core 共享，经 application 访问数据
```

架构原则：依赖向下（domain ← repositories ← application ← lan/panels）；DI 装配（ApplicationBootstrap/ServiceContainer）；每库 LibraryRuntime 作用域 + 领域事件总线 + 投影失效；Qt 信号仅限 UI 内部；fail-closed（无法确认安全状态即拒绝）。

---

## 项目结构

```
AssetsManager_old-bak/
├── AssetsManager/              # 主包（270 py / 9.2 万行，2026-08-27 实测）
│   ├── app.py  window.py  window_lifecycle_coordinator.py  dock_factory.py
│   ├── application/            # 应用服务层（51 模块，27.7k 行）
│   ├── controllers/            # 4 个无 Qt 控制器（file_list/info/tag_tree/sidebar）
│   ├── core/                   # 基础设施层（34 模块 + plugins/6）
│   ├── domain/                 # 领域层：16 个领域事件 + event_bus + errors + 值对象
│   ├── repositories/           # **17 个 SQL 仓库**（tag/metadata/thumbnail/favorite/
│   │                           #  share/auth/asset_index/plugin_metadata/shop/order/
│   │                           #  quota/free_download_quota/seller_profile/
│   │                           #  storefront_analytics/shop_buyer/gallery_home/
│   │                           #  revoked_token —— 统一 for_session + SAVEPOINT + CAS）
│   ├── lan/                    # LAN 服务器：核心 16 模块 + routes/ 24 模块（140 条路由）
│   │                           #  （17 个 SQL 仓库）+ 统一 for_session/SAVEPOINT/CAS
│   ├── panels/                 # 桌面面板（file_list 27 文件 mixin 星系 + sidebar/info/tag_tree/image_viewer）
│   ├── dialogs/                # Qt 对话框（21 个）+ sharing_settings 分包（外壳 1347 行 + 分页 1119 行）
│   ├── widgets/                # 可复用 Qt 组件（14 个）
│   ├── di/  i18n/  plugin_api/
├── webui/                      # React 18 + Vite + TS（119 ts/tsx 生产源码；
│   │                           #  api 15 工厂 / pages(26) / hooks(16) / stores(4 Context)；
│   │                           #  103 Vitest 文件 + 6 个 spec E2E）
├── tests/                      # 283 个 test_*.py（unit 106/integration 55/lan 54/
│   │                           #  desktop 35/core 17/plugins 12/e2e 2/performance 2）
├── docs/                       # overview-2026-08-27.md（地图）/ archive/（归档+INDEX）/
│                               # compose/（证据账本导航）/ full-review/（快照，勿动）/
│                               # deep-weakness-audit-2026-08-22/（冻结审计）/ adr/ plans/
│                               # architecture*.md  lan-security.md  migrations.md …
├── assets/ & Assets/           # 24 个主题 JSON + 图标源（Assets/icons 为跟踪源）
├── scripts/                    # 13 个门禁/工具脚本（check_*.py、gen_*.py）
├── Plugins/                    # 插件（Addons/booth_link、download_tracker）
├── RuntimeData/                # 运行时数据（设置、缓存、库身份标记）
├── main.py  run.py  build.py  setup_cython.py  AssetManager.spec  pytest.ini  ruff.toml …
```

---

## 快速开始

### 环境要求

- Python 3.12+（推荐 3.14）；Windows 10/11（主要平台）；Cython 编译需 Visual Studio Build Tools

### 安装

```bash
pip install -r requirements.txt      # 核心依赖
pip install -r requirements-lan.txt  # LAN 分享（可选）
pip install -r requirements-dev.txt  # 开发（可选）
```

### 运行

```bash
python main.py                       # 或双击 run.py
# 预构建版本: dist/AssetManager/AssetManager.exe
```

首次启动：启动窗口 → 选择/创建资产库目录 → 进入主窗口。

---

## 开发指南

### 质量门

每次提交前必须通过：

```bash
python -m ruff check AssetsManager tests scripts run.py
python -m pyright
python -m compileall -q AssetsManager tests
python -m pytest -q -p no:cacheprovider
python scripts/check_doc_stats.py     # README 结构统计门（另有 12 个门禁脚本，见 scripts/）
```

运行结果必须附日期化 command/artifact 证据（见上方验证边界）。全库结构/机制/弱点与开放项见 `docs/overview-2026-08-27.md` §18/§19。

> **G17 边界：** Reconciliation queue 当前支持单 library、单 application owner 下的 stop-the-world cutover、lease recovery 与 stale-worker protection；不支持旧版/新版应用同时持有同一 library 的 rolling upgrade。详细证据见 `docs/compose/reports/g17-stop-the-world-cutover-release-ownership-checklist-2026-08-08.md`。

### Cython 编译加速

```bash
pip install cython
python setup_cython.py build_ext --inplace   # 热点模块：cache/color_utils/format_utils/asset_filters
python -m pytest tests/performance/test_cython_benchmarks.py -v -s
```

### 性能基准

```bash
python -m pytest tests/performance/test_baselines.py -v   # perf 标记，CI 默认排除
```

观测脚本：`tests/perf/`（grid/directory/thumbnail telemetry）+ nightly grid（CI 每日 03:17 UTC，30 天趋势）。D3 正式基线与单连接架构决策（2026-08-29 实测）：`docs/perf-baseline-2026-08-29.md`。

---

## 构建与部署

```bash
python build.py --clean --build --optimize --report   # → dist/AssetManager/AssetManager.exe
```

- onedir bundle 约 127 MB（历史快照口径）；`--package-smoke` 冻结态冒烟（run.py）。
- CI（`.github/workflows/ci.yml`，9 job）：lint / hygiene / typecheck / webui / package-smoke(Windows) / windows-regression / python-browser-e2e / test（Python 3.12/3.13/3.14 矩阵）/ webui-e2e（6 个 spec；commerce-real-backend 需环境变量否则自带 skip）。
- **已知门禁缺口（2026-08-27 实测）**：仓库无 remote → CI 从未真实运行；触发仅 `master/main`；release 不依赖测试；perf 门禁默认排除；Windows lane 仅 4 文件子集。详见 `docs/overview-2026-08-27.md` §17。

---

## LAN 分享系统

### 启动

桌面工具栏分享按钮；或 `LanServer(runtime=runtime).start(port=8080)`（构造强制 runtime=，无 library_root 参数）。

### 主要端点（精选；完整 140 条路由表见 overview §16）

| 端点 | 说明 |
|---|---|
| `/api/files`、`/api/files/summaries` | 文件列表/目录摘要（browse） |
| `/api/search`、`/api/quicksearch` | 双轨搜索（标签/名称/索引；quick_search 75ms 预算） |
| `/api/gallery/*`、`/api/favorites` | 画廊投影（预算受限 + 事件增量）/收藏 |
| `/api/shares/*` | 分享管理；verify/info/download/preview 公开 |
| `/api/download/{path}`、`/api/download/batch` | 下载/批量 ZIP（先准备响应成功再计数） |
| `/api/thumbnails/{path}`、`/api/image` | 缩略图/原图（Pillow verify 内容门 + 模糊门） |
| `/api/auth/*`、`/api/users`、`/api/invites` | 认证/用户/邀请码（限流 + fail-closed） |
| `/api/shop/*`(54 条) | 商城全套（目录/购物车/结账幂等/订单/投递/卖家/分析） |
| `/ws` | WebSocket 失效推送（epoch+revision；缺口恢复走 `/api/revision`） |
| `/s/{id}`、`/browse`、`/storefront/*`、`/seller/*` | SPA 页面 |

### 权限模型

六种 principal（guest/password/access_key/local_ui/user/share）+ 8 位能力（browse/preview/download/upload*/manage_links/manage_users/settings/realtime；*upload 已下线）。管理员全能力；注册用户浏览/预览/实时；访客按 `lan_guest_*` 设置（下载默认关）；分享访问者能力由分享配置决定（密码/限时/限次/allow_preview）。

### 分享链接权限

只读预览 / 可下载（先准备响应成功再计数，超限 429）/ 密码保护（≥8 字符，失败 5 次锁 60s）/ 限时（过期 410 折叠 404）/ 限次 / 撤销即时阻断。

---

## 插件系统

- 插件位于 `Plugins/Addons/<name>/`（plugin.json + 入口模块），启动时发现加载；能力：分类、菜单/右键动作、文件解析器、主题令牌、事件钩子、命令与工具面板（v2 `register_class` 体系，API 见 `AssetsManager/plugin_api/`）。
- 权限体系**不是沙箱**：插件与主机同解释器运行，可经标准库直通绕过任何门禁；`host.services`/`settings.write` 有强制门，其余为 advisory。只应从可信来源安装插件。
- v1 手册已冻结（`Plugins/Docs/`），v2 现状以代码为准。

---

## 国际化

| 语言 | 状态 |
|---|---|
| English / 中文 / 日本語 | ✅ 完整（en 849 / zh 849 / ja 849 keys，桌面 + Web） |

添加语言：复制 `AssetsManager/i18n/en.json` → 翻译 → 在 `i18n/__init__.py` 注册。

---

## 测试

- `python -m pytest -q -p no:cacheprovider`（全套 283 文件，约 5 分钟；历史基线 2952→3722/3755，当前须附 dated 证据）。
- 分域：unit 106 / integration 55 / lan 54（含 lan_public_contracts.json 契约）/ desktop 35（PySide6 offscreen）/ core 17 / plugins 12 / e2e 2（Playwright Chromium 真实 LAN）/ performance 2。
- 前端：`cd webui && npm test && npm run typecheck && npm run build`；`npm run test:e2e`（6 个 spec；默认 51 passed、2 skipped）。
- fixture：`temp_dir`/`memory_db`/`schema_db` + autouse `_cleanup_stores`（3 全局点 + 测试数据目录清理）。

---

## 文档导航

| 需求 | 文档 |
|---|---|
| 结构/机制/数据流/弱点/开放项 | `docs/overview-2026-08-27.md`（LIVING 地图） |
| 架构与边界规则 / 迁移 / LAN 安全 | `docs/architecture.md`+`architecture-diagram.md` / `docs/migrations.md` / `docs/lan-security.md` |
| 开发规则 / 测试策略 / ADR | `docs/development.md` / `docs/testing.md` / `docs/adr/` |
| 证据账本（specs/plans/reports/handoffs） | `docs/compose/README.md`（导航） |
| 归档溯源 | `docs/archive/INDEX.md` |
| dated 审计快照与批次证据（进行中） | `docs/full-review/**`（勿动） |
| 08-22 全领域审计 / 08-01 基线审计 | `docs/deep-weakness-audit-2026-08-22/`（冻结） / `DeepSeek Docs/`（冻结） |

---

## 关键设计取舍

1. **单进程模型**：桌面与 LAN 同进程；SQLite 单连接 + 连接级写锁；跨进程一致性靠文件锁（WAL+timeout=30）与 CAS。
2. **"WebSocket 只是失效提示"**：前端断线恢复用 HTTP `/api/revision` 权威游标；广播帧 >1MB 截断 paths（不静默丢）。
3. **rotate 语义 = 轮换作废**：投递令牌 rotate 同事务作废旧令牌，总配额守恒。
4. **guest 默认不可下载**（`lan_guest_download` 默认 False）；下载经免费配额（20 次/日，匿名身份=签名 cookie）。
5. **插件权限门禁是诚实/意图边界**：同解释器无沙箱，任何门禁都可用标准库直通绕过，不构成安全边界。
6. **隐藏文件不索引**（展示口径统一）；目录 mtime 相等判定不可靠（快路径依赖 mtime 快照，退化方向安全）。
7. **云端隧道需强认证**：无认证拒绝启动隧道；隧道下限流按签名访客 cookie 隔离。
8. **导入/恢复/投递全部幂等优先**：manifest claim/lease、copy_id、请求指纹、结账 request_key 均为 CAS + 幂等。
9. **fail-closed 贯穿**：认证、库锁、schema 契约、settings 未来版本、restore 意图标记——无法确认安全状态时拒绝而非放行。
10. **证据文化**：任何"已修复/已验证"声明必须带日期化证据（commit+命令+平台+版本+digest）；无证据即 unverified。

---

## 许可证

私有项目。

---

*2026-08-27 维护批次:README 精简(详情下沉 `docs/overview-2026-08-27.md`);2026-08-09 本机 PyInstaller onedir smoke(6.19.0,15 passed,offscreen 存活)等历史复核记录保留于 dated 文档,不再在 README 展开。*
