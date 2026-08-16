# 架构审查报告（architecture-review-2026-08-15）

> 审查日期：2026-08-15 · 只读审查（未修改业务代码）
> 基线：`master @ 20c2062`；工作区另有 `docs/full-review/*` 未提交改动（未纳入本报告提交）
> 方法：主智能体复核 + 4 个只读审查代理（分层/DI、桌面 UI、LAN 服务、前端 SPA），并交叉引用 `docs/architecture.md`、`docs/full-review/09-deep-audit-2026-08-15.md`
> 门禁实测：ruff ✅、pyright 0e0w ✅、boundaries ✅、`gen_ts_types.py --check` ✅、`check_doc_stats.py` ✅、全量 pytest `3553 passed / 7 skipped / 0 failed`

---

## 0. 一句话结论

架构意图（五层单向流动、单一组合根、Runtime 冻结快照、领域事件与 Qt 信号分层）在 `application/domain/repositories` 层大体落地且测试守护较好；当前架构债主要集中在四类：

1. **`core` 层存在 3 处反向依赖**（core→application/repositories），尚未被现有门禁捕获。
2. **presentation 层存在两处“就地装配”**（LAN server 与插件服务），且 `widgets/dialogs ↔ lan` 存在双向依赖环。
3. **四个横切关注点各自造轮子**：异步任务/面板状态/定时器动画/样式刷新，没有像 `ThumbnailLoader` 那样的统一抽象。
4. **前端存在三份 `ProjectionDomain`/手写 DTO 镜像与双数据获取范式**，契约与失效语义未单源。

功能级缺陷（H-G1、H-L1/H-L2、H-D1/H-D2 等）已在 `09-deep-audit` 完整记录，本报告不重复；以下聚焦**架构归因与结构建议**。

---

## 1. 分层 / DI / 依赖健康

### 1.1 现状评估

- 五层规则（presentation → application → domain → infrastructure）在 `application/domain/repositories` 层执行良好：`test_non_presentation_layers_do_not_grow_qt_dependencies`、`test_application_does_not_import_lan_or_panels`、`test_repositories_only_depend_on_core_infrastructure_and_domain` 均实测覆盖。
- `LibraryRuntime` 构造严格单点：全库只有 `application/bootstrap.py` 允许 `LibraryRuntime(`；Desktop/LAN 共享同一冻结快照与惰性 `LanRuntimeServices` 单飞行。
- 组合根的生命周期语义（session lease、operation barrier、pre-close adapter）在 `bootstrap/context/runtime_validation` 形成闭环，是其他模块应复用的正例。

### 1.2 风险

| ID | 级别 | 问题 | 锚点（实测） | 架构归因 |
|---|---|---|---|---|
| H-1 | HIGH | `core.tag_store` 反向依赖 `repositories.tag_repository`，基础设施层直接绑定 SQL 实现 | `AssetsManager/core/tag_store.py:23` | core 未保持“纯基础设施”边界；未来换 TagStore 实现会拉入 repository |
| H-2 | HIGH | `core.database` 与 `core.settings` 之间存在模块级环（`SHARED_DIR` 定义于 database，settings 引用它） | `core/database.py`、`core/settings.py:10` | 基础设施内部缺少“常量/path_resolver 下沉”规则 |
| H-3 | MEDIUM | `core.plugins.manager` 运行时 import `application.asset_filters` | `core/plugins/manager.py:299,313` | 插件框架应通过注入 category provider，而不是圈层逃逸 |
| M-1 | MEDIUM | `widgets/dialogs` 依赖 `lan.*` 实现细节，且 `sharing_settings_dialog ↔ lan_sharing` 成环 | `widgets/lan_sharing.py:296`、`dialogs/sharing_settings_dialog.py` | presentation 就地组装 LAN，缺少 `LanControlPort` 窄接口 |
| M-2 | MEDIUM | `LanServer(` 存在两个生产构造点（`lan/manager.py:117`、`widgets/lan_sharing.py:296`） | 同上 | 与“单一组合根”原则冲突，安全快照/认证状态被双写 |
| M-3 | MEDIUM | application 服务仍有隐式全局回退：`AppSettings.instance()`（5 处）与 `get_library()`（tag_service） | `gallery_service.py:1252`、`security_preflight.py:400`、`seller_auth_service.py:24`、`shop_authorization.py:59`、`tag_service.py:197` | 服务不可用 fake provider 测试，配置成为隐式环境 |
| L-1 | LOW | `check_boundaries.py` 是 4 个 needle 点采样，不是圈层 DAG；core→application/repositories 这类横向逃逸无法发现 | `scripts/check_boundaries.py` | 静态门禁语义落后于已形成的架构测试 |
| L-2 | LOW | 巨型 God-file：`gallery_service.py` 2042 行、`sharing_settings_dialog.py` 1968 行、`shop.py` 1004 行 | 实测行数 | 未按子域/状态机拆分，审查与变更成本高 |

