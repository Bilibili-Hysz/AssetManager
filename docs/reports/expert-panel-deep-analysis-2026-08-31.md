# AssetManager 专家团深度分析报告（第二轮·五视角详尽版）

> 生成日期：2026-08-31
> 评审形式：五位专家并行源码级走查（架构 / 工程质量 / 安全威胁建模 / UX 双端一致性 / 性能与数据），主评审对全部 load-bearing 结论做源码抽查交叉验证。
> 关联文档：`docs/reports/project-analysis-2026-08-31.md`（第一轮总体评审）、`docs/reports/functional-analysis-and-serpent-comparison-2026-08-31.md`（功能对照 Serpent）。

---

## 0. 执行摘要

| 维度 | 评级 | 一句话结论 |
|---|---|---|
| 架构设计 | **B+** | 分层承诺大体兑现，但 DI 实为 Service Locator，domain→core 存在反向依赖 |
| 工程质量 | **B+**（接近 A-） | 测试文化、CI 门禁、契约代码生成是行业少见的强项；扣分在巨型文件与构建链脱节 |
| 安全 | **C+**（公网暴露前提下） | 密码学基本功扎实，但发现两条新的 HIGH 级 DoS/资源面漏洞 |
| UX / 双端一致性 | **B** | 桌面端快捷键/主题/空态工程化程度高；Web 端缺撤销重做是最重的功能缺口 |
| 性能与数据 | **B-** | 交互规模优秀；10 万文件库承载力受限于缩略图缓存失控与单连接读写互斥 |

**本轮新增的两个 HIGH 级安全发现（S2、S5）** 与 **一个打包链陈旧问题（spec 引用不存在的 shop 模块）** 是相对第一轮报告的增量核心。

---

## 1. 架构专家报告

### 1.1 分层违规探测（抽样 16 文件）

对 panels/ 8 个文件（sidebar、tag_tree、info、image_viewer、empty、base、file_list/_actions、file_list/_base）与 dialogs/ 8 个文件逐一检查：**均无 `import sqlite3`、无 `from AssetsManager.repositories` 直接引用**。表现层确实经 application 层工作（如 `panels/info.py:25` 依赖 `desktop_ports.TagsViewPort`；`panels/tag_tree.py:20-21` 走 `runtime_events.ProjectionDomain` + `_event_bridge`）。唯一的同层横向依赖是 `dialogs/tag_browser_dialog.py:13 → panels.tag_tree`。

lan/ 路由层同样干净：无任何 repositories import；`sqlite3` 仅用于异常类型捕获（`lan/routes/metadata.py:4,299`、`lan/routes/favorites.py:5,77`），服务获取统一经 `lan/routes/_helpers.py:419-441` 的 `get_xxx_service(request)`。

**轻微越层**：`lan/routes/metadata.py:371,386,418` 三个 handler 内联 `from AssetsManager.core.settings import AppSettings` 直读全局单例取 `sidebar_depth_cfg` —— transport 层绕过了 application 的配置接缝（`application/bootstrap.py:316-319` 专门设了 `app_settings_provider` seam，此处未用）。

### 1.2 DI 容器实态：披着 DI 外衣的 Service Locator

`AssetsManager/di/__init__.py:3` 模块 docstring 自述："Provides a **simple service locator**"。`ServiceContainer` 支持 register/resolve/deps 构造注入与循环检测（`di/__init__.py:86-133`），机制完整，但实态是全局定位器：

- `container.resolve` 全项目仅 8 处，全部在 bootstrap 内部（`bootstrap.py:314,365,418,743,845`），业务代码从不注入依赖，而是运行时主动拉取；
- 真正被广泛使用的是三类全局单例：`AppSettings.instance()` **74 处**、`get_event_bus()` **27 处**、`core.signal_bus` **16 处**、`tag_library.get_library()` 约 18 处（如 `dialogs/tag_editor_dialog.py:10`、`widgets/tag_chip.py`）；
- `core/database.py:281` 注释自认："routing through the ThreadSafeSingleton DatabaseManager **instead of DI**"。

值得肯定：`application/desktop_ports.py:20` 起的 Protocol 端口（如 `TagsViewPort`）是**真接口抽象**——panels 只依赖窄切片（`info.py:25`、`image_viewer.py:44`），是全项目最干净的接缝。

### 1.3 LibraryRuntime/LibrarySession 生命周期

构造点唯一：`ApplicationBootstrap.runtime_for`（`bootstrap.py:420-452`），以 `id(session)` 为键缓存，用 `threading.Event` 门闩防并发双建（`:437-446`），以 `cached.session is session` 身份校验（`:431`）缓解 id 复用碰撞。关闭协议精细：

- `runtime.close`（`application/runtime.py:150-185`）：状态机 open→closing→closed，router drain 后才执行 `_cleanup_adapters`（`:187-211`）；
- `LibrarySession.close`（`application/context.py:255-276`）有界排空 `_FINISH_CLOSE_TIMEOUT_SECONDS=30s`（`:30`），超时仅告警并**拒绝**上层关闭 DB（`:287-316`），`tag_store.clear_cache` 只清一次（`:304-306`）；
- `db_conn` 归 `DatabaseManager` 所有，session 不关连接（`context.py:142,258-259`），职责清晰。

**风险**：① router 关闭排空上限 2s，超时后 "closing anyway"（`application/runtime_events.py:37-41,88-92`），被放弃的 in-flight 回调可能继续触碰已清理的 runtime；② runtime 缓存键依赖 CPython `id()` 语义（`bootstrap.py:426`），存在会话对象回收后 id 复用导致错绑的窗口（session.event_token 已具备、可用作键，`context.py:147`）。未发现明显库间状态串扰——`LibraryScopedServices` 是 frozen dataclass 按快照分发（`runtime.py:44-54`）。

### 1.4 event_bus 事件流

`domain/events.py` 共 **15 种**领域事件（ShareChanged/FavoritesChanged/UserChanged/InviteChanged/ActivityChanged/MaintenanceChanged/PresenceChanged :22-78、FileSystemChanged :83、AssetTagsChanged/TagCatalogChanged/AssetNotesChanged/AssetUrlsChanged/AssetRatingChanged :95-144、QuotaChanged :149、CollectionChanged :159）。订阅者三类：① `RuntimeEventRouter` 按 `session_token` 过滤（`runtime_events.py:265-268`）——**已隔离跨库污染**；② panels 经 `panels/_event_bridge.py:11-37` 的 QueuedConnection 桥；③ **直接订阅未过滤**：`dialogs/undo_panel.py:39-40` 直接 `get_event_bus().subscribe(FileSystemChanged)`——切库瞬间另一库的 FileSystemChanged 可达 UI，**存在跨库事件污染窗口**。异常处理：publish 逐 handler try/except 并记录（`event_bus.py:129-135`），不吞异常但**同步派发**，慢 handler 会阻塞发布线程。