### 1.3 已验证健康

- `domain` 层无 sqlite3/repository/application/lan/panels 依赖，测试白名单备案完整。
- `application` 无 Qt、无 LAN 依赖；服务层对两种表现的隔离真实成立。
- `repositories` 依赖前缀白名单强制，无 application/lan/presentation 逃逸。
- `di.ServiceContainer` 有 `_resolving` 循环检测，且无模块级全局容器实例（“全局容器回退”不成立）。

### 1.4 建议

**批次 G0 — 圈层护栏先行（建议最先做，约 1 天）**

1. 新增 `scripts/check_layers.py`：用 AST 构建 `core/domain/infrastructure/application/lan/panels/widgets/dialogs` 的允许边 DAG，检查点级 import；错误输出完整非法路径。
2. 将 DAG 检查并入 `check_boundaries.py`（保留 gate 4/6 运行时门不变），并在 `tests/unit/test_layer_dag.py` 固化当前允许边。
3. 收紧 `pyrightconfig.json` 白名单，把 `core/*` 全部纳入 0e0w。
4. ADR 0001 增补“圈层 DAG + 新例外需 ADR”条款。

**批次 G1 — 消除 core 圈层逃逸（依赖 G0）**

- `TagStore` 拆分为“canonical 解析 + repository 注入”，SQL 落库只归 `tag_repository`；删除 `core/tag_store.py` 的 repository import。
- `SHARED_DIR` 下沉到 `core/path_resolver.py`/`constants.py`，破 `database↔settings` 环。
- `core.plugins.manager` 改为 `register_category_provider` 注入，`application` 在 bootstrap 时注册 `FILTER_CATEGORY_EXTS`。
- 验收：`grep 'from AssetsManager.(application|repositories|lan|panels)' AssetsManager/core` 为零。

**批次 G2 — presentation 窄接口 + LAN 单组合根（依赖 G1）**

- 定义 `LanControlPort`/`ShareSettingsPort`（放 `application/desktop_ports.py`），`widgets/lan_sharing.py` 与 `dialogs/sharing_settings_dialog.py` 只依赖 port；安全快照逻辑单点到 `security_preflight`。
- 删除 `lan/manager.py` 的重复装配或使其委托 bootstrap；`LanServer(` 生产构造点收敛为一处。
- `_actions.py` 插件菜单经 scoped `plugin_service` 注入，不再用 `QApplication.property("plugin_host_context")` 与就地 `PluginService(...)`。
- 验收：`widgets/dialogs` 内 `from AssetsManager.lan` 为零；SCC 环消失。

**状态：已完成** —— `lan/ports.py` 为唯一 `LanServer(` 装配点并由 `window.py` 组合根注入；共享设置契约移至 `widgets/sharing_contracts.py`，双向环已消除；`_actions.py` 改走 `_scoped_services.plugin_service`。

**批次 G3 — 服务配置注入 + God-file 拆分（可与 G2 并行）**

- application 层 `AppSettings.instance()` 仅保留 bootstrap 1 处；`get_library()` 在 application 层清零；服务构造注入 settings/tag-library provider。
- `gallery_service.py` 拆 `_projection_builder/_persistence/_incremental`；`sharing_settings_dialog.py` 按 tab 拆面板；`shop.py` 拆 `routes/shop/{catalog,cart,orders,delivery,seller}` 子包（保留兼容 re-export）。
- 验收：`grep 'AppSettings.instance()' application` == 1；shop 子模块 ≤ ~350 行；139 路由数不变。

**状态：已完成** —— application 的 `AppSettings.instance()` 仅存于 `bootstrap.py` 并安装 provider seam；`get_library()` 经 `tag_canonicalizer` seam 注入；三个 God-file 已拆分（shop 实际为 `_common/catalog/cart/orders/delivery`，seller 装配归 `_common`），兼容 re-export 保持测试 monkeypatch 面不变。

---

## 2. 桌面 UI 架构

### 2.1 现状评估

- 领域事件与 Qt 信号分层正确：业务 mutation 经 `DomainEventSubscription`（QueuedConnection）投递；`core.signal_bus` 明确限定 presentation-only。
- `ThumbnailLoader` 是 worker 工程质量的标杆（代际失效 + 有界 drain + 幂等 stop），应抽象复用而不是重写。
- 窗口切库失败回滚编排（`WindowLifecycleCoordinator`）与面板身份守卫（session token + path 校验）闭环良好。

### 2.2 风险

| ID | 级别 | 问题 | 锚点 | 架构归因 |
|---|---|---|---|---|
| D-A1 | HIGH | 异步任务各路径自造池/取消/收尾：全局池任务不可取消、`prepare_library_switch` 不 drain | `QThreadPool.globalInstance()` 多处；`_model.py:757` | 没有统一 worker 框架（呼应 09 H-D1/H-D2） |
| D-A2 | MEDIUM | UI 状态持久化分散：InfoPanel 布局、Sidebar state、FileList view memory、dock/tab state 各自 AppSettings key 或进程 dict | `info.py` 布局、`sidebar.save_state`、`_navigation.py:142` | 缺 `PanelState` 统一契约；`clone()` 多数未接线 |
| D-A3 | MEDIUM | `QTimer.singleShot` 批量调度与动画回调在销毁后访问；shutdown 未停全部成员定时器 | `sidebar.py` expand-all、`tag_tree.py` 批处理、`info.py` 定时器 | 定时器/动画没有统一生命周期句柄 |
| D-A4 | LOW | 样式源仍分散：全局 QSS / StyleKit / 面板局部 QSS 三种通道，主题刷新三 handler 各自重建 | `dock_factory.py` theme/language/scale 三 handler | 缺 `ui_refresh` 单帧事件与静态样式门禁 |

### 2.3 建议

**批次 D1 — 统一 Worker 框架（最高优先级）**

- 抽 `CancellableRunnable(generation, cancel_token)` + `BoundedPool` + `drain(timeout)`（以 `_loader.py` 已验证模式为底）。
- 迁移 `_ScanTask/_SizeTask/_PreloadTask/_FileInfoTask/_ImportTask/_LinkScanTask`；循环体内检查取消令牌。
- `prepare_library_switch/shutdown` 全部有界 drain；`WindowLifecycleCoordinator` 增加任务注册表。
- 验收：大库浏览后立即切库主线程不超阈值（新增桌面回归测试）。

**状态：已完成** —— 新增 `core/workers.py`（`CancellationToken`/`CancellableRunnable`/`BoundedPool`）；扫描、目录大小、侧栏预载、文件信息、链接扫描、导入任务全部携带代际取消令牌并迁移到私有有界池；`prepare_library_switch`/`shutdown` 采用 3s 有界 drain；`WindowLifecycleCoordinator` 负责取消并 drain 导入任务；`tests/unit/test_workers.py` 锁定取消与切库时限。

**批次 D2 — PanelState 统一 API**