### 1.5 Qt 与 asyncio 双世界边界

未用 qasync，双桥模式：① worker 线程 → GUI：domain 事件经 `Qt.QueuedConnection` 信号转投（`_event_bridge.py:19-27`）；② 任意线程 → asyncio loop：`run_coroutine_threadsafe`（`lan/server.py:571-576`、`server_lifecycle.py:171,249,271,616`）。**最怪异一环**：桌面分享对话框不打本地服务直调，而是在 `QRunnable` 里用阻塞 `requests` 打**自家 loopback HTTP**（`dialogs/_share_api.py:21-60` ShareApiTask）——桌面端分享功能依赖 LAN 服务器在线，且与服务直调双路径并存，错误语义分裂。sqlite 侧 `check_same_thread=False` 共享连接（`core/database.py:916-918`），靠 DatabaseManager 统一锁纪律，未见跨线程裸触 QWidget。

### 1.6 webui 与桌面端对称性

webui 无 zustand/redux，用 Context + 自研查询缓存（`webui/src/cache/QueryCacheContext.tsx`、`hooks/useCachedQuery.ts`）+ RealtimeContext（WebSocket）。两端共享同一批 application 服务（lan 侧 `LanScopedServices`，`_helpers.py:322-336`），核心业务规则单点化良好，但**校验常量三方硬编码**：notes 上限 4000 同时出现在 `lan/routes/metadata.py:30` 与 `webui/src/components/layout/InfoPanel.tsx:173`、`webui/src/pages/DetailPage.tsx:242`；rating 0-5 规则在 `application/metadata_service.py:335-338` 与 `lan/routes/metadata.py:154-161` 各写一遍。

### 1.7 实际依赖方向图与违规

```
panels/dialogs ──→ application(ports/services) ──→ repositories ──→ sqlite
      │                    │
      └──→ core(单例) ←── domain(✗ 反向)          lan ──→ application/domain
```

反向/循环依赖：① **domain → core**：`domain/events.py:11` 依赖 `core.event_contracts.DomainEventBase`（已验证），`domain/asset.py:7,21` 依赖 core.constants/format_utils——宣称最内层的 domain 反向依赖基础设施；② lan 路由直读 AppSettings 单例（`metadata.py:371`）；③ panels↔dialogs 横向循环群（`panels/sidebar.py:31-32` ↔ `dialogs/tag_browser_dialog.py:13`）；④ `bootstrap.py:318-322` 主动"安装 seam"补偿 core 单例（注释自认债）。

### 1.8 架构优势清单

1. 库会话隔离严格：session_token + epoch/revision 双重过滤（`runtime_events.py:265-268`、`runtime.py:23-24`）。
2. Qt 线程边界统一：全部经 QueuedConnection 桥（`_event_bridge.py:23`）。
3. 关闭协议极其防御性：有界排空、幂等关闭、failed 状态回滚（`context.py:287-316`、`runtime.py:136-148`）。
4. 桌面 Port/Protocol 窄接口（`desktop_ports.py:20-40`）。
5. 事件异常不静默（`event_bus.py:130-135`）。
6. 传输层零 repositories 依赖。

### 1.9 架构风险清单

| # | 风险 | 证据 | 建议 |
|---|---|---|---|
| A1 | DI 退化为 Service Locator，依赖不可静态追溯 | `di/__init__.py:3`；AppSettings.instance 74 处 | 至少收敛 AppSettings.instance 到已有 provider seam |
| A2 | domain → core 反向依赖，分层承诺失效 | `domain/events.py:11`（已验证）、`domain/asset.py:7` | DomainEventBase 下沉进 domain |
| A3 | 直接 bus 订阅绕过会话过滤，切库瞬间 UI 显示错库数据 | `dialogs/undo_panel.py:39-40` | UI 订阅统一走带 token 过滤的 RuntimeEventSubscription |
| A4 | router 关闭 2s 超时后静默放弃 in-flight 回调 | `runtime_events.py:37-41,88-92` | 超时后标记 runtime poisoned 并拒绝后续访问 |
| A5 | runtime 缓存以 id() 为键 | `bootstrap.py:426` | 改用 session.event_token 作键 |
| A6 | 桌面分享走 loopback HTTP | `dialogs/_share_api.py:21-60` | 分享流程接入 application 服务直调 |
| A7 | 校验常量三处硬编码 | `metadata.py:30` vs `InfoPanel.tsx:173`、`DetailPage.tsx:242` | 经 /api/system 元数据下发约束 |
| A8 | 共享 check_same_thread=False 连接，绕锁即数据竞争 | `core/database.py:916-918` | 写路径单写线程或严格 per-thread 读连接 |

---

## 2. 工程质量专家报告

**规模基线**：Python 约 8.9 万行（310 个测试文件），webui 约 2.4 万行 TS/TSX。整体是"文档驱动 + 脚本门禁"重治理型项目。

### 2.1 测试实态

- 分布（实测）：unit 114、integration 63、lan 51、desktop 49、core 17、plugins 12、performance 2、e2e 2，共 310 个测试文件。分层约定在 `pytest.ini:23-29`；默认排除 e2e/perf（`pytest.ini:16`），xdist `--dist worksteal` + `xdist_group("serial")`（`pytest.ini:4-8`）隔离固定端口测试。
- **核心模块覆盖深查**：
  - `core/database.py`（1610 行）→ `tests/unit/test_database.py` 仅 190 行/10 用例，基本只测慢查询阈值与包装器；`_ensure_library_data_identity`（174 行，database.py:699-873）与 `migrate_path_metadata`（213 行，:1336-1558）这两块最难的逻辑**无专测**。
  - LAN 路由：`tests/lan/test_lan_api.py` 高达 5997 行/210 用例/26 处 `pytest.raises`——异常与边界覆盖很深；但 `thumbnails.py`（484 行）仅 10 用例测试，`test_metadata_tag_mutation_routes.py` 仅 4 用例，**薄厚不均**。
  - `application/library_service.py` → `tests/integration/test_library_service.py` 1025 行/41 用例/93 处 tmp_path 隔离，异常路径覆盖最佳。
- skip/xfail 52 处，绝大多数为平台条件跳过（junction/symlink 不可用），合理。
- **flaky 风险**：测试目录 158 处 sleep；desktop 测试密集 `time.sleep(0.01)` 轮询（`tests/desktop/test_file_list_view.py:150,236,3135`）；`tests/conftest.py:155-168` 的 `_remove_dir_retry` 用 sleep(0.5) 重试删目录——项目自认存在资源清理竞争。

### 2.2 静态检查实态

- `ruff.toml:14-25` 只启用正确性规则族，风格族刻意关闭；ignore 仅 B009/B010/B008 且每条有理由注释（:27-39）；per-file-ignores（:41-51）只放过 tests 与纯打印脚本——抽查被豁免文件无实质硬伤。
- `pyrightconfig.json:28` 为 **basic** 而非 strict，`reportMissingImports/TypeStubs/ModuleSource` 全关（:29-31）。生产代码 `type: ignore` 极少（约 25 处，`core/db_migrations.py` 占 12 处）。**类型卫生好，但 basic 模式放过了大量可空性/泛型问题。**

### 2.3 巨型文件解剖（最长的 10 个 .py）

`dialogs/settings_dialog.py`(1939)、`panels/info.py`(1896)、`panels/file_list/_loader.py`(1883)、`core/schema_defs.py`(1780)、`core/plugins/host_context.py`(1657)、`application/reconciliation_queue.py`(1656)、`core/database.py`(1610)、`application/file_operation_service.py`(1588)、`core/db_migrations.py`(1587)、`application/library_service.py`(1468)。

- `lan/server.py`(1204 行)：单类混合配置读取、路由装配、生命周期、用户缓存失效——`__init__` 257 行（:60-316）、`invalidate_user_cache` 200 行（:1079-1278）。
- `core/database.py` 混了 4 种职责（慢查询监控、目录持久化/身份认领、写闸门锁、路径元数据迁移），两块 170-213 行的方法应拆独立模块。
- `settings_dialog.py` 每个 tab 一个大方法（`_build_appearance_tab` 108 行，:173-281）。
- webui 三大文件：`BrowsePage.tsx` 995 行（单组件 35 个 hook）、`client.ts` 549 行、`LandingPage.tsx` 534 行。

### 2.4 重复代码

重复治理总体良好：DTO 走代码生成——`webui/src/types/contracts.ts:1-3` 注明 "AUTO-GENERATED by scripts/gen_ts_types.py, Source of truth: AssetsManager/lan/dto.py"，CI 有 drift 门禁（`ci.yml:29`）；错误码在 webui 生产代码 0 处硬编码。残留：① `lan/dto.py` 内 10+ 个手写 `to_dict` 模板（:109-397）；② `webui/src/types/api.ts`（425 行手写类型）与生成的 `contracts.ts` 并存，同一 DTO 双源；③ `tests/perf/` 与 `tests/performance/` 双轨。

### 2.5 CI/CD 实态

`ci.yml` 有 9 个 job：lint（13 项自制门禁脚本，:26-49）、git hygiene、pyright 硬门禁（版本固定 :87）、webui、**Windows 真打包 smoke**（:124-190，含冻结运行 15 秒验证）、Windows 回归、媒体解码器 lane、Python 3.12/3.13/3.14 矩阵、浏览器 e2e。`release.yml`：tag 触发、测试门禁前置、Inno Setup、SHA256 校验 + 防覆盖重跑（:163-171）、actions 全 pin 到 commit SHA——**可复现性是同类项目高水准**。陷阱：① Python job 均未开 `cache: pip`；② 测试矩阵 3 版本各自重复 `npm ci + build`（:279-290）；③ `allow-prereleases: true`（:273）引入 3.14 预发布风险；④ `pip install rawpy || true`（:227）静默吞错。

### 2.6 构建链

- **Cython 名存实亡（已验证）**：`setup_cython.py:5-10` 定义了 4 个加速模块（cache/color_utils/format_utils/asset_filters），但 `build.py` 全文无任何 cython 调用（grep 零命中），release/ci workflow 也从不调用——加速声明未接入任何实际构建入口。
- **spec 资源路径大小写隐患（已验证）**：`AssetManager.spec:77,82,352` 引用大写 `Assets/`，磁盘实际是小写 `assets/`——Windows 大小写不敏感下侥幸工作，Linux 构建宿主会直接挂。
- **spec hiddenimports 引用不存在的模块（本轮新发现，已验证）**：`AssetManager.spec:177-182` 列出 `lan.routes.shop._common/cart/catalog/delivery/orders`、`:224` `application.order_service`、`:238-241` shop 三个 service、`:272-273` shop 两个 repository——glob 确认**这些文件全部不存在**。spec 与代码库脱节（同时再次印证"商城零实现"结论）；PyInstaller 对缺失 hiddenimports 通常告警不致命，但这是打包配置腐烂的明确信号。
- hiddenimports 手工枚举 100+ 模块兜住懒导入（spec:88-294）——新增模块必须记得改 spec，靠 `scripts/check_package_contents.py` 在 CI 兜底。

### 2.7 死代码与垃圾

生产代码 **TODO/FIXME/HACK 计数为 0**（grep 全量验证）。工作树垃圾：`artifacts/`（审计日志）、`mirror/`（git bundle）、`RuntimeData/_orphaned`、`outputs/`、`DeepSeek Docs/`——不影响运行但污染搜索上下文。

### 2.8 质量结论

优势：① 310 个测试文件、分层明确、并发端口隔离有专门设计；② 前后端契约代码生成 + CI drift 门禁；③ 13 项自制架构检查脚本 + pyright 硬门禁 + Windows 真打包冻结 smoke；④ Release 工程可靠（SHA256、防覆盖、actions pin SHA）；⑤ 零 TODO 债务、type: ignore 极少。

问题（按优先级）：Q1 Cython 链路断裂、Q2 spec 大小写 + 陈旧 shop 引用、Q3 十个 1400+ 行巨型文件与多个 100-250 行方法、Q4 database/thumbnails/metadata 测试空洞、Q5 desktop 测试 158 处 sleep 轮询、Q6 pyright 仅 basic、Q7 CI 无缓存 + 矩阵重复构建、Q8 api.ts/contracts.ts 双源、Q9 工作树垃圾、Q10 perf 测试双轨。

**综合评级 B+**：工程纪律是该项目最突出的资产，扣分项均为局部可修；完成 database/server 拆分并把 pyright 升到 strict 可入 A-。

---

## 3. 安全专家报告（威胁建模·第二轮纵深）

> 前一轮已确认的：插件无沙箱（CRITICAL，`core/plugins/loader.py:89,93`）、密码模式令牌用 password_hash 作 HMAC key（HIGH，`domain/auth.py:155`）、全局单写者（`core/database.py:523`）。本轮按攻击面挖**新问题**。

### 3.1 未认证攻击面

白名单经 `lan/route_policy.py:74` fail-closed 默认统一声明。`auth="public"` 有 `/`、`/browse`、`/detail`、`/login`、`/gallery*`、`/s/{id}`、`/mcp`、`/assets`（`lan/api.py:209-218,255,295,377`）。