- 定义 `PanelState(key, save(ctx)/restore(ctx))`；Info/Sidebar/FileList/TabContainer 统一委托。
- 接线 `TabContainer.save_state/restore_state` 到窗口级 workspace tabs（active index、view_mode、current_path）。
- 明确 `clone()` 语义并接线 dock split；或删除未接线契约并更新 base.py 注释。
- 验收：AppSettings 中 UI 状态 key 全经 PanelState；grep `.clone()` 非测试即已接线。

**状态：已完成** —— 新增 `panels/panel_state.py`（key + save/restore + persist/load）；InfoPanel 布局、Sidebar 配置、FileList 视图、WorkspaceSection 活动标签、dock 宽度全部经 PanelState；`TabContainer.save_state/restore_state` 携带每面板状态并恢复活动标签；dock split 改为 `clone()` 克隆源面板；架构测试锁定 UI state key 流转。

**批次 D3 — 定时器/动画收口**

- 引入可取消 timer 句柄，替换散落的 `QTimer.singleShot`；shutdown 统一停成员定时器并清 `_expand_frontier` 等。
- 动画回调统一 `try/except RuntimeError + shiboken6.isValid` 守卫。
- 验收：四个面板 init→start→immediate shutdown 用例无 RuntimeError/pending singleShot。

**状态：已完成** —— 新增 `core/timers.py`（`TimerHandle` 可取消一次性句柄）；panels 内 15 处 `QTimer.singleShot` 全部替换为 owner 持有的句柄（含 GridWidget/ImageViewer）；`PanelContent.shutdown` 与各面板 `prepare_library_switch` 统一清空挂起句柄及 `_expand_frontier`；FileList 缩放/滚动动画回调加 RuntimeError 停动画守卫；`tests/unit/test_panel_lifecycle.py` 锁定四面板 init→show→立即 shutdown。

**批次 D4 — 样式单入口**

- 静态门禁禁止局部 QSS 字面颜色/字号；重复对话框 QSS 抽 StyleKit 生成器；dock 三 handler 合并单帧刷新。
- 验收：新增 `scripts/check_style_sources.py` 可挂 CI。

**状态：已完成** —— 新增 `scripts/check_style_sources.py`（AST 级检查 75 个 UI 文件，禁止局部 QSS 的 `#hex`/具名颜色/`font-size` 数字字面量及 token 查找旁的 hex fallback，已挂 `.github/workflows/ci.yml` lint job）；`themes.font_size(key)` 语义字号令牌（24 套主题 JSON 扩展 xxs/xs/caption/xxl）+ `StyleKit.font_size()`；重复 QSS 抽取为 StyleKit 生成器（`button_css`/`switch_css`/`nav_css`/`status_bar_css`），startup 按钮、插件开关/主按钮、共享设置导航、窗口状态栏全部迁移；`dock_factory` 三个 theme/language/scale handler 合并为 `_schedule_dock_refresh` + `_run_dock_refresh` 单帧刷新（`TimerHandle` 0ms 合并）；`tests/unit/test_style_sources.py`、`tests/desktop/test_dock_factory.py` 锁定门禁与合并语义。

---

## 3. LAN 服务与会话生命周期

### 3.1 现状评估

- `RoutePolicy` fail-closed、方法级优先与路径规范化正确；错误映射 `_errors.py` 单点且不泄漏。
- 会话线性化与 Runtime 服务身份校验（`_publish_while_live` + `_validate_runtime_service_bindings`）是成熟模式。
- Scanner 代际隔离、WS authority lease / idempotent evict / send-after-teardown 防护均已闭环。

### 3.2 风险