- **S1（MEDIUM）`/api/info` 匿名信息泄露**：`lan/routes/system.py:69-135` 向未认证请求返回 `library_root.name`、`library_stats`（项目总数/库总容量）、`auth_mode`、feature_flags。公网隧道下可枚举目标价值、评估钓鱼收益。修复：匿名分支仅保留 `auth_mode`/`share_name`。版本信息无泄露（`system.py:113` 为常量）；`/assets` `show_index=False`（`api.py:376`）。

### 3.2 会话与令牌生命周期（健康面确认）

token 全部 `secrets`/`os.urandom`（`domain/auth.py:21,153,218,278`）；nonce 4 字节仅保证唯一性，无防重放表（stateless 设计，无内存耗尽面）；撤销表持久化 SQLite（`application/auth_service.py:313-316`），内存缓存上限 10000 且淘汰后回落 DB 权威查询（`lan/token_revocations.py:37,92-103`）；登出即持久化撤销且失败返回 503（`lan/routes/auth.py:184-217`）；用户缓存 TTL 仅 5s，停用账号即时失效（`auth_service.py:55,390-393`）；改密码/改 key 会轮换 local_ui 派生密钥（`lan/runtime_validation.py:47-69`）。**此面整体健康。**

### 3.3 新发现（核心增量）

- **S2（HIGH）skip 限流类 + 随机凭据探测 = 未认证 CPU DoS（已验证）**：`/api/image`、`/api/thumbnails/{path}`、`/api/revision`、`/ws`、`/assets` 等全部 `rate_limit="skip"`（`lan/api.py:134-136,166,225,235,276,291,307`；`lan/security.py:186` `skip_rate = policy.rate_limit == "skip"` 时跳过所有限流器）；而认证中间件对任何携带随机 Bearer 的请求都会执行：撤销表 DB 查询（`server.py:1120-1130`）→ 50k 轮 PBKDF2 `verify_key`（`server.py:1131-1134`；`domain/auth.py:28,44`）→ user token DB 查询（`server.py:1142-1148`）。攻击者向 skip 路由无限发送随机 token，绕过全部速率限制，每请求烧 ~20-50ms CPU + 2 次 SQLite 查询。**修复**：skip 类保留宽松兜底预算，或在 PBKDF2 前做廉价失败计数（改动小、收益大）。
- **S5（HIGH）全量文件读入内存且无上限（已验证，细节修正）**：`lan/safe_open.py:54-60` 的 `read_safe_file` **签名本身即无 max_bytes 参数**，返回 `tuple[bytes, FileIdentity]`——整文件 bytes。单文件 `/api/download`（`downloads.py:183`）、`/api/image`（`image.py:119,176`）、公开的 `/api/shares/{id}/download`（`shares.py:320`）均基于它。数 GB 文件 → 整文件进内存 → OOM。叠加：guest `preview` 默认 True（`lan/principal.py:96`）且 `/api/image` 为 skip 限流 → **未认证可打**。修复：为 read_safe_file 增加流式/上限变体（FileResponse 已验证 root-confined，可直接改用）。
- **S3（LOW）Windows 保留名依赖隐式行为**：`path_guard.py:104-107` 注释假设 `resolve()` 对 CON/NUL 抛错，非显式黑名单，行为随 Python 版本漂移。
- **S4（LOW）分享存在性预言机**：`/api/shares/{id}/verify` 对不存在与过期分别回 404/410（`shares.py:236-239`），info 端点泄露 `has_password/expired`（`shares.py:400-419`）；download 已正确折叠为 404（:301-306）但 verify 未对齐。share id 10 字符 62 进制 ≈59.5bit（`share_service.py:457-460`），QR/URL 面清洁。
- **S6（LOW）ZIP worker 并发配额缺失**：ZIP executor 仅 2 worker（`server.py:104-106`），并发 500MB 构建可占满 worker + 磁盘。
- **S7（MEDIUM）默认监听 0.0.0.0**（`server.py:146,403`）：`auth=none` 时整个库对 LAN 匿名开放（`principal.py:93-99`）。
- **S8（LOW）auth_strict 桶共享挤占**：tunnel 未认证访客共享 loopback 桶（`security.py:163-167`），攻击者刷 10 次/5min 预算可令真实访客登录 429。
- **S9（LOW）SPA 无 CSP/X-Frame-Options/HSTS**：`_spa_response` 为裸 FileResponse（`lan/routes/pages.py:16-23`）。

### 3.4 防御面确认（扎实项）

路径服务纵深逐行验证：`path_guard.py` 控制字符/NUL（:54,98）、`..` 逃逸（:102-109）、NTFS ADS 冒号（:110-117）、reparse point/junction 逐级拒绝（`core/file_snapshot.py:77-101`）、POSIX `O_NOFOLLOW` 逐目录打开（:104-127）、open 后 fstat 校验 + 二次 containment（:163-172）——TOCTOU 防护扎实；UNC `//server/share` 被困于 root。SQL 全参数化（f-string 仅限 PRAGMA/SAVEPOINT 内部标识符，`database.py:921,1574`）。Content-Disposition 经 `sanitize_filename` + RFC5987（`_helpers.py:44,242-253`、`downloads.py:80-86`）。webui 无 `dangerouslySetInnerHTML`/postMessage/eval，SVG 主动排除（`image.py:31-33`）。缩略图 admission 64MB 单源/256MB 批量（`thumbnail_service.py:52-53`）。ZIP 为磁盘临时文件流式 + 500MB/100 文件上限（`downloads.py:23-24`）。密码学达标：PBKDF2 600k/32B 盐（`domain/auth.py:55,70`）、全程 `hmac.compare_digest`（:45,125,178,262,303）、cloudflared SHA-256 pin（`tunnel.py:36-105`）、隧道启动强制认证（`server.py:732-742`）、500 不回栈（`_errors.py:132-139`）、日志无凭据。

### 3.5 安全优先级表

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| S2 | HIGH | skip 路由零限流 + 随机 token PBKDF2 探测 DoS | `api.py:225`、`security.py:186`、`server.py:1131` |
| S5 | HIGH | image/download/share 全量读内存无上限，guest 可打 | `safe_open.py:59`、`downloads.py:183`、`image.py:176`、`shares.py:320` |
| S1 | MED | /api/info 匿名泄露库规模/根名 | `system.py:112-131` |
| S7 | MED | 默认 0.0.0.0 + auth=none 匿名开放 | `server.py:146`、`principal.py:96` |
| S3/S4/S6/S8/S9 | LOW | 保留名/预言机/ZIP 配额/桶挤占/安全头 | 见上文 |

---

## 4. UX / 双端一致性专家报告

### 4.1 桌面端交互全景

键盘可达性是强项：集中式快捷键注册器 `AssetsManager/widgets/shortcut_manager.py:13`（单例 + 冲突检测 `:63-71`），文件列表 19 个快捷键以 `FILE_LIST_SHORTCUTS` 为唯一事实源（`panels/file_list/_commands.py:41-61`），帮助对话框从注册表生成——文档不可漂移。分发器保护搜索框焦点（`_shortcuts.py:17-26`）。空状态三段式语义图标（`panels/empty.py:26-48`），首启双卡片空库引导（`dialogs/startup.py:337-340,572-578`）。

短板：QMessageBox 模态轰炸——`settings_dialog.py` 47 处、`window.py` 26 处、`panels/file_list/_actions.py` 16 处，而 toast 仅 5 个文件引用；查看器 15+ 快捷键走裸 `keyPressEvent`（`panels/image_viewer.py:1064-1094`）未经 ShortcutManager 注册，F1 帮助失真。

### 4.2 主题系统

24 套主题为 JSON 令牌文件（`assets/themes/`：13 暗色 + 11 亮色），`core/themes.py` 令牌合并生成 QSS，插件可注入令牌回退；切换经 `theme_changed` 热应用（`window.py:660-664`）零重启。硬编码颜色治理极佳：全库 grep `setStyleSheet(...#hex)` 零命中（唯一例外取色器默认值 `dialogs/color_picker_dialog.py:23`）。背景特效 GL 优先、CPU 兜底（`background/pipeline.py`），模糊前先降采样（`core/bg_effects.py`）；纯 Python kuwahara 兜底在无 numpy 机器上可能卡顿。

### 4.3 i18n 实态

桌面三语各 1013 行，体量对齐；硬编码扫描仅命中注释，无绕过 tr() 的用户可见字符串。Web 端 `i18n.test.ts:19-60` **强制三语 key 结构/非空值/占位符三方一致——业界少见的严谨度**。但两套 key 体系完全独立：桌面 `filelist.sort.name` vs Web `sort.name`，同一概念双份维护、文案漂移无门禁；桌面侧缺对应的 i18n 平价测试。

### 4.4 双端一致性矩阵（核心交付）