| ID | 级别 | 问题 | 锚点 | 架构归因 |
|---|---|---|---|---|
| H-A1 | HIGH | 授权横切 fail-open 面：`public_optional` 的语义下，写路由安全依赖 handler 内手工检查，而非声明式能力 | `api.py` policy 注册、`shop.py` `require_seller` 多处 | 路由→能力映射没有中间件化（结构性，未发现当前可触发漏洞） |
| H-A2 | MEDIUM | `/api/info` 等 heavy 端点 `rate_limit="skip"` 且 `q` 无上限 | `api.py:207-234`、`security.py` | 限流分级缺 “browse” 档 |
| M-A2 | MEDIUM | access-key 校验 PBKDF2 在事件循环线程内联执行 | `server.py` `_auth_middleware`、`domain/auth.py` | 横切 CPU 校验未 to_thread/缓存 |
| M-A3 | MEDIUM | gallery prewarm 构建线程无 join/取消，stop 不对称 | `server.py`、`gallery_service.py` | daemon 任务未纳入可停止资源集合 |
| L-A1/L-A2 | LOW | `_zip_executor` 永不 shutdown；`/api/info` 计数缓存为模块级全局 | `_helpers.py:29`、`system.py:30-44` | 模块级资源/缓存无 owner |
| L-A3 | LOW | `shop.py` 55 路由/1004 行，ActivityLog 在 `_helpers` 内写 SQL 以绕开边界门禁 | `shop.py`、`_helpers.py` | 路由划分未对齐 commerce 子域 |

### 3.3 建议

- **批次 L1 — 声明式授权中间件**：扩展 `RoutePolicy` 增加 `capabilities`；写路由显式声明；新静态门禁拒绝“public/public_optional 的 POST/PUT/PATCH/DELETE 未声明 capability”。

**状态：已完成** —— `RoutePolicy` 新增 `capabilities` 字段并在声明期校验能力词汇表（未知能力 fail-closed）；新增 `lan/authorization.py`，`_auth_middleware` 在进入 handler 前执行 `enforce_capabilities`（principal 能力 / `require_user_write` / `require_admin` / seller 会话，seller 特性关闭时保持历史 404 `feature_disabled` 契约）；55 个写路由全部显式声明能力（principal 型 `browse/preview/download/manage_links`、helper 型 `write_notes/write_tags/admin_tags/admin_users`、commerce 型 `seller/buyer_cart/buyer_wishlist/buyer_orders/buyer_claim`、匿名引导型 `public_auth/public_signal/share_verify`）；`_add` 改为“首注册播种 pattern 级 fallback + 每方法独立声明”，同路径多方法策略不再互相覆盖；新增 `scripts/check_route_capabilities.py`（纯 AST、无 aiohttp 依赖，词汇表直接解析自 `route_policy.KNOWN_CAPABILITIES`）挂 CI；`tests/lan/test_route_capabilities.py` 锁定门禁、单元执行语义与“中间件先于 handler 拒绝 seller 写”的集成行为。

- **批次 L2 — 限流/输入/CPU 出循环**：新增 `browse` 档（如 600/min/IP），仅 image/thumbnails/stats 等可 skip；`q` ≤ 256；`verify_key` `asyncio.to_thread` 或短 TTL。

**状态：已完成** —— `RoutePolicy` 新增 `browse` 限流档并在 security 中间件接入独立 `browse_rate_limiter`（600/min/IP），gallery/search/tree/home/favorites/files/projects/tags/quicksearch/info/notes/activity/quota/tunnel-status 从 skip 迁入 browse，skip 只保留 image/thumbnails/stats/revision/ws/assets；`_helpers.oversized_query`（`q`≤256）接入 `/api/search` 与 `/api/quicksearch`，超限 400 `bad_request`；access-key PBKDF2 全部经 `asyncio.to_thread` 出事件循环（`_auth_middleware` 双路径 + `/api/auth/verify_key`）；`test_l2_rate_input_cpu.py` 锁定 browse 预算隔离、q 边界与 to_thread 接线，route policy 契约测试冻结新分级。
- **批次 L3 — 线程资源对称关闭**：prewarm thread 注册 + join；gallery 构建循环检查 `_closed`；zip executor 改实例持有并 shutdown。

**状态：已完成** —— `_zip_executor` 移除模块级全局，改为 LAN server 实例持有（`thread_name_prefix="lan-zip"`，经 `ZIP_EXECUTOR_APP_KEY` 发布给路由），`_shutdown` 执行 `shutdown(wait=False, cancel_futures=True)`；`build_zip_async` 改经 request 解析实例 executor（legacy 测试 app 回退 loop 默认执行器）；server 跟踪 `_gallery_prewarm_thread` 并在关闭 gallery service 后 `_join_gallery_prewarm`（10s 有界 join）；`_build_home_background` 在 pre_wait 后检查 `_closed`，与既有 `_visible_entries/_aggregate_project` 逐目录取消检查一起保证关闭后不再发起最后一次全库遍历；`tests/lan/test_l3_thread_resources.py` 锁定所有权与 join 语义。

- **批次 L4 — shop.py 子域拆分 + 表驱动注册**：`routes/shop/` 五个子模块，api.py 用 `(method, path, handler, policy)` 表声明，与 L1 同批落地。

**状态：已完成（G3 提前落地）** —— `routes/shop/` 已拆为五个子模块，`api.py` 表驱动注册与 L1 的能力声明同批闭环。

---

## 4. 前端 SPA 架构

### 4.1 现状评估

- API client 错误分类、超时/取消区分、blob/progress 路径共用是健康单点。
- `useCachedQuery/queryCache` 的身份隔离、gc、旧响应不污染新槽位设计正确。
- RealtimeContext 恢复状态机（generation 单飞、10s 超时、`notify(null)` 全量刷新）健壮。
- `useFavorites` 乐观更新/回滚/跨 tab 同步协议完整。
- Provider 嵌套作用域与 Web 设计令牌（CSS 变量 + 对比度）规范。

### 4.2 风险

| ID | 级别 | 问题 | 锚点 | 架构归因 |
|---|---|---|---|---|
| H-F1 | HIGH | 数据获取双范式：部分页面手写 fetch/AbortController，`saveNotes` 无 prev.path 守卫 | `DetailPage.tsx` 等 | 页面层直连 api 工厂，未强制统一 cache 协议 |
| H-F2 | HIGH | `loadMore` 无取消/过滤条件校验，旧响应可污染新列表 | `StorefrontBuyerOrdersPage.tsx:73-86` | 同 H-F1 |
| M-F3 | MEDIUM | 结账幂等键随组件 remount 变化，中断重试可能重复下单 | `StorefrontCartPage.tsx:45` | 幂等键未按 cart id 持久化 |
| M-F4 | MEDIUM | 单一根 ErrorBoundary，无 per-route 降级 | `main.tsx:19-21` | 前端错误隔离粒度不足 |
| L-F1 | LOW | `ProjectionDomain` 存在后端/生成脚本/前端三份拷贝；`types/api.ts` 手工镜像 DTO | `runtime_events.py`、`gen_ts_types.py`、`RealtimeContext.tsx` | 契约单源未闭环（直接引发 drift） |
| L-F2 | LOW | 测试/源不同源：孤儿测试文件未清理 | `AdminManagement.test.tsx` 等 | 前端治理门禁缺位 |
| L-F3 | LOW | `useCachedQuery` key 用 `JSON.stringify`，依赖对象插入序的隐式约定 | `useCachedQuery.ts:78` | cache key 规范未文档化 |

### 4.3 建议

- **批次 S1 — 契约与投影域单源**：`gen_ts_types.py` 直接解析 `ProjectionDomain` 枚举；删前端 `stats` 死注册；DTO 迁移到后端 DTO 模块并扩展生成；前端 `RealtimeContext` 改为 `import type` contracts 单点。

**状态：已完成** —— `gen_ts_types.py` 从 `runtime_events.py` 的 `ProjectionDomain(StrEnum)` 直接解析字面量（删除生成器内硬编码列表），`contracts.ts` 随后端枚举同步（移除前端虚构的 `stats` 域）；`RealtimeContext.tsx` 删除手写 `ProjectionDomain/InvalidationEvent/RuntimeCursor`，改为 `import type` + re-export `types/contracts.ts`，`cache/invalidation`、`useCachedQuery`、`useInvalidation` 全部改从 contracts 导入；StatusBar 删除 `stats` 无效 invalidation 注册（10s 轮询保留）。