| 功能 | 桌面 | Web | 不一致说明 |
|---|---|---|---|
| 排序维度 | name/date/size/**type**（`_base_layout.py`） | name/date/size（`FileToolbar.tsx`） | Web 缺"按类型" |
| 视图模式 | Grid/Details | grid/list/**masonry** | Web 多瀑布流，桌面多详情列 |
| 缩略图尺寸 | ZOOM_PRESETS 档位（`_base_layout.py:160`） | **无任何尺寸调节** | 桌面有 Web 无 |
| 撤销/重做 | Ctrl+Z/Y + undo_panel（`_commands.py:54-55`） | **完全没有**（全库 grep 零命中，已验证） | **最重缺口** |
| 标签编辑 | 对话框式（`tag_editor_dialog.py`） | 批量标签条内联（`BrowsePage.tsx:469-474,823-839`） | 交互范式不同 |
| 右键菜单 | 本地 FS 语义（复制/剪切/删除/属性） | LAN 语义（下载/详情/分享/复制链接） | 定位不同但无教育提示 |
| 搜索 | Ctrl+F 本地过滤 + F4 帮助 | 200ms 防抖 + Ctrl+K 命令面板 + `/` + `?`（`useSearch.ts:51-54`） | Web 多命令面板 |
| 错误反馈 | QMessageBox 为主 | toast 为主 + 降级总线（`api/degradationBus.ts`） | 通道完全不同 |
| 快捷键帮助 | F1（注册表驱动） | `?` ShortcutsDialog | 键位体系两套，无对照表 |

### 4.5 其他维度

- 响应式：Web 断点散落 11 处 CSS 且数值各异（680/768/1000/1100/1400/430/560/760），无 token 化；桌面 DPI 经 `core/ui_scale.py` 全局贯穿。
- 可访问性：Web 大量 aria-label/aria-pressed（`FileToolbar.tsx`），桌面有 `setAccessibleName`；升降序仅 ↑/↓ 字形，色弱风险。
- 设置项 6 Tab 组织清晰但 1939 行单文件 + 47 处 QMessageBox 需拆分。

### 4.6 UX 问题清单

| # | 级别 | 问题 | 证据 | 建议 |
|---|---|---|---|---|
| U1 | 高 | Web 无撤销/重做 | `webui/src` 全库无 undo（已验证） | 服务端操作日志 + 限时撤销 toast |
| U2 | 高 | 桌面错误提示模态轰炸，与 Web toast 体系割裂 | `settings_dialog.py` 47 处 | 非阻断通知统一走 `widgets/toast.py` |
| U3 | 中 | 查看器 15+ 快捷键绕过注册表，F1 帮助失真 | `image_viewer.py:1064-1094` | 并入 ShortcutManager |
| U4 | 中 | Web 排序缺 type、缺缩略图尺寸调节 | `FileToolbar.tsx` vs `_base_layout.py:160` | 补齐 |
| U5 | 中 | Web 断点数值不统一（11 处） | MasonryView.tsx、Header.css 等 | token 化到 480/768/1100 三档 |
| U6 | 中 | 双端 i18n key 体系独立无共享目录；桌面缺平价测试 | `filelist.sort.name` vs `sort.name` | 抽共享 key 目录 + 桌面平价测试 |
| U7 | 低 | 快捷键冲突静默"last wins" | `shortcut_manager.py:66-71` | 启动时汇总告警 |
| U8 | 低 | 升降序指示仅字形，色弱不友好 | FileToolbar | 加文字标注 |

---

## 5. 性能与数据专家报告

### 5.1 Schema 与高频查询

核心建表 `core/database.py:398-446`（WAL 首行启用 :399，busy_timeout 30s :70,921）；迁移层 `assets` 索引表（`core/db_migrations.py:548-565`）、FTS5 trigram 全文表 `asset_search`（`core/schema_defs.py:553-559`）、CAS 用 `asset_index_state`（:121-126）。

五个高频查询抽查：
- 文件列表分页：`lan/routes/files.py:18` `FILES_MAX_LIMIT=1000`，但 `limit=None` 回落全量列举；底层 `list_directory` 是**文件系统全扫描**而非 SQL 分页。
- 标签过滤：`get_files_by_tag` 走 `idx_file_tags_tag`，优；但 `get_files_by_tag_case_insensitive` 用 `LOWER(tag)=LOWER(?)`（`repositories/tag_repository.py:353`）**无表达式索引 → 全表扫描**。
- 搜索：FTS MATCH 优先（`search_index_service.py:222-226`），但 `needs_full_scan`（短于 3 字符或排除式）时**整表流式扫描 + Python 谓词**（:208-219），默认 `limit=10_000`。
- 缩略图状态：PK 直查 + touch 60s 节流（`panels/file_list/_loader.py:119,1592-1610`）防写放大——设计良好。
- 结构化搜索：`LIMIT ? OFFSET ?`（`asset_index_repository.py:726`）**OFFSET 深页 O(offset)**；`LIKE '%…%'` 前导通配非索引、ORDER BY 走 TEMP B-TREE（:676-682 已自认权衡），无 `(library_root, name)` 复合索引；`file_meta.rating` 无索引。

### 5.2 写路径与事务

`db_write_lock` = 每连接 RLock + 全局 `_WriteGate`（`database.py:461-536,1204-1263`）；`locked_read`（:1266-1302）把**所有读也串行化到同一把锁**——单连接被事件循环、to_thread、gallery 线程共享，长查询阻塞写、反之亦然，是吞吐上限的根本约束。**批量导入 1 万文件预估**：每文件 SHA-256 全量读两遍（`application/import_service.py:405-407,659-660`）；`upsert_dir_snapshot` **每目录一次 commit+fsync**（`asset_index_repository.py:460-467`）且未设 `synchronous=NORMAL`；FTS 增量按 500/块 DELETE+INSERT（`search_index_service.py:97-108`）——合计约 2-4 万行写、~1k 次 commit，HDD 分钟级。identity tagging（`os.link` 标记 + Windows FlushFileBuffers 目录链 fsync，`database.py:699-871`）每次开库一次性成本，换跨进程槽位防冲突，开销合理。

### 5.3 缩略图管线

QThreadPool 3 线程生成（`loader.py:418-419`），ffmpeg 专用 2 线程池防饿死（:67-69）；LAN 侧全部 `asyncio.to_thread`（`thumbnails.py:107,247,463`）。磁盘缓存按库存于 `RuntimeData/<hash>/thumbs`，**桌面与 webui 共享同一目录与元数据表**。档位 256/512/1024 webp(q85) + 512 视频帧 jpg（`thumbnail_key.py:13-17`）。内存 LRU 64MB（`loader.py:118,763-772`）。**淘汰是明显短板**：磁盘侧仅当用户手动触发 `enforce_cache_capacity` 才按 `last_access ASC` 淘汰（`thumbnail_service.py:441-473`），**写入路径无自动配额——无限增长**。命中率遥测齐全（`loader.py:814,1086-1089`）。

### 5.4 quicksearch 75ms 预算审计

实现为**有界文件系统 BFS**（非 DB/FTS）：预算 0.075s（`search_service.py:68`），上限 512 目录/1 万条目/1000 匹配（:63-67），每条目 `resolve(strict=False)` + is_dir/is_file（:1027-1069）——Windows 上 resolve 是重 syscall，**10 万文件库 75ms 内只扫到 1 万条即截断**，降级 = 返回部分结果（partial 可接受），事件循环不受影响（`lan/routes/quicksearch.py:81` 在 to_thread）。不会被"击穿"但召回受限；未利用已有 FTS 索引是设计取舍。

### 5.5 LAN 吞吐与前端

事件循环卫生极佳：重活全部 to_thread/executor。ZIP 落盘临时文件 + FileResponse 流式（`downloads.py:236-271`、`_helpers.py:724-752`），但 `build_zip_sync` 对每个文件**整读进内存** `zf.writestr`（`_helpers.py:668-672,691-692`），峰值内存 = 最大文件（≤500MB），且**无 HTTP Range**（不支持断点/视频拖动）。WS 广播单次序列化 + gather 扇出 + 背压（`ws.py:633-660`）。前端 dist 仅 667KB、路由懒加载、IntersectionObserver 增量加载；但 masonry 无真正虚拟滚动。启动性能良好：插件发现与 GL 预热延迟到启动窗显示后（`app.py:183-208`）。

### 5.6 性能问题清单

| # | 级别 | 问题 | 证据 | 建议 |
|---|---|---|---|---|
| P1 | 高 | 缩略图磁盘缓存无自动淘汰，10 万库可膨胀数十 GB | `thumbnail_service.py:441-473` | bake 路径尾部周期性调用 enforce（阈值=设置值×0.9） |
| P2 | 高 | 单连接读写互斥 + OFFSET 深分页 | `database.py:1266-1302`、`asset_index_repository.py:726` | 加 `(library_root,name)` 复合索引 + keyset 分页 |
| P3 | 中 | ZIP/单文件下载整读内存、无 Range | `_helpers.py:672`、`downloads.py:182` | `zf.open` 流式写 + Range 支持（与 S5 同修） |
| P4 | 中 | `LOWER(tag)=LOWER(?)` 全表扫 | `tag_repository.py:353` | 存小写列或 COLLATE NOCASE 索引 |
| P5 | 中 | 扫描器每目录一次 commit/fsync | `asset_index_repository.py:460-467` | 批量提交 + `PRAGMA synchronous=NORMAL`（WAL 下安全） |
| P6 | 低 | 短词查询流式全索引 | `search_index_service.py:208-219` | fts5vocab/缓存 |
| P7 | 低 | 批量缩略图 base64 JSON 可达 ~340MB 响应 | `thumbnails.py:351-391` | 改多路二进制端点 |

### 5.7 10 万文件规模承载力评估

读路径：单文件/目录级查询毫秒级，FTS MATCH 十毫秒级，可承载；但深分页、标签大小写过滤、无复合索引的结构化搜索会在 10 万行级退化到百 ms~秒级，且读写互斥被批量扫描放大。写路径：批量导入受 fsync 与双重哈希支配，HDD 3-8 分钟/SSD 1-2 分钟。磁盘：缩略图缓存失控是最大长期风险（P1）。**总体评级：中等偏上——交互浏览与搜索可用，需先落地 P1/P5/P2 方可平稳服务 10 万文件库。**

---

## 6. 交叉验证记录

| 论断 | 验证方式 | 结果 |
|---|---|---|
| S2 skip 限流策略存在 | grep `rate_limit="skip"` → `api.py:134-136,166,291`；`security.py:186` | ✅ |
| S5 全量读内存 | 读 `safe_open.py:54-60` 签名（返回 bytes、无 max_bytes 参数）+ 三处调用点 | ✅（细节修正：read_safe_file 本身无上限参数，修复需增加流式变体） |
| A2 domain→core 反向依赖 | 读 `domain/events.py:11` | ✅ |
| Q1 Cython 链路断裂 | grep build.py 全文无 cython | ✅ |
| Q2 spec `Assets/` 大小写 | `AssetManager.spec:77,82,352` vs 磁盘 `assets/` | ✅ |
| U1 Web 无 undo | grep webui/src → 仅 1 个测试文件命中 | ✅ |
| spec shop 模块引用 | glob `lan/routes/shop/**`、`application/shop*.py`、`repositories/shop*.py` → 均不存在 | ✅ **新发现** |

---

## 7. 全局风险登记表（按优先级合并）

### P0 — 公网/发布红线（1-2 周内）
1. 🔴 插件无沙箱（第一轮 CRITICAL，维持）——`core/plugins/loader.py:89,93`
2. 🔴 **S2** skip 路由零限流 + PBKDF2 探测 DoS——`api.py:225`、`security.py:186`
3. 🔴 **S5** 未认证可触发的全量读内存 OOM——`safe_open.py:59`、`downloads.py:183`、`shares.py:320`
4. 🔴 密码模式令牌可伪造（第一轮 HIGH，维持）——`domain/auth.py:155`
5. 🟠 **S1** `/api/info` 匿名信息泄露 + **S7** 默认 0.0.0.0——`system.py:112`、`server.py:146`

### P1 — 结构性风险（1-2 月）
6. P1 缩略图缓存无自动淘汰（磁盘失控）——`thumbnail_service.py:441`
7. P2/A8 单连接读写互斥 + id() 锁归属 + OFFSET 分页——`database.py:1266,543`
8. A1/A2 DI=Service Locator + domain→core 反向依赖——`di/__init__.py:3`、`domain/events.py:11`
9. U1/U2 Web 无撤销 + 桌面模态轰炸——`webui/src`、`settings_dialog.py`
10. Q2 spec 陈旧（大小写 + 幽灵 shop 模块）+ Q1 Cython 断链——`AssetManager.spec:77,177`
11. A3 undo_panel 跨库事件污染——`dialogs/undo_panel.py:39`

### P2 — 可维护性改善（持续）
12. Q3 十个巨型文件拆分（database/server/settings_dialog/BrowsePage）
13. Q4/Q5 测试空洞与 sleep 轮询
14. Q6 pyright basic→strict（先 core/application）
15. U3-U8 查看器快捷键注册、断点 token 化、i18n key 共享等
16. P3-P7 下载流式化/Range、NOCASE 索引、批量 fsync、二进制缩略图端点

---

## 8. 结语

第一轮报告的"文档↔代码背离"（商城零实现）在本轮获得**双重印证**：不仅 README 宣称 54 条 shop 路由无代码支撑，连打包 spec 的 hiddenimports 都还残留着这些幽灵模块的引用（`AssetManager.spec:177-182`）——说明商城功能曾是真实规划、后整体废弃，但文档与构建配置未同步回收。

项目最大的资产是**工程纪律**（测试规模、契约生成、门禁密度、release 可复现性、零 TODO 债务），最大的负债是**"最后一公里"缺口**：skip 限流的兜底预算、read_safe_file 的大小上限、缩略图缓存的自动配额——三处都是改动量小、收益立竿见影的补丁，却是公网暴露与 10 万文件库场景下的决定性短板。建议按 §7 优先级推进，P0 五项全部可在小改动内完成。

---

## 9. 恢复状态机专家复核（本轮增量）

专家对 `ReconciliationQueue` 与 `ImportManifestRecoveryService` 的复核将“队列提交”和“manifest 完成”明确分成两个 durable 事实：

```text
enqueue ──bind──> pending/enqueued ──claim──> running
                                      │
                         retryable ──┘│
                                      ├── succeeded ──ACK──> completed
                                      ├── terminal ─────────> recovery_pending/dead_letter
                                      ├── cancelled ────────> recovery_pending/cancelled
                                      └── evicted/missing ──> unbound/pending → re-enqueue
```

复核给出的实现约束：

- transition 必须携带 `previous`、`current`、`reason` 和完整 `operation_ids`；SQLite 的 expired lease 与容量 eviction 不能只依赖当前进程快照。
- listener 只能在 queue durable mutation 提交并释放 queue 锁后运行；listener 失败不得回滚 queue，必须由 bounded backlog/启动 recovery 重试。
- 一个合并 task 的 operation id 必须逐项做 library/path/kind scope 校验与 manifest generation CAS；任何一项失败不得替兄弟 operation ACK。
- 同一 `succeeded` event 可被 worker、启动补偿和 listener 重复观察，ACK 必须保留绑定 task id 且幂等；terminal/cancelled 进入 dead-letter 后不能在每次重启自动重排，需显式 retry 动作。

本轮代码已实现上述约束的第一层切片，并以 queue memory/SQLite、manifest transition、eviction、重复 ACK 和 dead-letter 回归测试验证（定向集合 `62 passed`）。2026-09-01 复核又发现并修正了两处边界：transition envelope 不得扩大 task 的 operation scope；listener 失败按 listener 维度进入可重试 backlog，并在下一次 mutation/显式 recovery pass 重试，overflow 通过计数和日志暴露。新增 scope 注入、旧 attempt 乱序、listener retry/overflow 测试后，queue + manifest unit 为 `45 passed`，reconciliation cross-process/lifecycle 子集为 `16 passed`，相关 `ruff`/`compileall`/`pyright`/package smoke 均通过。

2026-09-01 的后续实现补齐了显式运维重试：只有已绑定 durable task 的 `dead_letter`/`cancelled` manifest 能由 generation CAS 重新打开；旧 task id 会写入一个有界 retired 集合，延迟 listener/startup transition 对该 id 只作幂等 no-op。服务入口会先从刷新后的 queue snapshot 补写可能丢失的 terminal 回调，再调用常规 recovery 调度；调度失败保留可见的 `pending` 和错误，不将 enqueue 伪装为完成。终态、取消态、丢回调、enqueue 失败和双连接 CAS 竞争已由 32 项 manifest store 单元测试覆盖。

上述“仍未完成”是 v44 前的审查快照；后续已落地持久 outbox、delivery-token lease 和 ACK-gated consumer。剩余 H1 退出条件是 retention 告警/容量策略、ACK snapshot 成本，以及优雅关闭时 live lease 的产品策略；旧测试若将“enqueue acceptance”断言为 completed，必须改为显式 worker durable success ACK 或明确等待 lease/worker，不应回退 ACK-gated 状态机。

### 9.1 v44-v46 持久 outbox 追加复核（2026-09-01）

上一节末尾“仍缺持久化 outbox”是 v44 实施前的历史快照。最新工作树已在 `core/schema_defs.py`、`core/db_migrations.py` 与 `application/reconciliation_queue_store.py` 增加 `reconciliation_transition_outbox`：每次 queue mutation 在同一 SQLite transaction 写入 immutable `previous/current` snapshot；claim、ACK、fail 采用 `BEGIN IMMEDIATE` 和 delivery-token CAS；过期 lease 可接管，旧 token 不能确认或释放新 owner。`application/reconciliation_queue.py` 的 drain 以 outbox `id` 队首顺序交付，遇到其他进程持有的有效头部 lease 时停止，不让后续 event 越序。v43→v44、缺表拒绝、迁移历史、事务回滚、双连接 lease 和过期接管已进入定向门禁；此前相关 migration/queue/manifest 集合为 `174 passed`。

后续复核已关闭两个原始缺口：`ReconciliationTransitionDisposition` 将 durable consumer 的结果分为 `APPLIED`、`STALE`、`RETRY`；`ImportManifestRecoveryService` 只有在全部 applicable operation scope 已经持久写入或可证明无须写入时才返回前两者，数据库异常和未证明的 CAS 结果返回 `RETRY`，outbox 因而不 ACK。`AssetIndexReconciliationService` 随 runtime 启动可停止的 10 秒 sweeper，空闲时也会调用 outbox retry/drain；65 条积压在首批 64 条同步处理后可由 sweeper 排空。最新 `SQLite outbox + manifest + 双进程 claim` 定向重跑为 `65 passed`。

v45 已关闭 poison head 的永久阻塞：`reconciliation_transition_outbox_dead_letters` 保存 source event id、原始 `previous/current` snapshot、operation scope、delivery attempts、隔离时间和诊断错误。`claim_transition_outbox()` 对无法安全解码的 immutable row 在同一个 `BEGIN IMMEDIATE` transaction 中执行 CAS lease → dead-letter copy → source delete，并在不跨过有效 lease 的前提下继续扫描后续队首。decoder 现要求每个非空 snapshot 都匹配 event `task_id`，且 `operation_ids` 等于两个 snapshots 的确定性并集。坏 JSON、snapshot task-id 或 scope 错配会被隔离；v46 也复用该路径处理无法判断为 live/expired 的损坏 active delivery lease 或 retry deadline；dead-letter 表缺失、copy 或 delete 失败都会回滚，不能删除源行。

v46 将暂态投递失败与 poison 隔离保持分离：canonical durable consumer 的异常、`RETRY` 或非法 disposition 后，`next_delivery_at` 由 delivery-token CAS 原子写入。通用 observer 在 ACK 后执行，其异常仅进入本地 advisory backlog，不能触发 durable retry。退避从 15 秒指数增长到 300 秒上限，并以 `library_root + event_id + delivery_attempts` 的稳定 hash 加 0–20% 正向 jitter；jitter 后的最终值仍封顶为 300 秒。claim 仍只读取最早 pending id，未到 deadline 的 head 会阻塞后续 event，不能用“后行已到期”越序。ACK 清除 deadline；v45/第三方旧表缺列时保留即时 retry。外部损坏的 retry 或 active delivery lease deadline 会走 v45 隔离而不是永久阻塞。SQLite store 现以 delivery-token CAS 在慢 callback 期间每约三分之一租约续期；默认 300 秒 callback age 到期后停止续租，迟到 callback 不 ACK，最后一个租约窗口后允许另一连接重放。v45 表存在时，普通 durable delivery 默认第八次失败会在同一 token-CAS transaction 复制到 dead-letter 并删除 source row；v44 保持 retry，避免无证删除。迁移、token CAS、严格顺序、旧 schema fallback、损坏 lease/deadline、canonical consumer / observer 契约、callback heartbeat 和 delivery exhaustion 的定向 H1 回归为 `224 passed`，`pyright`、`ruff check` 通过。

新增真实子进程 crash-replay 门禁把此前缺失的核心窗口变成可复现证据：子进程先持久化 `succeeded` transition 对应 manifest 的 `completed` CAS，再阻塞在 outbox ACK 前；父进程终止该子进程后，第二个 SQLite 连接等待短 delivery lease 到期，重放同一 event。consumer 此时返回 `STALE`，event 的 delivery attempts 从 1 变为 2 并成功 ACK，而 manifest generation 与 attempts 均不再变化。第二、三个场景让两个 manifest 共享同一 terminal 或 evicted task，分别在首个 `dead_letter` CAS 或首个解绑 CAS 后崩溃；重放保持首项的 generation/attempts 不变，只持久化未处理的兄弟项再 ACK。新增长 callback 场景：子进程在 `succeeded` consumer 内阻塞，callback-age 到期后停止 heartbeat，第二进程接管过期 lease 并完成 manifest。该进程文件定向重跑为 `7 passed`。

retention 已接入同一 runtime-owned sweeper：每 10 秒的 lifecycle pass 仍负责 retry/drain 与 lease recovery，每小时另以 bounded `prune_transition_outbox()` 删除默认 7 天前的 ACK 和 30 天前的 dead-letter（每类最多 1000 条）。prune 失败不会阻断投递或 lease 回收，并会在下一次 10 秒 pass 重试；pending/leased 行仍由 store 层拒绝删除。新增频率/cutoff/limit 和故障重试门禁后，reconciliation service 定向集合为 `22 passed`。

这仍不是 H1 退出。专家复核确认以下边界：

- v45 dead-letter 表已处理损坏 immutable payload/delivery metadata 与默认第八次普通 delivery failure；v46 已压低普通投递失败的重复频率。应用层现已补齐 fail-closed dead-letter 列表、event-id/CAS 人工 replay、ACK/dead-letter bounded retention/prune 与 pending/ACK/dead-letter/lease/attempt/age 指标；runtime 已正式调度有界 retention，仍需定义告警阈值、容量预算和可配置保留窗口，并评估 ACK 后完整 JSON snapshot 的长期存储成本。
- 已收敛为唯一 `import_manifest_recovery` canonical durable consumer：它必须显式返回 `APPLIED`、`STALE` 或 `RETRY`，通用 listener 的 `None` 不再是 durable 接受，且 observer 不参与 `delivered_at`。当前没有第二个生产 durable consumer，因此不提前增加 v47。产品将来引入第二个独立 projection 时，必须先增加 `(event_id, consumer_id)` receipt/inbox、持久 registry、历史起点与 retention 语义，不能复用单一全局 ACK。
- decoder 的 identity/scope 校验已由 v45 收紧；SQLite delivery lease 已有有界 renew 与 callback age。它不能强制终止业务 callback，因此 deadline 后以停止续租和拒绝迟到 ACK 来保证可接管，幂等重放仍是契约前提；manifest CAS 后、ACK 前的独立进程 crash/replay，以及长运行 callback age 到期后的第二进程 lease 接管均已覆盖。
- 双进程 manifest claim winner、token lease，以及 worker durable success、outbox delivery、manifest CAS、ACK 前崩溃和另一进程 `STALE` 重放的完整链路均已验证；合并 terminal 与 eviction event 的首项 CAS 后崩溃、长 callback age 到期后的接管也已覆盖。

建议顺序：保持当前单 canonical consumer 契约；delivery dead-letter 的人工 replay/retention 和指标、核心 crash-replay 门禁已有实现，下一步补 retention 告警阈值、容量预算、可配置保留窗口和优雅关闭时 live lease 策略。只有产品出现第二个独立 durable projection 时，再先做 per-consumer receipt/inbox 设计。