- **批次 S2 — 数据获取完成迁移 + 分层门禁**：页面统一 `useCachedQuery`/领域 hooks；`pages/**` 禁止直接 import api 工厂（静态 grep）；顺带修 H-F1/H-F2、M-F3。

**状态：已完成** —— 新增 `hooks/usePageApis.ts`（useFilesApi/useGalleryApi/useMetadataApi/useNotesApi/useQuicksearchApi/useSharesApi/useShopApi/useSellerShopApi/useSystemApi/useTagsApi/useUsersApi/usePublicShareApi），18 个页面全部停止直接 import `api/*` 工厂（ShareReceivePage 的“无全局 401 复位”专用 client 迁移到 `usePublicShareApi`，SellerSettings 保留 seller 专用 client）；新增 `scripts/check_frontend_data_fetch.py`（pages 禁止 api 工厂 import/调用与直接 `fetch`，挂 CI）；H-F1 DetailPage `saveNotes` 增加 pathRef 守卫（旧路径响应不再提交状态/toast）；H-F2 `listBuyerOrders` 支持 AbortSignal，BuyerOrders 页 loadMore 用 generation+abort+状态过滤拒绝旧响应；M-F3 结账幂等键改按 cart id 持久化到 sessionStorage；webui `tsc --noEmit`/vitest 687 例/vite build 全绿。
- **批次 S3 — 重试/退避统一**：client 幂等 GET 指数退避 + `Retry-After`；recover 复用 client；退避策略单模块供 WS/client 共用。

**状态：已完成** —— 新增 `webui/src/utils/backoff.ts`（`sleep` 支持 AbortSignal、`retryAfterSeconds` 解析 delta-seconds/HTTP-date、`backoffDelay` 指数封顶），API client 对幂等 GET 自动重试网络错误/429/503，尊重 `Retry-After`，非 GET 不重试；Realtime recovery 从手写 `fetch` 改为 `api.get('revision')` 复用同一 client 与退避策略（10s 恢复超时保留）；新增 `backoff.test.ts` 与 client 重试/Retry-After 测试，webui 104 files / 695 tests 全绿。
- **批次 S4 — 设计令牌单源**：`assets/Themes/*.json` 同时产出 CSS `:root` 与 PySide 属性；`/api/theme` 或 `ServerInfo.theme_color` 下发 accent；Web 与桌面视觉同源。
- **批次 S5 — 清理与文档**：删除孤儿测试或补源；`useCachedQuery` key 规范文档化；CSS z-index 注释对齐。

---

## 5. 建议执行路线图（跨域）

1. **G0（护栏）→ G1（core 逃逸）**：这是架构优先项，预计 1–2 个工作日；完成前其他批次风险会持续增长。
2. **L1+L4（授权/路由声明化）与 D1（worker 框架）并行**：一个消除 LAN 结构性 fail-open，一个消除桌面不可取消任务主线。
3. **S1+S2（前端契约/数据层）**：成本低于桌面/LAN，完成 H-F1/H-F2 后前端数据一致性风险显著下降。
4. **G2（LAN 单组合根 + ports）**：可与 L1 同批推进，先抽 port 后删装配。
5. **D2/D3/D4、L2/L3、S3/S4**：收敛性批次，分别消除状态/定时器/样式、限流/线程、重试/设计令牌。
6. **收尾**：更新 ADR 与 `docs/architecture.md` 的过时表格；把 `docs/full-review` 纳入版本控制，避免后续会话继续以过时基线工作。

## 6. 最值得立即做的三件事

1. **上圈层 DAG 门禁**（G0）：把“点采样”升级为“方向性断言”，任何 `core→repositories`、`widgets→lan` 都 fail CI。
2. **统一桌面 worker 框架**（D1）：消除关闭/切库无界等待这一用户可感知的高危主线。
3. **前端契约与数据获取单源**（S1+S2）：用机制而非约定解决竞态污染与契约 drift。

---

*本报告为只读审查产物；未改动任何业务代码。文中行号以 2026-08-15 工作区实测为准，后续批次引用时请以当前工作区 grep 复核。*
